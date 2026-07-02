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

# (a121: the module-level QMessageBox patches were removed — tests/conftest.py's
# session-wide ``_silence_qt_modals`` already stubs every blocking modal, and a
# per-module raw assignment could fight it across test modules.)

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
    assert "ScripTree" not in texts, texts
    # a121 — the disabled "ScripTree: (default)" catalog header is also
    # SKIPPED for the hub (it can never bind a catalog).
    assert not any(t.startswith("ScripTree:") for t in texts), texts


def test_forest_menu_has_open_new_cell_and_exit(monkeypatch) -> None:
    forest = _forest_hub()
    captured = _capture_menu(monkeypatch)
    forest._show_context_menu(QPoint(0, 0))
    texts = _all_action_texts(captured[0])

    assert "Open…" in texts, texts
    assert "New" in texts, texts          # the New submenu title
    assert "Cell" in texts, texts         # New ▸ Cell
    assert "Exit all" in texts, texts
    # a121 ORDER: the everyday actions lead the hub menu (no catalog
    # header above them), Exit all closes it.
    non_sep = [t for t in (a.text() for a in captured[0].actions()) if t]
    assert non_sep[0] == "Open…", non_sep
    assert non_sep[-1] == "Exit all", non_sep


def test_forest_menu_fallback_when_hook_missing_or_raises(monkeypatch) -> None:
    """a121 — the hub must stay recoverable without a working controller
    hook.  A raw hub (no hook at all) and a hub whose hook RAISES both get
    the cell-native fallback Settings… / Preferences… / About items; and a
    TypeError from inside the builder must NOT re-invoke it (the old a25
    arity-sniff double-built the whole menu)."""
    # (1) no hook installed -> fallback present.
    forest = _forest_hub()
    captured = _capture_menu(monkeypatch)
    forest._show_context_menu(QPoint(0, 0))
    texts = _all_action_texts(captured[0])
    assert "Settings…" in texts, texts
    assert "Preferences…" in texts, texts
    assert any(t.startswith("About") for t in texts), texts

    # (2) hook adds one item then raises TypeError -> the item appears
    # EXACTLY once (no re-invoke) and the fallback still appears.
    forest2 = _forest_hub()

    def _bad_hook(menu, cell=None):  # noqa: ANN001
        menu.addAction("HOOK-MARKER")
        raise TypeError("bug inside the builder")

    forest2._forest_menu_extension = _bad_hook
    _NoExecMenu.captured = []
    forest2._show_context_menu(QPoint(0, 0))
    texts2 = _all_action_texts(_NoExecMenu.captured[0])
    assert texts2.count("HOOK-MARKER") == 1, texts2
    assert "Settings…" in texts2, texts2


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
    # a121 — the gate now RESOLVES the master id in the registry, so the
    # test needs a real, live master for the cell to be "docked" under.
    master = CellWindow(load_branding(), role="master")
    cell = CellWindow(load_branding())
    cell._group_master_id = master._id        # docked under a LIVE master
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


def test_orphan_cell_with_stale_master_id_keeps_submenus(monkeypatch) -> None:
    """a121 (review fix) — a cell whose ``_group_master_id`` does NOT
    resolve to a live cell in the registry is effectively standalone (its
    master died through an exceptional teardown, or a sidecar restored a
    member whose master never respawned).  It must KEEP the catalog/ring
    submenus, or the user has no way to rebind or save it."""
    _fresh_registry()
    cell = CellWindow(load_branding())
    cell._group_master_id = "ghost-master-never-registered"

    captured = _capture_menu(monkeypatch)
    cell._show_context_menu(QPoint(0, 0))
    texts = _all_action_texts(captured[0])

    assert "ScripTree" in texts, texts
    assert "Tree Ring" in texts, texts


def test_standalone_cell_keeps_catalog_and_ring_submenus(monkeypatch) -> None:
    _fresh_registry()
    cell = CellWindow(load_branding())
    assert cell._group_master_id is None      # standalone, not grouped

    captured = _capture_menu(monkeypatch)
    cell._show_context_menu(QPoint(0, 0))
    texts = _all_action_texts(captured[0])

    assert "ScripTree" in texts, texts        # catalog submenu still offered
    assert "Tree Ring" in texts, texts        # ring submenu still offered


def test_spawn_clamps_to_the_spawning_cells_screen(monkeypatch) -> None:
    """a121 (review fix) — ``_spawn_cell_with_catalog`` must clamp the new
    cell to the screen the SPAWNING cell is on (``screenAt(self.pos())``),
    not unconditionally to the primary screen, or New ▸ Cell on a secondary
    monitor materialises the cell on the primary one.

    The adversarial verify caught the first version of this test as
    VACUOUS: the spawned cell's ``_settle_no_overlap`` ALSO calls
    ``screenAt``, so merely asserting "screenAt was consulted" passed even
    with the primaryScreen() regression restored.  Hence: the settle step
    is stubbed out, and the assertion pins the one call the clamp itself
    makes — ``screenAt`` with EXACTLY the spawning cell's position."""
    _fresh_registry()
    forest = CellWindow(load_branding(), role="master", is_forest_master=True)

    asked: list = []
    real_screen_at = QApplication.screenAt

    def _recording_screen_at(pos):  # noqa: ANN001
        asked.append(pos)
        return real_screen_at(pos)

    monkeypatch.setattr(
        QApplication, "screenAt", staticmethod(_recording_screen_at),
    )
    # Silence the other screenAt caller inside the spawn path.
    monkeypatch.setattr(CellWindow, "_settle_no_overlap", lambda self: None)

    forest._new_blank_cell()
    assert any(p == forest.pos() for p in asked), (
        "the spawn clamp must call screenAt(self.pos()) — got "
        f"{[(p.x(), p.y()) for p in asked]!r}, expected to include "
        f"({forest.pos().x()}, {forest.pos().y()})"
    )
