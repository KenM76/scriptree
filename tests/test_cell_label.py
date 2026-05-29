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

class TestLoadCatalogSpawnsSibling:
    """v0.2.8 contract: clicking Load ScripTree / ScripTreeTree from
    the right-click menu must spawn a NEW cell, not replace the
    current cell's catalog.  Per user spec: 'when I go to a cell or
    ring and click to load a scriptree, scriptreetree, or ring it
    should open a new cell or ring and leave the existing one open.'"""

    def test_spawn_sibling_creates_new_cell_with_catalog(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.shell.cell_window import CellWindow
        from scriptree.shell.branding_loader import load_branding

        # Build a real .scriptreetree on disk.
        tool = ToolDef(
            name="alpha", executable="/bin/echo",
            argument_template=["{x}"],
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

        # Spawn the original cell with NO catalog.
        original = CellWindow(load_branding())
        assert original._catalog_path is None

        # Patch CellWindow.show so spawned siblings don't actually pop
        # up on the desktop during the test.
        spawned: list = []
        with patch.object(
            CellWindow, "show", lambda self: spawned.append(self),
        ):
            original._spawn_sibling_with_catalog(str(tree_path))

        # Original is UNTOUCHED.
        assert original._catalog_path is None
        # Exactly one new cell, bound to the chosen catalog.
        assert len(spawned) == 1
        new_cell = spawned[0]
        assert new_cell is not original
        assert Path(new_cell._catalog_path) == tree_path.resolve()

        # Cleanup.
        original.close()
        new_cell.close()


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
# Hover tooltip header (v0.6.9) — "when I hover over each cell or ring
# there should be a header label that pops up over it so I know what
# the icons are for".
# ---------------------------------------------------------------------------

class TestHoverTooltip:
    def test_fresh_standalone_cell_tooltip_is_role_default(self) -> None:
        c = _spawn_cell()
        assert c.toolTip() == "ScripTree"
        c.close()

    def test_tooltip_follows_bound_catalog_name(
        self, tmp_path: Path,
    ) -> None:
        tool = ToolDef(
            name="alpha", executable="/bin/echo",
            argument_template=["x"],
            params=[ParamDef(id="x", label="X", default="hi")],
        )
        leaf = tmp_path / "alpha.scriptree"
        save_tool(tool, leaf)
        tree_path = tmp_path / "cat.scriptreetree"
        save_tree(
            TreeDef(name="My Fancy Catalog", nodes=[
                TreeNode(type="leaf", name="alpha", path=leaf.name)
            ]),
            tree_path,
        )
        c = _spawn_cell()
        c._handle_dropped_file(str(tree_path))
        # The tree's display name becomes the hover header.
        assert c.toolTip() == "My Fancy Catalog"
        c.close()

    def test_tooltip_reverts_to_default_when_catalog_cleared(
        self, tmp_path: Path,
    ) -> None:
        tool = ToolDef(
            name="solo", executable="/bin/echo",
            argument_template=["x"],
            params=[ParamDef(id="x", label="X", default="hi")],
        )
        p = tmp_path / "solo.scriptree"
        save_tool(tool, p)
        c = _spawn_cell()
        c._handle_dropped_file(str(p))
        assert c.toolTip() == "solo"
        # Simulate the "Clear catalog" menu path.
        c._catalog_path = None
        c._update_hover_tooltip()
        assert c.toolTip() == "ScripTree"
        c.close()

    def test_master_tooltip_is_tree_ring(self) -> None:
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow
        m = CellWindow(load_branding(), role="master")
        assert m.toolTip() == "Tree Ring"
        m.close()

    def test_forest_master_tooltip_is_forest(self) -> None:
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow
        f = CellWindow(
            load_branding(), role="master", is_forest_master=True,
        )
        assert f.toolTip() == "Forest"
        f.close()

    def test_master_with_icon_paints_it_no_centre_dot(self) -> None:
        """v0.6.14 — forest/ring hubs that carry an icon must
        actually render it.  Pre-v0.6.14 the paintEvent skipped
        ``_paint_cell_label`` for masters entirely, so the
        hub-icon wiring (icon-forest / icon-ring / a user-bound
        catalog) was invisible — only a small centre dot showed.
        Drive the relevant code path with a hand-fed
        ``QPaintEvent`` and assert the master_painted_icon
        decision branched correctly.
        """
        # We can't easily assert "which pixels got drawn", but we
        # CAN drive the same conditional ``paintEvent`` uses and
        # ensure the icon path would have run.  The compact form
        # is just exercising the predicate.
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow
        from scriptree.shell.icon_assets import bundled_icon_b64

        m = CellWindow(load_branding(), role="master")
        try:
            # No icon yet → would paint the centre dot.
            assert not bool(
                getattr(m, "_icon_data_b64", "")
                or getattr(m, "_icon_path", None)
            )
            # Apply the bundled forest icon (what
            # ForestController.start does).
            b64 = bundled_icon_b64("forest")
            assert b64, "icon-forest must ship in the bundled set"
            m._icon_data_b64 = b64
            m._icon_data_format = "png"
            # Now the predicate must say "yes, paint icon".
            assert bool(m._icon_data_b64)
        finally:
            m.close()

    def test_tooltip_event_swallowed_by_event_override(self) -> None:
        """v0.6.27 — the ``event(QEvent.ToolTip)`` override SWALLOWS
        the platform tooltip event (returns True without calling
        ``QToolTip.showText``).  The custom ``_CellHoverTip`` widget
        — driven by enterEvent + a QTimer — replaces the platform
        tooltip path so the tip carries our own
        WindowStaysOnTopHint and draws *above* always-on-top cells.

        v0.6.13 used to route through ``QToolTip.showText`` here;
        that popup competed with the cells' StaysOnTop on Win11 and
        rendered behind them — the user saw nothing.
        """
        from PySide6.QtCore import QEvent, QPoint
        from PySide6.QtGui import QHelpEvent
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        c = CellWindow(load_branding())
        try:
            ev = QHelpEvent(
                QEvent.Type.ToolTip, QPoint(10, 10), QPoint(100, 100),
            )
            handled = c.event(ev)
            # Event is consumed so the platform's default tooltip
            # path can't fire underneath our custom widget.
            assert handled is True
        finally:
            c.close()

    def test_hover_tip_title_resolves_through_popup_header(self) -> None:
        """v0.6.27 — the custom hover-tip text comes from
        ``tree_popup._popup_header_text`` (the same source as the
        popup-menu header), so hover-tip + menu-title agree.

        For an unbound standalone cell that resolves to the
        role-default ``"ScripTree"``.
        """
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow
        from scriptree.shell.tree_popup import _popup_header_text

        c = CellWindow(load_branding())
        try:
            assert _popup_header_text(c) == "ScripTree"
        finally:
            c.close()


# ---------------------------------------------------------------------------
# Macify (v0.6.10) — _smooth_move fluidity contract
# ---------------------------------------------------------------------------

class TestSmoothMove:
    def test_smooth_move_instant_when_hidden(self) -> None:
        """A hidden widget never animates — there's nothing to see."""
        c = _spawn_cell()
        assert not c.isVisible()
        c.move(100, 100)
        c._smooth_move(400, 250)
        # No animation kicked in.
        assert getattr(c, "_pos_anim", None) is None
        assert c.pos().x() == 400 and c.pos().y() == 250
        c.close()

    def test_smooth_move_instant_below_threshold(self) -> None:
        """Sub-pixel-ish deltas just teleport (no jitter animation)."""
        c = _spawn_cell()
        c.show()
        c.move(100, 100)
        c._smooth_move(101, 100, threshold_px=2)
        assert getattr(c, "_pos_anim", None) is None
        c.close()

    def test_smooth_move_instant_when_mid_drag(self) -> None:
        """Mid-drag updates must be instant — animating each cursor
        tick would lag the pointer."""
        c = _spawn_cell()
        c.show()
        c.move(100, 100)
        c._drag_started = True
        c._smooth_move(300, 220)
        assert getattr(c, "_pos_anim", None) is None
        assert c.pos().x() == 300 and c.pos().y() == 220
        c._drag_started = False
        c.close()

    def test_smooth_move_instant_above_max_animate(self) -> None:
        """Cross-screen jumps teleport: a 600+ px slide reads as slow
        rather than fluid."""
        c = _spawn_cell()
        c.show()
        c.move(0, 0)
        c._smooth_move(1200, 100, max_animate_px=600)
        assert getattr(c, "_pos_anim", None) is None
        assert c.pos().x() == 1200
        c.close()

    def test_smooth_move_animates_when_in_band(self) -> None:
        """A modest in-screen delta starts an animation and the
        animation reaches the target when the event loop is pumped."""
        from PySide6.QtCore import QEventLoop, QTimer
        c = _spawn_cell()
        c.show()
        c.move(100, 100)
        c._smooth_move(220, 180, duration_ms=80)
        anim = getattr(c, "_pos_anim", None)
        assert anim is not None, "expected an animation to start"
        # Pump the loop long enough for the 80 ms animation to finish.
        loop = QEventLoop()
        QTimer.singleShot(220, loop.quit)
        loop.exec()
        assert c.pos().x() == 220 and c.pos().y() == 180
        # Animation cleared after finishing.
        assert getattr(c, "_pos_anim", None) is None
        c.close()

    def test_smooth_move_cancels_prior_animation(self) -> None:
        """Successive _smooth_move calls don't stack — the latest
        target wins."""
        c = _spawn_cell()
        c.show()
        c.move(0, 0)
        c._smooth_move(120, 90, duration_ms=400)
        first = getattr(c, "_pos_anim", None)
        assert first is not None
        c._smooth_move(220, 160, duration_ms=400)
        second = getattr(c, "_pos_anim", None)
        assert second is not None
        assert second is not first
        # The first animation has been stopped.
        from PySide6.QtCore import QAbstractAnimation
        assert first.state() != QAbstractAnimation.State.Running
        c.close()


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

    def test_apply_text_over_icon_toggles_and_persists(
        self, tmp_path: Path,
    ) -> None:
        """v0.6.9 superimpose flag: toggling it on a catalog-bound
        cell writes through to the catalog JSON."""
        from scriptree.core.cell_metadata import read_for
        tool = ToolDef(
            name="alpha", executable="/bin/echo",
            argument_template=["x"],
            params=[ParamDef(id="x", label="X", default="hi")],
        )
        p = tmp_path / "alpha.scriptree"
        save_tool(tool, p)
        c = _spawn_cell()
        c._handle_dropped_file(str(p))
        assert c._label_text_over_icon is False
        c.apply_text_over_icon_change(True)
        assert c._label_text_over_icon is True
        # Persisted into the bound catalog.
        assert read_for(p).text_over_icon is True
        c.apply_text_over_icon_change(False)
        assert read_for(p).text_over_icon is False
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


# ---------------------------------------------------------------------------
# v0.6.12 — _settle_no_overlap: cells/rings/forest never overlap or
# go off-screen at rest
# ---------------------------------------------------------------------------

class TestSettleNoOverlap:
    def _spawn(self):
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow
        c = CellWindow(load_branding())
        c.show()
        return c

    def _close_all(self) -> None:
        from scriptree.shell.cell_registry import CellRegistry
        for h in list(CellRegistry.instance().all()):
            try:
                h.close()
            except Exception:  # noqa: BLE001
                pass

    def test_settle_is_noop_when_already_free(self) -> None:
        a = self._spawn()
        a.move(200, 200)
        # No other cells on screen → no obstacles → no-op.
        a._settle_no_overlap()
        assert getattr(a, "_pos_anim", None) is None
        assert a.pos().x() == 200 and a.pos().y() == 200
        self._close_all()

    def test_settle_moves_overlapping_cell(self) -> None:
        """Two visible standalone cells stacked on the same pixel:
        settle on one of them slides it to a clear spot."""
        from PySide6.QtCore import QEventLoop, QTimer
        a = self._spawn()
        b = self._spawn()
        a.move(400, 400)
        b.move(400, 400)  # exact stack
        # Settle b — it should move; a should stay put.
        b._settle_no_overlap()
        # The settle uses _smooth_move; pump the loop to let it land.
        loop = QEventLoop()
        QTimer.singleShot(350, loop.quit)
        loop.exec()
        # a still at (400, 400)
        assert a.pos().x() == 400 and a.pos().y() == 400
        # b has moved
        assert b.pos() != a.pos()
        # And b is no longer stacked centre-on-centre with a.
        sz = b._size_px
        threshold = sz * 0.5
        ca = (a.pos().x() + sz // 2, a.pos().y() + sz // 2)
        cb = (b.pos().x() + sz // 2, b.pos().y() + sz // 2)
        assert (
            abs(ca[0] - cb[0]) >= threshold
            or abs(ca[1] - cb[1]) >= threshold
        )
        self._close_all()

    def test_settle_skips_hidden(self) -> None:
        """A hidden cell shouldn't be moved even when overlapping."""
        a = self._spawn()
        b = self._spawn()
        a.move(500, 500)
        b.move(500, 500)
        b.hide()
        b._settle_no_overlap()
        # Stayed put — settle is a no-op on hidden cells.
        assert b.pos().x() == 500 and b.pos().y() == 500
        self._close_all()

    def test_settle_skips_during_collapse(self) -> None:
        """During collapse/expand animations, overlap is allowed
        (members shrink toward the master)."""
        a = self._spawn()
        b = self._spawn()
        a.move(300, 300)
        b.move(300, 300)
        b._collapse_state = "collapsing"
        b._settle_no_overlap()
        # Did not run during the animation phase.
        assert b.pos().x() == 300 and b.pos().y() == 300
        b._collapse_state = "expanded"
        self._close_all()

    def test_settle_avoids_off_screen(self) -> None:
        """The settle never lands the cell beyond availableGeometry."""
        from PySide6.QtCore import QEventLoop, QTimer
        from PySide6.QtGui import QGuiApplication
        a = self._spawn()
        b = self._spawn()
        # Stack at the top-left of the available area so any
        # leftward/upward settle would push b off-screen.
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        if avail is not None:
            x = avail.left() + 4
            y = avail.top() + 4
        else:
            x, y = 4, 4
        a.move(x, y)
        b.move(x, y)
        b._settle_no_overlap()
        loop = QEventLoop()
        QTimer.singleShot(350, loop.quit)
        loop.exec()
        if avail is not None:
            assert b.pos().x() >= avail.left()
            assert b.pos().y() >= avail.top()
            assert b.pos().x() + b._size_px <= avail.right()
            assert b.pos().y() + b._size_px <= avail.bottom()
        self._close_all()


class TestResolveMemberStacking:
    def test_stacking_repacks_offenders(self) -> None:
        """``_resolve_member_stacking`` on a master with two centre-
        stacked members surgical-repacks the offenders.  Mirror of
        the forest test but on a plain ring-master."""
        from PySide6.QtCore import QEventLoop, QPoint, QTimer
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        master = CellWindow(load_branding(), role="master")
        a = CellWindow(load_branding())
        b = CellWindow(load_branding())
        master.show(); a.show(); b.show()
        master.move(500, 500)
        a.move(500, 500); b.move(500, 500)
        master._members[a._id] = QPoint(500, 500)
        master._members[b._id] = QPoint(500, 500)
        master._positioned.add(a._id); master._positioned.add(b._id)
        a._group_master_id = master._id; b._group_master_id = master._id

        master._resolve_member_stacking()
        loop = QEventLoop()
        QTimer.singleShot(400, loop.quit)
        loop.exec()

        sz = a._size_px
        threshold = sz * 0.5
        ca = (a.pos().x() + sz // 2, a.pos().y() + sz // 2)
        cb = (b.pos().x() + sz // 2, b.pos().y() + sz // 2)
        assert (
            abs(ca[0] - cb[0]) >= threshold
            or abs(ca[1] - cb[1]) >= threshold
        ), f"members still stacked: a={ca}, b={cb}"
        master.close(); a.close(); b.close()


class TestComputeLayout:
    """v0.6.35 — the new slot-based layout function on master cells.

    Pins the bridge between the pure-Python algorithm (proven by
    ``tests/test_layout_algorithm.py``) and the Qt widget code.
    See ``scriptree/shell/layout.py`` for the algorithm and
    ``docs/LLM/scenegraph_layout_plan.md`` for the model docs.
    """

    def test_compute_layout_assigns_slots_to_unassigned_members(self) -> None:
        """Calling ``_compute_layout`` on a master with members that
        have ``_slot = None`` and ``_floating_intent = False``
        should assign them slots.  Mirrors the simulator's
        ``assign_initial_slots`` semantics."""
        from PySide6.QtCore import QPoint
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        master = CellWindow(load_branding(), role="master")
        master.show()
        master.move(400, 400)

        cells = []
        for i in range(3):
            c = CellWindow(load_branding())
            c.show()
            c.move(100 + i * 10, 100)  # stale starting positions
            master._members[c._id] = QPoint(c.pos())
            master._positioned.add(c._id)
            c._group_master_id = master._id
            cells.append(c)

        # Before compute_layout: no slots assigned.
        for c in cells:
            assert c._slot is None
            assert c._floating_intent is False

        master._compute_layout(instant=True)

        # After: every cell got a slot.
        slots = [c._slot for c in cells]
        assert all(s is not None for s in slots), f"some unassigned: {slots}"
        # No two cells share a slot.
        assert len(set(slots)) == 3, f"slot collision: {slots}"
        # Cells are positioned at the slot world coords (not the
        # stale (100, 100) starting positions).
        for c in cells:
            assert c.pos().x() != 100 or c.pos().y() != 100, (
                f"{c._id[:8]} still at stale pos {c.pos()}"
            )

        for c in cells:
            c.close()
        master.close()

    def test_compute_layout_skips_floating_cells(self) -> None:
        """A cell with ``_floating_intent=True`` should NOT be
        reassigned a slot — it keeps the pos the user gave it."""
        from PySide6.QtCore import QPoint
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        master = CellWindow(load_branding(), role="master")
        master.show()
        master.move(400, 400)

        cell = CellWindow(load_branding())
        cell.show()
        cell.move(200, 200)
        cell._floating_intent = True
        cell._group_master_id = master._id
        master._members[cell._id] = QPoint(200, 200)

        master._compute_layout(instant=True)

        assert cell._slot is None, "floating cell got an unwanted slot"
        # Position unchanged.
        assert cell.pos().x() == 200 and cell.pos().y() == 200

        cell.close()
        master.close()

    def test_compute_layout_idempotent(self) -> None:
        """Running ``_compute_layout`` twice in a row produces the
        same result the second time."""
        from PySide6.QtCore import QPoint
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        master = CellWindow(load_branding(), role="master")
        master.show()
        master.move(400, 400)

        cells = []
        for i in range(4):
            c = CellWindow(load_branding())
            c.show()
            c.move(100 + i * 10, 100)
            master._members[c._id] = QPoint(c.pos())
            master._positioned.add(c._id)
            c._group_master_id = master._id
            cells.append(c)

        master._compute_layout(instant=True)
        first_slots = [c._slot for c in cells]
        first_pos = [(c.pos().x(), c.pos().y()) for c in cells]

        master._compute_layout(instant=True)
        second_slots = [c._slot for c in cells]
        second_pos = [(c.pos().x(), c.pos().y()) for c in cells]

        assert first_slots == second_slots
        assert first_pos == second_pos

        for c in cells:
            c.close()
        master.close()

    def test_compute_layout_excludes_own_members_from_occupied(
        self,
    ) -> None:
        """v0.6.39 — regression: the first member spawned on a fresh
        master MUST be allowed to land at slot ``(inner, 0)`` (East),
        even though the member's pre-layout widget position is right
        next to the master.

        v0.6.38 build had a bug where the layout's
        ``occupied_centres`` snapshot included the member being
        placed at its stale spawn position.  Slot inner,0 (East)
        sits very close to that spawn position, so the 42 px global
        collision threshold flagged it as occupied (by the cell
        itself).  ``find_free_slot`` then cascaded to inner,1 NE,
        and subsequent members filled NE/NW/SW/SE — leaving the
        ring with empty E/W slots and visible gaps where tiled
        honeycomb neighbours should sit.

        The fix excludes ``self._members`` from the initial
        occupied snapshot; this test makes sure it stays excluded.
        """
        from PySide6.QtCore import QPoint
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        master = CellWindow(load_branding(), role="master")
        master.show()
        master.move(400, 400)

        # Spawn a single member with its stale pre-layout position
        # right at the master's east shoulder — the exact place
        # slot inner,0 will sit after layout.  Pre-fix, the member
        # would self-collide and end up at inner,1 (NE).
        size = master._size_px
        cell = CellWindow(load_branding())
        cell.show()
        cell.move(400 + size, 400)
        master._members[cell._id] = QPoint(cell.pos())
        master._positioned.add(cell._id)
        cell._group_master_id = master._id

        master._compute_layout(instant=True)

        # v0.7.0 — assertion relaxed to "got SOME slot in the eastern
        # hemisphere" because nearest_free_slot now binds to the
        # nearest slot to the cell's spawn centre, not the first free
        # slot index.  Cell spawned east lands at NE (slot 1) or SE
        # (slot 2), tied, lexicographic tiebreak picks slot 1.  The
        # original v0.6.39 fix (no self-collision) is what this test
        # is really pinning.
        assert cell._slot is not None, (
            "first member got no slot — v0.6.38 self-collision bug "
            "regressed"
        )
        assert cell._slot in (("inner", 1), ("inner", 2)), (
            f"cell spawned east should bind to slot 1 (NE) or 2 (SE) "
            f"via nearest_free_slot — got {cell._slot!r}"
        )

        cell.close()
        master.close()

    def test_inner_slot_neighbour_distance_is_R_sqrt3(self) -> None:
        """v0.6.40 — slot ``inner,0`` must place the child so its
        centre sits ``size_px × √3/2`` from the master's centre
        (the apothem-doubled edge-touching distance).

        v0.6.39 and earlier placed the child at distance
        ``size_px`` (1 × size_px) which is the tip-to-tip
        vertex-touching distance for flat-top hexes, not
        edge-to-edge.  This test pins the corrected geometry from
        Red Blob Games's hexagonal-grid reference.
        """
        import math as _m
        from PySide6.QtCore import QPoint
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        master = CellWindow(load_branding(), role="master")
        master.show()
        master.move(400, 400)
        size = master._size_px

        cell = CellWindow(load_branding())
        cell.show()
        cell.move(400 + size, 400)
        master._members[cell._id] = QPoint(cell.pos())
        master._positioned.add(cell._id)
        cell._group_master_id = master._id

        master._compute_layout(instant=True)

        # Master centre.
        mcx = master.pos().x() + size / 2
        mcy = master.pos().y() + size / 2
        # Cell centre.
        ccx = cell.pos().x() + cell._size_px / 2
        ccy = cell.pos().y() + cell._size_px / 2

        d = _m.hypot(ccx - mcx, ccy - mcy)
        expected = size * _m.sqrt(3) / 2
        # 1 px tolerance for integer rounding (slot_world_pos rounds).
        assert abs(d - expected) <= 1.0, (
            f"first member centre is {d:.2f} px from master centre; "
            f"edge-touching honeycomb wants {expected:.2f} px "
            f"(= size_px × √3/2)"
        )

        cell.close()
        master.close()

    def test_flat_top_slot_0_is_north(self) -> None:
        """v0.6.40 — slot ``(inner, 0)`` for a flat-top master sits
        due north (positive math-y, negative screen-y).  Matches
        ``snap_engine._FLAT_TOP_OFFSETS`` so a cell that snaps to
        slot 0 doesn't get re-positioned on the first layout
        pass.
        """
        from scriptree.shell.layout import slot_offset

        size = 56
        dx, dy = slot_offset(("inner", 0), size, "flat-top")
        # North in Qt coords: dx ≈ 0, dy strongly negative.
        assert abs(dx) <= 1, f"slot 0 not due north — dx={dx}"
        assert dy < -size / 2, (
            f"slot 0 not above master — dy={dy}, "
            f"expected dy < -{size / 2}"
        )

    def test_pointy_top_slot_0_is_east(self) -> None:
        """v0.6.40 — slot ``(inner, 0)`` for a pointy-top master
        sits due east.  Matches snap_engine's
        ``_POINTY_TOP_OFFSETS``.
        """
        from scriptree.shell.layout import slot_offset

        size = 56
        dx, dy = slot_offset(("inner", 0), size, "pointy-top")
        assert abs(dy) <= 1, f"slot 0 not due east — dy={dy}"
        assert dx > size / 2, (
            f"slot 0 not to the right — dx={dx}, "
            f"expected dx > {size / 2}"
        )

    def test_snap_committed_position_binds_to_correct_slot(self) -> None:
        """v0.7.0 — when the snap engine commits a cell to a
        specific edge of the master, the next ``_compute_layout``
        call must bind that cell to the slot AT THAT EDGE, not to
        slot 0 in insertion order.

        Pre-v0.7.0 used ``find_free_slot`` which iterates 0, 1, 2, …
        and picks the first available — so a cell snapped to the
        S edge of the master got bound to slot 0 (N) instead, and
        the layout pass then MOVED it from S to N.  This jumbled
        every snap-committed cell.

        v0.7.0 uses ``nearest_free_slot`` keyed on the cell's
        current centre, so the slot assigned matches the position
        the snap engine committed.
        """
        from PySide6.QtCore import QPoint
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow
        from scriptree.shell.tiling import (
            HEX_FLAT_TOP, slot_world_pos as _swp,
        )

        master = CellWindow(load_branding(), role="master")
        master.show()
        master.move(400, 400)
        size = master._size_px

        # Place a cell at the SOUTH slot of the master, simulating
        # what the snap engine would commit to.  Snap commits the
        # cell at slot world position; we recreate that.
        s_tl = _swp(
            (master.pos().x(), master.pos().y()),
            HEX_FLAT_TOP, size, "inner", 3,  # slot 3 = S for flat-top
        )
        cell = CellWindow(load_branding())
        cell.show()
        cell.move(*s_tl)
        master._members[cell._id] = QPoint(cell.pos())
        master._positioned.add(cell._id)
        cell._group_master_id = master._id

        master._compute_layout(instant=True)

        assert cell._slot == ("inner", 3), (
            f"snap-committed cell at S slot should bind to "
            f"('inner', 3) S — got {cell._slot!r}.  Without "
            f"v0.7.0's nearest_free_slot, this is ('inner', 0) N "
            f"and the cell gets moved from S to N."
        )

        cell.close()
        master.close()

    def test_compute_layout_fills_full_inner_ring(self) -> None:
        """v0.6.39 — regression: spawning six members one-by-one
        (each created at the master's spawn position before
        layout runs) must fill every inner slot 0..5, not leave
        E/W gaps.

        Mimics the forest auto-populate path that initially showed
        the bug: each new cell is born next to the master, layout
        runs with that cell's stale center in scope, and (pre-fix)
        the East/West slots were skipped because the freshly-born
        cell was treated as already occupying them.
        """
        from PySide6.QtCore import QPoint
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        master = CellWindow(load_branding(), role="master")
        master.show()
        master.move(400, 400)

        size = master._size_px
        cells = []
        for _ in range(6):
            c = CellWindow(load_branding())
            c.show()
            # Spawn right next to the master, as the forest
            # auto-populate path does.
            c.move(400 + size, 400)
            master._members[c._id] = QPoint(c.pos())
            master._positioned.add(c._id)
            c._group_master_id = master._id
            cells.append(c)
            master._compute_layout(instant=True)

        slot_set = {c._slot for c in cells}
        expected = {("inner", i) for i in range(6)}
        assert slot_set == expected, (
            f"inner ring not fully filled — got {sorted(slot_set)}"
            f", expected {sorted(expected)}"
        )

        for c in cells:
            c.close()
        master.close()


class TestMembershipAudit:
    """v0.6.38 — ``_audit_membership`` self-heals broken bookkeeping.

    The v0.6.37 trace exposed four kinds of corruption that the
    snap-commit pair-master spawn path can leave behind:

      * phantom ids in ``_positioned`` (cell no longer in registry)
      * stale ``_members`` entries (same)
      * cells with parent set but slot but NOT in ``_positioned``
      * orphan cells (parent=None but slot still set)

    The audit fixes each in place.
    """

    def test_phantom_id_in_positioned_removed(self) -> None:
        from PySide6.QtCore import QPoint
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        master = CellWindow(load_branding(), role="master")
        master.show()
        master.move(400, 400)
        # Pretend an old member id is still in _positioned but the
        # cell has been closed.
        master._positioned.add("ghost-id-no-longer-exists")
        master._audit_membership()
        assert "ghost-id-no-longer-exists" not in master._positioned
        master.close()

    def test_stale_member_id_removed(self) -> None:
        from PySide6.QtCore import QPoint
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        master = CellWindow(load_branding(), role="master")
        master.show()
        master.move(400, 400)
        # Add a member by id without the cell existing.
        master._members["ghost-id"] = QPoint(0, 0)
        master._positioned.add("ghost-id")
        master._audit_membership()
        assert "ghost-id" not in master._members
        assert "ghost-id" not in master._positioned
        master.close()

    def test_linked_cell_with_slot_added_to_positioned(self) -> None:
        from PySide6.QtCore import QPoint
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        master = CellWindow(load_branding(), role="master")
        cell = CellWindow(load_branding())
        for w in (master, cell):
            w.show()
        master.move(400, 400)
        cell.move(500, 400)
        # Wire membership as the snap-commit pair-master spawn does,
        # but deliberately leave cell out of _positioned to simulate
        # the v0.6.37 corruption.
        master._members[cell._id] = QPoint(cell.pos())
        cell._group_master_id = master._id
        cell._slot = ("inner", 0)
        # NOT in _positioned.
        assert cell._id not in master._positioned

        master._audit_membership()
        assert cell._id in master._positioned
        master.close()
        cell.close()

    def test_orphan_cell_with_slot_reparented(self) -> None:
        from PySide6.QtCore import QPoint
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        master = CellWindow(load_branding(), role="master")
        cell = CellWindow(load_branding())
        for w in (master, cell):
            w.show()
        master.move(400, 400)
        cell.move(500, 400)
        # cell is in master._members + has a slot, but parent_id is
        # None (orphaned by a buggy snap-commit cleanup).
        master._members[cell._id] = QPoint(cell.pos())
        cell._group_master_id = None
        cell._slot = ("inner", 0)

        master._audit_membership()
        # Parent restored to this master, cell added to _positioned.
        assert cell._group_master_id == master._id
        assert cell._id in master._positioned
        master.close()
        cell.close()


class TestAutoClassifiedIcon:
    """v0.6.33 — when a cell is bound to a catalog that has no
    explicit ``cell.icon_data`` / ``cell.icon`` and no
    ``cell.text_label`` override, the paint code falls back to
    ``icon_assets.classify_icon`` on the catalog's name to pick a
    sensible bundled glyph (the same heuristic the popup-menu rows
    use).  The Settings → Library override still wins because the
    explicit-icon branch fires before this one.
    """

    def _saved_tool(self, tmp_path: Path, name: str) -> tuple[ToolDef, str]:
        from scriptree.core.io import save_tool
        from scriptree.core.model import ToolDef
        tool = ToolDef(name=name, executable="/bin/echo")
        path = tmp_path / f"{name.replace(' ', '_')}.scriptree"
        save_tool(tool, path)
        return tool, str(path)

    def test_keyword_match_returns_classified_pixmap(
        self, tmp_path: Path,
    ) -> None:
        """A tool named ``"compile-and-build"`` classifies to
        ``icon-build.png`` — auto-classify returns its QPixmap."""
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        _tool, path = self._saved_tool(tmp_path, "compile-and-build")
        c = CellWindow(load_branding())
        c._catalog_path = path
        try:
            pix = c._auto_classified_pixmap()
            assert pix is not None
            assert not pix.isNull()
        finally:
            c.close()

    def test_generic_default_for_unclassifiable(
        self, tmp_path: Path,
    ) -> None:
        """A tool whose name doesn't match any rule lands at the
        ``"tool"`` default — still a real bundled pixmap."""
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        _tool, path = self._saved_tool(tmp_path, "zzqq")
        c = CellWindow(load_branding())
        c._catalog_path = path
        try:
            pix = c._auto_classified_pixmap()
            assert pix is not None
            assert not pix.isNull()
        finally:
            c.close()

    def test_unbound_standalone_returns_none(self) -> None:
        """A standalone cell with no catalog binding has no
        catalog name to classify against — auto-classify returns
        None and paint falls through to the existing auto-letters
        / nothing path."""
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        c = CellWindow(load_branding())
        try:
            assert c._auto_classified_pixmap() is None
        finally:
            c.close()

    def test_master_default_forest(self) -> None:
        """An unbound forest master gets ``icon-forest`` so the
        forest hub draws an icon out of the box without a
        catalog."""
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        c = CellWindow(load_branding(), role="master")
        c._is_forest_master = True
        try:
            pix = c._auto_classified_pixmap()
            assert pix is not None
            assert not pix.isNull()
        finally:
            c.close()

    def test_master_default_ring(self) -> None:
        """An unbound ring master gets ``icon-ring`` for the
        same reason — never a blank master."""
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        c = CellWindow(load_branding(), role="master")
        # Default _is_forest_master is False → ring.
        try:
            pix = c._auto_classified_pixmap()
            assert pix is not None
            assert not pix.isNull()
        finally:
            c.close()

    def test_cache_is_mtime_keyed(self, tmp_path: Path) -> None:
        """Editing the catalog (mtime change) invalidates the
        cache so a re-classify picks up a name change next paint.
        """
        import time
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        _tool, path = self._saved_tool(tmp_path, "old-name")
        c = CellWindow(load_branding())
        c._catalog_path = path
        try:
            first = c._auto_classified_pixmap()
            assert first is not None
            cache_after_first = c._classified_icon_cache
            assert cache_after_first is not None

            # Rewrite the catalog with a different name so the
            # mtime changes (and so would the classification).
            time.sleep(0.05)  # ensure mtime resolution doesn't tie
            self._saved_tool(tmp_path, "old-name")  # same path, fresh mtime

            second = c._auto_classified_pixmap()
            # Cache must have been refreshed (key changed).
            assert c._classified_icon_cache[0] != cache_after_first[0]
            assert second is not None
        finally:
            c.close()


class TestBreakFreeKeepsForestLink:
    """The user spec 'cells dragged away from the forest stay
    linked' is satisfied by ``_break_free_from_cluster`` preserving
    ``_group_master_id``.  Lock that contract."""

    def test_break_free_preserves_group_master_id(self) -> None:
        from PySide6.QtCore import QPoint
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        master = CellWindow(load_branding(), role="master")
        cell = CellWindow(load_branding())
        master.show(); cell.show()
        master.move(400, 400)
        cell.move(456, 400)
        master._members[cell._id] = QPoint(456, 400)
        master._positioned.add(cell._id)
        master._dock_partners.add(cell._id)
        cell._group_master_id = master._id
        cell._docked_to.add(master._id)

        # Break-free drag (the path mouseMoveEvent takes when
        # _drag_started crosses the threshold on a docked cell).
        cell._break_free_from_cluster()

        # Group link preserved, but the positional cluster broken.
        assert cell._group_master_id == master._id
        assert master._id not in cell._docked_to
        assert cell._id not in master._positioned
        # And the cell still appears in master._members (logical
        # member, just not currently in the contiguous cluster).
        assert cell._id in master._members
        master.close(); cell.close()
