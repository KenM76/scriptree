"""
forest_visibility.py — three-mode visibility for the forest hub.

## For humans

The forest hub historically had ONE way to reach it: it floated above
the desktop as a frameless, always-on-top hex (``Qt.Tool`` +
``Qt.WindowStaysOnTopHint``).  v0.8.0a52 introduces two additional
surfaces so the user can pick whichever fits how they actually use
ScripTree:

  1. **Always-on-top over the desktop** (factory default, the
     pre-a52 behaviour).  The hub floats above every other app.
  2. **Show on taskbar** (PortableApps-style).  A persistent
     Windows taskbar entry titled "ScripTree Forest".  Click →
     forest hub appears at its saved position.  The entry survives
     the hub being hidden.
  3. **Show in system tray** (PortableApps-style).  A tray icon
     with the forest glyph.  Left-click → forest hub appears.
     Right-click → small menu (Show / Quit).

At least one of the three MUST be enabled — the UI refuses to
uncheck the last one, and the persisted preferences are repaired
on load if a hand-edited file ended up with all three False (see
``ForestPreferences.normalised`` in ``forest_io.py``).

When ``show_always_on_top`` is OFF the forest hub starts HIDDEN.
The user reveals it by clicking the taskbar entry or the tray
icon.  Once visible, it AUTO-HIDES on:

  * A tool launch (any spawned tool runner / standalone editor
    pulls focus away from the forest hierarchy).
  * The user clicking outside the forest hierarchy (any
    top-level window that isn't the forest hub itself OR a
    ``CellWindow`` registered in ``CellRegistry``).

The auto-hide rule fires only when always-on-top is OFF.  When
always-on-top is ON, focus loss is irrelevant — the hub stays
visible.

## For maintainers / LLMs

- ``ForestVisibilityManager.apply(prefs)`` is the single entry
  point for the controller.  It:
    1. Sets the hub's window flags to match
       ``show_always_on_top`` + ``show_on_taskbar``.
    2. Spawns / tears down ``ForestTaskbarHost`` per
       ``show_on_taskbar``.
    3. Spawns / tears down ``ForestTrayIcon`` per
       ``show_in_system_tray``.
    4. Hooks / unhooks the focus-watch when always-on-top
       changes.
- The flag swap on the hub uses ``Qt.Tool`` ↔ ``Qt.Window`` for
  taskbar visibility.  Qt requires ``hide() + setWindowFlags() +
  show()`` to take effect on Win11; we follow the cell_window
  pattern in ``_apply_always_on_top_flag``.  Position is restored
  after the re-show.
- ``ForestTaskbarHost`` is a tiny ``QMainWindow`` with a 1×1
  central widget.  We *minimise* it on first show so it sits in
  the taskbar without taking screen space; ``changeEvent`` then
  intercepts user "restore" clicks to instead reveal the real
  forest hub and re-minimise ourselves.  Closing the host quits
  the app (parity with PortableApps where dismissing the taskbar
  entry terminates the menu).
- ``ForestTrayIcon`` uses the bundled forest PNG (lifted from
  ``icon_assets.bundled_icon_b64('forest')``).  Activation reasons
  ``Trigger`` (single-click) and ``DoubleClick`` both reveal the
  hub; ``Context`` is handled by Qt's built-in menu mechanism.
- ``_FocusWatcher`` wraps ``QApplication.focusWindowChanged``.
  We compare the new focus QWindow to the QWindow of every
  registered ``CellWindow`` plus the forest hub itself.  When the
  new focus is None OR belongs to anything else, we hide the hub
  (only when always-on-top is OFF).
- Auto-hide is debounced by 80ms to avoid flicker when focus
  bounces between the hub and a transient popup or settings
  dialog during the same user action.

Public API
----------
    ForestVisibilityManager(forest_window, registry, quit_callback=None)
        .apply(prefs: ForestPreferences) → None
        .show_hub() → None
        .hide_hub() → None
        .teardown() → None
"""
from __future__ import annotations

import sys
from typing import Any, Callable

from PySide6.QtCore import (
    QObject, QPoint, QTimer, Qt,
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
    """Resolve the forest glyph for the taskbar host + tray icon.

    Prefers the bundled ``forest`` icon (the fractal-tree glyph
    introduced in v0.8.0a4+) and falls back to a Qt-standard
    desktop icon if the asset is missing (e.g. on a dev tree
    where ``icons/forest.png`` hasn't been generated yet).
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
    # Fallback: build a 1×1 transparent pixmap so the tray API
    # has something concrete; better than QIcon() (which some
    # Windows builds reject and refuse to show in the tray).
    pm = QPixmap(16, 16)
    pm.fill(Qt.transparent)
    return QIcon(pm)


# ---------------------------------------------------------------------------
# ForestTaskbarHost
# ---------------------------------------------------------------------------

class ForestTaskbarHost(QMainWindow):
    """A persistent Windows taskbar entry for the forest.

    The host is a tiny ``QMainWindow`` (no central content) shown
    minimised so the taskbar displays its title + icon but it
    never appears on the desktop itself.  Clicking the taskbar
    entry asks Windows to restore the host -- we intercept the
    state-change, hide ourselves back into the taskbar, and
    instead reveal the real forest hub.

    Closing the host via the (hidden but reachable via right-click
    taskbar) Close menu calls ``quit_callback`` so dismissing the
    taskbar entry terminates ScripTree.
    """

    def __init__(
        self,
        on_activate: Callable[[], None],
        on_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            None,
            Qt.Window | Qt.MSWindowsFixedSizeDialogHint,
        )
        self._on_activate = on_activate
        self._on_close = on_close
        self.setWindowTitle("ScripTree Forest")
        self.setWindowIcon(_forest_icon())
        # Resize to ridiculously small -- the host should never
        # be visible on the desktop, only in the taskbar.  We
        # ALSO move it off-screen as a belt-and-suspenders against
        # platforms (or future Qt versions) that briefly show the
        # window before our showMinimized() takes effect.
        self.resize(1, 1)
        self.move(-32000, -32000)
        # A 1x1 widget as central so QMainWindow doesn't paint
        # the default greyish backdrop.
        central = QWidget(self)
        central.setFixedSize(1, 1)
        self.setCentralWidget(central)

    def show_in_taskbar(self) -> None:
        """Make the host visible in the taskbar without showing
        it on the desktop.  Idempotent -- safe to call repeatedly
        when the manager reapplies preferences."""
        self.showMinimized()

    def changeEvent(self, event: Any) -> None:  # noqa: D401, ANN001
        """Intercept user clicks on the taskbar entry.

        When Windows tells us we've been restored (the user
        clicked the taskbar entry), we re-minimise ourselves so
        the host never paints on screen, and we call
        ``on_activate`` to reveal the real forest hub.
        """
        from PySide6.QtCore import QEvent
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            if not self.isMinimized() and self.isVisible():
                # User restored us -- bounce back to minimised
                # and reveal the hub instead.  Schedule via
                # singleShot so Qt finishes processing the state
                # change before we mess with it again.
                QTimer.singleShot(0, self.showMinimized)
                try:
                    self._on_activate()
                except Exception as exc:  # noqa: BLE001
                    _log(f"taskbar host: on_activate raised {exc!r}")

    def closeEvent(self, event: Any) -> None:  # noqa: D401, ANN001
        """Closing the taskbar entry quits ScripTree.

        Matches the PortableApps convention: dismissing the
        persistent entry terminates the launcher.
        """
        if self._on_close is not None:
            try:
                self._on_close()
            except Exception as exc:  # noqa: BLE001
                _log(f"taskbar host: on_close raised {exc!r}")
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# ForestTrayIcon
# ---------------------------------------------------------------------------

class ForestTrayIcon(QSystemTrayIcon):
    """System tray icon with Show / Quit menu.

    Left-click → ``on_activate``.  Right-click → menu offering
    Show (same as left-click) and Quit (terminates the app).
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
        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Trigger == single-click; DoubleClick == double-click.
        # Both should reveal the hub.  Context is handled by the
        # menu mechanism Qt sets up via setContextMenu.
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
    hierarchy.

    Active only when ``show_always_on_top`` is False.  Wraps
    ``QApplication.focusWindowChanged`` and debounces by 80ms
    to avoid flicker when focus bounces through a transient
    popup or modal dialog.
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
        app = QApplication.instance()
        if app is not None:
            app.focusWindowChanged.connect(self._on_focus_changed)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if not self._enabled:
            self._debounce.stop()

    def _on_focus_changed(self, _new_window: Any) -> None:
        if not self._enabled:
            return
        # Debounce -- focus often flickers between widgets during
        # a single user click, especially when modal dialogs or
        # popups open.  80ms is enough to coalesce the transients
        # without making the hide feel laggy.
        self._debounce.start()

    def _fire(self) -> None:
        if not self._enabled:
            return
        app = QApplication.instance()
        if app is None:
            return
        # Active window at the moment the timer fires -- this is
        # what the user is currently looking at, not whatever was
        # transiently focused mid-click.
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
        standalone -- per the strict-scope rule, only cells count
        as 'inside the forest').

        ``widget`` of None means "no app window has focus" --
        treated as outside.
        """
        if widget is None:
            return False
        if widget is self._forest_window:
            return True
        # Walk up to the top-level (popups, settings dialogs,
        # transient menus all live UNDER one of these as their
        # parent / window owner).
        try:
            top = widget.window()
        except Exception:  # noqa: BLE001
            top = widget
        if top is self._forest_window:
            return True
        # Settings dialogs of the forest hub itself parent to
        # forest_window -- catch them via the window() walk above.
        # CellWindows are top-level so the comparison is direct.
        try:
            from scriptree.shell.cell_window import CellWindow
            if isinstance(top, CellWindow):
                return True
        except Exception:  # noqa: BLE001
            pass
        # The forest hub's modal dialogs (settings, excluded
        # items, first-run welcome, diff dialog, uninstall dialog)
        # are parented to forest_window -- their window() is the
        # dialog itself; walk parents until we hit forest_window
        # or run out.
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
    Internal state is fully derived from ``prefs`` -- the manager
    spawns and tears down the taskbar host / tray icon as needed.
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
        self._taskbar_host: ForestTaskbarHost | None = None
        self._tray_icon: ForestTrayIcon | None = None
        self._watcher = _FocusWatcher(
            forest_window, registry, self.hide_hub,
        )
        # Track the current always-on-top state so we know what to
        # restore the hub to when the user toggles flags live.
        self._always_on_top: bool = True
        # Saved position of the hub so hide()/show() round-trips
        # don't lose placement.
        self._last_hub_position: QPoint | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply(self, prefs: Any) -> None:
        """Re-derive everything from the prefs object.

        ``prefs`` is a ``ForestPreferences`` (we duck-type the
        three flags we need so the import stays local to the
        caller).  Idempotent: calling twice with the same prefs
        is a no-op.
        """
        prefs = prefs.normalised()
        aot = bool(prefs.show_always_on_top)
        tb = bool(prefs.show_on_taskbar)
        tr = bool(prefs.show_in_system_tray)

        self._apply_always_on_top(aot)
        self._apply_taskbar(tb)
        self._apply_tray(tr)

        # Auto-hide is active only when always-on-top is off AND
        # the user has at least one other entry point (otherwise
        # hiding the hub strands the user, which the normalised()
        # invariant prevents but defence-in-depth here is cheap).
        auto_hide = (not aot) and (tb or tr)
        self._watcher.set_enabled(auto_hide)

        # When always-on-top flips OFF and we have a tray/taskbar
        # entry point, the hub should START hidden on subsequent
        # calls.  But the FIRST apply() (during start()) is run
        # before the hub has been shown, so the hub naturally
        # stays hidden if the controller skips show().  Live flag
        # changes after the hub is on-screen: hide it now so the
        # user sees the rule kick in immediately.
        if auto_hide and self._forest_window is not None:
            try:
                if self._forest_window.isVisible():
                    self.hide_hub()
            except Exception as exc:  # noqa: BLE001
                _log(f"apply: hide_hub after flag flip raised {exc!r}")

    def show_hub(self) -> None:
        """Bring the forest hub to the front.

        Used by the taskbar host and tray icon when the user
        clicks them, and by any external code that wants to
        guarantee the hub is visible (e.g. drop-on-tray scenarios
        the controller may add later).
        """
        w = self._forest_window
        if w is None:
            return
        try:
            if self._last_hub_position is not None and not w.isVisible():
                w.move(self._last_hub_position)
            w.show()
            w.raise_()
            w.activateWindow()
        except Exception as exc:  # noqa: BLE001
            _log(f"show_hub: {exc!r}")

    def hide_hub(self) -> None:
        """Hide the forest hub.

        Captures the current position so a later ``show_hub``
        restores it exactly where the user last placed it.  Safe
        to call when already hidden.
        """
        w = self._forest_window
        if w is None:
            return
        try:
            if w.isVisible():
                self._last_hub_position = QPoint(w.pos())
            w.hide()
        except Exception as exc:  # noqa: BLE001
            _log(f"hide_hub: {exc!r}")

    def teardown(self) -> None:
        """Release the taskbar host and tray icon.

        Called at app shutdown so Qt doesn't grumble about a tray
        icon outliving its QApplication.
        """
        if self._tray_icon is not None:
            try:
                self._tray_icon.hide()
            except Exception:  # noqa: BLE001
                pass
            self._tray_icon = None
        if self._taskbar_host is not None:
            try:
                self._taskbar_host.close()
            except Exception:  # noqa: BLE001
                pass
            self._taskbar_host = None
        self._watcher.set_enabled(False)

    # ------------------------------------------------------------------
    # Internals -- always-on-top
    # ------------------------------------------------------------------

    def _apply_always_on_top(self, on: bool) -> None:
        """Toggle ``WindowStaysOnTopHint`` AND swap ``Qt.Tool``
        with ``Qt.Window`` on the hub so the flag combination is
        coherent.

        Note: the ``Qt.Tool`` ↔ ``Qt.Window`` swap is gated by
        ``show_on_taskbar`` since ``Qt.Tool`` excludes the window
        from the taskbar.  ``_apply_taskbar`` handles that flag;
        here we only touch always-on-top.
        """
        w = self._forest_window
        if w is None:
            return
        # Use the existing helper on CellWindow so the hide/show
        # ritual stays consistent with the cell-settings path.
        try:
            w._apply_always_on_top_flag(on)
        except Exception as exc:  # noqa: BLE001
            _log(f"_apply_always_on_top: helper raised {exc!r}")
        self._always_on_top = on

    # ------------------------------------------------------------------
    # Internals -- taskbar
    # ------------------------------------------------------------------

    def _apply_taskbar(self, on: bool) -> None:
        """Spawn or tear down the taskbar host.

        Also swaps the hub's ``Qt.Tool`` ↔ ``Qt.Window`` flag --
        with ``Qt.Tool`` the hub itself isn't on the taskbar (the
        host is the entry); with ``Qt.Window`` the hub IS on the
        taskbar AND the host would be redundant.

        We always use the host approach: the host is the
        persistent entry, the hub keeps ``Qt.Tool`` (frameless +
        hex-shape friendly).  This means the hub's window flags
        don't depend on this setting at all -- only the host's
        presence / absence does.
        """
        if on and self._taskbar_host is None:
            host = ForestTaskbarHost(
                on_activate=self.show_hub,
                on_close=self._quit_callback,
            )
            host.show_in_taskbar()
            self._taskbar_host = host
        elif not on and self._taskbar_host is not None:
            try:
                self._taskbar_host.close()
            except Exception:  # noqa: BLE001
                pass
            self._taskbar_host = None

    # ------------------------------------------------------------------
    # Internals -- tray
    # ------------------------------------------------------------------

    def _apply_tray(self, on: bool) -> None:
        """Spawn or tear down the system tray icon."""
        if on and self._tray_icon is None:
            # Some environments report system tray unavailable
            # (server VMs, certain WSL setups).  Bail gracefully
            # if so -- the user's other entry points still work.
            if not QSystemTrayIcon.isSystemTrayAvailable():
                _log(
                    "_apply_tray: system tray not available on this "
                    "platform; tray flag ignored"
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
