#!/usr/bin/env python3
"""One-shot script: add ``"category"`` fields to every ``.scriptree``
in the listed roots, inferring the category from path segments.

This is a maintenance script, not part of the runtime.  Idempotent
(re-running produces the same JSON) and safe to interrupt — each
file write is atomic via ``Path.write_text``.

Usage::

    python scripts/bulk_categorize.py [--dry-run] [<root> ...]

Defaults to every ScripTree-apps root on Ken's machine if no
``<root>`` args are supplied.

Inference: walk the file path back from the ``.scriptree`` to the
enclosing ScripTreeApps (or equivalent) root, and use the segments
in between as the category path -- excluding the file's own
parent if it matches the file stem (the common "tool/tool.scriptree"
layout).

Examples:

* ``D:/Dev/ScripTreeAppProjects/MSOffice/Word/style-sanitizer/style-sanitizer.scriptree``
  -> ``MSOffice/Word`` (style-sanitizer dir matches stem, dropped)

* ``R:/ScripTreeApps/ffmpeg/compress.scriptree``
  -> ``ffmpeg``

* ``R:/ScripTreeApps/SolidWorks/AssemblyPerformance/force-rebuild.scriptree``
  -> ``SolidWorks/AssemblyPerformance``

* ``D:/Dev/ScripTree/ScripTreeApps/Demos/agg/agg.scriptree``
  -> ``Demos`` (the demos are flat-ish; only the top-level Demos
  bucket is meaningful, the inner subfolder is just the tool name)

Special-case overrides (applied before path inference):

* ``ScripTreeManagement/*.scriptree`` -> ``ScripTree`` (internal
  ScripTree maintenance tools)
* ``Demos/<tool>/<tool>.scriptree`` and ``Demos/<tool>.scriptree``
  -> ``Demos`` (deliberately flat; demos showcase variety, not a
  taxonomy)
* ``detail_drawings_to_burn_dxf/*.scriptree`` -> ``SolidWorks/DxfPipeline``
* ``outlook_migration/*.scriptree`` -> ``MSOffice/OutlookMigration``
* ``MSOffice/<App>/<tool>/<tool>.scriptree`` -> ``MSOffice/<App>``
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# Default roots — Ken's machine layout per the project rules.
DEFAULT_ROOTS = [
    Path(r"D:\Dev\ScripTreeAppProjects"),
    Path(r"D:\Dev\ScripTree\ScripTreeApps"),
    Path(r"R:\ScripTreeApps"),
    Path(r"R:\ScripTree\ScripTreeApps"),
    Path(r"C:\Users\Ken\OneDrive\Kens_Projects\Claude\Software\ScripTreeApps"),
    Path(r"C:\Users\Ken\OneDrive\Kens_Projects\Claude\Software\ScripTree\ScripTreeApps"),
]


# Path-segment renames applied before walking up the path -- maps the
# *first* segment seen (relative to the apps root) to the canonical
# top-level category we want in the JSON.  Most segments map to
# themselves; this lets us rename a folder name to a friendlier
# category without changing the on-disk layout.
SEGMENT_RENAMES: dict[str, str] = {
    "detail_drawings_to_burn_dxf": "SolidWorks/DxfPipeline",
    "outlook_migration": "MSOffice/OutlookMigration",
    "SolidWorksTools": "SolidWorks",  # legacy OneDrive folder name
    "ScripTreeManagement": "ScripTree",
    # Demos are intentionally flat -- one big bucket.
    "Demos": "Demos",
    # Legacy OneDrive top-level folders -- promote to SolidWorks
    # subcategories so they group under the same hub as everything else.
    "SwDxfExport": "SolidWorks/DxfExport",
    "sw_bridge": "SolidWorks/SwBridge",
    "dxf-cleanup": "SolidWorks/DxfExport",
    "dxf-export": "SolidWorks/DxfExport",
    "dxf-export-v2": "SolidWorks/DxfExport",
    "dxf-to-pdf": "SolidWorks/DxfExport",
    # robocopy is a Windows file-copy utility -- a Tools/Networking
    # type tool.  Lump under DevTools as a reasonable default.
    "robocopy": "DevTools/Robocopy",
}


# Roots that may exist as parent of the file -- everything ABOVE
# this directory name is install layout, not category.  Walks the
# file's parents to find the first matching ancestor.
APPS_ROOT_NAMES = {
    "scriptreeapps",
    "scriptreeappprojects",
    "scriptreeapprojects",
}


def _find_apps_root(p: Path) -> Path | None:
    """Walk up from ``p`` until we find one of the known apps-root
    folder names (case-insensitive)."""
    for ancestor in p.parents:
        if ancestor.name.lower() in APPS_ROOT_NAMES:
            return ancestor
    return None


def _infer_category(scriptree_path: Path) -> str:
    """Infer a category string from the file's path.

    Algorithm:

    1. Locate the apps-root ancestor (``ScripTreeApps`` /
       ``ScripTreeAppProjects``).  If none, return ``""``.
    2. Walk the segments between apps-root and the file.  Drop the
       last segment if it matches the file stem (the common
       ``foo/foo.scriptree`` layout where the wrapper folder
       duplicates the tool name).
    3. Apply ``SEGMENT_RENAMES`` to the first segment: if found,
       substitute (preserving any deeper segments).
    4. Join with ``/``.

    Returns ``""`` when the file is directly under the apps root
    with no taxonomy.
    """
    root = _find_apps_root(scriptree_path)
    if root is None:
        return ""
    try:
        rel = scriptree_path.relative_to(root)
    except ValueError:
        return ""
    # rel = e.g.  MSOffice/Word/style-sanitizer/style-sanitizer.scriptree
    segments = list(rel.parts[:-1])  # drop the .scriptree filename
    if not segments:
        return ""
    stem = scriptree_path.stem  # 'style-sanitizer'
    # Drop trailing wrapper folder that duplicates the tool stem.
    if segments and segments[-1].lower() == stem.lower():
        segments = segments[:-1]
    if not segments:
        # The tool was at apps-root with a wrapper folder named for
        # itself -- e.g. ``ScripTreeApps/style-sanitizer/style-sanitizer.scriptree``
        # -- giving it no category metadata.  Skip.
        return ""
    # Apply rename to top segment.  Preserves any deeper segments.
    top = segments[0]
    if top in SEGMENT_RENAMES:
        rename = SEGMENT_RENAMES[top]
        return "/".join([rename] + segments[1:])
    return "/".join(segments)


def _update_one(p: Path, *, dry_run: bool) -> tuple[bool, str]:
    """Read ``p``, infer category, write back.  Returns
    ``(changed, message)`` for stdout logging."""
    try:
        text = p.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        return (False, f"SKIP  {p}  (unreadable: {exc!r})")
    inferred = _infer_category(p)
    if not inferred:
        return (False, f"-     {p}  (no category)")
    existing = data.get("category", "")
    if existing == inferred:
        return (False, f"=     {p}  (already {inferred!r})")
    if existing and existing != inferred:
        # Already had a non-empty category that differs -- leave
        # it alone; the user's explicit value wins over our
        # inferred one.
        return (False, f"keep  {p}  (had {existing!r}, would have set {inferred!r})")
    data["category"] = inferred
    if dry_run:
        return (True, f"WOULD {p}  -> {inferred}")
    # Write back, preserving 2-space indent the loader uses.
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return (True, f"SET   {p}  -> {inferred}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would change without writing.",
    )
    parser.add_argument(
        "roots", nargs="*", type=Path, default=DEFAULT_ROOTS,
        help="ScripTree-apps roots to walk.  Defaults to Ken's "
             "machine layout when omitted.",
    )
    args = parser.parse_args(argv)

    total = 0
    changed = 0
    for root in args.roots:
        if not root.exists():
            print(f"missing root: {root}", file=sys.stderr)
            continue
        print(f"=== walking {root} ===")
        for p in root.rglob("*.scriptree"):
            # Filter: the .scriptreetree extension shares a prefix.
            if p.name.endswith(".scriptreetree"):
                continue
            total += 1
            did_change, msg = _update_one(p, dry_run=args.dry_run)
            print(msg)
            if did_change:
                changed += 1
    print(f"---\n{changed}/{total} files changed (dry-run={args.dry_run}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
