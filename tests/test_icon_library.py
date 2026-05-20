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


@pytest.mark.parametrize("svg", _SVGS, ids=lambda p: p.name)
def test_every_icon_has_a_png_runtime_artifact(svg: Path) -> None:
    """v0.6.8: the embed/runtime artifact is PNG (the portable
    vendored PySide6 has no qsvg plugin / QtSvg, so embedded SVG
    renders blank there).  Every spec .svg must have a sibling
    .png that decodes via the plugin-less core path
    (QPixmap.loadFromData(bytes,"PNG"))."""
    from PySide6.QtGui import QPixmap
    png = svg.with_suffix(".png")
    assert png.is_file(), f"missing runtime artifact {png.name}"
    pm = QPixmap()
    assert pm.loadFromData(png.read_bytes(), "PNG"), \
        f"{png.name}: QPixmap could not decode PNG"
    assert not pm.isNull() and pm.width() >= 48


def test_bundled_icon_format_is_png() -> None:
    from scriptree.shell.icon_assets import (
        BUNDLED_FORMAT, bundled_icon_b64,
    )
    import base64
    assert BUNDLED_FORMAT == "png"
    raw = base64.b64decode(bundled_icon_b64("folder").encode("ascii"))
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "hub icon must be a PNG"


def test_embedded_catalog_icon_round_trips(tmp_path: Path) -> None:
    """A catalog with an embedded PNG resolves to a non-null QIcon
    through the production helper (the portable-safe path)."""
    import json
    from scriptree.core.cell_metadata import (
        embed_icon, qicon_for_catalog, read_for,
    )
    cat = tmp_path / "t.scriptree"
    cat.write_text(json.dumps({
        "schema_version": 3, "name": "t",
        "executable": "echo", "params": [],
    }), encoding="utf-8")
    embed_icon(str(cat), str(_ICONS_DIR / "icon-cli.png"))
    md = read_for(cat)
    assert md.has_icon() and md.icon_format == "png"
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
        # v0.6.8: the bundled runtime artifact is PNG (renders in
        # the plugin-less portable runtime), not SVG.
        assert base64.b64decode(b)[:8] == b"\x89PNG\r\n\x1a\n"
    assert bundled_icon_b64("definitely-not-an-icon") == ""


def test_list_bundled_icons_and_png_path() -> None:
    """v0.6.9 — the Settings 'Library…' picker enumerates the
    shipped set by name and resolves each to a real PNG file."""
    from pathlib import Path
    from scriptree.shell.icon_assets import (
        bundled_icon_png_path, list_bundled_icons,
    )
    names = list_bundled_icons()
    assert isinstance(names, tuple) and len(names) >= 20
    # Sorted, de-prefixed, and includes the reference archetypes.
    assert names == tuple(sorted(names))
    for required in ("cli", "folder", "tool", "solidworks"):
        assert required in names, f"missing {required} in library"
    # Every advertised name resolves to an existing PNG.
    for nm in names:
        p = bundled_icon_png_path(nm)
        assert p is not None and Path(p).is_file()
        assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    # Unknown name → None.
    assert bundled_icon_png_path("definitely-not-an-icon") is None


def test_classify_icon_maps_keywords_to_glyphs() -> None:
    """v0.6.9 — the name→icon heuristic gives icon-less tools
    *variety* instead of one generic glyph."""
    from scriptree.shell.icon_assets import (
        classify_icon, list_bundled_icons,
    )
    cases = {
        "git status": "versioncontrol",
        "Backup to Zip Archive": "archive",
        "PostgreSQL dump": "database",
        "ffmpeg convert": "convert",
        "Run pytest suite": "test",
        "SolidWorks exporter": "solidworks",
        "DXF nesting / plasma cut": "scissors",
        "PowerShell deploy": "power",
        "ping host": "network",
        "Encrypt secret": "lock",
        "download release": "download",
        "Search files (ripgrep)": "search",
        # v0.6.13 — ScripTree's own primitives.  Keep these
        # examples clear of other rule keywords so we test the
        # ring/forest match itself, not the rule-order tiebreaker.
        "Tree ring layout": "ring",
        "Forest hub launcher": "forest",
        # Word-boundary guard: bare 'ring' inside another word
        # must NOT misroute to ring (this used to confuse "string").
        "Sort string list": "tool",
    }
    for nm, expected in cases.items():
        assert classify_icon(name=nm) == expected, (
            f"{nm!r} → {classify_icon(name=nm)!r}, want {expected!r}"
        )
    # Unknown → generic 'tool', and it's always a real bundled name.
    g = classify_icon(name="frobnicate the wibble")
    assert g == "tool"
    assert g in list_bundled_icons()
    # Every rule target must be a shipped icon (no dangling names).
    from scriptree.shell.icon_assets import _ICON_RULES
    names = set(list_bundled_icons())
    for _needles, icon in _ICON_RULES:
        assert icon in names, f"rule points at missing icon {icon!r}"


def test_catalog_icon_falls_back_to_classified_glyph(
    tmp_path,
) -> None:
    """An icon-less .scriptree gets a category glyph (not the bare
    OS file icon) chosen from its name."""
    from scriptree.core.io import save_tool
    from scriptree.core.model import ParamDef, ToolDef
    from scriptree.shell.tree_popup import _bundled_qicon, _catalog_icon

    tool = ToolDef(
        name="Zip Archive Backup", executable="/bin/zip",
        argument_template=["x"],
        params=[ParamDef(id="x", label="X", default="hi")],
    )
    p = tmp_path / "backup.scriptree"
    save_tool(tool, p)
    ic = _catalog_icon(str(p), "Zip Archive Backup")
    assert ic is not None and not ic.isNull()
    # It is specifically the 'archive' bundled glyph.
    expected = _bundled_qicon("archive")
    assert expected is not None
    assert ic.cacheKey() == expected.cacheKey()


def test_settings_dialog_has_icon_library_button() -> None:
    """The cell Settings dialog exposes a way to change the icon
    (Browse… AND a bundled-Library… picker)."""
    from scriptree.shell.branding_loader import load_branding
    from scriptree.shell.cell_window import CellWindow, SettingsDialog
    cell = CellWindow(load_branding())
    dlg = SettingsDialog(cell)
    assert hasattr(dlg, "_icon_browse_btn")
    assert hasattr(dlg, "_icon_library_btn")
    assert dlg._icon_library_btn.text() == "Library…"
    dlg.close()
    cell.close()


def test_pick_library_icon_embeds_into_bound_catalog(tmp_path) -> None:
    """Selecting a library icon on a catalog-bound cell embeds the
    PNG into the catalog (portable path)."""
    from unittest.mock import patch

    from PySide6.QtWidgets import QDialog

    from scriptree.core.cell_metadata import read_for
    from scriptree.core.io import save_tool
    from scriptree.core.model import ParamDef, ToolDef
    from scriptree.shell.branding_loader import load_branding
    from scriptree.shell.cell_window import CellWindow, SettingsDialog

    tool = ToolDef(
        name="alpha", executable="/bin/echo",
        argument_template=["x"],
        params=[ParamDef(id="x", label="X", default="hi")],
    )
    cat = tmp_path / "alpha.scriptree"
    save_tool(tool, cat)

    cell = CellWindow(load_branding())
    cell._handle_dropped_file(str(cat))
    dlg = SettingsDialog(cell)

    # Drive the modal picker: accept with "folder" chosen.
    def _fake_exec(self):
        # The handler stores the pick in a local dict captured by the
        # button lambdas; simulate the user clicking the "folder" tile
        # by walking the tool buttons and triggering the matching one.
        from PySide6.QtWidgets import QToolButton
        for b in self.findChildren(QToolButton):
            if b.text() == "folder":
                b.click()
                break
        return QDialog.Accepted

    with patch.object(QDialog, "exec", _fake_exec):
        dlg._on_icon_library()

    md = read_for(cat)
    assert md.is_embedded() and md.icon_format == "png"
    assert cell._icon_data_b64 and not cell._icon_path
    dlg.close()
    cell.close()


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
