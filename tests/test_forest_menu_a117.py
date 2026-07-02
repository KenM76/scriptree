"""v0.8.0a117 — the forest hub gets a deliberately MINIMAL right-click menu.

Contract (user, 2026-07-01: "clean up the right-click menus for the forest…
they should only show what is relevant"):

* The forest hub (``_is_forest_master``) must NEVER offer the standard
  cell/ring operations that could detach its members or make no sense for a
  workspace root:
    - "Close ring (undock all members)"   (caused the un-reassociable-cells bug)
    - "Close all related (master + members)"   (redundant with "Exit all")
    - "Disband group"                      (would tear members off the forest)
    - the "ScripTree" catalog submenu, the "Tree Ring" submenu, the "Cell"
      submenu ("Spawn another cell")
* Instead the forest offers exactly: its Forest submenu (added by the
  controller hook — not present in these unit-built hubs), an "Open…" that
  loads a Tree Ring / ScripTree / ScripTreeTree, a "New ▸ Cell", then
  About / Settings / Preferences and the single global "Exit all".
* Regression guard: a NON-forest master still shows "Close ring" + the
  "Tree Ring" submenu and does NOT show the forest-only "Open…"/"New".

The menu is captured by monkeypatching ``QMenu.exec`` to record the menu it
was called on and return ``None`` (so ``_show_context_menu`` builds the whole
menu then returns without acting), then walking the menu's actions.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QFileDialog

import scriptree.shell.cell_window as _cw

_app = QApplication.instance() or QApplication([])


class _NoExecMenu(QMenu):
    """A QMenu whose blocking ``exec`` is a no-op that records the menu.

    PySide6's ``QMenu.exec`` is a C++ slot that class-attribute
    monkeypatching does NOT override (a real menu then blocks the test
    forever).  Subclassing and overriding the virtual DOES work — PySide6
    dispatches to the Python override.  We patch the module-level ``QMenu``
    name in ``cell_window`` so every menu built inside ``_show_context_menu``
    is a ``_NoExecMenu``; its ``exec`` captures the top-level menu and
    returns ``None`` (== nothing chosen), so the builder runs in full and
    then returns without acting.
    """

    captured: list = []

    def exec(self, *a, **k):  # noqa: ANN001, ANN202  (shadow Qt's exec)
        _NoExecMenu.captured.append(self)
        return None

    exec_ = exec

# Auto-dismiss any incidental dialogs so a stray prompt never blocks.
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.question = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Yes
)

from scriptree.shell.branding_loader import load_branding  # noqa: E402
from scriptree.shell.cell_registry import CellRegistry  # noqa: E402
from scriptree.shell.cell_window import CellWindow  # noqa: E402


def _fresh_registry() -> CellRegistry:
    reg = CellRegistry.instance()
    try:
        for h in list(reg.standalones()) + list(reg.masters()):
            try:
                h.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    return reg


def _all_action_texts(menu: QMenu) -> list[str]:
    """Recursively collect the text of every action + submenu title."""
    out: list[str] = []
    for a in menu.actions():
        out.append(a.text())
        sub = a.menu()
        if sub is not None:
            out.extend(_all_action_texts(sub))
    return out


def _capture_menu(monkeypatch) -> list[QMenu]:
    """Make ``_show_context_menu`` build non-blocking menus and record them.

    Replaces the ``QMenu`` name in ``cell_window`` with :class:`_NoExecMenu`
    so every menu the builder creates is a subclass whose ``exec`` returns
    ``None`` (nothing chosen) after recording itself.
    """
    _NoExecMenu.captured = []
    monkeypatch.setattr(_cw, "QMenu", _NoExecMenu)
    return _NoExecMenu.captured


def _forest_hub() -> CellWindow:
    _fresh_registry()
    return CellWindow(load_branding(), role="master", is_forest_master=True)


# ---------------------------------------------------------------------------
# Forest hub — the stripped menu
# ---------------------------------------------------------------------------

def test_forest_menu_omits_ring_and_cell_destructive_actions(monkeypatch) -> None:
    forest = _forest_hub()
    captured = _capture_menu(monkeypatch)
    forest._show_context_menu(QPoint(0, 0))
    assert captured, "menu.exec was never called — capture failed"
    texts = _all_action_texts(captured[0])
    joined = " || ".join(texts)

    # The whole point: none of these appear on the forest.
    assert "Close ring" not in joined, texts
    assert "Close all related" not in joined, texts
    assert "Disband group" not in joined, texts
    assert "Spawn another cell" not in joined, texts
    # The catalog + ring submenus (exact submenu titles) are gone.
    assert "Tree Ring" not in texts, texts
    assert "ScripTree" not in texts, texts   # note: the disabled header
    #                                          "ScripTree: (default)" is a
    #                                          DIFFERENT string and may remain.


def test_forest_menu_has_open_new_cell_and_exit(monkeypatch) -> None:
    forest = _forest_hub()
    captured = _capture_menu(monkeypatch)
    forest._show_context_menu(QPoint(0, 0))
    texts = _all_action_texts(captured[0])

    assert "Open…" in texts, texts
    assert "New" in texts, texts          # the New submenu title
    assert "Cell" in texts, texts         # New ▸ Cell
    assert "Exit all" in texts, texts
    # v0.8.0a120 — "Settings…" and "Preferences…" are NO LONGER cell-native
    # items on the a117 branch: they moved into the controller hook's Settings
    # sub-menu as "More…" / "Preferences…".  A raw forest cell built without a
    # ForestController has no hook, so they are absent here (the grouped
    # versions are covered in test_forest_menu_consolidation_a119.py).
    assert "Settings…" not in texts, texts


# ---------------------------------------------------------------------------
# Non-forest master — regression: the cell path is untouched
# ---------------------------------------------------------------------------

def test_nonforest_master_still_has_ring_actions(monkeypatch) -> None:
    _fresh_registry()
    master = CellWindow(load_branding(), role="master")
    captured = _capture_menu(monkeypatch)
    master._show_context_menu(QPoint(0, 0))
    texts = _all_action_texts(captured[0])
    joined = " || ".join(texts)

    assert "Tree Ring" in texts, texts               # ring submenu intact
    assert "Close ring" in joined, texts             # close-ring intact
    # Forest-only additions must NOT leak onto a normal master.
    assert "Open…" not in texts, texts
    assert "New" not in texts, texts


# ---------------------------------------------------------------------------
# The new handlers
# ---------------------------------------------------------------------------

def test_new_blank_cell_spawns_unbound_standalone() -> None:
    reg = _fresh_registry()
    forest = CellWindow(load_branding(), role="master", is_forest_master=True)
    before = {id(c) for c in reg.standalones()}
    forest._new_blank_cell()
    fresh = [c for c in reg.standalones() if id(c) not in before]
    assert len(fresh) == 1, "New ▸ Cell should spawn exactly one standalone cell"
    assert fresh[0]._catalog_path is None, "New ▸ Cell must be unbound (blank)"


def test_forest_open_routes_through_open_catalog_path_without_rebinding(
    monkeypatch, tmp_path
) -> None:
    forest = _forest_hub()
    forest._catalog_path = None

    f = tmp_path / "tool.scriptree"
    f.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: (str(f), "")),
    )
    routed: list[str] = []
    monkeypatch.setattr(forest, "_open_catalog_path", lambda p: routed.append(p))

    forest._open_forest_file_dialog()

    assert routed == [str(f)], "Open… must dispatch the chosen path"
    # The hub is a master -> _can_bind_self False -> Open can never rebind it.
    assert forest._can_bind_self() is False
    assert forest._catalog_path is None, "the forest hub must not be rebound"


# ---------------------------------------------------------------------------
# a117 cell half — plain member cells omit the ScripTree / Tree Ring submenus
# ---------------------------------------------------------------------------

def test_plain_member_cell_omits_catalog_and_ring_submenus(monkeypatch) -> None:
    _fresh_registry()
    cell = CellWindow(load_branding())
    cell._group_master_id = "fake-master-id"   # docked under a master
    assert cell.role != "master"

    captured = _capture_menu(monkeypatch)
    cell._show_context_menu(QPoint(0, 0))
    texts = _all_action_texts(captured[0])

    # The two submenus (exact titles) are gone for a plain member.
    assert "ScripTree" not in texts, texts   # the "ScripTree: …" header is a
    #                                          different string and may remain.
    assert "Tree Ring" not in texts, texts
    # …but the member keeps its own cell actions + a way to close.
    assert "Cell" in texts, texts            # the Cell submenu
    assert "Close this cell" in texts, texts
    assert "Exit all" in texts, texts


def test_standalone_cell_keeps_catalog_and_ring_submenus(monkeypatch) -> None:
    _fresh_registry()
    cell = CellWindow(load_branding())
    assert cell._group_master_id is None      # standalone, not grouped

    captured = _capture_menu(monkeypatch)
    cell._show_context_menu(QPoint(0, 0))
    texts = _all_action_texts(captured[0])

    assert "ScripTree" in texts, texts        # catalog submenu still offered
    assert "Tree Ring" in texts, texts        # ring submenu still offered
