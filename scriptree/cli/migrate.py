"""``scriptree migrate <path>`` — upgrade v2 ``.scriptree`` files
to the v3 JSON-Schema-aligned vocabulary.

Renames applied (v2 → v3):

  type  : ``bool``       → ``boolean``
          ``float``      → ``number``
          ``int``        → ``integer``    (past LLM-noise)
          ``str``        → ``string``     (past LLM-noise)

  widget: ``file_open``  → ``file``
          ``file_save``  → ``save_file``
          ``enum_radio`` → ``radio``
          ``spinbox``    → ``number``     (past LLM-noise)
          ``radiobutton``→ ``radio``      (past LLM-noise)
          ``select``     → ``dropdown``   (past LLM-noise)

Also bumps ``schema_version`` from anything < 3 to 3.

Usage::

    python -m scriptree.cli.migrate path/to/tool.scriptree
    python -m scriptree.cli.migrate path/to/tree/            # recurse

The script is idempotent — re-running on already-migrated files
is a no-op.  Output: one ``migrated: <path>`` line per file
actually changed, plus a summary count at the end.

Flags:

  --dry-run   Print what WOULD change without writing.
  --quiet     Suppress per-file output; only print the summary.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


_RENAMES_TYPE = {
    "bool": "boolean",
    "float": "number",
    # LLM-noise (Python primitives the model reaches for when
    # in a Python context instead of JSON):
    "int": "integer",
    "str": "string",
}

_RENAMES_WIDGET = {
    "file_open": "file",
    "file_save": "save_file",
    "enum_radio": "radio",
    # LLM-noise:
    "spinbox": "number",
    "radiobutton": "radio",
    "select": "dropdown",
}

_TARGET_SCHEMA_VERSION = 3


def migrate_one(
    path: Path,
    *,
    dry_run: bool = False,
    log: callable = print,
) -> bool:
    """Migrate a single ``.scriptree`` or ``.scriptreetree`` file.

    Returns True iff the file was changed (or would be, in
    dry-run mode).  Skips files whose JSON can't be parsed,
    logging a warning to stderr.

    v0.5.3 — also walks ``.scriptreetree`` (tree-catalog) files,
    which share the main schema_version trajectory.  They don't
    have ``params`` so the type/widget rename map is inert there;
    we only bump ``schema_version``.  The separate
    ``.scriptreering`` / ``.scriptreeforest`` formats keep their
    own ``"version"`` keys under their own ``"format"`` discriminator
    and are deliberately NOT touched here.
    """
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  SKIP {path}: {exc!r}", file=sys.stderr)
        return False

    changed = False

    cur_version = data.get("schema_version", 1)
    if cur_version != _TARGET_SCHEMA_VERSION:
        data["schema_version"] = _TARGET_SCHEMA_VERSION
        changed = True

    for p in data.get("params", []) or []:
        if not isinstance(p, dict):
            continue
        cur_type = p.get("type")
        if cur_type in _RENAMES_TYPE:
            p["type"] = _RENAMES_TYPE[cur_type]
            changed = True
        cur_widget = p.get("widget")
        if cur_widget in _RENAMES_WIDGET:
            p["widget"] = _RENAMES_WIDGET[cur_widget]
            changed = True

    if changed and not dry_run:
        path.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )
    if changed:
        log(f"  {'would migrate' if dry_run else 'migrated'}: {path}")
    return changed


# File extensions whose schema_version follows the main 1 → 2 → 3
# trajectory.  Lowercase, with leading dot.  ``.scriptreering`` and
# ``.scriptreeforest`` have their own independent ``"version"`` keys
# under separate ``"format"`` discriminators and are not migrated by
# this CLI.
_MIGRATABLE_SUFFIXES = (".scriptree", ".scriptreetree")


def migrate_tree(
    root: Path,
    *,
    dry_run: bool = False,
    quiet: bool = False,
) -> tuple[int, int]:
    """Walk ``root`` and migrate every ``.scriptree`` / ``.scriptreetree``
    underneath.

    Returns ``(scanned_count, changed_count)``.
    """
    log = (lambda _msg: None) if quiet else print
    scanned = 0
    changed = 0
    if root.is_file():
        targets = [root]
    else:
        # Two passes is simpler than one glob with alternation —
        # globs concatenate, sorting is stable per pass.
        targets = sorted(
            list(root.rglob("*.scriptree"))
            + list(root.rglob("*.scriptreetree"))
        )
    for p in targets:
        if not p.is_file():
            continue
        if p.suffix.lower() not in _MIGRATABLE_SUFFIXES:
            continue
        scanned += 1
        if migrate_one(p, dry_run=dry_run, log=log):
            changed += 1
    return scanned, changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scriptree migrate",
        description=(
            "Upgrade v2 .scriptree files to v3 (JSON-Schema-aligned "
            "type names + HTML5-aligned widget names).  Idempotent; "
            "safe to re-run."
        ),
    )
    parser.add_argument(
        "path",
        type=Path,
        help=(
            "Path to a .scriptree file OR a directory to recurse "
            "through (every .scriptree found is migrated)."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what WOULD change without writing.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-file output; only print the summary.",
    )
    args = parser.parse_args(argv)

    if not args.path.exists():
        print(f"scriptree migrate: not found: {args.path}", file=sys.stderr)
        return 2

    scanned, changed = migrate_tree(
        args.path, dry_run=args.dry_run, quiet=args.quiet,
    )
    verb = "would migrate" if args.dry_run else "migrated"
    suffix = " (dry run)" if args.dry_run else ""
    print(f"scriptree migrate: {verb} {changed}/{scanned} file(s){suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
