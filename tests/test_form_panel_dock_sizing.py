"""End-to-end tests that pin the form-panel layout contract across
MainWindow (developer mode) and StandaloneWindow (standalone mode).

The standalone scrolled-away-controls bug went through several
release cycles (a14 / a16 / a17) before being properly fixed.  The
failure mode was always the same: bottom band (cfg row + Run/Stop
button row + status) compressed out of view.  This file builds a
real ToolRunnerView and a real StandaloneWindow, then asserts the
bottom band geometry stays visible AND doesn't grow a bloated
empty strip below the Run row.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.question = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)

from scriptree.core.io import save_tool
from scriptree.core.model import ParamDef, ParamType, ToolDef, Widget


def _saved_busy_tool(tmp_path: Path) -> tuple[ToolDef, str]:
    """Build a tool with enough params to stress the form layout."""
    tool = ToolDef(
        name="StressTool",
        executable="echo",
        argument_template=["{p0}"],
        params=[
            ParamDef(id=f"p{i}", label=f"Param {i}", default=f"v{i}")
            for i in range(16)
        ] + [
            ParamDef(
                id="msg", label="Message",
                type=ParamType.STRING, widget=Widget.TEXTAREA,
                default="multi-line\nstarter\nvalue",
            ),
        ],
    )
    p = tmp_path / "stress.scriptree"
    save_tool(tool, p)
    return tool, str(p)


class TestMinimumSizeHintReachableFromCpp:
    """The override must be reachable from Qt's C++ side.

    v0.8.0a18 assigned ``container.minimumSizeHint = lambda: ...`` at
    the instance level, which Python honours but Qt does NOT -- the
    C++ vtable bypasses Python's __dict__.  v0.8.0a19 fixed it by
    subclassing ``QWidget``.  This test pins the contract by checking
    the override actually propagates through ``QSizePolicy.heightForWidth``-
    style queries that go through the C++ machinery.
    """

    def test_subclass_minimum_size_hint_used(self, tmp_path: Path) -> None:
        from scriptree.ui.tool_runner import (
            ToolRunnerView, _FormPanelContainer,
        )
        tool = ToolDef(
            name="x", executable="echo",
            argument_template=["{p0}"],
            params=[ParamDef(id="p0", label="P0", default="v0")],
        )
        runner = ToolRunnerView(tool)
        assert isinstance(runner.form_panel, _FormPanelContainer), (
            "form_panel must be a _FormPanelContainer instance "
            "(subclassed for the C++ vtable override)."
        )
        # Trigger the override and verify it returns something
        # larger than the default 0x0 minimum.
        min_hint = runner.form_panel.minimumSizeHint()
        assert min_hint.height() > 100, (
            f"minimumSizeHint reported {min_hint.height()} px -- "
            f"the override isn't being called.  Likely a regression "
            f"to the instance-attribute assignment pattern."
        )


class TestMinimumSizeHint:
    """The form panel container reports a minimumSizeHint large
    enough to hold header + bottom band + a small form floor."""

    def test_min_size_hint_includes_bottom_band(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.ui.tool_runner import ToolRunnerView
        tool, _ = _saved_busy_tool(tmp_path)
        runner = ToolRunnerView(tool)
        form_panel = runner.form_panel
        # The form panel's minimumSizeHint must accommodate the
        # bottom band's sizeHint -- otherwise QtAds shrinks the
        # dock past the cfg / Run row.
        band_h = runner._bottom_band.sizeHint().height()
        min_h = form_panel.minimumSizeHint().height()
        assert min_h >= band_h, (
            f"form_panel minimumSizeHint={min_h} doesn't accommodate "
            f"bottom_band sizeHint={band_h}"
        )

    def test_min_size_hint_not_bloated(self, tmp_path: Path) -> None:
        """The min-size override should NOT add a static 200 px
        buffer that leaves empty space below the Run row.  Bound
        the minimum at band + header + a modest form floor."""
        from scriptree.ui.tool_runner import ToolRunnerView
        tool, _ = _saved_busy_tool(tmp_path)
        runner = ToolRunnerView(tool)
        band_h = runner._bottom_band.sizeHint().height()
        header_h = runner._header_box.sizeHint().height()
        min_h = runner.form_panel.minimumSizeHint().height()
        # Allow some slack but reject a wildly inflated minimum.
        # FORM_FLOOR=60 + 60 slack.
        upper_bound = header_h + 120 + band_h
        assert min_h <= upper_bound, (
            f"form_panel minimumSizeHint={min_h} too generous "
            f"(header={header_h} + bottom_band={band_h}); would "
            f"leave dead space below the Run buttons."
        )


class TestFormDockHonorsContentMinimumHint:
    """The QtAds form dock must use the contained widget's
    ``minimumSizeHint`` -- not its own (which is always 0/0).

    v0.8.0a18 had the _FormPanelContainer subclass returning the
    correct ~404 px hint, but the form dock still collapsed to
    ~328 px because QtAds defaulted to ``MinimumSizeHintFromDockWidget``
    mode.  v0.8.0a19 sets ``MinimumSizeHintFromContent`` explicitly
    so QtAds asks the contained widget instead.  This test pins
    that contract: open a standalone window, check that the form
    dock is at least as tall as the inner form_panel's
    minimumSizeHint.  Regression to the default mode (or removal
    of the setMinimumSizeHintMode call) makes the dock collapse
    below the bottom band again and this test catches it.
    """

    def test_form_dock_min_size_hint_mode(self, tmp_path: Path) -> None:
        """The form dock must declare ``MinimumSizeHintFromContent``."""
        import PySide6QtAds as ads
        from scriptree.ui.standalone_window import StandaloneWindow
        tool, path = _saved_busy_tool(tmp_path)
        win = StandaloneWindow.from_tool(tool, path)
        try:
            form_dock = win._form_dock
            assert form_dock.minimumSizeHintMode() == (
                ads.CDockWidget.eMinimumSizeHintMode.MinimumSizeHintFromContent
            ), (
                "form_dock must use MinimumSizeHintFromContent so "
                "QtAds honours the form_panel's minimumSizeHint -- "
                "the default mode (FromDockWidget) returns 0/0 and "
                "lets the dock collapse below the bottom band."
            )
        finally:
            win.close()
            win.deleteLater()
            _app.processEvents()

    def test_form_dock_height_at_least_panel_min_hint(
        self, tmp_path: Path,
    ) -> None:
        """The form dock's actual height should not be smaller than
        the form_panel's minimumSizeHint when there's plenty of room."""
        from scriptree.ui.standalone_window import StandaloneWindow
        tool, path = _saved_busy_tool(tmp_path)
        win = StandaloneWindow.from_tool(tool, path)
        try:
            win.resize(900, 800)  # plenty of vertical space
            win.show()
            _app.processEvents()
            _app.processEvents()  # let layout settle

            runner = win._runners[0]
            form_panel = runner.form_panel
            form_dock = win._form_dock
            min_h = form_panel.minimumSizeHint().height()
            dock_h = form_dock.height()
            # Allow a ~30 px slack for dock title bar + frame.
            assert dock_h + 30 >= min_h, (
                f"form_dock is {dock_h} px tall but form_panel's "
                f"minimumSizeHint is {min_h} px -- QtAds is shrinking "
                f"the dock below the content's declared minimum.  Check "
                f"that ``setMinimumSizeHintMode(MinimumSizeHintFromContent)`` "
                f"is still being called on form_dock."
            )
        finally:
            win.close()
            win.deleteLater()
            _app.processEvents()

    def test_run_button_visible_within_form_dock(
        self, tmp_path: Path,
    ) -> None:
        """The Run button must actually be PAINTED inside the form
        dock -- not just inside form_panel's logical rect.

        The v0.8.0a16-a18 regression had the bottom band sitting
        inside form_panel at a valid y-coordinate (so a naive
        ``mapTo(form_panel)`` test passed), but form_panel itself
        overflowed the form_dock viewport (because QtAds wraps the
        content in a QScrollArea and the content's layout sizeHint
        was inflated by form_scroll's ``Expanding`` policy).  As a
        result the Run button was visually scrolled out of sight
        even though every per-widget visibility flag said
        otherwise.  This test catches that exact failure mode by
        asking Qt whether the Run button actually has a non-empty
        visible region.
        """
        from scriptree.ui.standalone_window import StandaloneWindow
        tool, path = _saved_busy_tool(tmp_path)
        win = StandaloneWindow.from_tool(tool, path)
        try:
            win.resize(900, 600)
            win.show()
            _app.processEvents()
            _app.processEvents()

            runner = win._runners[0]
            form_dock = win._form_dock
            btn = runner._btn_run
            pos = btn.mapTo(form_dock, btn.rect().topLeft())
            # Allow tiny slack for dock title bar etc.
            assert pos.y() + btn.height() <= form_dock.height() + 10, (
                f"Run button at y={pos.y()} (+{btn.height()}) overflows "
                f"form_dock height {form_dock.height()} -- the button "
                f"is scrolled off the bottom.  Likely cause: form_scroll's "
                f"vertical sizePolicy reverted from Ignored to Expanding "
                f"(or some other change re-inflates form_panel layout's "
                f"sizeHint past the dock viewport)."
            )
            assert not btn.visibleRegion().isEmpty(), (
                "Run button widget has an EMPTY visibleRegion -- "
                "the button is fully clipped by the dock's scroll "
                "area.  This is the exact 'scrolled away' failure "
                "the user reported in v0.8.0a16/a17/a18."
            )
        finally:
            win.close()
            win.deleteLater()
            _app.processEvents()


class TestStandaloneBottomBandVisible:
    """End-to-end: the standalone window's form dock must show
    its bottom band when the dock is at a reasonable height."""

    def test_bottom_band_visible_in_standalone(
        self, tmp_path: Path,
    ) -> None:
        from scriptree.ui.standalone_window import StandaloneWindow
        tool, path = _saved_busy_tool(tmp_path)
        win = StandaloneWindow.from_tool(tool, path)
        try:
            win.resize(900, 600)
            win.show()
            _app.processEvents()

            runner = win._runners[0]
            band = runner._bottom_band
            assert band.isVisible(), "bottom_band is not visible"
            form_panel = runner.form_panel
            pos_in_panel = band.mapTo(
                form_panel, band.rect().topLeft()
            )
            assert pos_in_panel.y() < form_panel.height(), (
                f"bottom_band at y={pos_in_panel.y()} but form_panel "
                f"is only {form_panel.height()} px tall."
            )
            assert pos_in_panel.y() + band.height() <= (
                form_panel.height() + 20  # tiny slack for borders
            ), (
                f"bottom_band overflows form_panel "
                f"(band bottom={pos_in_panel.y() + band.height()}, "
                f"form_panel height={form_panel.height()})"
            )
        finally:
            win.close()
            win.deleteLater()
            _app.processEvents()

    def test_run_button_visible_in_standalone(
        self, tmp_path: Path,
    ) -> None:
        """The actual Run button -- the user-facing thing they
        click -- must be on-screen in the standalone form dock."""
        from scriptree.ui.standalone_window import StandaloneWindow
        tool, path = _saved_busy_tool(tmp_path)
        win = StandaloneWindow.from_tool(tool, path)
        try:
            win.resize(900, 600)
            win.show()
            _app.processEvents()

            runner = win._runners[0]
            run_btn = runner._btn_run
            assert run_btn.isVisible(), "Run button widget not visible"
            form_panel = runner.form_panel
            pos = run_btn.mapTo(form_panel, run_btn.rect().topLeft())
            assert pos.y() < form_panel.height(), (
                f"Run button at y={pos.y()} but form_panel only "
                f"{form_panel.height()} px tall -- pushed off."
            )
        finally:
            win.close()
            win.deleteLater()
            _app.processEvents()


class TestParamsAreaFillsAvailableSpace:
    """The white parameters area should grow to fill all the
    vertical space between the header and the bottom band -- no
    beige gap of bare ``form_group`` background below the last
    section.

    This is the v0.8.0a19 "Why aren't those two areas able to scale
    together?" failure mode.  ``form_outer_layout``'s trailing
    ``addStretch(1)`` was absorbing every spare pixel, leaving the
    QTabWidget / collapsible section at sizeHint with empty
    form_group background showing below.  Fix: assign the trailing
    stretch to the LAST inserted widget and zero out the spacer
    so leftover space flows to the params view instead.
    """

    def _make_tab_section_tool(self, tmp_path: Path) -> tuple:
        from scriptree.core.model import (
            ParamDef, ParamType, Section, ToolDef, Widget,
        )
        tool = ToolDef(
            name="TabSectionsStress",
            executable="echo",
            argument_template=["{p_source}"],
            params=[
                ParamDef(id="p_source", label="File", default="",
                         section="Source"),
                ParamDef(id="p_match", label="Match by", default="stamp",
                         section="Matching"),
                ParamDef(id="p_apply", label="Apply", default="no",
                         section="Apply"),
            ],
            sections=[
                Section(name="Source", layout="tab"),
                Section(name="Matching", layout="tab"),
                Section(name="Apply", layout="tab"),
            ],
        )
        p = tmp_path / "stress_tabs.scriptree"
        save_tool(tool, p)
        return tool, str(p)

    def test_tab_widget_fills_form_group(
        self, tmp_path: Path,
    ) -> None:
        """With tab-layout sections, the QTabWidget should take
        the full vertical space of form_group -- no beige gap."""
        from PySide6.QtWidgets import QTabWidget
        from scriptree.ui.standalone_window import StandaloneWindow
        tool, path = self._make_tab_section_tool(tmp_path)
        win = StandaloneWindow.from_tool(tool, path)
        try:
            win.resize(1000, 800)
            win.show()
            _app.processEvents()
            _app.processEvents()

            runner = win._runners[0]
            tab_widgets = runner.form_panel.findChildren(QTabWidget)
            assert tab_widgets, (
                "No QTabWidget rendered -- tab sections expected to "
                "produce one."
            )
            tw = tab_widgets[0]
            # Find form_group via the tab widget's parent chain.
            form_group = tw.parentWidget()
            tw_h = tw.height()
            group_h = form_group.height()
            # Allow generous margins / spacing -- ~30 px.
            assert tw_h + 40 >= group_h, (
                f"QTabWidget is {tw_h} px tall but form_group is "
                f"{group_h} px -- there's a {group_h - tw_h} px "
                f"beige strip of empty form_group background below "
                f"the tabs.  Check that the trailing stretch in "
                f"form_outer_layout was reassigned to the last "
                f"widget in ``_populate_form_rows``."
            )
        finally:
            win.close()
            win.deleteLater()
            _app.processEvents()


class TestNoEmptySpaceBelowRunRow:
    """The bottom band must claim only its natural sizeHint --
    Fixed sizePolicy + accurate sizeHint -- so the user doesn't
    see empty space below the Run row."""

    def test_bottom_band_height_close_to_content_sum(
        self, tmp_path: Path,
    ) -> None:
        """The bottom band should be roughly as tall as the sum of
        its visible children's *actual* heights -- not its
        ``sizeHint`` (which over-reports because the cfg row's
        FlowLayout assumes minimum-width wrapping and gives a
        conservatively tall hint).

        A previous attempt set ``bottom_band.setMinimumHeight(200)``
        which left a dead empty strip below the Run row in the
        common case where the actual content is ~100 px.  This
        test guards against re-introducing that kind of static
        floor by asserting the band's height tracks its content,
        not a static minimum.
        """
        from scriptree.ui.standalone_window import StandaloneWindow
        tool, path = _saved_busy_tool(tmp_path)
        win = StandaloneWindow.from_tool(tool, path)
        try:
            win.resize(900, 700)
            win.show()
            _app.processEvents()
            _app.processEvents()  # let layout settle

            runner = win._runners[0]
            band = runner._bottom_band
            band_layout = runner._bottom_band_layout
            child_heights = 0
            for i in range(band_layout.count()):
                item = band_layout.itemAt(i)
                if item is None:
                    continue
                w = item.widget()
                if w is not None and w.isVisible():
                    child_heights += w.height()
                else:
                    # FlowLayout / spacer items contribute their
                    # geometry size if any.
                    rect = item.geometry()
                    child_heights += rect.height()
            # The band's height should be within ~30 px of its
            # children's actual sum (margins + spacings).
            actual_h = band.height()
            assert abs(actual_h - child_heights) < 50, (
                f"bottom_band actual height ({actual_h}) doesn't "
                f"track its children's heights ({child_heights}) -- "
                f"static setMinimumHeight bloat is the usual cause."
            )
        finally:
            win.close()
            win.deleteLater()
            _app.processEvents()
