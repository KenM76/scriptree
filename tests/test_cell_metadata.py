"""Tests for ``scriptree.core.cell_metadata`` — read / write cell
visual settings inside a ``.scriptree`` or ``.scriptreetree`` JSON
file, plus the embed / unembed round-trip.

Auto-dismisses any ``QMessageBox`` (per the standing rule)."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])

QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)


from scriptree.core.cell_metadata import (  # noqa: E402
    CellMetadata,
    embed_icon,
    read_for,
    unembed_icon_to_file,
    write_for,
)
from scriptree.core.io import load_tool, load_tree, save_tool, save_tree  # noqa: E402
from scriptree.core.model import (  # noqa: E402
    ParamDef, ToolDef, TreeDef, TreeNode,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Smallest PNG we can construct: 1×1 transparent pixel, no compression.
# Use a known-valid PNG dataURI so QPixmap.loadFromData accepts it.
_TINY_PNG_BYTES = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABAQMAAAAl21bKAAAAA1BMVEUAAACnej3aAAAAAXRS"
    b"TlMAQObYZgAAAApJREFUCNdjYAAAAAIAAeIhvDMAAAAASUVORK5CYII="
)


def _save_tool(tmp: Path, name: str = "demo") -> Path:
    tool = ToolDef(
        name=name,
        executable="/bin/echo",
        argument_template=["{x}"],
        params=[ParamDef(id="x", label="X", default="hi")],
    )
    p = tmp / f"{name}.scriptree"
    save_tool(tool, p)
    return p


def _save_tree(tmp: Path, name: str = "demo") -> Path:
    tree = TreeDef(name=name, nodes=[])
    p = tmp / f"{name}.scriptreetree"
    save_tree(tree, p)
    return p


# ---------------------------------------------------------------------------
# read_for
# ---------------------------------------------------------------------------

class TestReadFor:
    def test_returns_defaults_for_legacy_tool(self, tmp_path: Path) -> None:
        """A .scriptree with no cell metadata should return an
        all-default CellMetadata."""
        p = _save_tool(tmp_path)
        md = read_for(p)
        assert md.icon == ""
        assert md.icon_data == ""
        assert md.icon_format == ""
        assert md.text_label == ""
        assert md.icon_scale == 1.0
        assert md.label_opacity == 1.0
        assert md.icon_resolved_path == ""

    def test_returns_defaults_for_legacy_tree(self, tmp_path: Path) -> None:
        p = _save_tree(tmp_path)
        md = read_for(p)
        assert md.icon == ""
        assert md.icon_scale == 1.0

    def test_resolves_relative_icon_path(self, tmp_path: Path) -> None:
        """A relative cell.icon should resolve against the catalog
        directory."""
        # Drop a fake icon next to the catalog.
        icon = tmp_path / "myicon.png"
        icon.write_bytes(_TINY_PNG_BYTES)
        # Build the catalog with relative path.
        tool = ToolDef(
            name="alpha", executable="/bin/echo",
            argument_template=["{x}"],
            params=[ParamDef(id="x", label="X", default="hi")],
            cell_icon="myicon.png",
        )
        catalog = tmp_path / "alpha.scriptree"
        save_tool(tool, catalog)
        md = read_for(catalog)
        assert md.icon == "myicon.png"
        assert Path(md.icon_resolved_path) == icon.resolve()

    def test_returns_empty_metadata_for_missing_file(
        self, tmp_path: Path,
    ) -> None:
        md = read_for(tmp_path / "nope.scriptree")
        assert md.icon == ""

    def test_unsupported_extension_returns_defaults(self, tmp_path: Path) -> None:
        bad = tmp_path / "garbage.txt"
        bad.write_text("not a catalog")
        md = read_for(bad)
        assert md.icon == ""

    def test_is_embedded_detects_embedded_icon(self, tmp_path: Path) -> None:
        tool = ToolDef(
            name="alpha", executable="/bin/echo",
            argument_template=["{x}"],
            params=[ParamDef(id="x", label="X", default="hi")],
            cell_icon_data="aGVsbG8=",  # base64 for "hello"
            cell_icon_format="png",
        )
        catalog = tmp_path / "alpha.scriptree"
        save_tool(tool, catalog)
        md = read_for(catalog)
        assert md.is_embedded() is True
        assert md.has_icon() is True


# ---------------------------------------------------------------------------
# write_for + relative-path normalisation
# ---------------------------------------------------------------------------

class TestWriteFor:
    def test_writes_text_label_to_scriptree(self, tmp_path: Path) -> None:
        p = _save_tool(tmp_path)
        write_for(p, text_label="DXF")
        # Re-read; cell_text_label should be set.
        loaded = load_tool(str(p))
        assert loaded.cell_text_label == "DXF"

    def test_writes_text_label_to_scriptreetree(self, tmp_path: Path) -> None:
        p = _save_tree(tmp_path)
        write_for(p, text_label="HE")
        loaded = load_tree(str(p))
        assert loaded.cell_text_label == "HE"

    def test_relativises_icon_path_under_catalog_dir(
        self, tmp_path: Path,
    ) -> None:
        """Per user spec: 'paths should default to relative.'  When
        the icon file lives at or under the catalog's directory, the
        stored path should be relative."""
        icon = tmp_path / "icons" / "alpha.png"
        icon.parent.mkdir()
        icon.write_bytes(_TINY_PNG_BYTES)
        catalog = _save_tool(tmp_path)

        md = write_for(catalog, icon=str(icon.resolve()))
        # Path stored in JSON should be relative (forward slashes).
        loaded = load_tool(str(catalog))
        assert loaded.cell_icon == "icons/alpha.png"
        # And resolves correctly back to absolute.
        assert Path(md.icon_resolved_path).resolve() == icon.resolve()

    def test_keeps_absolute_when_icon_outside_catalog_dir(
        self, tmp_path: Path,
    ) -> None:
        """Icon paths that aren't inside the catalog's directory tree
        stay absolute — there's no clean relative path."""
        outside = tmp_path.parent / "external_icon.png"
        try:
            outside.write_bytes(_TINY_PNG_BYTES)
            catalog = _save_tool(tmp_path)
            write_for(catalog, icon=str(outside))
            loaded = load_tool(str(catalog))
            # Stored as absolute; not inside catalog dir.
            assert Path(loaded.cell_icon).is_absolute()
        finally:
            outside.unlink(missing_ok=True)

    def test_only_passed_fields_are_changed(self, tmp_path: Path) -> None:
        p = _save_tool(tmp_path)
        write_for(p, text_label="ALPHA", icon_scale=1.5)
        # Update only icon_scale; text_label should survive.
        write_for(p, icon_scale=0.8)
        loaded = load_tool(str(p))
        assert loaded.cell_text_label == "ALPHA"
        assert loaded.cell_icon_scale == 0.8

    def test_writing_to_missing_file_raises(self, tmp_path: Path) -> None:
        import pytest
        with pytest.raises(FileNotFoundError):
            write_for(tmp_path / "nope.scriptree", text_label="x")

    def test_writing_unsupported_extension_raises(
        self, tmp_path: Path,
    ) -> None:
        import pytest
        bad = tmp_path / "garbage.txt"
        bad.write_text("nope")
        with pytest.raises(ValueError):
            write_for(bad, text_label="x")


# ---------------------------------------------------------------------------
# embed_icon
# ---------------------------------------------------------------------------

class TestEmbedIcon:
    def test_embed_reads_file_and_stores_base64(
        self, tmp_path: Path,
    ) -> None:
        icon = tmp_path / "alpha.png"
        icon.write_bytes(_TINY_PNG_BYTES)
        catalog = _save_tool(tmp_path)

        md = embed_icon(catalog, icon)
        # Returned metadata has the encoded data.
        assert md.icon_data
        assert md.icon_format == "png"
        # Encoded bytes match the source file.
        decoded = base64.b64decode(md.icon_data.encode("ascii"))
        assert decoded == _TINY_PNG_BYTES
        # External path is cleared (icon now lives inside the JSON).
        assert md.icon == ""
        assert md.icon_resolved_path == ""
        # JSON has the bytes saved.
        loaded = load_tool(str(catalog))
        assert loaded.cell_icon_data
        assert loaded.cell_icon_format == "png"
        assert loaded.cell_icon == ""

    def test_embed_missing_icon_raises(self, tmp_path: Path) -> None:
        import pytest
        catalog = _save_tool(tmp_path)
        with pytest.raises(FileNotFoundError):
            embed_icon(catalog, tmp_path / "missing.png")


# ---------------------------------------------------------------------------
# unembed_icon_to_file
# ---------------------------------------------------------------------------

class TestUnembedIcon:
    def test_unembed_round_trips_bytes(self, tmp_path: Path) -> None:
        # Start with embedded data.
        catalog = _save_tool(tmp_path)
        write_for(
            catalog,
            icon="",
            icon_data=base64.b64encode(_TINY_PNG_BYTES).decode("ascii"),
            icon_format="png",
        )
        # Unembed to a chosen file.
        out = tmp_path / "extracted.png"
        md = unembed_icon_to_file(catalog, out)
        assert out.is_file()
        assert out.read_bytes() == _TINY_PNG_BYTES
        # Catalog now references the file (relativised).
        loaded = load_tool(str(catalog))
        assert loaded.cell_icon == "extracted.png"
        assert loaded.cell_icon_data == ""
        assert loaded.cell_icon_format == ""
        # Returned metadata's resolved path matches.
        assert Path(md.icon_resolved_path).resolve() == out.resolve()

    def test_unembed_with_no_embedded_data_raises(
        self, tmp_path: Path,
    ) -> None:
        import pytest
        catalog = _save_tool(tmp_path)
        with pytest.raises(ValueError):
            unembed_icon_to_file(catalog, tmp_path / "out.png")


# ---------------------------------------------------------------------------
# ToolDef / TreeDef round-trip via io.py
# ---------------------------------------------------------------------------

class TestModelRoundTrip:
    def test_tooldef_cell_fields_round_trip(self, tmp_path: Path) -> None:
        tool = ToolDef(
            name="alpha", executable="/bin/echo",
            argument_template=["{x}"],
            params=[ParamDef(id="x", label="X", default="hi")],
            cell_icon="icons/foo.png",
            cell_text_label="DXF",
            cell_icon_scale=1.5,
            cell_label_opacity=0.7,
        )
        p = tmp_path / "alpha.scriptree"
        save_tool(tool, p)
        loaded = load_tool(str(p))
        assert loaded.cell_icon == "icons/foo.png"
        assert loaded.cell_text_label == "DXF"
        assert loaded.cell_icon_scale == 1.5
        assert loaded.cell_label_opacity == 0.7

    def test_treedef_cell_fields_round_trip(self, tmp_path: Path) -> None:
        tree = TreeDef(
            name="cat",
            nodes=[],
            cell_icon_data="aGVsbG8=",  # "hello"
            cell_icon_format="png",
            cell_icon_scale=0.5,
        )
        p = tmp_path / "cat.scriptreetree"
        save_tree(tree, p)
        loaded = load_tree(str(p))
        assert loaded.cell_icon_data == "aGVsbG8="
        assert loaded.cell_icon_format == "png"
        assert loaded.cell_icon_scale == 0.5

    def test_legacy_tool_loads_with_default_cell_fields(
        self, tmp_path: Path,
    ) -> None:
        """A .scriptree without the 'cell' sub-object loads cleanly."""
        legacy = {
            "schema_version": 1,
            "name": "alpha",
            "executable": "/bin/echo",
            "argument_template": ["{x}"],
            "params": [{"id": "x", "label": "X", "default": "hi"}],
        }
        p = tmp_path / "alpha.scriptree"
        p.write_text(json.dumps(legacy), encoding="utf-8")
        loaded = load_tool(str(p))
        assert loaded.cell_icon == ""
        assert loaded.cell_icon_scale == 1.0

    def test_legacy_tree_loads_with_default_cell_fields(
        self, tmp_path: Path,
    ) -> None:
        legacy = {
            "schema_version": 1,
            "name": "cat",
            "nodes": [],
        }
        p = tmp_path / "cat.scriptreetree"
        p.write_text(json.dumps(legacy), encoding="utf-8")
        loaded = load_tree(str(p))
        assert loaded.cell_icon == ""
        assert loaded.cell_icon_scale == 1.0

    def test_default_cell_fields_omitted_from_json(
        self, tmp_path: Path,
    ) -> None:
        """Tools / trees with all-default cell fields don't get a
        'cell' key in the saved JSON — keeps legacy files byte-
        identical."""
        tool = ToolDef(
            name="x", executable="/bin/y",
            argument_template=[],
            params=[],
        )
        p = tmp_path / "x.scriptree"
        save_tool(tool, p)
        on_disk = json.loads(p.read_text(encoding="utf-8"))
        assert "cell" not in on_disk


# ---------------------------------------------------------------------------
# CellWindow integration: cell pulls metadata from catalog
# ---------------------------------------------------------------------------

class TestCellWindowCatalogIntegration:
    def test_cell_load_reads_text_label_from_catalog(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow
        # Catalog with an explicit text label.
        tree = TreeDef(name="cat", nodes=[], cell_text_label="HZ")
        p = tmp_path / "cat.scriptreetree"
        save_tree(tree, p)
        # Construct a cell bound to it; constructor should pull the
        # text label from the catalog.
        cell = CellWindow(load_branding(), catalog_path=str(p))
        assert cell._text_label == "HZ"
        cell.close()

    def test_cell_load_reads_icon_scale_from_catalog(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow
        tree = TreeDef(
            name="cat", nodes=[],
            cell_icon_scale=1.5, cell_label_opacity=0.6,
        )
        p = tmp_path / "cat.scriptreetree"
        save_tree(tree, p)
        cell = CellWindow(load_branding(), catalog_path=str(p))
        assert cell._icon_scale == 1.5
        assert cell._label_opacity == 0.6
        cell.close()

    def test_cell_apply_label_change_writes_to_catalog(
        self, tmp_path: Path,
    ) -> None:
        """Changing the cell's label via apply_label_change should
        write the new value into the catalog JSON."""
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow
        tree = TreeDef(name="cat", nodes=[])
        p = tmp_path / "cat.scriptreetree"
        save_tree(tree, p)

        cell = CellWindow(load_branding(), catalog_path=str(p))
        cell.apply_label_change(text_label="DXF")
        # Re-read from disk; the field should be set.
        loaded = load_tree(str(p))
        assert loaded.cell_text_label == "DXF"
        cell.close()

    def test_cell_apply_change_without_catalog_uses_qsettings(
        self, tmp_path: Path,
    ) -> None:
        """A cell with NO bound catalog falls back to QSettings.  We
        just verify apply_label_change doesn't crash on the
        unbound-cell path; QSettings interaction is covered by the
        existing tests."""
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow
        cell = CellWindow(load_branding())
        assert cell._catalog_path is None
        cell.apply_label_change(text_label="XX")  # no-throw
        assert cell._text_label == "XX"
        cell.close()
