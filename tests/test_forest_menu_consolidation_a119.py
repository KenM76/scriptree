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

from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

_app = QApplication.instance() or QApplication([])

QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)

from scriptree.shell.branding_loader import load_branding  # noqa: E402
from scriptree.shell.cell_registry import CellRegistry  # noqa: E402
from scriptree.shell.forest_controller import ForestController  # noqa: E402
from scriptree.shell.forest_io import ForestDef  # noqa: E402


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


def _build_forest_menu():
    """Return ``(ctrl, menu)`` where ``menu`` has the DISSOLVED forest actions
    built directly into it.  The caller MUST keep ``menu`` alive while it walks
    the tree (its sub-menus are Qt children of ``menu``)."""
    _fresh_registry()
    ctrl = ForestController(load_branding(), CellRegistry.instance(), None)
    ctrl.start(forest=ForestDef(), suppress_first_run=True)
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
