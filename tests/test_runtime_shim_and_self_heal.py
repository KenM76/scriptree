"""Tests for the v0.3.13 layered fix:

1. **Runtime shim** (``scriptree/core/_runtime_shim.py``) — splices
   between the Python interpreter and the user's tool script so
   sibling imports work regardless of ``._pth`` mode, ``-P``,
   ``PYTHONSAFEPATH``, etc.

2. **Self-healing** (``run_scriptree.py`` / ``run_scriptreering.py``)
   — rebuilds ``Lib/site-packages/sitecustomize.py`` and re-patches
   ``python<ver>._pth`` if a user replaced ``lib/python/`` with a
   fresh python.org embed download (which strips both).

The shim is the durable architectural fix; the self-heal is
belt-and-suspenders for callers who run the bundled python.exe
directly without going through ScripTree.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


# ===========================================================================
# Part B — runtime shim wiring in the runner
# ===========================================================================

class TestShimDetection:
    """Unit tests for ``_inject_runtime_shim`` argv detection rules."""

    def test_python_interpreter_basenames(self) -> None:
        from scriptree.core.runner import _looks_like_python_interpreter as f
        assert f("python")
        assert f("python3")
        assert f("python.exe")
        assert f("pythonw.exe")
        assert f("python3.13.exe")
        assert f(r"C:\Python313\python.exe")
        assert f("/usr/bin/python3")

    def test_non_python_interpreters(self) -> None:
        from scriptree.core.runner import _looks_like_python_interpreter as f
        assert not f("")
        assert not f("ruby")
        assert not f("node.exe")
        assert not f("powershell.exe")
        # py.exe (Windows launcher) intentionally excluded — its
        # argv conventions differ and would need separate handling.
        assert not f("py.exe")
        assert not f("py")

    def test_script_path_detection(self) -> None:
        from scriptree.core.runner import _looks_like_script_path as f
        assert f("tool.py")
        assert f(r"C:\tools\tool.py")
        assert f("./tool.pyw")
        assert f("/usr/local/bin/tool.py")
        assert f("subdir/script.py")

    def test_non_script_args(self) -> None:
        from scriptree.core.runner import _looks_like_script_path as f
        # Flags must NOT be treated as scripts.
        assert not f("-c")
        assert not f("-m")
        assert not f("--version")
        assert not f("-X")
        assert not f("-")  # stdin
        assert not f("")


class TestShimSplicing:
    """``_inject_runtime_shim`` mutates the argv list correctly."""

    def test_splices_when_python_runs_a_script(self) -> None:
        from scriptree.core.runner import _inject_runtime_shim
        argv = ["python.exe", "tool.py", "--flag"]
        out = _inject_runtime_shim(argv)
        assert len(out) == 4
        assert out[0] == "python.exe"
        assert out[1].endswith("_runtime_shim.py")
        assert out[2] == "tool.py"
        assert out[3] == "--flag"

    def test_does_not_splice_for_native_executables(self) -> None:
        from scriptree.core.runner import _inject_runtime_shim
        argv = [r"C:\tools\my_app.exe", "--flag"]
        assert _inject_runtime_shim(argv) is argv  # unchanged

    def test_does_not_splice_for_python_dash_c(self) -> None:
        """``python -c "print(1)"`` shouldn't have a shim shoved
        in; the shim only handles the script-path shape."""
        from scriptree.core.runner import _inject_runtime_shim
        argv = ["python.exe", "-c", "print(1)"]
        assert _inject_runtime_shim(argv) is argv

    def test_does_not_splice_for_python_dash_m(self) -> None:
        from scriptree.core.runner import _inject_runtime_shim
        argv = ["python.exe", "-m", "json.tool"]
        assert _inject_runtime_shim(argv) is argv

    def test_does_not_splice_short_argv(self) -> None:
        from scriptree.core.runner import _inject_runtime_shim
        # Just an interpreter, no script.
        argv = ["python.exe"]
        assert _inject_runtime_shim(argv) is argv

    def test_resolved_command_uses_shim(self) -> None:
        """End-to-end via ``resolve()``: a Python tool gets the
        shim spliced in by the time the runner returns the
        resolved command."""
        from scriptree.core.io import save_tool, load_tool
        from scriptree.core.model import (
            ParamDef, ParamType, ToolDef, Widget,
        )
        from scriptree.core.runner import resolve
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            tool_py = tdp / "tool.py"
            tool_py.write_text("print('hi')\n", encoding="utf-8")
            tool = ToolDef(
                name="x",
                executable="python",
                argument_template=["tool.py"],
                params=[],
            )
            p = tdp / "demo.scriptree"
            save_tool(tool, p)
            tool = load_tool(p)
            cmd = resolve(tool, {})
            # argv = [python, shim, tool.py]
            assert cmd.argv[0] == "python"
            assert cmd.argv[1].endswith("_runtime_shim.py")
            assert cmd.argv[2] == "tool.py"


# ===========================================================================
# Part B — runtime shim end-to-end (Windows-only, requires bundled Python)
# ===========================================================================

_BUNDLED_PY = REPO / "lib" / "python" / "python.exe"
_SHIM = REPO / "scriptree" / "core" / "_runtime_shim.py"


@pytest.mark.skipif(
    sys.platform != "win32" or not _BUNDLED_PY.is_file(),
    reason="Requires the bundled Windows embeddable Python.",
)
class TestShimEndToEnd:
    """The acceptance test: shim makes sibling imports work even
    when ``sitecustomize.py`` is removed (i.e. simulates the user
    having replaced ``lib/python/`` with a fresh python.org embed
    that lacks our patches)."""

    def _make_layout(self, tmp_path: Path) -> Path:
        helper = tmp_path / "_sibling_helper.py"
        helper.write_text(
            "def hello():\n    return 'shim-fix-ok'\n",
            encoding="utf-8",
        )
        main = tmp_path / "main.py"
        main.write_text(
            "import _sibling_helper\nimport sys\n"
            "print(_sibling_helper.hello())\n"
            "print('argv0:', sys.argv[0])\n",
            encoding="utf-8",
        )
        return main

    def test_sibling_import_works_via_shim(self, tmp_path: Path) -> None:
        """Direct shim invocation under the bundled Python — should
        succeed without any sitecustomize / PYTHONPATH plumbing."""
        main = self._make_layout(tmp_path)
        # Strip env to isolate the test from any inherited
        # SCRIPTREE_TOOL_DIR / PYTHONPATH from the test runner.
        env = {
            k: v for k, v in os.environ.items()
            if k.upper() in ("SYSTEMROOT", "PATH", "PATHEXT", "TEMP", "TMP",
                             "USERPROFILE", "WINDIR", "COMSPEC")
        }
        result = subprocess.run(
            [str(_BUNDLED_PY), str(_SHIM), str(main), "extra-arg"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        assert result.returncode == 0, (
            f"shim invocation failed:\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "shim-fix-ok" in result.stdout
        # argv[0] must be the tool's path, not the shim's.
        assert "main.py" in result.stdout
        assert "_runtime_shim.py" not in result.stdout

    def test_shim_evicts_own_dir_so_stdlib_wins(self, tmp_path: Path) -> None:
        """Regression: the shim lives in ``scriptree/core``, which holds
        package modules whose top-level names shadow the stdlib —
        ``platform.py`` (``scriptree.core.platform``), ``io.py``, etc.
        Python auto-inserts the shim's own directory at ``sys.path[0]``;
        if the shim doesn't evict it, a spawned tool — or, worse, a
        third-party library the tool imports (real case: ezdxf's font
        manager calling ``platform.system()``) — resolves a bare
        ``import platform`` to ScripTree's module and dies with
        ``AttributeError: module 'platform' has no attribute 'system'``.

        The tool below imports the stdlib ``platform``; it must get the
        real one, not ``scriptree/core/platform.py``.
        """
        main = tmp_path / "main.py"
        main.write_text(
            "import platform\n"
            "print('PLATFORM_FILE', platform.__file__)\n"
            "print('HAS_SYSTEM', hasattr(platform, 'system'))\n"
            "print('SYSTEM', platform.system())\n",
            encoding="utf-8",
        )
        env = {
            k: v for k, v in os.environ.items()
            if k.upper() in ("SYSTEMROOT", "PATH", "PATHEXT", "TEMP", "TMP",
                             "USERPROFILE", "WINDIR", "COMSPEC")
        }
        result = subprocess.run(
            [str(_BUNDLED_PY), str(_SHIM), str(main)],
            capture_output=True, text=True, timeout=30, env=env,
        )
        assert result.returncode == 0, (
            f"shim failed resolving stdlib platform:\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "HAS_SYSTEM True" in result.stdout
        # The stdlib platform must win, NOT scriptree/core/platform.py.
        core_dir = str((REPO / "scriptree" / "core").resolve())
        assert core_dir not in result.stdout, (
            "tool imported ScripTree's scriptree/core/platform.py instead "
            f"of the stdlib:\n{result.stdout}"
        )

    def test_shim_works_when_sitecustomize_missing(
        self, tmp_path: Path,
    ) -> None:
        """The acceptance criterion: shim survives a stripped
        ``lib/python/``.  We temporarily move sitecustomize.py
        aside, run the test, and restore it."""
        sc = REPO / "lib" / "python" / "Lib" / "site-packages" \
                                            / "sitecustomize.py"
        backup = sc.with_suffix(".py.bak-test")
        moved = False
        if sc.is_file():
            sc.rename(backup)
            moved = True
        try:
            main = self._make_layout(tmp_path)
            env = {
                k: v for k, v in os.environ.items()
                if k.upper() in ("SYSTEMROOT", "PATH", "PATHEXT", "TEMP",
                                 "TMP", "USERPROFILE", "WINDIR", "COMSPEC")
            }
            result = subprocess.run(
                [str(_BUNDLED_PY), str(_SHIM), str(main)],
                capture_output=True, text=True, timeout=30, env=env,
            )
            assert result.returncode == 0, (
                f"shim failed without sitecustomize:\n"
                f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
            )
            assert "shim-fix-ok" in result.stdout
        finally:
            if moved:
                backup.rename(sc)

    def test_shim_propagates_exit_code(self, tmp_path: Path) -> None:
        """``runpy`` propagates ``SystemExit`` — the tool's exit
        code must reach the OS unchanged."""
        main = tmp_path / "exit.py"
        main.write_text("import sys\nsys.exit(42)\n", encoding="utf-8")
        result = subprocess.run(
            [str(_BUNDLED_PY), str(_SHIM), str(main)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 42

    def test_shim_passes_argv_to_tool(self, tmp_path: Path) -> None:
        main = tmp_path / "argv.py"
        main.write_text(
            "import sys\nprint('|'.join(sys.argv))\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [str(_BUNDLED_PY), str(_SHIM), str(main), "a", "b", "c"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        # argv[0] = main.py, argv[1:] = [a, b, c]
        parts = result.stdout.strip().split("|")
        assert parts[0].endswith("argv.py")
        assert parts[1:] == ["a", "b", "c"]

    def test_shim_handles_missing_tool_clearly(self, tmp_path: Path) -> None:
        """A missing tool script must produce a clear error, not a
        traceback from inside runpy."""
        result = subprocess.run(
            [str(_BUNDLED_PY), str(_SHIM), str(tmp_path / "nope.py")],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode != 0
        # Either the shim's "tool script not found" line or a
        # FileNotFoundError — both are acceptable as clear errors.
        combined = result.stdout + result.stderr
        assert "not found" in combined.lower() or "no such file" in combined.lower()


# ===========================================================================
# Part A — self-healing patches a stripped lib/python/ tree
# ===========================================================================

class TestSelfHealLogic:
    """We can't easily run ``run_scriptree.py``'s ``_self_heal_bundled_python``
    against the live ``lib/python/`` tree (it'd touch real files).
    Instead we exercise the same logic against a fabricated copy in
    tmp_path using the helper functions extracted from the launcher.

    The launcher's helper isn't importable as a module (it's defined
    inside ``run_scriptree.py`` which has top-level side effects), so
    we paraphrase its contract here as a lightweight reproduction
    and verify the file-system effects.
    """

    def _fake_fresh_embed(self, tmp_path: Path) -> Path:
        """Lay out a directory matching what a fresh python.org
        embed extraction looks like — restrictive ._pth, no Lib/."""
        py_dir = tmp_path / "lib" / "python"
        py_dir.mkdir(parents=True)
        # python.exe placeholder so the existence check passes.
        (py_dir / "python.exe").write_bytes(b"")
        # Restrictive ._pth as shipped in the fresh embed.
        (py_dir / "python313._pth").write_text(
            "python313.zip\n.\n\n# Uncomment to run site.main() automatically\n#import site\n",
            encoding="utf-8",
        )
        return py_dir

    def _run_self_heal(self, scriptree_root: Path) -> None:
        """Invoke ``_self_heal_bundled_python`` from the launcher
        by execing it.  The launcher script defines the helper at
        module load time but also runs the rest of the bootstrap
        — to avoid that, we extract the helper text and exec it
        in isolation."""
        launcher = REPO / "run_scriptree.py"
        text = launcher.read_text(encoding="utf-8")
        # Locate the helper definition.  Parse from
        # "def _self_heal_bundled_python" through the last
        # function we'd need (`_write_minimal_sitecustomize`).
        start = text.index("def _self_heal_bundled_python")
        end = text.index("_check_python_version()", start)
        helper_src = text[start:end]
        # Run with __file__ pointing at the fabricated launcher
        # location so the helper resolves lib/python/ correctly.
        fake_launcher = scriptree_root / "run_scriptree.py"
        fake_launcher.write_text("# placeholder\n", encoding="utf-8")
        ns = {
            "__file__": str(fake_launcher),
            "Path": Path,
        }
        exec(helper_src, ns)
        ns["_self_heal_bundled_python"]()

    def test_pth_gets_patched(self, tmp_path: Path) -> None:
        py_dir = self._fake_fresh_embed(tmp_path)
        self._run_self_heal(tmp_path)
        pth = py_dir / "python313._pth"
        text = pth.read_text(encoding="utf-8")
        # `import site` is now uncommented.
        assert "import site" in text
        assert "#import site" not in text and "# import site" not in text

    def test_sitecustomize_gets_written(self, tmp_path: Path) -> None:
        py_dir = self._fake_fresh_embed(tmp_path)
        self._run_self_heal(tmp_path)
        sc = py_dir / "Lib" / "site-packages" / "sitecustomize.py"
        assert sc.is_file()
        text = sc.read_text(encoding="utf-8")
        # Marker comment present, fix function present.
        assert "ScripTree bundled-Python site customisation" in text
        assert "_scriptree_fix_sys_path" in text

    def test_self_heal_skips_when_lib_python_absent(
        self, tmp_path: Path,
    ) -> None:
        """No-op when the user is on system Python (no
        ``lib/python/`` directory at all)."""
        # No lib/python/ — but we still need a fake launcher.
        (tmp_path / "lib").mkdir(exist_ok=True)
        # Should not raise.
        self._run_self_heal(tmp_path)

    def test_self_heal_idempotent(self, tmp_path: Path) -> None:
        """Running the self-heal twice on an already-patched tree
        leaves the files byte-identical (no spurious churn)."""
        py_dir = self._fake_fresh_embed(tmp_path)
        self._run_self_heal(tmp_path)
        pth_after_1 = (py_dir / "python313._pth").read_bytes()
        sc_after_1 = (
            py_dir / "Lib" / "site-packages" / "sitecustomize.py"
        ).read_bytes()
        self._run_self_heal(tmp_path)
        pth_after_2 = (py_dir / "python313._pth").read_bytes()
        sc_after_2 = (
            py_dir / "Lib" / "site-packages" / "sitecustomize.py"
        ).read_bytes()
        assert pth_after_1 == pth_after_2
        assert sc_after_1 == sc_after_2

    def test_self_heal_when_sitecustomize_partially_corrupt(
        self, tmp_path: Path,
    ) -> None:
        """If a third-party tool wrote its own sitecustomize.py
        (no ScripTree marker), we replace it.  Any LLM-generated
        tool's sitecustomize would lose to ours by design — the
        marker check is intentional."""
        py_dir = self._fake_fresh_embed(tmp_path)
        sp = py_dir / "Lib" / "site-packages"
        sp.mkdir(parents=True)
        (sp / "sitecustomize.py").write_text(
            "# unrelated content\n", encoding="utf-8"
        )
        self._run_self_heal(tmp_path)
        text = (sp / "sitecustomize.py").read_text(encoding="utf-8")
        assert "ScripTree bundled-Python site customisation" in text
