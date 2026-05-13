"""``scriptree validate <path>`` — verify a ``.scriptree`` file
loads cleanly via the real ``io.load_tool`` path, and that every
param's widget is valid for its type per ``VALID_WIDGETS``.

This is the command automated test harnesses (and LLM hooks)
should run before declaring a ``.scriptree`` file done.  It
catches the failure modes that JSON-shape validation misses —
notably the v0.5.0 vocabulary slip where an LLM writes ``int``
or ``spinbox`` instead of the canonical ``integer`` / ``number``.

Usage::

    python -m scriptree.cli.validate path/to/tool.scriptree
    python -m scriptree.cli.validate path/to/tree/            # recurse

Exit codes:
  * 0 — every file passed
  * 1 — at least one file failed
  * 2 — input path doesn't exist

Output (success)::

    ✓ Valid: path/to/tool.scriptree (34 params)

Output (failure) shows the offending field, the value, the
nearest valid alternative (via difflib), and the full list of
valid values — same format ``io.py``'s loader produces.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def validate_one(path: Path) -> tuple[bool, str]:
    """Validate a single ``.scriptree`` or ``.scriptreetree`` file.

    Returns ``(ok, message)``.  ``ok=True`` ⇒ valid, ``message``
    is a one-line summary.  ``ok=False`` ⇒ invalid, ``message``
    is the loader's error text (already formatted with hints).

    Dispatches by suffix: ``.scriptree`` → ``load_tool``,
    ``.scriptreetree`` → ``load_tree``.
    """
    from scriptree.core.io import load_tool, load_tree
    from scriptree.core.model import VALID_WIDGETS

    suffix = path.suffix.lower()
    try:
        if suffix == ".scriptreetree":
            tree = load_tree(path)
            return True, (
                f"Valid: {path} ({len(tree.nodes)} top-level "
                f"node(s))"
            )
        tool = load_tool(path)
    except (OSError, ValueError) as exc:
        return False, str(exc)

    # Cross-check widget validity against the param's type.
    # ``io.load_tool`` doesn't enforce this (the loader is
    # permissive so legacy / hand-edited files don't hard-fail
    # on a widget mismatch that the editor would tolerate); we
    # do it here so ``validate`` catches it before run time.
    issues: list[str] = []
    for p in tool.params:
        valid_widgets = VALID_WIDGETS.get(p.type, ())
        if p.widget not in valid_widgets:
            allowed = ", ".join(w.value for w in valid_widgets) or "(none)"
            issues.append(
                f"  param {p.id!r}: widget {p.widget.value!r} "
                f"is not valid for type {p.type.value!r}.\n"
                f"    Valid widgets for {p.type.value!r}: {allowed}."
            )
    if issues:
        return False, "Widget / type mismatch:\n" + "\n".join(issues)

    types = sorted({p.type.value for p in tool.params})
    widgets = sorted({p.widget.value for p in tool.params})
    return True, (
        f"Valid: {path} ({len(tool.params)} params; "
        f"types: {', '.join(types)}; widgets: {', '.join(widgets)})"
    )


_VALIDATABLE_SUFFIXES = (".scriptree", ".scriptreetree")


def validate_tree(root: Path) -> tuple[int, int]:
    """Walk ``root`` and validate every ``.scriptree`` and
    ``.scriptreetree`` underneath.

    Returns ``(scanned_count, failed_count)``.
    """
    if root.is_file():
        targets = [root]
    else:
        targets = sorted(
            list(root.rglob("*.scriptree"))
            + list(root.rglob("*.scriptreetree"))
        )
    scanned = 0
    failed = 0
    # ASCII markers — Windows consoles often run cp1252 which
    # can't encode ✓/✗.  Stick to OK / FAIL so output renders
    # cleanly everywhere.
    for p in targets:
        if not p.is_file():
            continue
        if p.suffix.lower() not in _VALIDATABLE_SUFFIXES:
            continue
        scanned += 1
        ok, msg = validate_one(p)
        marker = "OK  " if ok else "FAIL"
        print(f"[{marker}] {msg}")
        if not ok:
            failed += 1
    return scanned, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scriptree validate",
        description=(
            "Verify .scriptree files load cleanly via the real "
            "loader and that every widget matches its param's "
            "type."
        ),
    )
    parser.add_argument(
        "path",
        type=Path,
        help=(
            "Path to a .scriptree file OR a directory to recurse "
            "through (every .scriptree found is validated)."
        ),
    )
    args = parser.parse_args(argv)

    if not args.path.exists():
        print(f"scriptree validate: not found: {args.path}", file=sys.stderr)
        return 2

    scanned, failed = validate_tree(args.path)
    if scanned == 0:
        print(
            f"scriptree validate: no .scriptree files found under "
            f"{args.path}", file=sys.stderr,
        )
        return 2
    if failed:
        print(
            f"\nscriptree validate: {failed}/{scanned} failed."
        )
        return 1
    print(f"\nscriptree validate: {scanned}/{scanned} valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
