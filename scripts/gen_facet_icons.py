"""Author + rasterise the shipped facet-icon set.

v0.6.9 — the cell/menu icon system needed *variety*: most icon-less
tools were falling back to one generic glyph.  This script:

  1. Writes any *missing* ``icons/icon-<name>.svg`` from the curated
     table below — every entry is a trademark-safe, ``currentColor``,
     2.5-stroke line glyph that obeys ``help/host-software-icon-style.md``
     (and therefore ``tests/test_icon_library.py``).  Existing SVGs are
     left untouched (hand-edits win; this is additive).
  2. Rasterises **every** ``icons/*.svg`` to a sibling ``.png`` (the
     portable/vendored PySide6 has no qsvg plugin, so the runtime
     artifact must be PNG — see ``icon_assets.BUNDLED_FORMAT``).

Idempotent: safe to re-run after adding a new SVG.  Run from anywhere:

    python scripts/gen_facet_icons.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ICONS = Path(__file__).resolve().parents[1] / "icons"

# --- the new glyphs (name -> [1-4 stroke-only elements]) -------------------
#
# Each value is the inner SVG (the element lines only); the header,
# the mandatory "generic … not the trademark" comment, and the
# closing tag are added uniformly so the whole set stays one family.
# Category archetypes, never a vendor mark (style guide §5).

_SVG_HEADER = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" '
    'fill="none" aria-hidden="true">'
)

_NEW: dict[str, tuple[str, str]] = {
    # name: (human category for the comment, inner elements)
    "script": (
        "script/automation",
        '  <rect x="10" y="6" width="28" height="36" rx="2" '
        'stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"/>\n'
        '  <path d="M16 19l5 4-5 4" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round" '
        'stroke-linejoin="round"/>\n'
        '  <path d="M26 27h8" stroke="currentColor" stroke-width="2.5" '
        'stroke-linecap="round"/>',
    ),
    "network": (
        "network/nodes",
        '  <circle cx="24" cy="10" r="4" stroke="currentColor" '
        'stroke-width="2.5"/>\n'
        '  <circle cx="12" cy="36" r="4" stroke="currentColor" '
        'stroke-width="2.5"/>\n'
        '  <circle cx="36" cy="36" r="4" stroke="currentColor" '
        'stroke-width="2.5"/>\n'
        '  <path d="M22 14l-8 18M26 14l8 18M16 36h16" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linecap="round" stroke-linejoin="round"/>',
    ),
    "download": (
        "download",
        '  <path d="M9 31v8h30v-8" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round" '
        'stroke-linejoin="round"/>\n'
        '  <path d="M24 8v22" stroke="currentColor" stroke-width="2.5" '
        'stroke-linecap="round"/>\n'
        '  <path d="M15 22l9 9 9-9" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round" '
        'stroke-linejoin="round"/>',
    ),
    "upload": (
        "upload",
        '  <path d="M9 31v8h30v-8" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round" '
        'stroke-linejoin="round"/>\n'
        '  <path d="M24 38V16" stroke="currentColor" stroke-width="2.5" '
        'stroke-linecap="round"/>\n'
        '  <path d="M15 25l9-9 9 9" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round" '
        'stroke-linejoin="round"/>',
    ),
    "build": (
        "build/blocks",
        '  <rect x="7" y="26" width="15" height="13" rx="1" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linejoin="round"/>\n'
        '  <rect x="26" y="26" width="15" height="13" rx="1" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linejoin="round"/>\n'
        '  <rect x="16" y="9" width="16" height="13" rx="1" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linejoin="round"/>',
    ),
    "test": (
        "test/flask",
        '  <path d="M20 7h8M22 7v13L12 37a3 3 0 003 5h18a3 3 0 003-5'
        'L26 20V7" stroke="currentColor" stroke-width="2.5" '
        'stroke-linecap="round" stroke-linejoin="round"/>\n'
        '  <path d="M17 31h14" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round"/>',
    ),
    "lock": (
        "lock/security",
        '  <rect x="10" y="21" width="28" height="20" rx="2" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linejoin="round"/>\n'
        '  <path d="M16 21v-5a8 8 0 0116 0v5" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round" '
        'stroke-linejoin="round"/>\n'
        '  <path d="M24 28v6" stroke="currentColor" stroke-width="2.5" '
        'stroke-linecap="round"/>',
    ),
    "key": (
        "key/credential",
        '  <circle cx="16" cy="17" r="8" stroke="currentColor" '
        'stroke-width="2.5"/>\n'
        '  <path d="M22 23l16 16M33 34l5-5M28 29l4 4" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linecap="round" stroke-linejoin="round"/>',
    ),
    "cloud": (
        "cloud",
        '  <path d="M16 38a9 9 0 01-1-18 12 12 0 0123-3 8 8 0 012 21z" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linejoin="round"/>',
    ),
    "server": (
        "server/rack",
        '  <rect x="8" y="8" width="32" height="14" rx="2" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linejoin="round"/>\n'
        '  <rect x="8" y="26" width="32" height="14" rx="2" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linejoin="round"/>\n'
        '  <path d="M13 15h5M13 33h5" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round"/>',
    ),
    "chart": (
        "chart/analytics",
        '  <path d="M10 8v32h30" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round" '
        'stroke-linejoin="round"/>\n'
        '  <path d="M18 40V27M26 40V15M34 40V22" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linecap="round"/>',
    ),
    "calendar": (
        "calendar/schedule",
        '  <rect x="8" y="11" width="32" height="29" rx="2" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linejoin="round"/>\n'
        '  <path d="M8 19h32" stroke="currentColor" '
        'stroke-width="2.5"/>\n'
        '  <path d="M17 6v9M31 6v9" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round"/>',
    ),
    "audio": (
        "audio/sound",
        '  <path d="M10 19h6l9-7v24l-9-7h-6z" stroke="currentColor" '
        'stroke-width="2.5" stroke-linejoin="round"/>\n'
        '  <path d="M31 18a8 8 0 010 12M35 14a13 13 0 010 20" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linecap="round"/>',
    ),
    "video": (
        "video/film",
        '  <rect x="6" y="12" width="36" height="24" rx="3" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linejoin="round"/>\n'
        '  <path d="M21 19l10 5-10 5z" stroke="currentColor" '
        'stroke-width="2.5" stroke-linejoin="round"/>',
    ),
    "edit": (
        "edit/pencil",
        '  <path d="M30 8l10 10-23 23H7v-10z" stroke="currentColor" '
        'stroke-width="2.5" stroke-linejoin="round"/>\n'
        '  <path d="M26 12l10 10" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round"/>',
    ),
    "convert": (
        "convert/transform",
        '  <path d="M11 19a14 14 0 0124-7" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round"/>\n'
        '  <path d="M37 29a14 14 0 01-24 7" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round"/>\n'
        '  <path d="M30 9l6 3-3 6M18 39l-6-3 3-6" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linecap="round" stroke-linejoin="round"/>',
    ),
    "filter": (
        "filter/funnel",
        '  <path d="M8 10h32L27 27v11l-6 4V27z" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round" '
        'stroke-linejoin="round"/>',
    ),
    "pin": (
        "location/pin",
        '  <path d="M24 42c8-9 12-15 12-22a12 12 0 10-24 0c0 7 4 13 '
        '12 22z" stroke="currentColor" stroke-width="2.5" '
        'stroke-linejoin="round"/>\n'
        '  <circle cx="24" cy="20" r="4" stroke="currentColor" '
        'stroke-width="2.5"/>',
    ),
    "printer": (
        "printer",
        '  <path d="M14 18V8h20v10" stroke="currentColor" '
        'stroke-width="2.5" stroke-linejoin="round"/>\n'
        '  <rect x="8" y="18" width="32" height="14" rx="2" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linejoin="round"/>\n'
        '  <rect x="14" y="30" width="20" height="10" rx="1" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linejoin="round"/>',
    ),
    "scissors": (
        "scissors/cut",
        '  <circle cx="14" cy="14" r="5" stroke="currentColor" '
        'stroke-width="2.5"/>\n'
        '  <circle cx="14" cy="34" r="5" stroke="currentColor" '
        'stroke-width="2.5"/>\n'
        '  <path d="M18 17l22 16M18 31L40 15" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round" '
        'stroke-linejoin="round"/>',
    ),
    "ruler": (
        "ruler/measure",
        '  <rect x="6" y="18" width="36" height="12" rx="2" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linejoin="round"/>\n'
        '  <path d="M14 18v6M21 18v9M28 18v6M35 18v9" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linecap="round"/>',
    ),
    "chip": (
        "processor/chip",
        '  <rect x="14" y="14" width="20" height="20" rx="2" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linejoin="round"/>\n'
        '  <path d="M20 14V8M28 14V8M20 34v6M28 34v6M14 20H8M14 28H8'
        'M34 20h6M34 28h6" stroke="currentColor" stroke-width="2.5" '
        'stroke-linecap="round"/>',
    ),
    "package": (
        "package/parcel",
        '  <path d="M24 6l16 9v18l-16 9-16-9V15z" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linejoin="round"/>\n'
        '  <path d="M8 15l16 9 16-9M24 24v18" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round" '
        'stroke-linejoin="round"/>',
    ),
    "bug": (
        "bug/debug",
        '  <circle cx="24" cy="26" r="10" stroke="currentColor" '
        'stroke-width="2.5"/>\n'
        '  <path d="M24 16v-4M14 21l-5-4M34 21l5-4M14 26H7M34 26h7'
        'M15 34l-5 5M33 34l5 5" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round"/>',
    ),
    "link": (
        "link/chain",
        '  <path d="M19 29l10-10" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round"/>\n'
        '  <path d="M16 24l-4 4a6 6 0 008 8l4-4" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linecap="round" stroke-linejoin="round"/>\n'
        '  <path d="M32 24l4-4a6 6 0 00-8-8l-4 4" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linecap="round" stroke-linejoin="round"/>',
    ),
    "shield": (
        "shield/protect",
        '  <path d="M24 6l14 5v11c0 9-6 16-14 20-8-4-14-11-14-20V11z" '
        'stroke="currentColor" stroke-width="2.5" '
        'stroke-linejoin="round"/>\n'
        '  <path d="M18 24l4 4 9-10" stroke="currentColor" '
        'stroke-width="2.5" stroke-linecap="round" '
        'stroke-linejoin="round"/>',
    ),
}


def _svg_for(name: str) -> str:
    category, inner = _NEW[name]
    comment = (
        f"  <!-- Generic {category} shape — placeholder, "
        f"not a vendor trademark logo -->"
    )
    return f"{_SVG_HEADER}\n{comment}\n{inner}\n</svg>\n"


def write_missing_svgs() -> list[str]:
    created: list[str] = []
    for name in _NEW:
        p = _ICONS / f"icon-{name}.svg"
        if p.exists():
            continue
        p.write_text(_svg_for(name), encoding="utf-8")
        created.append(p.name)
    return created


def rasterise_all() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication
    from PySide6.QtSvg import QSvgRenderer

    _ = QApplication.instance() or QApplication([])
    count = 0
    for svg in sorted(_ICONS.glob("*.svg")):
        png = svg.with_suffix(".png")
        r = QSvgRenderer(str(svg))
        if not r.isValid():
            print(f"  !! invalid SVG: {svg.name}", file=sys.stderr)
            continue
        img = QImage(256, 256, QImage.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        r.render(p)
        p.end()
        img.save(str(png), "PNG")
        count += 1
    return count


def main() -> None:
    created = write_missing_svgs()
    if created:
        print(f"created {len(created)} new SVG(s): {', '.join(created)}")
    else:
        print("no new SVGs (all present)")
    n = rasterise_all()
    print(f"rasterised {n} icon(s) to PNG")


if __name__ == "__main__":
    main()
