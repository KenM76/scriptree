"""Re-embed name-appropriate icons in shipped .scriptree[tree] catalogs.

Background: prior bulk-embed passes baked the same generic "tool"
glyph into every sub-tool of a multi-leaf app (ffmpeg, outlook
migration, etc.).  The cell menu therefore shows a wall of
identical icons.  This script walks one or more directories, picks
a sensible bundled glyph per catalog (hand-curated overrides first,
``icon_assets.classify_icon`` heuristic as fallback), and re-embeds
the chosen ``icons/icon-<name>.png`` via the production
``embed_icon`` helper.

Default targets — the apps the user has flagged:
  * R:/ScripTreeApps/ffmpeg/
  * R:/ScripTreeApps/outlook_migration/
  * the OneDrive mirrors of both.

Idempotent: re-running embeds the same bytes again (the bundled
PNG hasn't changed), so subsequent runs are no-ops on disk by md5.

Usage:
    python scripts/refresh_app_icons.py            # default targets
    python scripts/refresh_app_icons.py DIR ...    # custom dirs
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the in-tree scriptree package importable when running this
# script from anywhere.
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scriptree.core.cell_metadata import embed_icon  # noqa: E402
from scriptree.shell.icon_assets import (             # noqa: E402
    bundled_icon_png_path, classify_icon,
)


# Hand-curated per-stem icon picks.  Keys are the catalog FILE STEM
# (no extension, case-insensitive); values are the bundled icon
# name (the ``<name>`` of ``icon-<name>.png``).  Anything not listed
# falls through to ``classify_icon(name=ToolDef.name)``.
_OVERRIDES: dict[str, str] = {
    # --- ffmpeg ---------------------------------------------------
    "compress": "archive",            # bitrate/size reduction
    "concat": "link",                 # join clips end-to-end
    "convert": "convert",
    "crop": "scissors",
    "extract-audio": "audio",
    "extract-frames": "image",
    "ffmpeg-advanced": "settings",    # power-user pass-through
    "ffmpeg": "video",                # the .scriptreetree itself
    "ffprobe": "search",              # inspect / probe
    "gif": "image",
    "resize": "ruler",                # explicit dimensions
    "rotate-flip": "convert",
    "speed": "clock",                 # time-stretch
    "subtitles": "document",
    "thumbnail": "image",
    "trim": "scissors",
    "volume": "audio",
    "watermark": "image",
    # --- outlook migration ---------------------------------------
    # Differentiated by *operation* so the column doesn't read as
    # five identical email icons — the row label tells the user
    # it's Outlook; the icon tells them WHAT each one does.
    "outlookmigration": "email",      # the .scriptreetree itself
    "backup_outlook_data": "archive",
    "restore_outlook_data": "download",
    "inventory_outlook_data": "search",
    "transfer_outlook_pst": "upload",
    "transfer_outlook_autocomplete": "key",  # autocomplete = stored key/data
    "merge_autocomplete_addresses": "link",
}


def _pick_icon(p: Path) -> str:
    """Decide which bundled icon name to embed in ``p``."""
    stem = p.stem.lower()
    # Strip trailing ".scriptree" if the path is a .scriptreetree
    # (Path.stem only drops one extension).
    if stem.endswith(".scriptree"):
        stem = stem[: -len(".scriptree")]
    if stem in _OVERRIDES:
        return _OVERRIDES[stem]
    # Heuristic fallback.  Use the file stem as the "name" hint so
    # tools without a hand-pick still get something better than the
    # generic "tool" default whenever the stem carries a keyword.
    return classify_icon(name=p.stem)


def _walk(root: Path) -> list[Path]:
    return sorted(root.rglob("*.scriptree")) + sorted(
        root.rglob("*.scriptreetree")
    )


def refresh(targets: list[Path]) -> int:
    embedded = 0
    skipped = 0
    for root in targets:
        if not root.is_dir():
            print(f"!! skip (not a dir): {root}", file=sys.stderr)
            continue
        print(f"== {root}")
        for cat in _walk(root):
            icon_name = _pick_icon(cat)
            png = bundled_icon_png_path(icon_name)
            if png is None:
                print(
                    f"  !! no bundled icon-{icon_name}.png — skipping "
                    f"{cat.name}",
                    file=sys.stderr,
                )
                skipped += 1
                continue
            try:
                embed_icon(str(cat), str(png))
            except Exception as exc:  # noqa: BLE001
                print(
                    f"  !! embed_icon failed on {cat.name}: {exc!r}",
                    file=sys.stderr,
                )
                skipped += 1
                continue
            embedded += 1
            print(f"  {cat.name:42}  <- icon-{icon_name}.png")
    print(
        f"\nDone — embedded {embedded}, skipped {skipped} "
        f"(targets: {len(targets)})"
    )
    return embedded


_DEFAULT_TARGETS = [
    Path("R:/ScripTreeApps/ffmpeg"),
    Path("R:/ScripTreeApps/outlook_migration"),
    Path(
        "C:/Users/Ken/OneDrive/Kens_Projects/Claude/Software/"
        "ScripTreeApps/ffmpeg"
    ),
    Path(
        "C:/Users/Ken/OneDrive/Kens_Projects/Claude/Software/"
        "ScripTreeApps/outlook_migration"
    ),
]


def main() -> None:
    if len(sys.argv) > 1:
        targets = [Path(a) for a in sys.argv[1:]]
    else:
        targets = _DEFAULT_TARGETS
    refresh(targets)


if __name__ == "__main__":
    main()
