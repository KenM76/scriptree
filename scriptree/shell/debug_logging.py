"""
debug_logging.py — runtime-toggleable stderr-to-file logging for
diagnostics.

## For humans

When a user reports a tricky bug (the v0.8.0a55+ virtual-desktop
follow-the-user logic is the motivating case), the first thing
needed for diagnosis is the program's actual stderr output -- the
``[win_virtual_desktops:debug]`` lines, exception tracebacks,
warning messages.  ScripTree's launchers don't pipe stderr to a
file by default because the typical end user has no use for them.

This module gives the user (or a developer in their place) a way
to turn that capture on without editing batch files or knowing
env vars:

  * Forest right-click -> Forest -> Debug -> Enable verbose logging
  * Tray icon right-click -> Enable verbose logging

The toggle:
  * Tees ``sys.stderr`` to a file under
    ``%APPDATA%/ScripTree/logs/scriptree-debug-YYYY-MM-DD.log``.
    The original stderr (console) is untouched -- output goes BOTH
    places, so a developer watching the console still sees
    everything, and the user has the file to email.
  * Flips ``is_enabled()`` so other modules (notably
    ``win_virtual_desktops``) start emitting their verbose
    ``_dlog`` lines.
  * Persists in ``QSettings`` so the choice survives a restart --
    the user can flip it on, restart, reproduce the bug, and grab
    the log.

The "Open debug folder" action just runs ``explorer.exe`` on the
logs directory so the user can grab the latest log to send.

## For maintainers / LLMs

- Module is import-safe everywhere; nothing it does has side
  effects until ``set_enabled(True)`` is called.
- ``_TeeStream`` wraps the original ``sys.stderr`` and the log
  file -- writes go to both, exceptions on either side are
  swallowed (the priority is "don't break the app if logging
  fails").
- ``set_enabled(False)`` cleanly restores the original stderr and
  closes the file handle.  Idempotent both ways.
- Log files are append-mode -- multiple ScripTree launches on the
  same calendar day share one file.  Each run writes a header
  banner so it's easy to find where the latest run starts.
- QSettings key: ``debug/verbose_logging_enabled``.  Loaded by
  the launcher (``ForestController.start``) so the toggle takes
  effect on next launch as well as immediately.
"""
from __future__ import annotations

import datetime
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


_log_file_handle: Any = None
_enabled: bool = False
_original_stderr: Any = sys.stderr


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def get_log_dir() -> Path:
    """Return the directory where debug log files live.

    ``%APPDATA%/ScripTree/logs`` on Windows, ``~/.scriptree/logs``
    elsewhere -- the location was chosen to live next to
    ``forest_preferences.json`` (same directory) so the user can
    grab both files if needed.

    Creates the directory if missing.
    """
    appdata = os.environ.get("APPDATA")
    if appdata:
        root = Path(appdata) / "ScripTree"
    else:
        root = Path.home() / ".scriptree"
    p = root / "logs"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        # If we can't create the dir, return it anyway -- the
        # caller's open() will fail with a clear message rather
        # than silently logging to nowhere.
        pass
    return p


def get_current_log_path() -> Path:
    """Today's log file path.

    One file per calendar day so a long-running ScripTree session
    spanning midnight rolls over at the obvious cut.
    """
    today = datetime.date.today().isoformat()
    return get_log_dir() / f"scriptree-debug-{today}.log"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    """Is the debug tee currently active?"""
    return _enabled


def set_enabled(on: bool) -> bool:
    """Enable or disable verbose stderr capture.

    Returns the actual new state -- False if enabling failed (e.g.
    couldn't open the log file).  The user-facing menu code should
    check this so the checkable action's UI matches reality.

    Idempotent: calling with the current state is a no-op.
    """
    global _enabled, _log_file_handle
    if bool(on) == _enabled:
        return _enabled
    if on:
        try:
            log_path = get_current_log_path()
            f = open(log_path, "a", encoding="utf-8", buffering=1)
            now = datetime.datetime.now().isoformat(sep=" ", timespec="seconds")
            f.write(
                f"\n=== ScripTree debug logging enabled at {now} ===\n"
            )
            f.flush()
            _log_file_handle = f
            sys.stderr = _TeeStream(_original_stderr, f)
            _enabled = True
        except Exception as exc:  # noqa: BLE001
            print(
                f"[debug_logging] failed to enable: {exc!r}",
                file=_original_stderr,
            )
            _enabled = False
    else:
        # Disable: restore original stderr, close the file.  Tee
        # any final goodbye message into the file before closing.
        if _log_file_handle is not None:
            try:
                now = datetime.datetime.now().isoformat(
                    sep=" ", timespec="seconds",
                )
                _log_file_handle.write(
                    f"=== Disabled at {now} ===\n\n"
                )
                _log_file_handle.flush()
                _log_file_handle.close()
            except Exception:  # noqa: BLE001
                pass
            _log_file_handle = None
        sys.stderr = _original_stderr
        _enabled = False
    return _enabled


def open_log_folder() -> bool:
    """Open the logs folder in the platform's file manager.

    Returns True on success.  Used by the "Open debug folder"
    menu action.
    """
    folder = get_log_dir()
    try:
        if sys.platform == "win32":
            # ``explorer.exe`` is the canonical way to pop a folder
            # window on Windows; ``os.startfile`` would also work
            # but explorer is explicit and avoids any default-app
            # confusion (some users have a different file manager
            # registered as the folder handler).
            subprocess.Popen(["explorer.exe", str(folder)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
        return True
    except Exception as exc:  # noqa: BLE001
        print(
            f"[debug_logging] open_log_folder failed: {exc!r}",
            file=_original_stderr,
        )
        return False


# ---------------------------------------------------------------------------
# QSettings persistence
# ---------------------------------------------------------------------------

_QSETTINGS_KEY = "debug/verbose_logging_enabled"


def load_persisted_state() -> bool:
    """Read the persisted toggle from QSettings.

    Called by ``ForestController.start`` so the choice survives a
    restart.  Defaults to False if there's no value or QSettings
    isn't usable.
    """
    try:
        from PySide6.QtCore import QSettings
        s = QSettings()
        raw = s.value(_QSETTINGS_KEY, False)
        # QSettings returns strings on Windows for bool values that
        # were never explicitly set; normalise.
        if isinstance(raw, str):
            return raw.lower() in ("true", "1", "yes", "on")
        return bool(raw)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[debug_logging] load_persisted_state: {exc!r}",
            file=_original_stderr,
        )
        return False


def save_persisted_state(on: bool) -> None:
    """Write the toggle state to QSettings."""
    try:
        from PySide6.QtCore import QSettings
        s = QSettings()
        s.setValue(_QSETTINGS_KEY, bool(on))
        s.sync()
    except Exception as exc:  # noqa: BLE001
        print(
            f"[debug_logging] save_persisted_state: {exc!r}",
            file=_original_stderr,
        )


def set_enabled_and_persist(on: bool) -> bool:
    """One-shot helper used by the menu actions: flip the runtime
    state and save the choice for next launch.  Returns the
    actual new state (which may differ from ``on`` if enabling
    failed)."""
    new_state = set_enabled(on)
    save_persisted_state(new_state)
    return new_state


# ---------------------------------------------------------------------------
# Tee stream
# ---------------------------------------------------------------------------

class _TeeStream:
    """Forward ``write`` and ``flush`` to both an original stream
    and a log file.

    Failures on either side are swallowed -- the original stream
    losing writes would be invisible (it's stderr), but if we
    raised here we'd kill whatever code emitted the log line.
    """

    def __init__(self, original: Any, log_file: Any) -> None:
        self._original = original
        self._file = log_file

    def write(self, s: str) -> int:
        try:
            self._original.write(s)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._file.write(s)
        except Exception:  # noqa: BLE001
            pass
        return len(s)

    def flush(self) -> None:
        try:
            self._original.flush()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._file.flush()
        except Exception:  # noqa: BLE001
            pass

    def __getattr__(self, name: str) -> Any:
        # Delegate any other attribute access (isatty, encoding,
        # etc.) to the original stream.  Some libraries probe these
        # to decide whether to colourise output etc.
        return getattr(self._original, name)
