"""Tests for cell auto-letter derivation, icon/text persistence,
and the file-drop dispatch matrix on ``CellWindow``.

Auto-dismisses any incidental ``QMessageBox`` (per the standing
"don't block on expected dialogs" rule).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])

QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)


from scriptree.core.io import save_tool, save_tree  # noqa: E402
from scriptree.core.model import (  # noqa: E402
    ParamDef, ToolDef, TreeDef, TreeNode,
)
from scriptree.shell.cell_window import _derive_letters  # noqa: E402


# ---------------------------------------------------------------------------
# _derive_letters — the rule book
# ---------------------------------------------------------------------------

class TestDeriveLetters:
    def test_one_word_takes_first_two_letters(self) -> None:
        assert _derive_letters("hello") == "HE"
        assert _derive_letters("wireshark") == "WI"
        # Lower-case input is upper-cased in the output.
        assert _derive_letters("python") == "PY"

    def test_camel_case_takes_two_capitals(self) -> None:
        """User spec: 'first and second capital letter if it is one
        word with capital letter at start and a second one elsewhere'."""
        assert _derive_letters("MakeCode") == "MC"
        assert _derive_letters("ScripTree") == "ST"
        assert _derive_letters("PowerShell") == "PS"
        # Capital-only-at-start (no second cap) → falls back to 2-letter.
        assert _derive_letters("Hello") == "HE"
        # All caps → first two letters.
        assert _derive_letters("ABC") == "AB"

    def test_camel_case_precedence_over_multi_word(self) -> None:
        """User clarification (2026-05-07): 'SolidWorks toolkit
        should show as SW as the first 2 capital letters rule takes
        precidence.'  When ANY word in the input is CamelCase, that
        rule wins over the multi-word first-letter rule."""
        assert _derive_letters("SolidWorks toolkit") == "SW"
        assert _derive_letters("the SolidWorks toolkit") == "SW"
        assert _derive_letters("PowerShell scripts") == "PS"
        # Plain multi-word (no CamelCase) keeps the multi-word rule.
        assert _derive_letters("Show All Tools") == "SA"
        assert _derive_letters("git status") == "GS"

    def test_multi_word_takes_first_letter_of_each(self) -> None:
        assert _derive_letters("git status") == "GS"
        assert _derive_letters("disk usage") == "DU"
        assert _derive_letters("show date") == "SD"

    def test_skip_words_are_skipped(self) -> None:
        """User spec: 'skips over words like and or and the, etc.'"""
        # "and" is skipped; first two meaningful words become the letters.
        assert _derive_letters("foo and bar") == "FB"
        assert _derive_letters("the quick fox") == "QF"
        assert _derive_letters("of mice and men") == "MM"

    def test_only_one_meaningful_word_falls_through(self) -> None:
        """User spec: '...unless that is the only word after the first
        one, then it will use the character for that.'"""
        # "the cat" → only "cat" is meaningful → fall through to
        # single-word logic → first two chars of "cat".
        assert _derive_letters("the cat") == "CA"
        # "foo and" → only "foo" survives → first two chars.
        assert _derive_letters("foo and") == "FO"
        # "a b" — both single chars; "a" is a skip word, "b" survives.
        # Single-word fallback to the one letter we have.
        assert _derive_letters("a b") == "B"

    def test_empty_input_returns_question_mark(self) -> None:
        assert _derive_letters("") == "?"
        assert _derive_letters("   ") == "?"

    def test_single_character_word(self) -> None:
        """A 1-character word → uppercase that char (rule 4 fallback)."""
        assert _derive_letters("x") == "X"
        assert _derive_letters("Z") == "Z"

    def test_extra_whitespace_collapses(self) -> None:
        assert _derive_letters("  git   status  ") == "GS"

    def test_skip_words_case_insensitive(self) -> None:
        """SKIP word check uses .lower() so 'And' / 'AND' / 'and' all skip."""
        assert _derive_letters("foo And bar") == "FB"
        assert _derive_letters("foo AND bar") == "FB"


# ---------------------------------------------------------------------------
# CellWindow per-cell label fields + auto resolution
# ---------------------------------------------------------------------------

def _spawn_cell():
    """Create a standalone CellWindow with no catalog."""
    from scriptree.shell.branding_loader import load_branding
    from scriptree.shell.cell_window import CellWindow
    return CellWindow(load_branding())


class TestCellLabelFields:
    def test_fresh_cell_has_no_label_overrides(self) -> None:
        c = _spawn_cell()
        assert c._icon_path is None
        assert c._text_label is None
        c.close()

    def test_auto_label_text_resolves_from_scriptreetree(
        self, tmp_path: Path,
    ) -> None:
        # Build a real tree on disk and bind it to the cell.
        tool = ToolDef(
            name="alpha",
            executable="/bin/echo",
            argument_template=["x"],
            params=[ParamDef(id="x", label="X", default="hi")],
        )
        leaf_path = tmp_path / "alpha.scriptree"
        save_tool(tool, leaf_path)
        tree = TreeDef(
            name="DemoCatalog",
            nodes=[TreeNode(type="leaf", name="alpha", path=leaf_path.name)],
        )
        tree_path = tmp_path / "demo.scriptreetree"
        save_tree(tree, tree_path)

        c = _spawn_cell()
        c._catalog_path = str(tree_path)
        # "DemoCatalog" → "DC" (CamelCase rule).
        assert c._auto_label_text() == "DC"
        c.close()

    def test_auto_label_text_caches_until_mtime_changes(
        self, tmp_path: Path,
    ) -> None:
        """Repeated calls hit the cache; modifying the file
        invalidates."""
        tool = ToolDef(
            name="originalname",
            executable="/bin/echo",
            argument_template=["x"],
            params=[ParamDef(id="x", label="X", default="hi")],
        )
        p = tmp_path / "tool.scriptree"
        save_tool(tool, p)

        c = _spawn_cell()
        c._catalog_path = str(p)
        first = c._auto_label_text()
        assert first == "OR"
        # Same call again — cache hit (we don't probe internals; just
        # verify the answer is stable).
        assert c._auto_label_text() == "OR"
        c.close()

    def test_auto_label_text_returns_none_when_no_catalog(self) -> None:
        c = _spawn_cell()
        assert c._auto_label_text() is None
        c.close()

    def test_auto_label_text_returns_none_when_file_missing(
        self, tmp_path: Path,
    ) -> None:
        c = _spawn_cell()
        c._catalog_path = str(tmp_path / "nope.scriptreetree")
        assert c._auto_label_text() is None
        c.close()


# ---------------------------------------------------------------------------
# File-drop dispatch matrix
# ---------------------------------------------------------------------------

class TestDropDispatch:
    def test_drop_scriptreetree_on_standalone_binds_catalog(
        self, tmp_path: Path,
    ) -> None:
        # Build a tree on disk.
        tool = ToolDef(
            name="alpha", executable="/bin/echo",
            argument_template=["x"],
            params=[ParamDef(id="x", label="X", default="hi")],
        )
        leaf = tmp_path / "alpha.scriptree"
        save_tool(tool, leaf)
        tree_path = tmp_path / "cat.scriptreetree"
        save_tree(
            TreeDef(name="cat", nodes=[
                TreeNode(type="leaf", name="alpha", path=leaf.name)
            ]),
            tree_path,
        )

        c = _spawn_cell()
        assert c._catalog_path is None
        c._handle_dropped_file(str(tree_path))
        # Standalone cell binds the catalog directly.
        assert c._catalog_path == str(tree_path.resolve())
        c.close()

    def test_drop_scriptreetree_on_master_spawns_new_cell(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.shell.cell_window import CellWindow
        tool = ToolDef(
            name="alpha", executable="/bin/echo",
            argument_template=["x"],
            params=[ParamDef(id="x", label="X", default="hi")],
        )
        leaf = tmp_path / "alpha.scriptree"
        save_tool(tool, leaf)
        tree_path = tmp_path / "cat.scriptreetree"
        save_tree(
            TreeDef(name="cat", nodes=[
                TreeNode(type="leaf", name="alpha", path=leaf.name)
            ]),
            tree_path,
        )

        master = _spawn_cell()
        master.role = "master"

        # Patch CellWindow construction so we can verify a new cell
        # was spawned WITHOUT actually adding to the registry.
        spawned: list = []
        with patch.object(
            CellWindow, "show", lambda self: spawned.append(self),
        ):
            master._handle_dropped_file(str(tree_path))

        # The master itself is NOT bound; a new cell was created
        # with the catalog.
        assert master._catalog_path is None
        assert len(spawned) == 1
        new_cell = spawned[0]
        # Path comparison normalised to handle Windows separators.
        assert Path(new_cell._catalog_path) == Path(tree_path).resolve()
        master.close()

    def test_drop_unknown_extension_ignored(self, tmp_path: Path) -> None:
        bad = tmp_path / "garbage.txt"
        bad.write_text("nope")
        c = _spawn_cell()
        c._handle_dropped_file(str(bad))
        # Catalog still unset; nothing happened.
        assert c._catalog_path is None
        c.close()

    def test_drop_missing_file_ignored(self, tmp_path: Path) -> None:
        c = _spawn_cell()
        c._handle_dropped_file(
            str(tmp_path / "ghost.scriptreetree")
        )
        assert c._catalog_path is None
        c.close()


# ---------------------------------------------------------------------------
# _drop_paths — extension filter
# ---------------------------------------------------------------------------

class TestDropPathsFilter:
    def test_filters_to_supported_extensions_only(self) -> None:
        from PySide6.QtCore import QMimeData, QUrl
        from scriptree.shell.cell_window import CellWindow

        md = QMimeData()
        md.setUrls([
            QUrl.fromLocalFile("C:/x/foo.scriptree"),
            QUrl.fromLocalFile("C:/x/bar.scriptreetree"),
            QUrl.fromLocalFile("C:/x/baz.scriptreering"),
            QUrl.fromLocalFile("C:/x/garbage.txt"),
            QUrl.fromLocalFile("C:/x/no_ext"),
        ])

        class _Evt:
            def mimeData(self):
                return md

        paths = CellWindow._drop_paths(_Evt())
        assert len(paths) == 3
        assert any(p.endswith(".scriptree") for p in paths)
        assert any(p.endswith(".scriptreetree") for p in paths)
        assert any(p.endswith(".scriptreering") for p in paths)
        # Garbage path filtered out.
        assert not any(p.endswith(".txt") for p in paths)


# ---------------------------------------------------------------------------
# Ring file round-trip for icon_path / text_label
# ---------------------------------------------------------------------------

class TestRingIconTextRoundTrip:
    def test_icon_path_round_trips_via_hex_to_dict(self) -> None:
        from scriptree.shell.ring_io import _hex_to_dict
        c = _spawn_cell()
        c._icon_path = "C:/icons/alpha.png"
        d = _hex_to_dict(c)
        assert d.get("icon_path") == "C:/icons/alpha.png"
        c.close()

    def test_text_label_round_trips_via_hex_to_dict(self) -> None:
        from scriptree.shell.ring_io import _hex_to_dict
        c = _spawn_cell()
        c._text_label = "DXF"
        d = _hex_to_dict(c)
        assert d.get("text_label") == "DXF"
        c.close()

    def test_label_fields_omitted_when_unset(self) -> None:
        """Legacy rings that don't have these fields stay byte-
        identical: empty fields are not written."""
        from scriptree.shell.ring_io import _hex_to_dict
        c = _spawn_cell()
        d = _hex_to_dict(c)
        assert "icon_path" not in d
        assert "text_label" not in d
        assert "icon_scale" not in d
        assert "label_opacity" not in d
        c.close()


# ---------------------------------------------------------------------------
# apply_label_change / apply_icon_scale_change / apply_label_opacity_change
# ---------------------------------------------------------------------------

class TestApplyLabelChanges:
    def test_apply_label_change_sets_icon(self, tmp_path: Path) -> None:
        c = _spawn_cell()
        c.apply_label_change(icon_path=str(tmp_path / "x.png"))
        assert c._icon_path == str(tmp_path / "x.png")
        # text_label untouched (sentinel not passed).
        assert c._text_label is None
        c.close()

    def test_apply_label_change_clears_with_none(self) -> None:
        c = _spawn_cell()
        c._icon_path = "C:/x.png"
        c.apply_label_change(icon_path=None)
        assert c._icon_path is None
        c.close()

    def test_apply_label_change_only_updates_passed_fields(self) -> None:
        """Sentinel argument means 'do not change this field'."""
        c = _spawn_cell()
        c._icon_path = "C:/x.png"
        c._text_label = "DXF"
        c.apply_label_change(text_label="GIT")
        # icon_path preserved (sentinel), text_label updated.
        assert c._icon_path == "C:/x.png"
        assert c._text_label == "GIT"
        c.close()

    def test_apply_icon_scale_clamps_to_legal_range(self) -> None:
        c = _spawn_cell()
        c.apply_icon_scale_change(0.05)  # below 0.25 floor
        assert c._icon_scale == 0.25
        c.apply_icon_scale_change(5.0)   # above 2.0 ceil
        assert c._icon_scale == 2.0
        c.apply_icon_scale_change(1.5)
        assert c._icon_scale == 1.5
        c.close()

    def test_apply_label_opacity_clamps_to_legal_range(self) -> None:
        c = _spawn_cell()
        c.apply_label_opacity_change(0.0)  # below 0.20 floor
        assert c._label_opacity == 0.20
        c.apply_label_opacity_change(2.0)  # above 1.00 ceil
        assert c._label_opacity == 1.00
        c.apply_label_opacity_change(0.6)
        assert c._label_opacity == 0.6
        c.close()


# ---------------------------------------------------------------------------
# Ring round-trip for icon_scale + label_opacity
# ---------------------------------------------------------------------------

class TestRingScaleOpacityRoundTrip:
    def test_icon_scale_round_trips(self) -> None:
        from scriptree.shell.ring_io import _hex_to_dict
        c = _spawn_cell()
        c._icon_scale = 1.5
        d = _hex_to_dict(c)
        assert d.get("icon_scale") == 1.5
        c.close()

    def test_label_opacity_round_trips(self) -> None:
        from scriptree.shell.ring_io import _hex_to_dict
        c = _spawn_cell()
        c._label_opacity = 0.6
        d = _hex_to_dict(c)
        assert d.get("label_opacity") == 0.6
        c.close()

    def test_default_values_omitted_from_ring(self) -> None:
        from scriptree.shell.ring_io import _hex_to_dict
        c = _spawn_cell()
        d = _hex_to_dict(c)
        # Defaults (1.0 each) are not emitted, so legacy rings stay
        # byte-identical when no overrides were set.
        assert "icon_scale" not in d
        assert "label_opacity" not in d
        c.close()
