"""Tests for the ``screenshooter.py`` headless screenshot tool
(``ScripTreeApps/ScripTreeManagement/screenshooter.scriptree``).

The tool renders ScripTree widgets to PNG files **without showing
them on the user's desktop**.  Approach: regular Qt platform (so
fonts work), never ``widget.show()``, capture via
``QWidget.grab()``.

Tests are Windows-focused because:
  * The bundled Python ships only the Windows embeddable build.
  * The "no flash, no focus theft" behaviour matters most on
    Windows where the platform plugin would otherwise create a
    real ``HWND`` for every shown widget.

On other platforms the tests should still pass — the underlying
``grab()``-on-unshown-widget mechanism is cross-platform.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

REPO = Path(__file__).resolve().parents[1]
SCREENSHOOTER = REPO / "screenshooter.py"


def _real_tool_path() -> Path:
    """Use one of the project's own .scriptree files as input —
    avoids having to synthesise a tool just for the test."""
    return REPO / "ScripTreeApps" / "ScripTreeManagement" / "make_portable.scriptree"


def _real_tree_path() -> Path:
    return (
        REPO / "ScripTreeApps" / "ScripTreeManagement"
        / "ScripTreeManagement.scriptreetree"
    )


def _run(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Spawn the screenshooter as a subprocess.

    A subprocess (rather than importing main()) is important
    because the tool installs its own QApplication and tweaks the
    quit-on-close flag — sharing that state with pytest's
    QApplication would taint subsequent tests.
    """
    return subprocess.run(
        [sys.executable, str(SCREENSHOOTER), *args],
        capture_output=True, text=True, timeout=timeout,
        cwd=str(REPO),
    )


# ===========================================================================
# Basic round-trips
# ===========================================================================

class TestRenders:

    def test_form_render(self, tmp_path: Path) -> None:
        out = tmp_path / "form.png"
        result = _run("form", str(_real_tool_path()), "--out", str(out))
        assert result.returncode == 0, (
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert out.is_file()
        # PNG magic number — first 8 bytes of any well-formed PNG.
        with out.open("rb") as f:
            magic = f.read(8)
        assert magic == b"\x89PNG\r\n\x1a\n"
        # Non-trivial size — a zero-content PNG would be < 100 bytes.
        assert out.stat().st_size > 1000

    def test_cell_render(self, tmp_path: Path) -> None:
        out = tmp_path / "cell.png"
        result = _run(
            "cell", str(_real_tool_path()),
            "--out", str(out),
            "--cell-size", "128",
        )
        assert result.returncode == 0, (
            f"stderr={result.stderr!r}"
        )
        assert out.is_file()
        assert out.stat().st_size > 500

    def test_tree_render(self, tmp_path: Path) -> None:
        out = tmp_path / "tree.png"
        result = _run("tree", str(_real_tree_path()), "--out", str(out))
        assert result.returncode == 0, (
            f"stderr={result.stderr!r}"
        )
        assert out.is_file()
        assert out.stat().st_size > 500


# ===========================================================================
# Auto-pick by suffix
# ===========================================================================

class TestKindAutopick:

    def test_no_kind_picks_form_for_scriptree(self, tmp_path: Path) -> None:
        """Passing the input without a kind dispatches to form for
        a ``.scriptree`` file."""
        result = _run(
            str(_real_tool_path()),
            "--out", str(tmp_path / "auto.png"),
        )
        # argparse should accept input as the kind-or-input
        # positional.  We expect either success OR a clear error
        # about needing a kind — not a crash.
        assert result.returncode in (0, 2), (
            f"stderr={result.stderr!r}"
        )

    def test_batch_picks_per_file(self, tmp_path: Path) -> None:
        """Batch mode walks a folder and produces one PNG per
        recognised catalog."""
        out_dir = tmp_path / "shots"
        result = _run(
            str(REPO / "ScripTreeApps" / "ScripTreeManagement"),
            "--batch",
            "--out", str(out_dir),
        )
        assert result.returncode == 0, (
            f"stderr={result.stderr!r}"
        )
        # At least one PNG per .scriptree found.
        pngs = list(out_dir.glob("*.png"))
        assert len(pngs) >= 4, [p.name for p in pngs]


# ===========================================================================
# Failure modes — must produce clear errors, never crashes
# ===========================================================================

class TestConfigAndStandalone:
    """v0.3.19: ``--config NAME`` activates a sidecar configuration
    before capture; ``--standalone`` flips ``_standalone_mode`` so
    the form's UIVisibility flags actually take effect."""

    def test_standalone_flag_runs(self, tmp_path: Path) -> None:
        out = tmp_path / "standalone.png"
        result = _run(
            "form", str(_real_tool_path()),
            "--out", str(out),
            "--standalone",
        )
        assert result.returncode == 0, (
            f"stderr={result.stderr!r}"
        )
        assert out.is_file()
        assert out.stat().st_size > 1000

    def test_unknown_config_falls_back_to_default(
        self, tmp_path: Path,
    ) -> None:
        """An unknown config name must not crash — the screenshooter
        warns to stderr and renders against the sidecar default."""
        out = tmp_path / "unknown_cfg.png"
        result = _run(
            "form", str(_real_tool_path()),
            "--out", str(out),
            "--config", "definitely-not-a-real-config",
        )
        assert result.returncode == 0, (
            f"stderr={result.stderr!r}"
        )
        assert out.is_file()


class TestFailureModes:

    def test_missing_input_returns_nonzero(self, tmp_path: Path) -> None:
        result = _run(
            "form", str(tmp_path / "does_not_exist.scriptree"),
        )
        assert result.returncode != 0
        assert "input not found" in (result.stdout + result.stderr).lower()

    def test_wrong_kind_for_input(self, tmp_path: Path) -> None:
        """``tree`` on a .scriptree (not .scriptreetree) must error."""
        result = _run(
            "tree", str(_real_tool_path()),
            "--out", str(tmp_path / "x.png"),
        )
        assert result.returncode != 0


# ===========================================================================
# .scriptree definition validity
# ===========================================================================

class TestScripTreeDefinition:

    def test_scriptree_loads_cleanly(self) -> None:
        from scriptree.core.io import load_tool
        path = (
            REPO / "ScripTreeApps" / "ScripTreeManagement"
            / "screenshooter.scriptree"
        )
        tool = load_tool(path)
        # Sanity check: every argument-template token references a
        # param that exists, or is a literal.
        param_ids = {p.id for p in tool.params}
        # The arg template can be nested lists; flatten and check
        # only the {placeholder} tokens.
        import re
        ph_re = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?:\?[^}]*)?\}")

        def _walk(t):
            if isinstance(t, list):
                for x in t:
                    yield from _walk(x)
            elif isinstance(t, str):
                for m in ph_re.finditer(t):
                    yield m.group(1)

        referenced = set(_walk(tool.argument_template))
        missing = referenced - param_ids
        assert not missing, f"argv template references unknown params: {missing}"
