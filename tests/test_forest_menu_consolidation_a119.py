"""v0.8.0a119 + a120 — forest right-click menu consolidation.

a119 grouped the forest actions under File / Auto / Settings sub-menus nested
inside a "Forest" container.  a120 then, per Ken:

* renamed **Auto → Sources**;
* **dissolved the "Forest" container** — File / Sources / Settings / Recent
  layouts / Bring-cells-back / About… are now built DIRECTLY into the
  right-click ``menu``;
* moved **Recent layouts OUT of File** to the top level;
* moved the cell's **Settings… → "More…"** and grouped it with **Preferences…**
  under the Settings sub-menu;
* folded About into a single top-level **About…** (a two-tab dialog).

``_populate_forest_menu`` only *builds* into the passed menu (it no longer
``insertMenu``s a container, and never ``exec``s), so we call it directly on a
started controller and walk the menu.  Keep the ``menu`` alive while inspecting
its child sub-menus (Qt GCs children with the parent).
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QMenu

_app = QApplication.instance() or QApplication([])

# (a121: the module-level QMessageBox.warning patch was removed —
# tests/conftest.py's session-wide ``_silence_qt_modals`` already stubs
# every blocking modal.)

from scriptree.shell.branding_loader import load_branding  # noqa: E402
from scriptree.shell.cell_registry import CellRegistry  # noqa: E402
from scriptree.shell.forest_controller import ForestController  # noqa: E402
from scriptree.shell.forest_io import ForestDef  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_from_user_appdata(tmp_path, monkeypatch):  # noqa: ANN001, ANN201
    """a121 (review fix) — every test in this module starts a REAL
    ForestController, and ``start()`` reads forest preferences + the
    autoload path.  Without redirection those come from the developer's
    live ``%APPDATA%/ScripTree`` (visibility flags from live testing can
    spawn a real tray icon / fold cells mid-suite, and autosave could
    write the dev's actual ``default.scriptreeforest``).  Same isolation
    ``test_forest.py`` applies via its class fixtures."""
    from scriptree.shell import forest_controller as fc_mod
    from scriptree.shell import forest_io as io_mod

    monkeypatch.setattr(
        io_mod, "default_preferences_path",
        lambda branding: tmp_path / "forest_preferences.json",
    )
    monkeypatch.setattr(
        fc_mod, "default_autoload_path",
        lambda branding: tmp_path / "default.scriptreeforest",
    )
    monkeypatch.setattr(
        io_mod, "default_autoload_path",
        lambda branding: tmp_path / "default.scriptreeforest",
    )


def _fresh_registry() -> None:
    reg = CellRegistry.instance()
    try:
        for h in list(reg.standalones()) + list(reg.masters()):
            try:
                h.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass


def _find_submenu(menu: QMenu, title: str) -> QMenu | None:
    for a in menu.actions():
        sub = a.menu()
        if sub is not None and a.text() == title:
            return sub
    return None


def _direct_texts(menu: QMenu) -> list[str]:
    return [a.text() for a in menu.actions()]


def _make_controller() -> ForestController:
    """Fresh, started controller with autosave OFF (a121: so tests never
    write the redirected — let alone a real — autoload forest file)."""
    _fresh_registry()
    ctrl = ForestController(load_branding(), CellRegistry.instance(), None)
    ctrl.set_autosave_enabled(False)
    ctrl.start(forest=ForestDef(), suppress_first_run=True)
    return ctrl


def _build_forest_menu():
    """Return ``(ctrl, menu)`` where ``menu`` has the DISSOLVED forest actions
    built directly into it.  The caller MUST keep ``menu`` alive while it walks
    the tree (its sub-menus are Qt children of ``menu``)."""
    ctrl = _make_controller()
    menu = QMenu()
    ctrl._populate_forest_menu(menu, ctrl.forest_window)
    return ctrl, menu


# ---------------------------------------------------------------------------
# a120 — dissolved top level
# ---------------------------------------------------------------------------

def test_no_forest_container_items_are_top_level() -> None:
    ctrl, menu = _build_forest_menu()
    try:
        titles = _direct_texts(menu)
        # The wrapping "Forest" sub-menu is gone; its children are top-level.
        assert "Forest" not in titles, titles
        assert "File" in titles
        assert "Sources" in titles          # a120: renamed from "Auto"
        assert "Auto" not in titles         # old name gone
        assert "Settings" in titles
        assert "Recent layouts" in titles   # a120: moved OUT of File
        assert "Bring all cells back on-screen" in titles
        assert "About…" in titles           # a120: two-tab About
    finally:
        ctrl.forest_window.close()


def test_file_submenu_has_forest_layout_portable_but_NOT_recent() -> None:
    ctrl, menu = _build_forest_menu()
    try:
        file_m = _find_submenu(menu, "File")
        assert file_m is not None
        t = _direct_texts(file_m)
        for label in (
            "Save forest", "Save forest as…", "Open forest…",
            "Save layout", "Save layout as…", "Open layout…",
            "Make a portable copy (incl. local tools)…",
        ):
            assert label in t, (label, t)
        assert any("Convert this install" in x for x in t), t
        # a120 — Recent layouts is NO LONGER inside File.
        assert _find_submenu(file_m, "Recent layouts") is None
        assert "Recent layouts" not in t
    finally:
        ctrl.forest_window.close()


def test_recent_layouts_is_top_level() -> None:
    ctrl, menu = _build_forest_menu()
    try:
        assert _find_submenu(menu, "Recent layouts") is not None
    finally:
        ctrl.forest_window.close()


def test_sources_submenu_groups_discovery_and_renames_settings() -> None:
    ctrl, menu = _build_forest_menu()
    try:
        src_m = _find_submenu(menu, "Sources")
        assert src_m is not None
        t = _direct_texts(src_m)
        assert "Refresh from sources" in t
        assert "Auto-add from ScripTreeApps now" in t
        assert any("Re-organise" in x for x in t), t
        assert "App Discovery…" in t
        assert "Manage excluded items…" in t
        assert "Forest settings…" not in t
    finally:
        ctrl.forest_window.close()


def test_settings_submenu_nests_visibility_autostart_debug_more_prefs() -> None:
    ctrl, menu = _build_forest_menu()
    try:
        settings_m = _find_submenu(menu, "Settings")
        assert settings_m is not None
        assert _find_submenu(settings_m, "Visibility") is not None
        assert _find_submenu(settings_m, "Auto-load on startup") is not None
        assert _find_submenu(settings_m, "Debug") is not None
        # a120 — More… (renamed Settings…) + Preferences… grouped here.
        t = _direct_texts(settings_m)
        assert "More…" in t, t
        assert "Preferences…" in t, t
    finally:
        ctrl.forest_window.close()


def test_about_dialog_has_two_tabs() -> None:
    from PySide6.QtWidgets import QTabWidget
    _fresh_registry()
    ctrl = ForestController(load_branding(), CellRegistry.instance(), None)
    ctrl.set_autosave_enabled(False)
    ctrl.start(forest=ForestDef(), suppress_first_run=True)
    try:
        dlg = ctrl._build_about_dialog()
        tabs = dlg.findChild(QTabWidget)
        assert tabs is not None
        assert tabs.count() == 2, tabs.count()
        labels = [tabs.tabText(i) for i in range(2)]
        assert any("About" in x for x in labels), labels        # About <brand>
        assert any("forest" in x.lower() for x in labels), labels  # This forest
        dlg.deleteLater()
    finally:
        ctrl.forest_window.close()


def test_forest_settings_dialog_omits_click_action_tab() -> None:
    """a120 — the forest hub's SettingsDialog drops the 'Click action' tab; a
    normal standalone cell keeps it."""
    from PySide6.QtWidgets import QTabWidget
    from scriptree.shell.cell_window import CellWindow, SettingsDialog

    _fresh_registry()
    forest = CellWindow(load_branding(), role="master", is_forest_master=True)
    dlg_f = SettingsDialog(forest)
    tabs_f = dlg_f.findChild(QTabWidget)
    labels_f = [tabs_f.tabText(i) for i in range(tabs_f.count())]
    assert "Click action" not in labels_f, labels_f
    dlg_f.deleteLater()
    forest.close()

    cell = CellWindow(load_branding())
    dlg_c = SettingsDialog(cell)
    tabs_c = dlg_c.findChild(QTabWidget)
    labels_c = [tabs_c.tabText(i) for i in range(tabs_c.count())]
    assert "Click action" in labels_c, labels_c
    dlg_c.deleteLater()
    cell.close()


def test_save_layout_quicksave_vs_saveas(monkeypatch, tmp_path) -> None:
    _fresh_registry()
    ctrl = ForestController(load_branding(), CellRegistry.instance(), None)
    ctrl.set_autosave_enabled(False)
    ctrl.start(forest=ForestDef(), suppress_first_run=True)
    try:
        calls: list[str] = []
        monkeypatch.setattr(ctrl, "_on_save_layout_as", lambda: calls.append("as"))
        ctrl._on_save_layout()
        assert calls == ["as"]

        p = tmp_path / "l.scriptreelayout"
        ctrl._saved_layout_path = p
        wrote: list = []
        monkeypatch.setattr(ctrl, "_write_layout_to_path", lambda path: wrote.append(path))
        ctrl._on_save_layout()
        assert wrote == [p]
    finally:
        ctrl.forest_window.close()


# ---------------------------------------------------------------------------
# a121 — review fixes: layout data-loss guards, About dedup, dialog title
# ---------------------------------------------------------------------------

def test_write_layout_refuses_while_collapsed(monkeypatch, tmp_path) -> None:
    """a121 — while the forest is collapsed every member sits at the hub, so
    a capture would record ~(0,0) offsets; the quick-save one-click path made
    that a single-click data-loss.  The writer must refuse + warn."""
    from PySide6.QtWidgets import QMessageBox

    ctrl = _make_controller()
    try:
        warned: list[str] = []
        monkeypatch.setattr(
            QMessageBox, "warning",
            staticmethod(lambda parent, title, text, *a, **k:
                         warned.append(text) or QMessageBox.StandardButton.Ok),
        )
        ctrl.forest_window._collapse_state = "collapsed"
        target = tmp_path / "l.scriptreelayout"
        ctrl._write_layout_to_path(target)
        assert not target.exists(), "no file may be written while collapsed"
        assert warned and "collapsed" in warned[0], warned
        assert getattr(ctrl, "_saved_layout_path", None) is None
    finally:
        ctrl.forest_window.close()


def test_write_layout_warns_when_nothing_positionable(monkeypatch, tmp_path) -> None:
    """a121 — 'Save layout as…' with nothing positionable used to bail with a
    log line only, right after the user picked a filename.  Now it warns."""
    from PySide6.QtWidgets import QMessageBox

    ctrl = _make_controller()      # empty forest -> zero positionable cells
    try:
        warned: list[str] = []
        monkeypatch.setattr(
            QMessageBox, "warning",
            staticmethod(lambda parent, title, text, *a, **k:
                         warned.append(text) or QMessageBox.StandardButton.Ok),
        )
        target = tmp_path / "l.scriptreelayout"
        ctrl._write_layout_to_path(target)
        assert not target.exists()
        assert warned and "Nothing to save" in warned[0], warned
        assert getattr(ctrl, "_saved_layout_path", None) is None
    finally:
        ctrl.forest_window.close()


def test_zero_match_open_does_not_arm_quicksave(tmp_path) -> None:
    """a121 — opening a layout that matches NO current cell is a visible
    no-op; it must NOT become the quick-save target (a later one-click
    'Save layout' would silently overwrite that unrelated file)."""
    from scriptree.shell.layout_io import LayoutDef, LayoutEntry, save_layout

    ctrl = _make_controller()      # empty forest -> nothing can match
    try:
        p = tmp_path / "foreign.scriptreelayout"
        # NOTE: a LOCAL non-existent path — a fake drive letter (Z:/…) can
        # be a real blocked network share on a dev machine and make
        # Path.resolve() raise OSError inside _norm.
        save_layout(LayoutDef(name="foreign", entries=[
            LayoutEntry(catalog_path=str(tmp_path / "ghost" / "x.scriptree"),
                        rel_offset=(40, 40), kind="tool"),
        ]), p)
        ctrl._apply_layout_from_path(str(p))
        assert getattr(ctrl, "_saved_layout_path", None) is None, (
            "a zero-match apply must not arm the quick-save target"
        )
    finally:
        ctrl.forest_window.close()


def test_open_forest_clears_quicksave_target(tmp_path) -> None:
    """a121 — switching forests must forget the previous forest's layout
    file, or 'Save layout' in forest B clobbers forest A's layout."""
    from scriptree.shell.forest_io import save_forest

    ctrl = _make_controller()
    try:
        ctrl._saved_layout_path = tmp_path / "a.scriptreelayout"
        f = tmp_path / "other.scriptreeforest"
        save_forest(ForestDef(name="Other"), f)
        ctrl.open(str(f))
        assert getattr(ctrl, "_saved_layout_path", None) is None
    finally:
        ctrl.forest_window.close()


def test_app_discovery_dialog_title_matches_menu() -> None:
    """a121 — the menu says 'App Discovery…'; the dialog it opens must not
    still be titled 'Forest settings' (a119 renamed the menu entry only)."""
    from scriptree.shell.forest_dialogs import ForestSettingsDialog

    ctrl = _make_controller()
    try:
        dlg = ForestSettingsDialog(ctrl)
        assert dlg.windowTitle() == "App Discovery", dlg.windowTitle()
        dlg.deleteLater()
    finally:
        ctrl.forest_window.close()


def test_about_tab_one_uses_shared_html() -> None:
    """a121 — tab 1 of the two-tab About must render EXACTLY the shared
    ``branding_loader.about_app_html`` string (the same one the cell menu's
    About box shows), so the two surfaces cannot drift."""
    from PySide6.QtWidgets import QLabel, QTabWidget
    from scriptree.shell.branding_loader import about_app_html

    ctrl = _make_controller()
    try:
        dlg = ctrl._build_about_dialog()
        tabs = dlg.findChild(QTabWidget)
        first_label = tabs.widget(0).findChild(QLabel)
        assert first_label.text() == about_app_html(ctrl._branding)
        dlg.deleteLater()
    finally:
        ctrl.forest_window.close()


def test_uninstall_action_appears_for_installed_cell(monkeypatch, tmp_path) -> None:
    """a121 — the per-cell Uninstall block read the never-existing
    ``catalog_path`` attribute (CellWindow stores ``_catalog_path``), so it
    could NEVER fire.  With a cell whose catalog lives under an install
    root, the action must now appear."""
    from scriptree.core import app_install

    monkeypatch.setattr(app_install, "default_personal_root",
                        lambda: str(tmp_path))
    monkeypatch.setattr(app_install, "default_shared_root",
                        lambda: str(tmp_path / "shared"))

    ctrl = _make_controller()
    try:
        import types
        fake = types.SimpleNamespace(
            _catalog_path=str(tmp_path / "someapp" / "tool.scriptree"),
        )
        menu = QMenu()
        ctrl._populate_forest_menu(menu, fake)
        texts = [a.text() for a in menu.actions() if a.text()]
        assert "Uninstall app from disk..." in texts, texts
    finally:
        ctrl.forest_window.close()
