"""The shipped ``icons/`` set must obey help/host-software-icon-style.md.

Locks the invariant skeleton so any icon added later (by a human or
an LLM) that breaks the style is caught in CI rather than shipping a
ragged / un-themeable / trademark-risky glyph. Also asserts every
icon renders non-blank through the same pipeline the cell menu /
tree view use.
"""
from __future__ import annotations

import re
import xml.dom.minidom
from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

_ICONS_DIR = Path(__file__).resolve().parents[1] / "icons"
_SVGS = sorted(_ICONS_DIR.glob("*.svg"))


def test_icon_library_present() -> None:
    assert _ICONS_DIR.is_dir(), "icons/ directory missing"
    assert len(_SVGS) >= 20, f"expected the full set, got {len(_SVGS)}"
    # The reference archetypes from the style guide must exist.
    names = {p.stem for p in _SVGS}
    for required in (
        "icon-cli", "icon-solidworks", "icon-msoffice",
        "icon-spreadsheet", "icon-folder", "icon-tool",
    ):
        assert required in names, f"missing {required}.svg"


@pytest.mark.parametrize("svg", _SVGS, ids=lambda p: p.name)
def test_icon_obeys_style_skeleton(svg: Path) -> None:
    text = svg.read_text(encoding="utf-8")

    # Well-formed XML.
    xml.dom.minidom.parseString(text)

    # Invariant skeleton (style guide §2).
    assert 'viewBox="0 0 48 48"' in text, "must use the 48 grid"
    assert 'fill="none"' in text, "root must be fill=none"
    assert 'aria-hidden="true"' in text
    assert "width=" not in text.split(">", 1)[0], \
        "no hardcoded width on <svg> (breaks responsive sizing)"
    assert "height=" not in text.split(">", 1)[0], \
        "no hardcoded height on <svg>"
    # Mandatory leading generic / not-a-trademark comment.
    assert re.search(r"<!--.*(generic|placeholder).*-->",
                     text, re.I | re.S), \
        "missing the 'generic … not the trademark' comment"

    # Every stroke is currentColor — never a literal/hex/named colour
    # (that would break currentColor theming).
    for m in re.finditer(r'stroke="([^"]+)"', text):
        assert m.group(1) == "currentColor", \
            f"non-currentColor stroke {m.group(1)!r} in {svg.name}"
    # No fills on shapes (these are line glyphs); root fill=none only.
    assert text.count('fill="') == 1, \
        f"only the root fill=none allowed in {svg.name}"

    # Stroke weight is 2.5 (a single nested detail may be 2).
    widths = set(re.findall(r'stroke-width="([0-9.]+)"', text))
    assert widths and widths <= {"2.5", "2"}, \
        f"stroke-width must be 2.5 (or 2 for one detail): {widths}"

    # 1–4 drawable primitives.
    prims = (text.count("<rect") + text.count("<circle")
             + text.count("<path"))
    assert 1 <= prims <= 4, f"{svg.name}: {prims} primitives (want 1–4)"


@pytest.mark.parametrize("svg", _SVGS, ids=lambda p: p.name)
def test_icon_renders_non_blank(svg: Path) -> None:
    from PySide6.QtGui import QColor, QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer

    raw = svg.read_bytes()
    r = QSvgRenderer(raw)
    assert r.isValid(), f"{svg.name}: QSvgRenderer invalid"
    pm = QPixmap(24, 24)
    pm.fill(QColor("white"))
    p = QPainter(pm)
    r.render(p)
    p.end()
    img = pm.toImage()
    nonwhite = sum(
        1 for y in range(24) for x in range(24)
        if img.pixelColor(x, y) != QColor("white")
    )
    assert nonwhite >= 10, \
        f"{svg.name}: renders blank/near-blank at 24px ({nonwhite}px)"


def test_embedded_catalog_icon_round_trips(tmp_path: Path) -> None:
    """A catalog with an embedded icons/ SVG resolves to a non-null
    QIcon through the production helper."""
    import json
    from scriptree.core.cell_metadata import (
        embed_icon, qicon_for_catalog, read_for,
    )
    cat = tmp_path / "t.scriptree"
    cat.write_text(json.dumps({
        "schema_version": 3, "name": "t",
        "executable": "echo", "params": [],
    }), encoding="utf-8")
    embed_icon(str(cat), str(_ICONS_DIR / "icon-cli.svg"))
    md = read_for(cat)
    assert md.has_icon() and md.icon_format == "svg"
    ic = qicon_for_catalog(str(cat))
    assert ic is not None and not ic.isNull()


# ---------------------------------------------------------------------------
# v0.6.7 — ring/forest hub icons + icon_assets
# ---------------------------------------------------------------------------

def test_icon_assets_resolves_bundled_set() -> None:
    from scriptree.shell.icon_assets import bundled_icon_b64, icons_dir
    assert icons_dir() is not None
    import base64
    for nm in ("container", "folder", "tool", "cli"):
        b = bundled_icon_b64(nm)
        assert b, f"bundled icon {nm} empty"
        # Valid base64 of a real SVG.
        assert b"<svg" in base64.b64decode(b)
    assert bundled_icon_b64("definitely-not-an-icon") == ""


def test_forest_icon_round_trips_and_is_additive(tmp_path) -> None:
    from scriptree.shell.forest_io import (
        ForestDef, load_forest, save_forest,
    )
    import json
    p = tmp_path / "f.scriptreeforest"
    # No icon → key absent (byte-stability contract).
    save_forest(ForestDef(name="F"), str(p))
    assert "icon_data" not in json.loads(p.read_text())
    # With icon → round-trips.
    f = load_forest(str(p))
    f.icon_data = "QUJD"  # 'ABC'
    f.icon_format = "svg"
    save_forest(f, str(p))
    blob = json.loads(p.read_text())
    assert blob["icon_data"] == "QUJD" and blob["icon_format"] == "svg"
    f2 = load_forest(str(p))
    assert f2.icon_data == "QUJD" and f2.icon_format == "svg"


def test_ring_hex_dict_icon_data_additive() -> None:
    """_hex_to_dict emits icon_data ONLY when set (legacy rings with
    no embedded icon must stay byte-identical)."""
    from scriptree.shell.ring_io import _hex_to_dict

    class _Stub:
        role = "standalone"
        _id = "x"
        _shape = "hexagon"
        _orientation = "flat-top"
        _size_px = 96
        _transparency = 0.85
        _always_on_top = True

        def __init__(self, **kw):
            self.__dict__.update(kw)

        def pos(self):
            from PySide6.QtCore import QPoint
            return QPoint(0, 0)

    bare = _Stub()
    d = _hex_to_dict(bare)
    assert "icon_data" not in d and "icon_format" not in d

    iconned = _Stub(_icon_data_b64="QUJD", _icon_data_format="svg")
    d2 = _hex_to_dict(iconned)
    assert d2["icon_data"] == "QUJD" and d2["icon_format"] == "svg"
