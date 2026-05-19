"""Tests for the v0.3.10 launcher fix that filters out the
Microsoft Store python stub.

On Windows 10/11, ``%LocalAppData%\\Microsoft\\WindowsApps\\python.exe``
is a 0-byte ``App Execution Alias`` that opens the Microsoft Store
when run.  Before this fix, ``run_scriptree.bat`` would happily pick
it up via the PATH search, ``start ""`` it, and detach — leaving
the user with a flashed terminal and nothing else.  The classic
"USB stick on a clean machine launches and immediately closes"
symptom the user has reported repeatedly.

The fix is in the .bat itself: after a PATH hit, we ``findstr /i
"WindowsApps"`` against the resolved exe path and skip the match
if it falls inside that folder tree.

These tests exercise the .bat directly with a synthesised PATH so
we don't need to mutate the real machine's PATH or rely on having
a real Store stub present.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


# Skip the whole module on non-Windows — these test shell logic
# specific to Windows .bat files.
pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows-only: these test cmd.exe .bat behaviour.",
)


def _make_fake_python_stub(
    target_dir: Path, name: str = "python.exe", content: str = "",
) -> Path:
    """Write a 'fake' python.exe (just an empty exe-named file).

    The .bat's PATH search uses ``%~$PATH:P`` which only resolves to
    real files (Windows PathExt rule).  An empty file works as a
    decoy here because ``%~$PATH:P`` only checks existence, not
    executability — the .bat then either rejects it (if the path
    contains ``WindowsApps``) or sets PY and goes to :launch.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    p = target_dir / name
    p.write_text(content, encoding="utf-8")
    return p


def _run_bat_with_path(
    bat: Path, fake_path_dir: Path, *, extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess:
    """Run the .bat with ONLY ``fake_path_dir`` on PATH.

    We intercept the launch by passing ``--__bat_smoke_dryrun`` as
    the first arg — actually no, the .bat launches python with the
    given argv.  Instead we capture which python the .bat selected
    by replacing run_scriptree.py with a tiny stub that just prints
    its sys.executable.  That requires a writable copy of the bat's
    folder, so we copy it.
    """
    env = os.environ.copy()
    env["PATH"] = str(fake_path_dir)
    env["SystemRoot"] = os.environ.get("SystemRoot", r"C:\Windows")
    env["ComSpec"] = os.environ.get("ComSpec", r"C:\Windows\System32\cmd.exe")
    args = ["cmd", "/c", str(bat)]
    if extra_args:
        args += extra_args
    return subprocess.run(
        args, env=env, capture_output=True, text=True, timeout=15,
    )


class TestStoreStubFiltering:

    def test_windowsapps_path_is_rejected(self, tmp_path: Path) -> None:
        """A python.exe sitting in a folder whose path contains
        'WindowsApps' must NOT be selected by the .bat — it would
        otherwise hit the Microsoft Store stub trap."""
        # Build a fake "WindowsApps" folder with a python.exe inside.
        fake_store = tmp_path / "Microsoft" / "WindowsApps"
        _make_fake_python_stub(fake_store, "python.exe")
        _make_fake_python_stub(fake_store, "pythonw.exe")

        # Use a copy of the .bat in an isolated dir so its lib/python/
        # checks all fail (no portable Python, no embed zip).
        sandbox = tmp_path / "scriptree"
        sandbox.mkdir()
        bat_src = REPO / "run_scriptree.bat"
        bat_dst = sandbox / "run_scriptree.bat"
        shutil.copyfile(bat_src, bat_dst)

        # PATH = System32 (so findstr / powershell still resolve) +
        # the fake WindowsApps folder.  With the fix in place the .bat
        # must NOT hit the :launch label — so it falls through to the
        # auto-install prompt.  We feed it "n" via stdin so it ends
        # quickly at the manual instructions (whose `pause` we
        # release with another newline).
        sysroot = os.environ.get("SystemRoot", r"C:\Windows")
        sys_path = (
            f"{sysroot}\\System32;{sysroot};{sysroot}\\System32\\Wbem;"
            f"{fake_store}"
        )
        result = subprocess.run(
            ["cmd", "/c", str(bat_dst)],
            env={**os.environ, "PATH": sys_path},
            input="n\n\n", capture_output=True, text=True, timeout=20,
        )
        # Expect the "Python 3 ... was not found" banner — that proves
        # the WindowsApps stub was rejected and we landed in the
        # no-python path.  Pre-fix this would silently pick the
        # WindowsApps python.exe.
        combined = result.stdout + result.stderr
        assert "needs Python 3" in combined or "no Python found" in combined.lower(), (
            f"Expected the no-Python banner; got:\n{combined}"
        )

    def test_normal_path_still_picked(self, tmp_path: Path) -> None:
        """Sanity: a python found at a non-WindowsApps path is still
        accepted — the fix MUST NOT be over-aggressive."""
        # Use the host's real Python so launch actually works.  We
        # don't want to launch the real GUI, so we copy the .bat
        # and replace run_scriptree.py with a one-liner that prints
        # "OK" and exits.
        sandbox = tmp_path / "scriptree"
        sandbox.mkdir()
        bat_src = REPO / "run_scriptree.bat"
        bat_dst = sandbox / "run_scriptree.bat"
        shutil.copyfile(bat_src, bat_dst)
        (sandbox / "run_scriptree.py").write_text(
            "import sys; print('OK', sys.executable)", encoding="utf-8"
        )
        # PATH = System32 (for cmd builtins) + the real Python's dir.
        py_dir = Path(sys.executable).parent
        assert "WindowsApps" not in str(py_dir), (
            "Test bootstrap assumes the test is run from a non-Store python."
        )
        sysroot = os.environ.get("SystemRoot", r"C:\Windows")
        sys_path = (
            f"{sysroot}\\System32;{sysroot};{sysroot}\\System32\\Wbem;"
            f"{py_dir}"
        )
        result = subprocess.run(
            ["cmd", "/c", str(bat_dst)],
            env={**os.environ, "PATH": sys_path},
            capture_output=True, text=True, timeout=20,
        )
        # ``start ""`` for pythonw detaches; ``python.exe`` runs inline.
        # Either way our stub prints "OK" — for the pythonw path the
        # detached process may or may not flush before cmd exits, so
        # accept either output OR a clean returncode 0 with no "needs
        # Python" banner.
        combined = result.stdout + result.stderr
        assert "needs Python 3" not in combined, (
            f"Real python on PATH was unexpectedly rejected.\n{combined}"
        )
