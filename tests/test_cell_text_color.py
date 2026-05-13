"""Tests for the v0.3.8 cell text-colour customisation feature.

Mirror of ``test_cell_fill_color.py`` — every check the fill-colour
suite runs is exercised here against ``cell_text_color`` /
``_text_color_hex`` / ``apply_text_color_change`` / the Settings
dialog's text-colour group.

Differences from the fill suite:

* The default colour is the cell's ``_compute_stroke_color()``,
  not a fixed branding fill.  "Reset" therefore reverts to whatever
  stroke colour the paint code currently picks (role-dependent),
  not a static reference value.
* No alpha-preservation test — the text colour override is RGB only;
  the paint code derives alpha from ``transparency × label_opacity``
  on every paint, so there is no per-instance alpha state to preserve.
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
    CellMetadata, _normalise_hex_rgb, read_for, write_for,
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
                type=ParamType.PATH, widget=Widget.FILE,
            ),
        ],
    )


# ===========================================================================
# 1. Schema round-trip
# ===========================================================================

class TestSchemaRoundTrip:

    def test_default_empty(self) -> None:
        t = ToolDef(name="x", executable="python")
        assert t.cell_text_color == ""

    def test_tree_default_empty(self) -> None:
        tree = TreeDef(name="t", nodes=[])
        assert tree.cell_text_color == ""

    def test_tool_default_omits_field_in_json(self, tmp_path: Path) -> None:
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        on_disk = json.loads(p.read_text(encoding="utf-8"))
        cell_obj = on_disk.get("cell", {})
        assert "text_color" not in cell_obj

    def test_tool_text_color_preserved(self, tmp_path: Path) -> None:
        t = _tool()
        t.cell_text_color = "#ff8800"
        p = tmp_path / "demo.scriptree"
        save_tool(t, p)
        on_disk = json.loads(p.read_text(encoding="utf-8"))
        assert on_disk["cell"]["text_color"] == "#ff8800"
        loaded = load_tool(p)
        assert loaded.cell_text_color == "#ff8800"

    def test_tree_text_color_preserved(self, tmp_path: Path) -> None:
        leaf = tmp_path / "leaf.scriptree"
        save_tool(_tool(), leaf)
        tree = TreeDef(
            name="t",
            nodes=[TreeNode(type="leaf", path=str(leaf))],
            cell_text_color="#33aa66",
        )
        p = tmp_path / "demo.scriptreetree"
        save_tree(tree, p)
        loaded = load_tree(p)
        assert loaded.cell_text_color == "#33aa66"

    def test_fill_and_text_color_independent(self, tmp_path: Path) -> None:
        """Setting one must not affect the other on disk."""
        t = _tool()
        t.cell_fill_color = "#111111"
        t.cell_text_color = "#eeeeee"
        p = tmp_path / "demo.scriptree"
        save_tool(t, p)
        loaded = load_tool(p)
        assert loaded.cell_fill_color == "#111111"
        assert loaded.cell_text_color == "#eeeeee"


# ===========================================================================
# 2. cell_metadata read_for / write_for
# ===========================================================================

class TestCellMetadataTextColor:

    def test_read_default(self, tmp_path: Path) -> None:
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        md = read_for(p)
        assert md.text_color == ""

    def test_write_for_persists(self, tmp_path: Path) -> None:
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        write_for(p, text_color="#ff8800")
        md = read_for(p)
        assert md.text_color == "#ff8800"

    def test_write_for_invalid_clears(self, tmp_path: Path) -> None:
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        write_for(p, text_color="#ff8800")
        write_for(p, text_color="bogus")
        md = read_for(p)
        assert md.text_color == ""

    def test_write_for_three_digit_expanded(self, tmp_path: Path) -> None:
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        write_for(p, text_color="#abc")
        assert read_for(p).text_color == "#aabbcc"

    def test_write_for_does_not_clobber_fill(self, tmp_path: Path) -> None:
        """Pass-through rule: writing one colour leaves the other
        untouched on disk."""
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        write_for(p, fill_color="#112233")
        write_for(p, text_color="#445566")
        md = read_for(p)
        assert md.fill_color == "#112233"
        assert md.text_color == "#445566"


# ===========================================================================
# 3. CellWindow.apply_text_color_change
# ===========================================================================

class TestApplyTextColorChange:

    def _spawn_cell(self):
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow
        return CellWindow(load_branding())

    def test_sets_text_color_hex(self) -> None:
        cell = self._spawn_cell()
        cell.apply_text_color_change("#ff8800")
        assert cell._text_color_hex == "#ff8800"
        cell.close()

    def test_invalid_hex_treated_as_reset(self) -> None:
        cell = self._spawn_cell()
        cell.apply_text_color_change("#ff8800")
        cell.apply_text_color_change("not-a-hex")
        assert cell._text_color_hex == ""
        cell.close()

    def test_empty_string_clears_override(self) -> None:
        cell = self._spawn_cell()
        cell.apply_text_color_change("#11ff22")
        cell.apply_text_color_change("")
        assert cell._text_color_hex == ""
        cell.close()

    def test_three_digit_expanded(self) -> None:
        cell = self._spawn_cell()
        cell.apply_text_color_change("#abc")
        assert cell._text_color_hex == "#aabbcc"
        cell.close()

    def test_persists_to_bound_catalog(self, tmp_path: Path) -> None:
        cell = self._spawn_cell()
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        cell._catalog_path = str(p)
        cell.apply_text_color_change("#abcdef")
        md = read_for(p)
        assert md.text_color == "#abcdef"
        cell.close()


# ===========================================================================
# 4. Loading a catalog applies the colour
# ===========================================================================

class TestCatalogLoadAppliesTextColor:

    def test_refresh_label_from_catalog_applies_text_color(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        t = _tool()
        t.cell_text_color = "#11ff22"
        p = tmp_path / "demo.scriptree"
        save_tool(t, p)

        cell = CellWindow(load_branding())
        cell._catalog_path = str(p)
        cell._refresh_label_from_catalog()
        assert cell._text_color_hex == "#11ff22"
        cell.close()

    def test_refresh_label_from_catalog_resets_when_unset(
        self, tmp_path: Path,
    ) -> None:
        """A catalog with empty text_color resets any prior in-memory
        override so re-binds don't leak."""
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        cell = CellWindow(load_branding())
        cell.apply_text_color_change("#ff00ff")
        p = tmp_path / "demo.scriptree"
        save_tool(_tool(), p)
        cell._catalog_path = str(p)
        cell._refresh_label_from_catalog()
        assert cell._text_color_hex == ""
        cell.close()


# ===========================================================================
# 5. Settings dialog two-way sync
# ===========================================================================

class TestSettingsDialogTextColorSync:

    def _open(self):
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow, SettingsDialog
        cell = CellWindow(load_branding())
        dlg = SettingsDialog(cell)
        return cell, dlg

    def test_initial_state_matches_stroke_default(self) -> None:
        """With no override, the dialog opens showing the cell's
        actual stroke-derived colour — not a misleading blank."""
        cell, dlg = self._open()
        sc = cell._compute_stroke_color()
        assert dlg._text_color_r_spin.value() == sc.red()
        assert dlg._text_color_g_spin.value() == sc.green()
        assert dlg._text_color_b_spin.value() == sc.blue()
        dlg.close()
        cell.close()

    def test_rgb_change_syncs_hex_and_hue(self) -> None:
        cell, dlg = self._open()
        dlg._text_color_r_spin.setValue(255)
        dlg._text_color_g_spin.setValue(128)
        dlg._text_color_b_spin.setValue(0)
        assert dlg._text_color_hex_edit.text() == "#ff8000"
        assert cell._text_color_hex == "#ff8000"
        assert 25 <= dlg._text_color_hue_slider.value() <= 35
        dlg.close()
        cell.close()

    def test_hex_change_syncs_rgb_and_hue(self) -> None:
        cell, dlg = self._open()
        dlg._text_color_hex_edit.setText("#33aa66")
        dlg._text_color_hex_edit.editingFinished.emit()
        assert dlg._text_color_r_spin.value() == 0x33
        assert dlg._text_color_g_spin.value() == 0xaa
        assert dlg._text_color_b_spin.value() == 0x66
        assert cell._text_color_hex == "#33aa66"
        dlg.close()
        cell.close()

    def test_hue_change_syncs_rgb_and_hex(self) -> None:
        cell, dlg = self._open()
        dlg._text_color_hue_slider.setValue(120)  # green
        assert dlg._text_color_r_spin.value() == 0
        assert dlg._text_color_g_spin.value() == 255
        assert dlg._text_color_b_spin.value() == 0
        assert dlg._text_color_hex_edit.text() == "#00ff00"
        assert cell._text_color_hex == "#00ff00"
        dlg.close()
        cell.close()

    def test_reset_button_clears_override(self) -> None:
        cell, dlg = self._open()
        dlg._text_color_hue_slider.setValue(0)  # red
        assert cell._text_color_hex == "#ff0000"
        dlg._text_color_reset_btn.click()
        # Override cleared in the cell — paint code falls back.
        assert cell._text_color_hex == ""
        # Dialog reflects the now-default stroke colour.
        sc = cell._compute_stroke_color()
        assert dlg._text_color_r_spin.value() == sc.red()
        dlg.close()
        cell.close()

    def test_invalid_hex_typing_does_not_crash(self) -> None:
        cell, dlg = self._open()
        dlg._text_color_hex_edit.setText("#abc")  # 3-digit valid
        dlg._text_color_hex_edit.editingFinished.emit()
        assert dlg._text_color_r_spin.value() == 0xaa
        # Invalid input — no crash, no garbage.
        dlg._text_color_hex_edit.setText("#xy")
        dlg._text_color_hex_edit.editingFinished.emit()
        # Cell stays at the prior valid value.
        assert cell._text_color_hex == "#aabbcc"
        dlg.close()
        cell.close()

    def test_text_and_fill_color_independent(self) -> None:
        """Changing the text colour must not touch fill, and vice
        versa.  The two sliders / spinboxes are fully independent."""
        cell, dlg = self._open()
        # Start with a known fill.
        dlg._color_hex_edit.setText("#112233")
        dlg._color_hex_edit.editingFinished.emit()
        # Change text colour.
        dlg._text_color_hex_edit.setText("#aabbcc")
        dlg._text_color_hex_edit.editingFinished.emit()
        # Both are set on the cell, neither clobbers the other.
        assert cell._fill_color_hex == "#112233"
        assert cell._text_color_hex == "#aabbcc"
        # The fill controls don't drift to the text value.
        assert dlg._color_hex_edit.text() == "#112233"
        dlg.close()
        cell.close()
