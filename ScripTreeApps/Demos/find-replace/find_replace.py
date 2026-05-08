"""find_replace.py — interactive query-replace, Emacs M-% style.

Usage:

    python find_replace.py <file> <pattern> <replacement> [--regex] [--case-sensitive]

For each match in the file, prints a one-line preview to stdout and
reads a single character from stdin:

    y   replace this match
    n   skip this match
    !   replace this and every remaining match
    q   quit and write whatever's been accepted so far

When all answers are collected, the file is written back in-place
(the original content is held in memory; we only write on a clean
finish or on `q` after at least one accepted replacement).

Designed to pair with ScripTree V3's interactive runner (v0.3.0+):
the .scriptree's ``interactive`` flag is set, so the runner spawns
this script with stdin piped to its send-line widget.  The user
types ``y`` / ``n`` / ``!`` / ``q`` (or clicks the matching quick-
response button) and the response flows here.

Stdout is line-buffered (``flush=True`` on every print) so the
runner's QPlainTextEdit shows each prompt as it's emitted, not all
at once after the script exits.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="find_replace",
        description=(
            "Interactive query-replace, Emacs M-% style.  "
            "Reads y/n/!/q answers from stdin one per match."
        ),
    )
    p.add_argument("file", help="Path to the file to search and modify.")
    p.add_argument("pattern", help="String or regex to find.")
    p.add_argument("replacement", help="Replacement text.")
    p.add_argument(
        "--regex",
        action="store_true",
        help="Treat <pattern> as a Python regex (default: literal string).",
    )
    p.add_argument(
        "--case-sensitive",
        action="store_true",
        help="Case-sensitive matching (default: case-insensitive).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show prompts and accepted matches but do NOT write the "
            "file back to disk.  Useful for previewing before "
            "committing."
        ),
    )
    return p


def _flush_print(*args: object, sep: str = " ", end: str = "\n") -> None:
    """``print`` that always flushes — the runner reads line-by-line
    so a buffered emit looks like a hang."""
    print(*args, sep=sep, end=end, flush=True)


def _read_answer() -> str:
    """Read one line of input, returning the first non-whitespace
    character.  EOF (pipe closed) returns ``"q"`` so the loop exits
    cleanly when the user clicks End input."""
    line = sys.stdin.readline()
    if not line:
        return "q"
    stripped = line.strip()
    return stripped[:1].lower() if stripped else ""


def _format_context(
    text: str, start: int, end: int, max_context: int = 40,
) -> str:
    """Return a one-line snippet of ``text`` around the match span.

    Replaces newlines with spaces inside the snippet so the prompt
    stays one visual line.
    """
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    line_text = text[line_start:line_end]
    rel_start = start - line_start
    rel_end = end - line_start
    # Trim around the match if the line is long.
    if len(line_text) > max_context * 2:
        l = max(0, rel_start - max_context)
        r = min(len(line_text), rel_end + max_context)
        prefix = "..." if l > 0 else ""
        suffix = "..." if r < len(line_text) else ""
        line_text = prefix + line_text[l:r] + suffix
    return line_text


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)

    file_path = Path(args.file)
    if not file_path.is_file():
        _flush_print(
            f"[error] File not found: {file_path}", end="\n",
        )
        return 2
    try:
        original = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        _flush_print(
            f"[error] Cannot decode {file_path} as UTF-8: {exc}",
        )
        return 2

    flags = 0 if args.case_sensitive else re.IGNORECASE
    if args.regex:
        try:
            regex = re.compile(args.pattern, flags)
        except re.error as exc:
            _flush_print(f"[error] Invalid regex: {exc}")
            return 2
    else:
        regex = re.compile(re.escape(args.pattern), flags)

    matches = list(regex.finditer(original))
    if not matches:
        _flush_print(
            f"[done] No matches for {args.pattern!r} in {file_path.name}.",
        )
        return 0

    _flush_print(
        f"[start] {len(matches)} match(es) for {args.pattern!r} "
        f"in {file_path.name}",
    )
    _flush_print("Answer y / n / ! / q for each match.")
    _flush_print("")

    accept_all = False
    edits: list[tuple[int, int, str]] = []  # (start, end, replacement)
    quit_requested = False

    for idx, m in enumerate(matches, 1):
        replacement = m.expand(args.replacement) if args.regex else args.replacement
        context = _format_context(original, m.start(), m.end())
        _flush_print(
            f"[{idx}/{len(matches)}] {context}",
        )
        _flush_print(
            f"        replace {m.group(0)!r} -> {replacement!r}?",
        )
        if accept_all:
            answer = "y"
            _flush_print("        (auto: !)")
        else:
            _flush_print("        [y/n/!/q]:", end=" ")
            answer = _read_answer()

        if answer == "y":
            edits.append((m.start(), m.end(), replacement))
            _flush_print("        accepted.")
        elif answer == "!":
            edits.append((m.start(), m.end(), replacement))
            accept_all = True
            _flush_print("        accepted (and accepting all remaining).")
        elif answer == "q":
            _flush_print("        quit requested.")
            quit_requested = True
            break
        elif answer == "n":
            _flush_print("        skipped.")
        else:
            _flush_print(
                f"        unrecognised answer {answer!r} - treating as n (skip)",
            )

    # Apply edits in reverse so earlier indices stay valid.
    if edits:
        new_text = original
        for start, end, repl in reversed(edits):
            new_text = new_text[:start] + repl + new_text[end:]

        if args.dry_run:
            _flush_print(
                f"[done] {len(edits)} edit(s) accepted, "
                f"file NOT written (--dry-run)."
            )
        else:
            file_path.write_text(new_text, encoding="utf-8")
            _flush_print(
                f"[done] Wrote {len(edits)} edit(s) to {file_path.name}.",
            )
    else:
        _flush_print("[done] No edits accepted; file unchanged.")

    return 1 if quit_requested else 0


if __name__ == "__main__":
    sys.exit(main())
