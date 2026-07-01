"""
forest_visibility.py — three-mode visibility for the forest hub.

## For humans

The forest hub historically had ONE way to reach it: it floated above
the desktop as a frameless, always-on-top hex (``Qt.Tool`` +
``Qt.WindowStaysOnTopHint``).  v0.8.0a52 added two more surfaces
(taskbar + system tray); v0.8.0a54 rewrote the taskbar plumbing to
fix a Qt-on-Windows transient-parent quirk (see below).

The three modes the user can pick:

  1. **Always-on-top over the desktop** (factory default).  The hub
     floats above every other app, ``Qt.Tool`` + AOT.
  2. **Show on taskbar** (PortableApps-style).  The hub itself
     carries ``Qt.Window`` so Windows gives it a taskbar entry.
     "Hidden" becomes ``showMinimized`` -- the taskbar button
     stays, the hex is off-screen.
  3. **Show in system tray** (PortableApps-style).  Left-click ->
     show, right-click -> Show / Quit menu.

At least one MUST be enabled.  When ``show_always_on_top`` is OFF
the hub starts MINIMISED (taskbar mode) or HIDDEN (tray-only).
Clicking the taskbar / tray reveals the hub plus every cell that
belongs to it; auto-hide fires when focus moves outside the forest
hierarchy.

## a54 architecture: no more proxy host

Pre-a54 the taskbar entry came from a separate ``ForestTaskbarHost``
``QMainWindow`` proxy: minimised-off-screen, its ``changeEvent``
caught taskbar-restore clicks and called ``show_hub`` then
re-minimised itself.

That hit a Qt-on-Windows quirk: ``Qt.Tool`` windows shown right after
another window was active become *transient children* of that other
window in Windows' internal Z-order book-keeping.  When the proxy
host then bounced back to minimised, Windows pulled the freshly-shown
forest hub (a Tool) DOWN with it.  Result: forest pops up briefly,
then disappears; cells (which weren't transient children) stay behind.

a54 fix: ditch the proxy.  When ``show_on_taskbar`` is on, swap
the forest hub's flag from ``Qt.Tool`` to ``Qt.Window`` so the
hub IS the taskbar entry.  Click the taskbar -> Windows restores
the hub directly, no proxy, no transient parent, no race.
"Hidden" in that mode is ``showMinimized`` -- the hub minimises
to the taskbar without leaving the desktop.

## For maintainers / LLMs

- ``ForestVisibilityManager.apply(prefs)`` is the single entry
  point for the controller.  It re-derives everything:
    1. ``_apply_taskbar_flag`` on the hub (``Qt.Tool`` <->
       ``Qt.Window``) per ``show_on_taskbar``.
    2. ``_apply_always_on_top_flag`` on the hub per
       ``show_always_on_top``.
    3. Spawn / tear down ``ForestTrayIcon`` per
       ``show_in_system_tray``.
    4. Watcher enabled / disabled per ``auto_hide``.
    5. Apply the initial hidden state if ``auto_hide`` is on
       (called when the hub is currently visible: minimise or
       hide and hide descendants).
- ``hide_hub`` minimises the hub when it carries ``Qt.Window``
  (taskbar mode); otherwise it calls ``hide()``.  Either way, it
  also hides every currently-visible cell that belongs to the
  forest hierarchy and remembers which it hid so ``show_hub``
  restores only those (user-collapsed cells stay collapsed).
- ``show_hub`` calls ``showNormal()`` so a minimised hub
  un-minimises and a hidden hub appears at its last position.
  Then raise + activate, then restore tracked descendants.
- An event filter on the hub catches its ``WindowStateChange``
  transition out of "minimised".  This is how we detect the
  user clicked the taskbar entry: we make the descendants
  reappear automatically.  The filter only acts when
  ``auto_hide`` is enabled, otherwise normal user-driven
  minimise / restore is left alone.
- ``ForestTaskbarHost`` survives as a deprecated class so any
  external code that imported it still resolves, but the manager
  no longer instantiates it.

Public API
----------
    ForestVisibilityManager(forest_window, registry, quit_callback=None)
        .apply(prefs: ForestPreferences) -> None
        .show_hub() -> None
        .hide_hub() -> None
        .teardown() -> None
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Callable

from PySide6.QtCore import (
    QEvent, QObject, QPoint, QTimer, Qt,
)
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QMenu, QSystemTrayIcon, QWidget,
)


def _log(msg: str) -> None:
    print(f"[forest_visibility] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _forest_icon() -> QIcon:
    """Resolve the forest glyph for the tray icon (and any other
    surface that wants the bundled fractal-tree icon).

    Prefers the bundled ``forest`` icon (a54+ uses this same icon
    for the hub's own ``setWindowIcon`` so the taskbar entry shows
    the right glyph).  Falls back to a 1x1 transparent pixmap if
    the asset isn't on disk (a Qt-on-Windows quirk: passing
    ``QIcon()`` to ``QSystemTrayIcon`` can cause it to silently
    refuse to render).
    """
    try:
        from scriptree.shell.icon_assets import bundled_icon_png_path
        p = bundled_icon_png_path("forest")
        if p is not None:
            ic = QIcon(str(p))
            if not ic.isNull():
                return ic
    except Exception as exc:  # noqa: BLE001
        _log(f"_forest_icon: bundled lookup failed: {exc!r}")
    pm = QPixmap(16, 16)
    pm.fill(Qt.transparent)
    return QIcon(pm)


# ---------------------------------------------------------------------------
# ForestTaskbarHost (DEPRECATED in a54)
# ---------------------------------------------------------------------------

class ForestTaskbarHost(QMainWindow):
    """[DEPRECATED in a54] Proxy taskbar entry for the forest hub.

    Pre-a54 the manager spawned this as a minimised ``QMainWindow``
    so Windows had something to show on the taskbar; its
    ``changeEvent`` intercepted taskbar restore clicks and called
    ``show_hub`` while immediately re-minimising itself.

    The proxy turned out to be the source of the "forest pops up
    briefly then hides" bug -- the hub was ``Qt.Tool`` and Windows
    made it a transient child of whichever window was most recently
    active.  When the proxy bounced back to minimised, the hub
    (transient child) got dragged down too.

    a54 ditches the proxy entirely.  ``ForestVisibilityManager``
    no longer instantiates this class.  It is kept here only so
    external code that imported the symbol still resolves; new
    callers should not use it.
    """

    def __init__(
        self,
        on_activate: Callable[[], None],
        on_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(None, Qt.Window | Qt.MSWindowsFixedSizeDialogHint)
        self._on_activate = on_activate
        self._on_close = on_close
        self.setWindowTitle("ScripTree Forest")
        self.setWindowIcon(_forest_icon())
        self.resize(1, 1)
        self.move(-32000, -32000)
        central = QWidget(self)
        central.setFixedSize(1, 1)
        self.setCentralWidget(central)


# ---------------------------------------------------------------------------
# ForestTrayIcon
# ---------------------------------------------------------------------------

class ForestTrayIcon(QSystemTrayIcon):
    """System tray icon with Show / Quit menu.

    Left-click (Trigger) and double-click both call ``on_activate``.
    Right-click pops the standard QSystemTrayIcon context menu.
    """

    def __init__(
        self,
        on_activate: Callable[[], None],
        on_quit: Callable[[], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(_forest_icon(), parent)
        self._on_activate = on_activate
        self._on_quit = on_quit
        self.setToolTip("ScripTree Forest")
        self._menu = QMenu()
        a_show = QAction("Show forest", self._menu)
        a_show.triggered.connect(self._on_show_clicked)
        self._menu.addAction(a_show)
        if on_quit is not None:
            self._menu.addSeparator()
            a_quit = QAction("Quit", self._menu)
            a_quit.triggered.connect(self._on_quit_clicked)
            self._menu.addAction(a_quit)
        # v0.8.0a57: same Debug submenu as the Forest right-click
        # so the user can flip verbose logging on / open the log
        # folder without having to first reach the (potentially
        # hidden) forest hub.
        try:
            from scriptree.shell import debug_logging as _dbg
            self._menu.addSeparator()
            debug_sub = self._menu.addMenu("Debug")
            self._tray_verbose_action = debug_sub.addAction(
                "Enable verbose logging"
            )
            self._tray_verbose_action.setCheckable(True)
            self._tray_verbose_action.setChecked(_dbg.is_enabled())
            self._tray_verbose_action.toggled.connect(
                self._on_tray_verbose_toggled
            )
            tray_open_log = debug_sub.addAction("Open debug folder")
            tray_open_log.triggered.connect(_dbg.open_log_folder)
        except Exception as exc:  # noqa: BLE001
            _log(f"ForestTrayIcon: debug submenu wiring failed: {exc!r}")

        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)

    def _on_tray_verbose_toggled(self, checked: bool) -> None:
        try:
            from scriptree.shell import debug_logging as _dbg
            actual = _dbg.set_enabled_and_persist(checked)
            if actual != checked:
                self._tray_verbose_action.blockSignals(True)
                self._tray_verbose_action.setChecked(actual)
                self._tray_verbose_action.blockSignals(False)
        except Exception as exc:  # noqa: BLE001
            _log(f"_on_tray_verbose_toggled: {exc!r}")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._on_show_clicked()

    def _on_show_clicked(self) -> None:
        try:
            self._on_activate()
        except Exception as exc:  # noqa: BLE001
            _log(f"tray icon: on_activate raised {exc!r}")

    def _on_quit_clicked(self) -> None:
        if self._on_quit is None:
            return
        try:
            self._on_quit()
        except Exception as exc:  # noqa: BLE001
            _log(f"tray icon: on_quit raised {exc!r}")


# ---------------------------------------------------------------------------
# _FocusWatcher
# ---------------------------------------------------------------------------

class _FocusWatcher(QObject):
    """Hide the forest hub when focus moves outside the forest hierarchy.

    Active only when ``auto_hide`` is True (i.e. always-on-top is
    OFF and at least one of taskbar / tray is ON).  Wraps
    ``QApplication.focusWindowChanged`` and debounces by 80ms so
    transient focus flickers (popups, modal dialogs) don't trigger
    a spurious hide.

    a54: the taskbar proxy is gone, so the post-show suppression
    window has been simplified -- the hub itself is now the
    taskbar entry, so a click on the entry activates the hub
    directly and the watcher sees ``activeWindow == forest_window``
    on the very next event.  No race to suppress.  We still expose
    ``suppress_for`` because the tray path (and any external
    programmatic show) benefits from a short suppression to ride
    out the platform's focus shuffle.

    v0.8.0a107: the a55 virtual-desktop "follow the user across
    desktops" path was removed (see
    ``docs/archive/removed_virtual_desktop_a107/``); this watcher is
    now hide-only.
    """

    def __init__(
        self,
        forest_window: Any,
        registry: Any,
        on_focus_left: Callable[[], None],
    ) -> None:
        super().__init__()
        self._forest_window = forest_window
        self._registry = registry
        self._on_focus_left = on_focus_left
        self._enabled = False
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(80)
        self._debounce.timeout.connect(self._fire)
        self._suppress_timer = QTimer(self)
        self._suppress_timer.setSingleShot(True)
        self._suppress_timer.timeout.connect(self._clear_suppression)
        self._suppressed: bool = False
        # v0.8.0a107 — the virtual-desktop "follow the user across desktops"
        # feature was removed (see docs/archive/removed_virtual_desktop_a107/).
        # This watcher is now hide-only.
        app = QApplication.instance()
        if app is not None:
            app.focusWindowChanged.connect(self._on_focus_changed)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if not self._enabled:
            self._debounce.stop()

    def suppress_for(self, ms: int) -> None:
        """Ignore focusWindowChanged for the next ``ms`` ms.

        Used around programmatic show calls (tray click, in
        particular) so platform focus shuffle during the show /
        raise / activate sequence doesn't queue a phantom hide.
        """
        self._suppressed = True
        self._debounce.stop()
        self._suppress_timer.start(int(ms))

    def _clear_suppression(self) -> None:
        self._suppressed = False

    def _on_focus_changed(self, _new_window: Any) -> None:
        if not self._enabled or self._suppressed:
            return
        self._debounce.start()

    def _fire(self) -> None:
        if not self._enabled or self._suppressed:
            return
        app = QApplication.instance()
        if app is None:
            return
        # v0.8.0a60 -- never auto-hide while one of OUR OWN modal
        # dialogs or popup menus is open.  A forest-spawned dialog
        # (Settings, About, a warning QMessageBox) or the cell
        # right-click menu steals the active-window slot, and its
        # parent chain doesn't always resolve back to a CellWindow
        # (e.g. a static ``QMessageBox.warning(...)`` or an
        # unparented dialog), so ``_is_inside_forest`` would
        # mis-read it as "focus left the forest" and hide the hub +
        # every cell out from under the user mid-interaction -- the
        # a52-era "forest vanishes while I'm in a dialog" complaint.
        # An active modal / popup belongs to THIS Qt app (the call
        # only ever returns our own widgets), so the user is plainly
        # still interacting with the forest; suppress the hide until
        # the dialog / menu closes.
        try:
            if (
                app.activeModalWidget() is not None
                or app.activePopupWidget() is not None
            ):
                return
        except Exception:  # noqa: BLE001
            pass
        active = app.activeWindow()
        if self._is_inside_forest(active):
            return
        try:
            self._on_focus_left()
        except Exception as exc:  # noqa: BLE001
            _log(f"_FocusWatcher._fire: on_focus_left raised {exc!r}")

    def _is_inside_forest(self, widget: Any) -> bool:
        """Return True if ``widget`` is the forest hub itself OR
        a registered CellWindow (any cell, ring member, or
        standalone -- per the strict-scope rule).

        ``widget`` of None means "no app window has focus" --
        treated as outside.
        """
        if widget is None:
            return False
        if widget is self._forest_window:
            return True
        try:
            top = widget.window()
        except Exception:  # noqa: BLE001
            top = widget
        if top is self._forest_window:
            return True
        try:
            from scriptree.shell.cell_window import CellWindow
            if isinstance(top, CellWindow):
                return True
        except Exception:  # noqa: BLE001
            pass
        # Walk parents for modal dialogs / popups parented to the
        # forest hub or to any cell.
        try:
            owner = top.parent() if top is not None else None
            while owner is not None:
                if owner is self._forest_window:
                    return True
                from scriptree.shell.cell_window import CellWindow
                if isinstance(owner, CellWindow):
                    return True
                owner = owner.parent()
        except Exception:  # noqa: BLE001
            pass
        return False


# ---------------------------------------------------------------------------
# ForestHubState — the single source of truth (model)
# ---------------------------------------------------------------------------

@dataclass
class ForestHubState:
    """v0.8.0a108 — the ONE model the forest hub's show/hide/restore reads.

    See ``docs/LLM/forest_show_apply_design.md``.  ``ForestVisibilityManager``
    mutates this on events and reflects it via the single idempotent
    ``apply_state()``; nothing else stores hub position / visibility / mode.
    """

    #: The hub's desired top-left in global screen coords — THE one position
    #: store.  Written ONLY by user drag (drag-end) + initial load.  Read by
    #: apply_state().  ``None`` => no stored position yet (let the OS place it).
    hub_position: QPoint | None = None

    #: Window MODE (derived from the 3 visibility prefs in ``apply``).
    always_on_top: bool = True
    taskbar: bool = False          #: hub carries ``Qt.Window`` (taskbar entry)
    tray: bool = False             #: a tray icon exists

    #: Desired visibility of the whole forest (False => hidden / minimised).
    shown: bool = True

    #: IDs of descendants we hid on the last hide, so a show reveals exactly
    #: them (user-collapsed cells stay collapsed).
    hidden_descendant_ids: list[str] = field(default_factory=list)

    @property
    def auto_hide(self) -> bool:
        """Derived: the focus-watcher (auto-hide) is on iff always-on-top is OFF
        and at least one of taskbar / tray is on."""
        return (not self.always_on_top) and (self.taskbar or self.tray)


# ---------------------------------------------------------------------------
# ForestVisibilityManager
# ---------------------------------------------------------------------------

class ForestVisibilityManager(QObject):
    """Orchestrates the three forest visibility modes.

    The controller calls ``apply(prefs)`` once at startup and
    again whenever the user changes any of the three flags.
    Internal state is fully derived from ``prefs``.
    """

    def __init__(
        self,
        forest_window: Any,
        registry: Any,
        quit_callback: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._forest_window = forest_window
        self._registry = registry
        self._quit_callback = quit_callback
        self._tray_icon: ForestTrayIcon | None = None
        self._watcher = _FocusWatcher(
            forest_window, registry, self.hide_hub,
        )
        # v0.8.0a108 — THE single source of truth.  Window mode (the three
        # flags), desired visibility, the one hub-position store, and the set
        # of descendants folded away on the last hide all live in this model.
        # Events mutate it; ``apply_state()`` is the only thing that reflects it
        # onto the live window.  The old scattered fields (_taskbar_on /
        # _always_on_top / _auto_hide / _last_hub_position /
        # _hidden_descendant_ids) collapsed into this one object so the three
        # historically-divergent show paths (tray click, taskbar restore,
        # startup) can no longer drift apart.  See
        # ``docs/LLM/forest_show_apply_design.md``.
        self._state = ForestHubState()
        # v0.8.0a108 (review fix) — re-entrancy guard.  ``apply_state`` MOVES the
        # hub programmatically (clamp-on-show), and ``CellWindow.moveEvent``
        # emits ``hexagonMoved`` on EVERY move, including programmatic ones.
        # ``forest_controller._on_hex_moved`` listens for that and writes
        # ``state.hub_position`` — so without a guard, apply_state's own clamp
        # would re-enter and overwrite the stored position with the clamped
        # value (losing a real off-screen position + persisting the clamp).
        # This flag, set True for the duration of apply_state, tells
        # _on_hex_moved "this move is mine, not the user's — don't capture it".
        self._applying_state: bool = False
        # Install the event filter on the hub so we can detect
        # the user clicking its taskbar entry (restore from
        # minimised).  See eventFilter() below.
        try:
            forest_window.installEventFilter(self)
        except Exception as exc:  # noqa: BLE001
            _log(f"__init__: installEventFilter failed: {exc!r}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply(self, prefs: Any) -> None:
        """Re-derive everything from the prefs object.

        Idempotent: same prefs in -> same state out.  ``prefs`` is
        a ``ForestPreferences`` (we duck-type the three flags).
        """
        prefs = prefs.normalised()
        aot = bool(prefs.show_always_on_top)
        tb = bool(prefs.show_on_taskbar)
        tr = bool(prefs.show_in_system_tray)

        # Order matters: swap Qt.Tool / Qt.Window BEFORE adjusting
        # always-on-top, since the latter's hide+show ritual
        # picks up whatever flag combination is current at the
        # moment of show().
        self._apply_taskbar_flag(tb)
        self._apply_always_on_top(aot)
        # If the hub is now in Qt.Window mode AND show_always_on_top
        # is False, set the icon + title so the taskbar entry
        # displays something useful.  Cheap to do every time --
        # setWindowIcon / setWindowTitle on an unchanged value is
        # a no-op.
        try:
            self._forest_window.setWindowIcon(_forest_icon())
            self._forest_window.setWindowTitle("ScripTree Forest")
        except Exception:  # noqa: BLE001
            pass

        self._apply_tray(tr)

        # The three flag setters above each wrote their field into self._state
        # (state.taskbar / state.always_on_top / state.tray).  ``auto_hide`` is
        # the derived rule "watcher on iff always-on-top OFF and taskbar-or-tray
        # ON".
        self._watcher.set_enabled(self._state.auto_hide)

        # If auto-hide is on AND the hub is currently visible /
        # not-minimised, transition into the hidden / minimised
        # state immediately so the user sees the rule take
        # effect.  On the first apply() (during start()) the hub
        # hasn't been shown yet -- this branch becomes a no-op
        # and the controller leaves the hub in its hidden state.
        if self._state.auto_hide and self._forest_window is not None:
            try:
                w = self._forest_window
                if w.isVisible() and not w.isMinimized():
                    self.hide_hub()
            except Exception as exc:  # noqa: BLE001
                _log(f"apply: post-flip auto-hide raised {exc!r}")

    def _clamp_hub(self, pos: "QPoint") -> "QPoint":
        """Clamp a prospective hub top-left onto a visible screen.

        a69: programmatic hub moves (show_hub restore, startup
        restore) must never strand the hub off-screen -- the
        "forest disappeared" bug.  Reuses the hub's own
        ``CellWindow._clamp_to_screen`` (the same helper interactive
        drag and ``screen_watcher.rescue_all_cells`` use); degrades
        to the raw point if the hub doesn't expose it.
        """
        w = self._forest_window
        try:
            if w is not None and hasattr(w, "_clamp_to_screen"):
                return w._clamp_to_screen(pos)
        except Exception as exc:  # noqa: BLE001
            _log(f"_clamp_hub: {exc!r}")
        return pos

    # ------------------------------------------------------------------
    # apply_state() -- THE single render pass (v0.8.0a108)
    # ------------------------------------------------------------------

    def apply_state(self) -> None:
        """Reflect ``self._state`` onto the live hub window -- the ONE place
        that shows / hides / moves the forest.

        This is the "render pass" of the model->apply design
        (``docs/LLM/forest_show_apply_design.md`` §4).  Every show / hide /
        restore path -- tray click, taskbar-entry restore, startup, an
        auto-hide flip -- mutates ``self._state`` then calls this; they can no
        longer diverge the way ``show_hub`` (forced a stored position) and the
        taskbar restore (trusted the OS) used to.

        Contract / invariants:
          * **Position comes from the model.**  When showing, the hub is moved
            to ``state.hub_position`` *clamped on-screen* -- "wherever the user
            last left it", never (0,0) and never a stale off-screen spot.
            ``hub_position`` is kept current by the drag-end capture in
            ``forest_controller`` (and, defensively, re-captured here at hide).
          * **Idempotent.**  Calling it twice with an unchanged model lands the
            same window geometry / visibility; showNormal / move / show on
            already-correct values are no-ops.  In particular a redundant HIDE
            (a second focus-left event while already hidden) is a no-op that
            PRESERVES ``hidden_descendant_ids`` -- it must NOT re-derive the
            list from the (already-hidden) descendants, or the next show would
            reveal nothing ("forest comes back empty").  [review fix]
          * **Programmatic moves are not user drags.**  ``_applying_state`` is
            held True for the duration so the clamp-on-show move (which fires
            ``hexagonMoved``) can't re-enter ``_on_hex_moved`` and overwrite the
            stored ``hub_position`` with the clamped value.  [review fix]
          * **Never invokes the bloom / layout engine.**  Docking, the bloom
            expand/collapse, and remembered offsets stay entirely the docking
            engine's job (design §6a).  This method only show()/hide()/move()s
            windows that already exist -- it never re-tiles.
          * **Descendants follow the hub.**  Showing reveals exactly the cells
            the last hide folded away (``state.hidden_descendant_ids``) and
            rescues any now off-screen; hiding folds every visible descendant
            and records which ones.
        """
        w = self._forest_window
        if w is None:
            return
        st = self._state
        # [review fix] Re-entrancy guard: hold this True across the whole render
        # pass so any programmatic move() below (the clamp-on-show) is ignored
        # by forest_controller._on_hex_moved -- only a real USER drag should
        # write state.hub_position.  finally-reset so an exception can't strand
        # it (which would silently freeze all future drag-captures).
        self._applying_state = True
        try:
            if st.shown:
                # Suppress the focus watcher across the show+raise focus
                # shuffle so the platform churn can't queue a spurious
                # auto-hide (was 300ms in the old show_hub).
                try:
                    self._watcher.suppress_for(300)
                except Exception:  # noqa: BLE001
                    pass
                # Move to the stored position (clamped) THEN show so the window
                # never flashes at (0,0) / a stale spot.  a69 clamp guards a
                # stale or off-screen stored position (resolution shrank,
                # monitor unplugged, dragged off-screen).
                if st.taskbar:
                    # v0.8.0a111 -- only un-minimise / show when the window
                    # actually needs it.  Calling ``showNormal()`` on a window
                    # the OS has ALREADY restored (the user's taskbar click)
                    # re-maps it and DROPS the foreground/active state Windows
                    # just granted -- which is why the first reveal's hub was
                    # clickable but NOT draggable until a manual minimise/
                    # restore.  Re-mapping only when needed preserves activation.
                    if w.isMinimized():
                        w.showNormal()
                    elif not w.isVisible():
                        w.show()
                    if st.hub_position is not None:
                        w.move(self._clamp_hub(st.hub_position))
                else:
                    if st.hub_position is not None and not w.isVisible():
                        w.move(self._clamp_hub(st.hub_position))
                    if not w.isVisible():
                        w.show()
                    if st.hub_position is not None:
                        # Re-show in tray / always-on-top mode must land where
                        # the user left it even if the window was already
                        # visible (cheap + idempotent).  This is the a108 fix
                        # for "tray click jumps the forest back to its
                        # show-time position": now it reads the LIVE
                        # drag-captured position, not a stale hide-time one.
                        w.move(self._clamp_hub(st.hub_position))
                self._reveal_hidden_descendants()
                try:
                    w.raise_()
                    w.activateWindow()
                    # v0.8.0a111 -- re-assert activation on the NEXT event-loop
                    # tick, after the OS finishes the map/restore.  A frameless
                    # window revealed programmatically on Win11 can fail to
                    # become foreground in the same tick (foreground lock), so
                    # its first drag gesture is dropped; the deferred activate
                    # makes the hub draggable on first reveal without a manual
                    # hide/show cycle.
                    QTimer.singleShot(0, self._post_show_activate)
                except Exception:  # noqa: BLE001
                    pass
            else:
                # [review fix] IDEMPOTENT HIDE.  If the hub is ALREADY in its
                # hidden state (minimised in taskbar mode; not-visible
                # otherwise), this is a redundant hide -> NO-OP.  Re-running the
                # fold loop here would be catastrophic: every descendant is
                # already hidden, so the loop records NOTHING, and the
                # unconditional ``hidden_descendant_ids = []`` would WIPE the
                # set captured by the first hide -> the next show reveals no
                # cells ("forest comes back empty / cells left behind").  This
                # double-hide is reachable in auto-hide mode: the focus watcher
                # stays enabled while hidden and fires hide_hub again on a
                # second focus-left event (or the hide's own focus churn).
                # Returning early preserves the recorded set and makes
                # hide();hide();show() == hide();show() (design §4 idempotence).
                already_hidden = (
                    w.isMinimized() if st.taskbar else (not w.isVisible())
                )
                if already_hidden:
                    return
                # First (real) hide: fold every visible descendant away,
                # recording exactly which ones so the next show reveals only
                # those (user-collapsed / explicitly-closed cells stay as they
                # were), capture the live hub position as a safety net, then
                # minimise (taskbar mode, keeps the taskbar entry) or hide
                # (tray-only / always-on-top toggle).
                st.hidden_descendant_ids = []
                for descendant in self._forest_descendants():
                    try:
                        if descendant.isVisible():
                            descendant.hide()
                            cell_id = getattr(descendant, "_id", None)
                            if cell_id:
                                st.hidden_descendant_ids.append(cell_id)
                    except Exception:  # noqa: BLE001
                        continue
                if st.taskbar:
                    if w.isVisible() and not w.isMinimized():
                        st.hub_position = QPoint(w.pos())
                    w.showMinimized()
                else:
                    if w.isVisible():
                        st.hub_position = QPoint(w.pos())
                    w.hide()
        except Exception as exc:  # noqa: BLE001
            _log(f"apply_state: {exc!r}")
        finally:
            self._applying_state = False

    def _post_show_activate(self) -> None:
        """v0.8.0a111 -- deferred re-activation of the freshly-revealed hub.

        Scheduled one event-loop tick after ``apply_state`` shows the hub.  A
        frameless window shown programmatically on Win11 can fail to become the
        foreground/active window in the same tick (the OS foreground lock), so
        its first drag gesture is silently dropped -- the user-reported "I can
        click the forest icon (menu opens) but can't drag it until I minimise
        and restore it".  Re-asserting ``raise_`` + ``activateWindow`` + the
        active window-state here, after the OS has finished the map, gives the
        hub the input focus it needs to be draggable on first reveal.  Guarded
        to act only when the hub is genuinely shown (not minimised/hidden)."""
        w = self._forest_window
        if w is None:
            return
        try:
            if w.isVisible() and not w.isMinimized():
                w.raise_()
                w.activateWindow()
                # activateWindow() alone can be a no-op under the Win11
                # foreground lock; setting the ACTIVE window-state explicitly is
                # the stronger nudge.  Clearing Minimized keeps it a no-op when
                # already normal (so no spurious WindowStateChange storm).
                w.setWindowState(
                    (w.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive
                )
        except Exception as exc:  # noqa: BLE001
            _log(f"_post_show_activate: {exc!r}")

    def _reveal_hidden_descendants(self) -> None:
        """Show exactly the descendants the last hide folded away, then clamp
        any whose stored position is now off-screen, and clear the tracked-id
        list.  Shared by every show path (tray, taskbar restore, startup) so
        the reveal logic exists in ONE place.

        a62 (user-reported): the hub may have moved while the cells were hidden,
        leaving a revealed cell's stored position off every connected screen; a
        bare ``show()`` would strand it.  ``_rescue_cells_on_screen`` clamps each
        back onto its containing screen, moving only those that actually changed.
        """
        st = self._state
        shown: list[Any] = []
        for cell_id in st.hidden_descendant_ids:
            cell = self._registry.get(cell_id)
            if cell is None:
                continue
            try:
                cell.show()
                shown.append(cell)
            except Exception:  # noqa: BLE001
                continue
        st.hidden_descendant_ids = []
        self._rescue_cells_on_screen(shown)

    def show_hub(self) -> None:
        """Reveal the forest hub AND its descendants.

        Thin wrapper (v0.8.0a108): flip the model to ``shown`` and render once.
        EVERY show entry point -- the tray icon, the taskbar-entry restore
        detector (``eventFilter`` below), and external callers -- funnels
        through here into ``apply_state``, so they can't drift apart the way
        the old hand-written ``show_hub`` / ``_restore_descendants`` pair did.
        """
        self._state.shown = True
        self.apply_state()

    def hide_hub(self) -> None:
        """Hide the forest hub AND every visible forest descendant.

        Thin wrapper (v0.8.0a108): flip the model to hidden and render once.
        ``apply_state`` captures the live hub position, records which
        descendants it folded (so the next show reveals only those), and
        minimises (taskbar mode) or hides (tray-only / always-on-top toggle).
        """
        self._state.shown = False
        self.apply_state()

    def toggle_hub(self) -> None:
        """Toggle the forest's visibility: hide it if shown, show it if hidden.

        v0.8.0a111 -- the tray icon (and any single click-to-toggle surface)
        funnels here so a SECOND click on the tray/taskbar icon HIDES the whole
        forest (hub + bloomed cells) when always-on-top is OFF, instead of the
        old behaviour where a tray click always showed and never hid.  Reads the
        one model flag ``state.shown`` so it stays in lock-step with the
        taskbar-entry toggle handled in ``eventFilter``.
        """
        if self._state.shown:
            self.hide_hub()
        else:
            self.show_hub()

    def hide_descendants_only(self) -> None:
        """Hide every visible forest descendant WITHOUT touching
        the hub itself.

        Used by ``ForestController.start`` after the spawn pass
        in auto-hide mode -- the hub is already in its initial
        hidden state (minimised for taskbar mode, hidden for
        tray-only) but the spawn pass shows each cell as it
        loads.  This call folds those cells away to match the
        invariant and seeds ``_hidden_descendant_ids`` so the
        first ``show_hub`` reveals them again.
        """
        st = self._state
        st.hidden_descendant_ids = []
        for descendant in self._forest_descendants():
            try:
                if descendant.isVisible():
                    descendant.hide()
                    cell_id = getattr(descendant, "_id", None)
                    if cell_id:
                        st.hidden_descendant_ids.append(cell_id)
            except Exception:  # noqa: BLE001
                continue

    def fold_new_visible_descendants(self) -> None:
        """v0.8.0a114 -- fold any descendant that is CURRENTLY VISIBLE while the
        forest is HIDDEN, APPENDING each to ``hidden_descendant_ids`` (never
        resetting the list).

        This is the FIRST-RUN fix.  At startup ``hide_descendants_only`` folds
        the forest once; but on a NEW install the forest is EMPTY at that point,
        so nothing is folded, and the first-run discovery then populates it via
        ``ForestController.add_item`` -- each freshly-spawned cell appears
        VISIBLE on the desktop while the hub is already hidden ("hub
        disappeared, cells left behind").  Calling this after each such add
        folds the new cell(s) into the hidden set so the next reveal
        (taskbar/tray click) brings them back with the rest of the forest.

        Crucially it APPENDS rather than resetting the id list, so calling it
        repeatedly across a discovery burst never wipes the already-folded set
        (the trap ``hide_descendants_only`` would hit if reused per-item).
        No-op when the forest is currently shown -- then a new cell belongs on
        screen with everything else.
        """
        st = self._state
        if st.shown:
            return
        for descendant in self._forest_descendants():
            try:
                if descendant.isVisible():
                    descendant.hide()
                    cell_id = getattr(descendant, "_id", None)
                    if cell_id and cell_id not in st.hidden_descendant_ids:
                        st.hidden_descendant_ids.append(cell_id)
            except Exception:  # noqa: BLE001
                continue

    def teardown(self) -> None:
        """Release the tray icon at app shutdown."""
        if self._tray_icon is not None:
            try:
                self._tray_icon.hide()
            except Exception:  # noqa: BLE001
                pass
            self._tray_icon = None
        self._watcher.set_enabled(False)

    # ------------------------------------------------------------------
    # Event filter on the hub -- detect taskbar-click restores
    # ------------------------------------------------------------------

    def eventFilter(self, obj: Any, event: Any) -> bool:  # noqa: N802
        """Hook ``WindowStateChange`` on the hub so the user
        clicking its taskbar entry triggers a full show_hub
        (which also reveals the descendants).

        Without this, a taskbar click would un-minimise the hub
        but leave the cells hidden -- the visible inverse of the
        a52 / a53 bug.

        Only acts when auto-hide is on (i.e. always-on-top is
        OFF).  In always-on-top mode the user can minimise /
        restore the hub normally without us interfering.
        """
        # Defensive (a61): a Qt event filter must NEVER raise.  During
        # interpreter / Qt teardown this object can receive a final
        # event after its Python attributes have been torn down -- read
        # them via getattr so we degrade to "not handled" instead of
        # spewing "Error calling Python override of eventFilter".
        fw = getattr(self, "_forest_window", None)
        st = getattr(self, "_state", None)
        if (
            fw is not None
            and st is not None
            and obj is fw
            and event.type() == QEvent.Type.WindowStateChange
            and st.auto_hide
            and st.taskbar
        ):
            try:
                if not fw.isMinimized() and fw.isVisible():
                    # RESTORE: the user un-minimised the hub from the taskbar.
                    # Only act if our model says we WERE hidden (else this is
                    # the echo of our own showNormal -> no double-fire).  Run
                    # the SAME show path the tray click uses (model ->
                    # apply_state) so the two can never diverge -- the a108
                    # unification.  Scheduled on the next event-loop tick so the
                    # OS finishes the state change first.
                    if not st.shown:
                        QTimer.singleShot(0, self.show_hub)
                elif fw.isMinimized() and st.shown:
                    # MINIMISE (v0.8.0a111): the user clicked the taskbar entry
                    # of the SHOWN forest, so Windows minimised the hub window.
                    # But the hub's frameless cells are SEPARATE windows -- the
                    # OS leaves them on screen, and the focus watcher misses it
                    # because focus lands on one of the still-visible cells
                    # (``_is_inside_forest`` -> True -> no hide).  Fold the cells
                    # ourselves so the WHOLE forest hides together on a second
                    # taskbar click (the user-requested behaviour).  The hub is
                    # already minimised by the OS, so we only fold the
                    # descendants (``hide_descendants_only`` records them so the
                    # next restore reveals exactly them) and sync the model.
                    st.shown = False
                    QTimer.singleShot(0, self.hide_descendants_only)
            except Exception as exc:  # noqa: BLE001
                _log(f"eventFilter: taskbar state-change raised {exc!r}")
        return super().eventFilter(obj, event)

    def _rescue_cells_on_screen(self, cells: list[Any]) -> None:
        """Clamp each just-revealed cell back onto a visible screen.

        Bug A (a62, user-reported): if the forest hub was relocated
        (dragged to a new spot, moved by the follow-the-user logic,
        or the display layout changed) WHILE its cells were hidden,
        the cells keep their last on-screen positions -- which may
        now be partly or wholly off every connected screen.  A bare
        ``show()`` would leave them there, invisible and unreachable.

        Mirror ``screen_watcher.rescue_all_cells``: clamp each
        revealed cell's top-left to its containing screen's available
        area (``CellWindow._clamp_to_screen`` falls back to the
        primary screen for a position that maps to no screen) and
        move it ONLY when the clamp actually changed something, so a
        cell that's already on-screen is left exactly where it is.
        """
        for cell in cells:
            try:
                raw = cell.pos()
                clamped = cell._clamp_to_screen(raw)
                if clamped != raw:
                    cell.move(clamped)
                    _log(
                        f"_rescue_cells_on_screen: cell "
                        f"{getattr(cell, '_id', '?')[:8]} "
                        f"({raw.x()},{raw.y()}) -> "
                        f"({clamped.x()},{clamped.y()})"
                    )
            except Exception as exc:  # noqa: BLE001
                _log(f"_rescue_cells_on_screen: {exc!r}")
                continue

    # ------------------------------------------------------------------
    # Internals -- always-on-top
    # ------------------------------------------------------------------

    def _apply_always_on_top(self, on: bool) -> None:
        """Toggle ``WindowStaysOnTopHint`` on the hub."""
        w = self._forest_window
        if w is None:
            return
        try:
            w._apply_always_on_top_flag(on)
        except Exception as exc:  # noqa: BLE001
            _log(f"_apply_always_on_top: helper raised {exc!r}")
        self._state.always_on_top = on

    # ------------------------------------------------------------------
    # Internals -- taskbar
    # ------------------------------------------------------------------

    def _apply_taskbar_flag(self, on: bool) -> None:
        """Swap the hub's ``Qt.Tool`` <-> ``Qt.Window`` flag.

        a54: replaces the a52 / a53 proxy-host approach.  The
        flag swap puts the hub itself on the taskbar -- no proxy,
        no transient-parent quirk, no race when the user clicks
        the taskbar entry.
        """
        w = self._forest_window
        if w is None:
            return
        try:
            w._apply_taskbar_flag(on)
        except Exception as exc:  # noqa: BLE001
            _log(f"_apply_taskbar_flag: helper raised {exc!r}")
        self._state.taskbar = on

    # ------------------------------------------------------------------
    # Internals -- tray
    # ------------------------------------------------------------------

    def _apply_tray(self, on: bool) -> None:
        """Spawn or tear down the system tray icon."""
        self._state.tray = on
        if on and self._tray_icon is None:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                _log(
                    "_apply_tray: system tray not available; "
                    "tray flag ignored"
                )
                return
            tray = ForestTrayIcon(
                # v0.8.0a111 -- TOGGLE, not show-only: a second tray click now
                # hides the forest (hub + bloomed cells) when always-on-top is
                # OFF, matching the taskbar-entry toggle.
                on_activate=self.toggle_hub,
                on_quit=self._quit_callback,
                parent=self,
            )
            tray.show()
            self._tray_icon = tray
        elif not on and self._tray_icon is not None:
            try:
                self._tray_icon.hide()
            except Exception:  # noqa: BLE001
                pass
            self._tray_icon = None

    # ------------------------------------------------------------------
    # Internals -- descendant walk
    # ------------------------------------------------------------------

    def _forest_descendants(self) -> list[Any]:
        """Return the flat list of every CellWindow attached to the forest hub.

        Enumerates via BOTH attachment graphs, because either alone misses
        cells the user sees as "part of the forest":

          * the LINK / membership graph (``_members``) -- rings + standalone
            forest items the forest OWNS; and
          * the DOCK graph (``_dock_children_by_edge``) -- cells/rings snapped
            onto an edge of a node.

        Why both (v0.8.0a85 fix): a ring (or any sub-cluster whose root is a
        master) dragged onto the forest goes through ``_try_spawn_master``
        **Case M1** -- *"a ring docking onto anything is purely spatial -- no
        link change"*.  It is wired into the DOCK graph
        (``hub._dock_children_by_edge``) so it moves with the forest and looks
        attached, but it is NEVER added to ``hub._members`` and its
        ``_group_master_id`` is never set to the hub.  The pre-a85 walk
        followed only ``_members`` (and recursed only into masters), so it
        never enumerated that sub-cluster -- ``hide_hub`` left it on screen
        ("cells left behind on the desktop").  Following the dock graph too,
        and recursing through EVERY node (a plain cell can carry a dock-chain),
        makes "what is hidden/shown with the forest" == "what is visually
        attached to it".  The ``seen`` set keeps it finite and dedupes the
        overlap between the two graphs.
        """
        w = self._forest_window
        if w is None:
            return []
        out: list[Any] = []
        seen: set[str] = set()

        def _walk(parent: Any) -> None:
            child_ids: list[str] = list(getattr(parent, "_members", None) or {})
            dock_children = getattr(parent, "_dock_children_by_edge", None) or {}
            child_ids.extend(dock_children.values())
            for child_id in child_ids:
                if child_id in seen:
                    continue
                seen.add(child_id)
                cell = self._registry.get(child_id)
                if cell is None:
                    continue
                out.append(cell)
                # Recurse through EVERY node (the ``seen`` set bounds it).  The
                # old ``role == "master"`` gate stopped at the first plain cell
                # and stranded any dock-chain hanging off it.
                _walk(cell)

        try:
            _walk(w)
        except Exception as exc:  # noqa: BLE001
            _log(f"_forest_descendants: walk raised {exc!r}")
        return out
