"""Tests for the v0.3.6 cell fill-colour customisation feature.

Coverage:

1. ``cell_metadata._normalise_hex_rgb`` parser correctness.
2. Schema round-trip — ``cell_fill_color`` on ToolDef / TreeDef
   survives ``save_*`` / ``load_*``; default ("") stays out of JSON.
3. ``CellMetadata.fill_color`` round-trip through read_for / write_for.
4. ``CellWindow.apply_fill_color_change`` updates ``_fill_color`` +
   ``_fill_color_hex`` and persists when bound to a catalog.
5. Resetting (``apply_fill_color_change("")``) reverts to the
   branding default.
6. Loading a catalog with ``cell.fill_color`` set applies it
   automatically.
7. Settings dialog two-way sync:
   - Setting RGB spinboxes updates hex + hue + swatch.
   - Setting hex updates spinboxes + hue + swatch.
   - Setting hue updates spinboxes + hex + swatch.
   - Reset button reverts every control to default.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])

QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)


from scriptree.core.cell_metadata import (
    CellMetadata,
    _normalise_hex_rgb,
    read_for,
    write_for,
)
from scriptree.core.io import load_tool, load_tree, save_tool, save_tree
from scriptree.core.model import (
    ParamDef, ParamType, ToolDef, TreeDef, TreeNode, Widget,
)


def _tool() -> ToolDef:
    return ToolDef(
        name="x", executable="python",
        params=[
            ParamDef(
                id="p", label="P",
                type=ParamType.PATH, widget=Widget.FILE_OPEN,
            ),
        ],
    )


# ===========================================================================
# 1. Hex parser
# ===========================================================================

class TestNormaliseHex:

    def test_six_digit_lowercased(self) -> None:
        assert _normalise_hex_rgb("#AABBCC") == "#aabbcc"

    def test_six_digit_no_hash(self) -> None:
        assert _normalise_hex_rgb("aabbcc") == "#aabbcc"

    def test_three_digit_expanded(self) -> None:
        assert _normalise_hex_rgb("#abc") == "#aabbcc"
        assert _normalise_hex_rgb("ABC") == "#aabbcc"

    def test_invalid_returns_empty(self) -> None:
        assert _normalise_hex_rgb("xyz") == ""
        assert _normalise_hex_rgb("#zz1234") == ""
        assert _normalise_hex_rgb("#12345") == ""  # 5-digit not allowed

    def test_empty_returns_empty(self) -> None:
        assert _normalise_hex_rgb("") == ""
        assert _normalise_hex_rgb("   ") == ""

    def test_alpha_variant_rejected(self) -> None:
        """4-digit and 8-digit (RGBA) variants are rejected — alpha
        is owned by the transparency slider."""
        assert _normalise_hex_rgb("#aabbccdd") == ""
        assert _normalise_hex_rgb("#abcd") == ""


# ===========================================================================
# 2. Schema round-trip
# ===========================================================================

class TestSchemaRoundTrip:

    def test_default_empty(self) -> None:
        t = ToolDef(name="x", executable="python")
        assert t.cell_fill_color == ""

    def test_tree_default_empty(self) -> None:
        tree = TreeDef(name="t", nodes=[])
        assert tree.cell_fill_color == ""

    def test_tool_default_omits_field_in_json(
        self, tmp_path: Path,
    ) -> None:
        """Legacy round-trip: empty fill_color stays out of the JSON
        so v0.3.5 catalogs round-trip byte-identical."""
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        on_disk = json.loads(p.read_text(encoding="utf-8"))
        cell_obj = on_disk.get("cell", {})
        assert "fill_color" not in cell_obj

    def test_tool_fill_color_preserved(self, tmp_path: Path) -> None:
        t = _tool()
        t.cell_fill_color = "#ff8800"
        p = tmp_path / "demo.scriptree"
        save_tool(t, p)
        on_disk = json.loads(p.read_text(encoding="utf-8"))
        assert on_disk["cell"]["fill_color"] == "#ff8800"
        loaded = load_tool(p)
        assert loaded.cell_fill_color == "#ff8800"

    def test_tree_fill_color_preserved(self, tmp_path: Path) -> None:
        leaf = tmp_path / "leaf.scriptree"
        save_tool(_tool(), leaf)
        tree = TreeDef(
            name="t",
            nodes=[TreeNode(type="leaf", path=str(leaf))],
            cell_fill_color="#33aa66",
        )
        p = tmp_path / "demo.scriptreetree"
        save_tree(tree, p)
        loaded = load_tree(p)
        assert loaded.cell_fill_color == "#33aa66"


# ===========================================================================
# 3. cell_metadata read_for / write_for
# ===========================================================================

class TestCellMetadataFillColor:

    def test_read_default(self, tmp_path: Path) -> None:
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        md = read_for(p)
        assert md.fill_color == ""

    def test_write_for_persists(self, tmp_path: Path) -> None:
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        write_for(p, fill_color="#ff8800")
        md = read_for(p)
        assert md.fill_color == "#ff8800"

    def test_write_for_invalid_clears(self, tmp_path: Path) -> None:
        """A typo or out-of-range value silently clears the override
        rather than poisoning the catalog file."""
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        write_for(p, fill_color="#ff8800")  # set
        write_for(p, fill_color="bogus")    # then clear via invalid input
        md = read_for(p)
        assert md.fill_color == ""

    def test_write_for_three_digit_expanded(self, tmp_path: Path) -> None:
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        write_for(p, fill_color="#abc")
        assert read_for(p).fill_color == "#aabbcc"


# ===========================================================================
# 4. CellWindow.apply_fill_color_change
# ===========================================================================

class TestApplyFillColorChange:

    def _spawn_cell(self):
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow
        return CellWindow(load_branding())

    def test_sets_fill_color_and_hex(self) -> None:
        cell = self._spawn_cell()
        cell.apply_fill_color_change("#ff8800")
        assert cell._fill_color.red() == 0xff
        assert cell._fill_color.green() == 0x88
        assert cell._fill_color.blue() == 0x00
        assert cell._fill_color_hex == "#ff8800"
        cell.close()

    def test_alpha_preserved_across_changes(self) -> None:
        """Changing the fill colour must NOT touch alpha — the
        transparency slider is the only knob for that axis."""
        cell = self._spawn_cell()
        original_alpha = cell._fill_color.alpha()
        cell.apply_fill_color_change("#ff0000")
        assert cell._fill_color.alpha() == original_alpha
        cell.apply_fill_color_change("#0000ff")
        assert cell._fill_color.alpha() == original_alpha
        cell.close()

    def test_invalid_hex_treated_as_reset(self) -> None:
        cell = self._spawn_cell()
        cell.apply_fill_color_change("#ff8800")
        cell.apply_fill_color_change("not-a-hex")
        # Empty canonical → reset to branding default.
        assert cell._fill_color.red() == cell._branding_fill_color.red()
        assert cell._fill_color_hex == ""
        cell.close()

    def test_empty_string_resets_to_branding_default(self) -> None:
        cell = self._spawn_cell()
        cell.apply_fill_color_change("#11ff22")
        cell.apply_fill_color_change("")
        assert cell._fill_color_hex == ""
        # Components match branding default exactly.
        bd = cell._branding_fill_color
        assert cell._fill_color.red() == bd.red()
        assert cell._fill_color.green() == bd.green()
        assert cell._fill_color.blue() == bd.blue()
        cell.close()

    def test_persists_to_bound_catalog(self, tmp_path: Path) -> None:
        cell = self._spawn_cell()
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        cell._catalog_path = str(p)
        cell.apply_fill_color_change("#abcdef")
        md = read_for(p)
        assert md.fill_color == "#abcdef"
        cell.close()


# ===========================================================================
# 5. Loading a catalog applies the colour
# ===========================================================================

class TestCatalogLoadAppliesColor:

    def test_refresh_label_from_catalog_applies_fill_color(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        # Save a tool with a non-default fill_color set.
        t = _tool()
        t.cell_fill_color = "#11ff22"
        p = tmp_path / "demo.scriptree"
        save_tool(t, p)

        cell = CellWindow(load_branding())
        cell._catalog_path = str(p)
        cell._refresh_label_from_catalog()
        assert cell._fill_color.green() == 0xff
        assert cell._fill_color_hex == "#11ff22"
        cell.close()

    def test_refresh_label_from_catalog_resets_when_unset(
        self, tmp_path: Path,
    ) -> None:
        """A catalog with empty fill_color resets the cell to the
        branding default — overrides shouldn't leak across re-binds."""
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        # First load: catalog with custom colour → cell adopts it.
        cell = CellWindow(load_branding())
        # Pre-populate an override in memory only (simulating prior bind).
        cell.apply_fill_color_change("#ff00ff")
        # Now re-bind to a catalog with NO override.
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        cell._catalog_path = str(p)
        cell._refresh_label_from_catalog()
        assert cell._fill_color_hex == ""
        # Components match branding default.
        bd = cell._branding_fill_color
        assert cell._fill_color.red() == bd.red()
        cell.close()


# ===========================================================================
# 6. Settings dialog two-way sync
# ===========================================================================

class TestSettingsDialogSync:

    def _open(self):
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow, SettingsDialog
        cell = CellWindow(load_branding())
        dlg = SettingsDialog(cell)
        return cell, dlg

    def test_initial_state_matches_branding_default(self) -> None:
        cell, dlg = self._open()
        bd = cell._branding_fill_color
        assert dlg._color_r_spin.value() == bd.red()
        assert dlg._color_g_spin.value() == bd.green()
        assert dlg._color_b_spin.value() == bd.blue()
        # Hex starts at the branding default's hex form.
        assert dlg._color_hex_edit.text().lower() == (
            f"#{bd.red():02x}{bd.green():02x}{bd.blue():02x}"
        )
        dlg.close()
        cell.close()

    def test_rgb_change_syncs_hex_and_hue(self) -> None:
        cell, dlg = self._open()
        dlg._color_r_spin.setValue(255)
        dlg._color_g_spin.setValue(128)
        dlg._color_b_spin.setValue(0)
        # Hex updates.
        assert dlg._color_hex_edit.text() == "#ff8000"
        # Cell colour applied.
        assert cell._fill_color.red() == 255
        assert cell._fill_color.green() == 128
        assert cell._fill_color.blue() == 0
        # Hue slider points at the orange-y hue (≈30°).
        assert 25 <= dlg._color_hue_slider.value() <= 35
        dlg.close()
        cell.close()

    def test_hex_change_syncs_rgb_and_hue(self) -> None:
        cell, dlg = self._open()
        dlg._color_hex_edit.setText("#33aa66")
        # Trigger editingFinished by emitting it directly.
        dlg._color_hex_edit.editingFinished.emit()
        assert dlg._color_r_spin.value() == 0x33
        assert dlg._color_g_spin.value() == 0xaa
        assert dlg._color_b_spin.value() == 0x66
        # Cell applied.
        assert cell._fill_color.green() == 0xaa
        dlg.close()
        cell.close()

    def test_hue_change_syncs_rgb_and_hex(self) -> None:
        cell, dlg = self._open()
        dlg._color_hue_slider.setValue(120)  # green
        # 120° at full S/V → pure green.
        assert dlg._color_r_spin.value() == 0
        assert dlg._color_g_spin.value() == 255
        assert dlg._color_b_spin.value() == 0
        assert dlg._color_hex_edit.text() == "#00ff00"
        assert cell._fill_color.green() == 255
        dlg.close()
        cell.close()

    def test_reset_button_reverts_to_branding_default(self) -> None:
        cell, dlg = self._open()
        # First change away from default.
        dlg._color_hue_slider.setValue(0)  # red
        assert dlg._color_r_spin.value() == 255
        # Then reset.
        dlg._color_reset_btn.click()
        bd = cell._branding_fill_color
        assert dlg._color_r_spin.value() == bd.red()
        assert dlg._color_hex_edit.text().lower() == (
            f"#{bd.red():02x}{bd.green():02x}{bd.blue():02x}"
        )
        # Cell's hex override cleared.
        assert cell._fill_color_hex == ""
        dlg.close()
        cell.close()

    def test_invalid_hex_typing_does_not_crash(self) -> None:
        """Partial-typing scenarios where the user hasn't finished
        entering a 6-digit value must not crash or apply garbage."""
        cell, dlg = self._open()
        bd_red = cell._fill_color.red()
        dlg._color_hex_edit.setText("#abc")  # 3-digit IS valid (expands)
        dlg._color_hex_edit.editingFinished.emit()
        # Should round-trip cleanly to #aabbcc.
        assert dlg._color_r_spin.value() == 0xaa
        # Now type something invalid.
        dlg._color_hex_edit.setText("#xy")
        dlg._color_hex_edit.editingFinished.emit()
        # Cell stays at the previous valid value (#aabbcc), no crash.
        assert cell._fill_color.red() == 0xaa
        dlg.close()
        cell.close()
