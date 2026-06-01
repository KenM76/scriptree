"""CI guard for the no-bytecode policy.

See ``docs/LLM/no_bytecode_policy.md`` for the why.

These tests fail if anyone weakens the guard that prevents ScripTree
from writing ``__pycache__/*.pyc`` files into its install tree --
which is mandatory because the install commonly lives in a
Dropbox / OneDrive / Google Drive folder where ``.pyc`` writes
trigger sync storms that paralyse the cloud client for 15-30
seconds per launch.

Each entry-point and the package ``__init__`` must include the
self-disabling line:

    sys.dont_write_bytecode = True

at module-top level, BEFORE any other import.  Each ``.bat`` /
``.cmd`` launcher must set ``PYTHONDONTWRITEBYTECODE=1`` before
invoking Python.  This file enforces both rules verbatim.

If you are adding a new launcher and this test fails, the fix is to
add the guard to your new launcher -- NOT to relax the test.  See
the policy doc for the rationale.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


# Repository root, derived from this test file's location.
_REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Python entry-points: every file in this list MUST contain
# ``sys.dont_write_bytecode = True`` at module level, BEFORE any other
# ``import`` statement other than ``import sys`` itself.
# ---------------------------------------------------------------------------
_PY_ENTRY_POINTS = (
    "run_scriptree.py",
    "run_scriptreeforest.py",
    "run_scriptreering.py",
    "screenshooter.py",
    "scriptree/__init__.py",
)


# Regex matching the canonical guard line.  Permissive about whitespace
# and inline comments so reformatting doesn't break the check; strict
# about the actual statement so a sneaky ``= False`` slip fails loudly.
_GUARD_PATTERN = re.compile(
    r"^\s*(?:_?sys|sys)\.dont_write_bytecode\s*=\s*True\b",
    re.MULTILINE,
)


# Regex matching a non-stdlib import that, if it appears BEFORE the
# guard line, would already have written ``.pyc`` for some module
# before the guard kicked in.  ``import sys`` is exempt because
# ``sys`` is built-in and never compiles to a ``.pyc``.
_FORBIDDEN_PRE_GUARD = re.compile(
    r"^\s*(?:from|import)\s+(?!sys\b|__future__\b)",
    re.MULTILINE,
)


@pytest.mark.parametrize("entry_point", _PY_ENTRY_POINTS)
def test_python_entry_point_sets_dont_write_bytecode(entry_point: str) -> None:
    """Every entry-point sets ``sys.dont_write_bytecode = True``."""
    path = _REPO_ROOT / entry_point
    assert path.exists(), f"Expected entry-point missing: {entry_point}"

    src = path.read_text(encoding="utf-8")

    m = _GUARD_PATTERN.search(src)
    assert m is not None, (
        f"{entry_point} does not set ``sys.dont_write_bytecode = True`` "
        f"at module level.  Add the guard immediately after the module "
        f"docstring (and before any sub-module import).  See "
        f"docs/LLM/no_bytecode_policy.md."
    )

    # Make sure no offending import sneaks in BEFORE the guard.  Anything
    # imported before the guard line is compiled and ``.pyc``-written
    # regardless of the guard.
    pre_guard = src[: m.start()]
    bad = _FORBIDDEN_PRE_GUARD.findall(pre_guard)
    assert not bad, (
        f"{entry_point}: found non-``sys`` import statement(s) BEFORE the "
        f"bytecode guard line.  Move the guard to the top of the module "
        f"(after the docstring) so it fires before any import that would "
        f"trigger ``.pyc`` writes.  See docs/LLM/no_bytecode_policy.md."
    )


# ---------------------------------------------------------------------------
# Shell launchers: every ``.bat`` (and any future ``.cmd``/``.sh``) that
# invokes Python on the install tree MUST set ``PYTHONDONTWRITEBYTECODE=1``
# before its ``:launch`` label / before the ``python`` invocation.
# ---------------------------------------------------------------------------
_LAUNCHER_BAT_FILES = (
    "run_scriptree.bat",
    "run_scriptreeforest.bat",
    "run_scriptreering.bat",
    "run_screenshooter.bat",
)


# Match either ``set PYTHONDONTWRITEBYTECODE=1`` or
# ``set "PYTHONDONTWRITEBYTECODE=1"`` (Windows shell quoting variants).
_BAT_ENV_PATTERN = re.compile(
    r"^\s*set\s+\"?PYTHONDONTWRITEBYTECODE\s*=\s*1\"?\s*$",
    re.MULTILINE | re.IGNORECASE,
)


@pytest.mark.parametrize("launcher", _LAUNCHER_BAT_FILES)
def test_bat_launcher_sets_dont_write_bytecode(launcher: str) -> None:
    """Every Windows launcher sets ``PYTHONDONTWRITEBYTECODE=1``."""
    path = _REPO_ROOT / launcher
    assert path.exists(), f"Expected launcher missing: {launcher}"
    src = path.read_text(encoding="utf-8")
    assert _BAT_ENV_PATTERN.search(src) is not None, (
        f"{launcher} does not ``set PYTHONDONTWRITEBYTECODE=1`` before "
        f"its Python invocation.  Add the line immediately after "
        f"``setlocal EnableDelayedExpansion``.  See "
        f"docs/LLM/no_bytecode_policy.md."
    )


# ---------------------------------------------------------------------------
# Runtime check: importing ``scriptree`` MUST set the flag in the
# current process.  This catches refactors that move the guard line
# somewhere it doesn't actually run on import.
# ---------------------------------------------------------------------------

def test_importing_scriptree_sets_dont_write_bytecode() -> None:
    """Importing the ``scriptree`` package sets ``sys.dont_write_bytecode``.

    We can't easily test this in a fresh subprocess (pytest itself has
    typically already imported half the codebase), so we verify the
    end state holds by the time tests run.  The complementary
    static check above ensures the line is in the source where it
    will execute on first import.
    """
    import sys
    import scriptree  # noqa: F401  -- import for side effect

    assert sys.dont_write_bytecode is True, (
        "After importing ``scriptree``, ``sys.dont_write_bytecode`` "
        "must be True.  The guard line in scriptree/__init__.py was "
        "likely moved, commented out, or had its right-hand side "
        "flipped to False.  See docs/LLM/no_bytecode_policy.md."
    )


def test_policy_doc_exists() -> None:
    """The policy doc the error messages point at must exist.

    Prevents a broken-link footgun where a future contributor follows
    one of this test file's failure messages, looks for the doc, and
    finds nothing.
    """
    doc = _REPO_ROOT / "docs" / "LLM" / "no_bytecode_policy.md"
    assert doc.exists(), (
        f"docs/LLM/no_bytecode_policy.md is missing -- the test "
        f"failure messages in this file reference it, and "
        f"scriptree/__init__.py / the launcher .py and .bat files "
        f"point at it in their comments."
    )
