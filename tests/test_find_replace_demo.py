"""Tests for the ``ScripTreeApps/Demos/find-replace/find_replace.py``
demo script.

Spawned as a real subprocess so we exercise the same code path the
runner uses (including the line-buffered prompt-then-readline loop).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


_DEMO_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "ScripTreeApps" / "Demos" / "find-replace" / "find_replace.py"
)


def _make_text_file(content: str) -> Path:
    fd, path = tempfile.mkstemp(suffix=".txt", text=True)
    os.close(fd)
    Path(path).write_text(content, encoding="utf-8")
    return Path(path)


def _run(
    target: Path,
    pattern: str,
    replacement: str,
    answers: str,
    *,
    extra: list[str] | None = None,
    timeout: float = 10.0,
) -> tuple[int, str, str]:
    args = [
        sys.executable, str(_DEMO_SCRIPT),
        str(target), pattern, replacement,
    ]
    if extra:
        args.extend(extra)
    proc = subprocess.run(
        args,
        input=answers,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
    )
    return proc.returncode, proc.stdout, proc.stderr


# ---------------------------------------------------------------------------
# Sanity
# ---------------------------------------------------------------------------

def test_demo_script_exists() -> None:
    assert _DEMO_SCRIPT.is_file(), (
        f"Expected demo script at {_DEMO_SCRIPT}"
    )


def test_demo_scriptree_exists() -> None:
    sib = _DEMO_SCRIPT.parent / "find-replace.scriptree"
    assert sib.is_file()


def test_demo_scriptree_declares_interactive_true() -> None:
    """The accompanying .scriptree MUST set interactive=true so the
    runner shows the send-line widget."""
    import json

    sib = _DEMO_SCRIPT.parent / "find-replace.scriptree"
    data = json.loads(sib.read_text(encoding="utf-8"))
    assert data.get("interactive") is True


# ---------------------------------------------------------------------------
# Match accept / skip / quit
# ---------------------------------------------------------------------------

def test_accept_all_via_y() -> None:
    f = _make_text_file("apple\napple\napple\n")
    code, out, _ = _run(f, "apple", "banana", "y\ny\ny\n")
    assert code == 0
    assert f.read_text(encoding="utf-8") == "banana\nbanana\nbanana\n"
    assert "[done] Wrote 3 edit(s)" in out
    f.unlink()


def test_accept_some_skip_others() -> None:
    f = _make_text_file("apple\napple\napple\n")
    code, out, _ = _run(f, "apple", "banana", "y\nn\ny\n")
    assert code == 0
    assert f.read_text(encoding="utf-8") == "banana\napple\nbanana\n"
    f.unlink()


def test_bang_accepts_remaining() -> None:
    """The ``!`` answer should accept the current match AND every
    remaining one without further prompts."""
    f = _make_text_file("apple\napple\napple\napple\n")
    code, out, _ = _run(f, "apple", "banana", "n\n!\n")
    assert code == 0
    # First match skipped; bang at second flips accept-all → 3 edits.
    assert f.read_text(encoding="utf-8") == "apple\nbanana\nbanana\nbanana\n"
    f.unlink()


def test_quit_writes_partial_then_returns_one() -> None:
    """``q`` after at least one accepted match writes the partial
    file and returns exit code 1 (meaningful for scripting)."""
    f = _make_text_file("apple\napple\napple\n")
    code, out, _ = _run(f, "apple", "banana", "y\nq\n")
    assert code == 1
    # First was accepted, then quit before the rest.
    assert f.read_text(encoding="utf-8") == "banana\napple\napple\n"
    f.unlink()


def test_dry_run_does_not_write_file() -> None:
    original = "apple\napple\n"
    f = _make_text_file(original)
    code, out, _ = _run(f, "apple", "banana", "y\ny\n", extra=["--dry-run"])
    assert code == 0
    assert f.read_text(encoding="utf-8") == original
    assert "file NOT written" in out
    f.unlink()


# ---------------------------------------------------------------------------
# Regex + case sensitivity
# ---------------------------------------------------------------------------

def test_regex_groups_in_replacement() -> None:
    f = _make_text_file("name=alice\nname=bob\n")
    code, out, _ = _run(
        f, r"name=(\w+)", r"user:\1",
        "y\ny\n",
        extra=["--regex", "--case-sensitive"],
    )
    assert code == 0
    assert f.read_text(encoding="utf-8") == "user:alice\nuser:bob\n"
    f.unlink()


def test_case_insensitive_default() -> None:
    f = _make_text_file("Apple\nAPPLE\napple\n")
    code, _, _ = _run(f, "apple", "x", "y\ny\ny\n")
    assert code == 0
    assert f.read_text(encoding="utf-8") == "x\nx\nx\n"
    f.unlink()


def test_case_sensitive_filters_matches() -> None:
    f = _make_text_file("Apple\nAPPLE\napple\n")
    code, out, _ = _run(
        f, "apple", "x", "y\n",
        extra=["--case-sensitive"],
    )
    assert code == 0
    # Only the lowercase line should match.
    assert f.read_text(encoding="utf-8") == "Apple\nAPPLE\nx\n"
    f.unlink()


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

def test_missing_file_returns_two() -> None:
    code, out, _ = _run(
        Path("does-not-exist.txt"),  # type: ignore[arg-type]
        "x", "y", "",
    )
    assert code == 2
    assert "[error]" in out


def test_no_matches_returns_zero_no_writes() -> None:
    original = "hello world\n"
    f = _make_text_file(original)
    code, out, _ = _run(f, "absent", "x", "")
    assert code == 0
    assert "No matches" in out
    assert f.read_text(encoding="utf-8") == original
    f.unlink()


def test_invalid_regex_returns_two() -> None:
    f = _make_text_file("anything")
    code, out, _ = _run(f, "(", "x", "", extra=["--regex"])
    assert code == 2
    assert "Invalid regex" in out
    f.unlink()


def test_eof_treated_as_quit() -> None:
    """Closing stdin (no answer for any prompt) should exit cleanly,
    treating each unanswered prompt as q."""
    original = "apple\napple\n"
    f = _make_text_file(original)
    code, out, _ = _run(f, "apple", "x", "")  # empty stdin
    # Expecting q -> exit code 1, no writes.
    assert code == 1
    assert f.read_text(encoding="utf-8") == original
    f.unlink()
