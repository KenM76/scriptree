"""``scriptree migrate <path>`` — upgrade v2 ``.scriptree`` files
to the v3 JSON-Schema-aligned vocabulary.

## For humans

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

The ``int``/``str``/``spinbox``/``radiobutton``/``select`` entries
fold legacy LLM-noise aliases — Python primitives or non-canonical
widget names a model reaches for instead of the canonical vocabulary.

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

## For maintainers / LLMs

- Idempotency is a hard contract: a second run on migrated files
  MUST change nothing. Any new rename rule must be a no-op on its
  own target value (the rename maps are not closures over their
  own values, which is what keeps re-runs inert).
- ``_TARGET_SCHEMA_VERSION = 3``. ``schema_version`` change is
  driven by ``cur_version != _TARGET`` (not ``<``), so a file at a
  hypothetical higher version would be force-downgraded to 3 —
  intentional today, revisit if v4 ships.
- Walks BOTH ``.scriptree`` and ``.scriptreetree`` (v0.5.3).
  ``.scriptreetree`` has no ``params`` so the type/widget maps are
  inert there; only ``schema_version`` is bumped. ``.scriptreering``
  / ``.scriptreeforest`` have independent ``"version"`` keys under
  their own ``"format"`` discriminator and are deliberately NOT
  migrated here — do not add their suffixes to
  ``_MIGRATABLE_SUFFIXES``.
- Directory recursion = two ``rglob`` passes (one per suffix) then
  ``sorted``; suffixes are re-checked case-insensitively per file.
  Changing the suffix tuple => keep ``migrate_tree``'s rglob calls
  in sync with ``_MIGRATABLE_SUFFIXES``.
- Unparseable JSON is skipped (warned to stderr), counted as
  scanned but not changed; it never aborts the walk.
- Output is rewritten as ``json.dumps(indent=2) + "\\n"`` (UTF-8):
  formatting/key-order is normalized on any changed file, so a
  "changed" verdict can also reflow whitespace, not just vocab.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
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
    # M1 fix: only ever UPGRADE.  A file already at the target — or,
    # crucially, a *newer* file (a hypothetical schema_version 4) —
    # must not be rewritten.  ``!=`` would silently downgrade a v4
    # file to v3, corrupting it; ``<`` makes the migrator a pure
    # forward step and keeps it idempotent across future versions.
    if cur_version < _TARGET_SCHEMA_VERSION:
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
        # M2 fix: atomic write.  ``path.write_text`` truncates the
        # user's source file then writes — an interruption (disk
        # full, kill, power loss) between those steps leaves a
        # zero/partial ``.scriptree``.  Write to a temp file in the
        # same directory (so ``os.replace`` is atomic — same
        # filesystem) and rename over the original.  On any failure
        # the original is left untouched.
        payload = json.dumps(data, indent=2) + "\n"
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp_name, path)
        except OSError:
            # Best-effort cleanup; never leave the temp behind, and
            # never partially clobber the original.
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
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
