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
    """Hide the forest hub when focus moves outside the forest
    hierarchy, AND follow the user across virtual desktops.

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

    a55: the focus signal ALSO triggers the virtual-desktop
    follow-the-user logic.  When focus moves to a window on a
    different desktop than the forest hub, we move the hub (and
    its visible descendants) to the user's current desktop.  This
    is independent of ``_enabled`` -- the user wants the forest
    to follow them whether or not auto-hide is on.  Implementation:
    ``_on_focus_changed`` always calls the follow path; the hide
    path is gated by ``_enabled`` as before.
    """

    def __init__(
        self,
        forest_window: Any,
        registry: Any,
        on_focus_left: Callable[[], None],
        on_focus_changed_for_follow: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._forest_window = forest_window
        self._registry = registry
        self._on_focus_left = on_focus_left
        self._on_focus_changed_for_follow = on_focus_changed_for_follow
        self._enabled = False
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(80)
        self._debounce.timeout.connect(self._fire)
        self._suppress_timer = QTimer(self)
        self._suppress_timer.setSingleShot(True)
        self._suppress_timer.timeout.connect(self._clear_suppression)
        self._suppressed: bool = False
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
        # a55: the follow-the-user path runs UNCONDITIONALLY (it
        # only matters when virtual desktops are in play, which is
        # a no-op for users on a single desktop).  This is what
        # gives the user the "forest appears on every desktop"
        # PortableApps-style behaviour without the private-COM
        # ``PinWindow`` fragility.
        if self._on_focus_changed_for_follow is not None:
            try:
                self._on_focus_changed_for_follow()
            except Exception as exc:  # noqa: BLE001
                _log(f"_on_focus_changed: follow callback raised {exc!r}")
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
            on_focus_changed_for_follow=self._follow_user_across_desktops,
        )
        # Current visibility state derived from the last apply().
        self._taskbar_on: bool = False
        self._always_on_top: bool = True
        self._auto_hide: bool = False
        # Saved position of the hub so hide/show round-trips
        # don't lose placement.  Only used in tray-only (no
        # taskbar) mode -- in taskbar mode "hide" means minimise,
        # which preserves position natively.
        self._last_hub_position: QPoint | None = None
        # IDs of cells we hid in the last hide_hub() call.  Only
        # these get re-shown by show_hub() -- if the user had
        # other cells collapsed / explicitly closed before we
        # ran, leave them alone.
        self._hidden_descendant_ids: list[str] = []
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

        self._auto_hide = (not aot) and (tb or tr)
        self._watcher.set_enabled(self._auto_hide)

        # If auto-hide is on AND the hub is currently visible /
        # not-minimised, transition into the hidden / minimised
        # state immediately so the user sees the rule take
        # effect.  On the first apply() (during start()) the hub
        # hasn't been shown yet -- this branch becomes a no-op
        # and the controller leaves the hub in its hidden state.
        if self._auto_hide and self._forest_window is not None:
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

    def show_hub(self) -> None:
        """Bring the forest hub AND its descendants back into view.

        Used by the tray icon, by the taskbar restore detector
        (eventFilter below), and by external code that wants to
        guarantee everything is visible.

        Briefly suppresses the focus watcher (200ms) so the
        platform focus shuffle during show + raise + activate
        doesn't trigger a spurious hide.  In a54 the suppression
        is much shorter than a53's 300ms because the taskbar
        proxy bounce-back is gone.
        """
        try:
            self._watcher.suppress_for(300)
        except Exception:  # noqa: BLE001
            pass

        w = self._forest_window
        if w is None:
            return

        # a59: move BEFORE show, while window is still minimised.
        #
        # The a56 ritual hid the window before moving, on the
        # theory that hide() would clear Windows' minimise-state
        # desktop tracking.  The diagnostic log (after a58 fixed
        # ctypes) revealed the real failure mode:
        #
        #   [win_virtual_desktops:debug] MoveWindowToDesktop(...) -> HRESULT=0x8002802B FAIL
        #
        # 0x8002802B is TYPE_E_ELEMENTNOTFOUND -- and it's what
        # ``MoveWindowToDesktop`` returns when the target window
        # is HIDDEN.  Minimised windows accept the call;
        # ``hide()``-d ones don't.  So the a56 "hide then move"
        # sequence was self-defeating: it disabled the very call
        # it was trying to make work.  By the time the post-show
        # move ran with HRESULT=OK, ``showNormal()`` had already
        # called ``SwitchToThisWindow`` and yanked the user to
        # the origin desktop.
        #
        # a59: keep the window minimised, move it (the COM call
        # accepts minimised windows just fine), THEN restore.
        # ``showNormal`` then restores on the desktop we just
        # moved it to -- which IS the user's current desktop --
        # so the SwitchToThisWindow internal becomes a no-op.
        desktop_id = None
        try:
            from scriptree.shell import win_virtual_desktops as wvd
            if wvd.is_supported():
                desktop_id = wvd.get_current_desktop_id()
        except Exception as exc:  # noqa: BLE001
            _log(f"show_hub: resolve current desktop raised {exc!r}")

        try:
            hwnd = int(w.winId()) if w is not None else 0

            if self._taskbar_on:
                # Move FIRST, while still minimised.
                if desktop_id is not None and hwnd:
                    try:
                        from scriptree.shell import win_virtual_desktops as wvd
                        ok = wvd.move_window_to_desktop(hwnd, desktop_id)
                        on_current = wvd.is_window_on_current_desktop(hwnd)
                        _log(
                            f"show_hub: hub move (minimised path): "
                            f"ok={ok} on_current_after={on_current}"
                        )
                    except Exception as exc:  # noqa: BLE001
                        _log(f"show_hub: pre-show move raised {exc!r}")
                # Now restore -- the window is on the user's
                # current desktop, so SwitchToThisWindow inside
                # showNormal does nothing.
                w.showNormal()
                if self._last_hub_position is not None:
                    # a69: clamp so a stale / off-screen last position
                    # (resolution shrank, monitor unplugged, hub last
                    # dragged off-screen) can't strand the hub off the
                    # visible desktop -- the "forest disappeared" bug.
                    w.move(self._clamp_hub(self._last_hub_position))
                # Belt-and-suspenders: re-check after show, in
                # case some platform race put us back on the
                # origin desktop.  Log the result so we can see
                # whether this second call is doing real work or
                # whether the pre-show move was sufficient.
                if desktop_id is not None and hwnd:
                    try:
                        from scriptree.shell import win_virtual_desktops as wvd
                        if not wvd.is_window_on_current_desktop(hwnd):
                            ok = wvd.move_window_to_desktop(
                                hwnd, desktop_id,
                            )
                            _log(
                                f"show_hub: hub corrective post-show "
                                f"move: ok={ok}"
                            )
                    except Exception as exc:  # noqa: BLE001
                        _log(f"show_hub: post-show move raised {exc!r}")
            else:
                # Tray-only / hidden mode -- the hub is HIDDEN
                # (not minimised) here, so MoveWindowToDesktop
                # would return TYPE_E_ELEMENTNOTFOUND.  We have
                # to show first, then move.  Trade-off: brief
                # flash on origin desktop possible.  Mitigated
                # by suppress_for above.
                if self._last_hub_position is not None and not w.isVisible():
                    # a69: clamp the restore position on-screen (see the
                    # taskbar branch above).
                    w.move(self._clamp_hub(self._last_hub_position))
                w.show()
                if desktop_id is not None and hwnd:
                    try:
                        from scriptree.shell import win_virtual_desktops as wvd
                        ok = wvd.move_window_to_desktop(hwnd, desktop_id)
                        _log(f"show_hub: hub move (tray-only path): ok={ok}")
                    except Exception as exc:  # noqa: BLE001
                        _log(f"show_hub: tray-mode move raised {exc!r}")

            # a59: show descendants FIRST, then move.  Hidden
            # windows reject MoveWindowToDesktop with
            # TYPE_E_ELEMENTNOTFOUND (the bug a59 fixed for the
            # hub); descendants hit the same wall.  The trade-off
            # here is a brief flash on the origin desktop before
            # the move catches up, but the suppress_for(300)
            # above buys enough time that the user doesn't
            # perceive it as a desktop switch.
            shown_descendants: list[Any] = []
            for cell_id in self._hidden_descendant_ids:
                cell = self._registry.get(cell_id)
                if cell is None:
                    continue
                try:
                    cell.show()
                    shown_descendants.append(cell)
                except Exception:  # noqa: BLE001
                    continue
            # Now they're visible -- move them.
            if desktop_id is not None:
                try:
                    from scriptree.shell import win_virtual_desktops as wvd
                    for cell_id in self._hidden_descendant_ids:
                        cell = self._registry.get(cell_id)
                        if cell is None:
                            continue
                        try:
                            d_hwnd = int(cell.winId())
                            wvd.move_window_to_desktop(d_hwnd, desktop_id)
                        except Exception:  # noqa: BLE001
                            continue
                except Exception as exc:  # noqa: BLE001
                    _log(f"show_hub: descendant post-show move raised {exc!r}")
            # a62 (user-reported): the hub may have moved while the
            # cells were hidden, so a revealed cell's stored position
            # can now be off-screen.  Rescue each one onto a visible
            # screen before we clear the tracking list.
            self._rescue_cells_on_screen(shown_descendants)
            self._hidden_descendant_ids = []
            w.raise_()
            w.activateWindow()
        except Exception as exc:  # noqa: BLE001
            _log(f"show_hub: {exc!r}")

    def hide_hub(self) -> None:
        """Hide the forest hub AND every visible forest descendant.

        Behaviour depends on whether the hub carries ``Qt.Window``
        (taskbar mode):
          * Taskbar mode: ``showMinimized()`` so the taskbar entry
            stays visible.
          * Otherwise: ``hide()`` so the window is removed
            entirely (tray-only or always-on-top toggles).

        Tracks which descendants we hid so ``show_hub`` restores
        only those (user-collapsed cells stay collapsed).
        """
        w = self._forest_window
        if w is None:
            return
        try:
            self._hidden_descendant_ids = []
            for descendant in self._forest_descendants():
                try:
                    if descendant.isVisible():
                        descendant.hide()
                        cell_id = getattr(descendant, "_id", None)
                        if cell_id:
                            self._hidden_descendant_ids.append(cell_id)
                except Exception:  # noqa: BLE001
                    continue
            if self._taskbar_on:
                # Capture position before minimising so showNormal
                # can put it back exactly where the user had it.
                if w.isVisible() and not w.isMinimized():
                    self._last_hub_position = QPoint(w.pos())
                w.showMinimized()
            else:
                if w.isVisible():
                    self._last_hub_position = QPoint(w.pos())
                w.hide()
        except Exception as exc:  # noqa: BLE001
            _log(f"hide_hub: {exc!r}")

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
        self._hidden_descendant_ids = []
        for descendant in self._forest_descendants():
            try:
                if descendant.isVisible():
                    descendant.hide()
                    cell_id = getattr(descendant, "_id", None)
                    if cell_id:
                        self._hidden_descendant_ids.append(cell_id)
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
        if (
            fw is not None
            and obj is fw
            and event.type() == QEvent.Type.WindowStateChange
            and getattr(self, "_auto_hide", False)
            and getattr(self, "_taskbar_on", False)
        ):
            try:
                if not fw.isMinimized() and fw.isVisible():
                    # User restored us from the taskbar.  Reveal the
                    # descendants too.  Schedule on the next event-loop
                    # tick so the OS finishes processing the state
                    # change first.
                    QTimer.singleShot(0, self._restore_descendants)
            except Exception as exc:  # noqa: BLE001
                _log(f"eventFilter: taskbar restore raised {exc!r}")
        return super().eventFilter(obj, event)

    def _restore_descendants(self) -> None:
        """Helper used by the event filter to show only the
        descendants WE hid, without touching the hub (it's
        already restored by the user's click)."""
        # Suppress the watcher so the platform focus shuffle
        # during the cell shows doesn't queue a hide.
        try:
            self._watcher.suppress_for(200)
        except Exception:  # noqa: BLE001
            pass
        # a61: SHOW each tracked cell FIRST, then move it to the
        # user's current desktop.
        #
        # The hub is already on the user's current desktop (Windows
        # put it there when the user clicked the taskbar entry), but
        # the cells were last shown wherever the forest used to
        # live, so they need moving to land beside the hub.  Pre-a61
        # this called ``_ensure_descendants_on_current_desktop()``
        # BEFORE the show loop -- while the cells were still hidden.
        # ``MoveWindowToDesktop`` returns TYPE_E_ELEMENTNOTFOUND for
        # a hidden window (the exact failure a59 fixed for the hub
        # in ``show_hub``), so the move silently no-op'd and the
        # cells reappeared on the forest's OLD desktop instead of
        # beside the hub.  Mirror a59: show -> then move.
        shown: list[Any] = []
        for cell_id in self._hidden_descendant_ids:
            cell = self._registry.get(cell_id)
            if cell is None:
                continue
            try:
                cell.show()
                shown.append(cell)
            except Exception:  # noqa: BLE001
                continue
        self._hidden_descendant_ids = []
        # Now that they're visible, move the ones we just revealed to
        # the current desktop.  We move only ``shown`` (not the full
        # descendant walk) so we don't force-create native windows
        # for cells the user had deliberately collapsed/closed.
        if shown:
            try:
                from scriptree.shell import win_virtual_desktops as wvd
                if wvd.is_supported():
                    desktop_id = wvd.get_current_desktop_id()
                    if desktop_id is not None:
                        for cell in shown:
                            try:
                                wvd.move_window_to_desktop(
                                    int(cell.winId()), desktop_id,
                                )
                            except Exception:  # noqa: BLE001
                                continue
            except Exception as exc:  # noqa: BLE001
                _log(f"_restore_descendants: post-show move raised {exc!r}")
        # a62 (user-reported): rescue any revealed cell whose stored
        # position is now off-screen -- the hub may have moved while
        # the cells were hidden, leaving them stranded.
        self._rescue_cells_on_screen(shown)
        # Bring the hub itself to the foreground in case the
        # restore from taskbar didn't activate it properly.
        try:
            self._forest_window.raise_()
            self._forest_window.activateWindow()
        except Exception:  # noqa: BLE001
            pass

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
        self._always_on_top = on

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
        self._taskbar_on = on

    # ------------------------------------------------------------------
    # Internals -- tray
    # ------------------------------------------------------------------

    def _apply_tray(self, on: bool) -> None:
        """Spawn or tear down the system tray icon."""
        if on and self._tray_icon is None:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                _log(
                    "_apply_tray: system tray not available; "
                    "tray flag ignored"
                )
                return
            tray = ForestTrayIcon(
                on_activate=self.show_hub,
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

    # ------------------------------------------------------------------
    # Virtual-desktop follow-the-user (a55+)
    # ------------------------------------------------------------------

    def _ensure_hub_on_current_desktop(self) -> None:
        """Move the forest hub to the user's current virtual
        desktop if it isn't already there.

        Called from ``show_hub`` and ``_restore_descendants`` so
        any programmatic reveal (tray click, taskbar restore,
        external code) puts the hub on whichever desktop the
        user is actually looking at.  Without this, clicking the
        tray icon from desktop B yanks the user back to desktop
        A where the forest happens to live.

        Cheap on systems with one desktop -- the underlying
        ``ensure_on_current_desktop`` short-circuits to a single
        COM call when the window is already there.
        """
        try:
            from scriptree.shell import win_virtual_desktops as wvd
            if not wvd.is_supported():
                return
            hwnd = int(self._forest_window.winId())
            wvd.ensure_on_current_desktop(hwnd)
        except Exception as exc:  # noqa: BLE001
            _log(f"_ensure_hub_on_current_desktop: {exc!r}")

    def _ensure_descendants_on_current_desktop(self) -> None:
        """Move every visible forest descendant to the user's
        current desktop.

        Used when a show triggers descendant reveal -- without
        this, the hub would arrive on desktop B and the cells
        would be left behind on desktop A (where they were last
        shown).  The user then sees a hub with no cells around
        it on the current desktop.
        """
        try:
            from scriptree.shell import win_virtual_desktops as wvd
            if not wvd.is_supported():
                return
            for descendant in self._forest_descendants():
                try:
                    hwnd = int(descendant.winId())
                    wvd.ensure_on_current_desktop(hwnd)
                except Exception:  # noqa: BLE001
                    continue
        except Exception as exc:  # noqa: BLE001
            _log(f"_ensure_descendants_on_current_desktop: {exc!r}")

    def _follow_user_across_desktops(self) -> None:
        """Wire focus-changes -> move-forest-to-current-desktop.

        Called by the watcher on every focusWindowChanged event,
        regardless of auto-hide state -- the user wants the forest
        reachable on every desktop whether or not auto-hide is on.

        The heavy lifting is in ``ensure_on_current_desktop``,
        which is idempotent.  The CHECK (is_window_on_current
        desktop) is a single COM call; the MOVE only fires when
        the hub is actually on a different desktop.  So the cost
        on the common (single-desktop) case is one COM call per
        focus event -- negligible.
        """
        try:
            from scriptree.shell import win_virtual_desktops as wvd
            if not wvd.is_supported():
                return
            if self._forest_window is None:
                return
            # Only follow when the hub HAS a native handle (i.e.
            # has been shown at least once).  Calling winId on an
            # un-shown widget forces window creation, which we
            # don't want here.
            if not self._forest_window.testAttribute(
                Qt.WidgetAttribute.WA_WState_Created
            ):
                return
            hwnd = int(self._forest_window.winId())
            if wvd.is_window_on_current_desktop(hwnd):
                return
            # Hub is on a different desktop -- the user switched.
            # Move the hub AND every currently-visible descendant.
            desktop_id = wvd.get_current_desktop_id()
            if desktop_id is None:
                return
            wvd.move_window_to_desktop(hwnd, desktop_id)
            for descendant in self._forest_descendants():
                try:
                    if descendant.isVisible():
                        d_hwnd = int(descendant.winId())
                        wvd.move_window_to_desktop(d_hwnd, desktop_id)
                except Exception:  # noqa: BLE001
                    continue
        except Exception as exc:  # noqa: BLE001
            _log(f"_follow_user_across_desktops: {exc!r}")

    # ------------------------------------------------------------------
    # Descendant walk
    # ------------------------------------------------------------------

    def _forest_descendants(self) -> list[Any]:
        """Return the flat list of every CellWindow that belongs
        to the forest hub.

        Walks the hub's ``_members`` (direct forest members --
        rings + standalone forest items), then for each member
        that's a master walks ITS ``_members`` recursively.
        """
        w = self._forest_window
        if w is None:
            return []
        out: list[Any] = []
        seen: set[str] = set()

        def _walk(parent: Any) -> None:
            members = getattr(parent, "_members", None) or {}
            for member_id in list(members):
                if member_id in seen:
                    continue
                seen.add(member_id)
                cell = self._registry.get(member_id)
                if cell is None:
                    continue
                out.append(cell)
                if getattr(cell, "role", None) == "master":
                    _walk(cell)

        try:
            _walk(w)
        except Exception as exc:  # noqa: BLE001
            _log(f"_forest_descendants: walk raised {exc!r}")
        return out
