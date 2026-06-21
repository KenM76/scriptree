---
topic: virtual_desktop_follow_debounce
date: 2026-06-21
status: gotcha
related: [cell_positioning_central_tracker, hub_onscreen_clamp_programmatic,
          show_before_move_desktop_api, minimised_hub_virtual_desktop_follow]
---
# Virtual-desktop follow must be debounced and skip while the hub is being dragged (a70)

## What happened (user-reported)

The prime "forest disappeared, cells left behind" failure mode: the user
drags the hub or switches focus rapidly, and a burst of `focusWindowChanged`
events fires the `_follow_user_across_desktops` COM call once per event.
Multiple rapid `MoveWindowToDesktop` calls during focus churn created race
conditions where the hub ended up on an unexpected desktop while the member
cells (moved by a separate descendant loop) lagged behind or were skipped
entirely. The user would switch to desktop B, the hub would follow, but cells
stayed on desktop A — or the hub would overshoot to desktop C.

A second failure mode: the user is mid-drag on the hub when a focus-change
fires. The drag generates its own focus churn. A `MoveWindowToDesktop` call
mid-drag moves the native window to a different virtual desktop while the Qt
drag loop is still running, which can cause the hub to vanish from under the
cursor.

## Root cause

`_FocusWatcher._on_focus_changed` called
`_follow_user_across_desktops` synchronously on every `focusWindowChanged`
signal. A rapid sequence of focus changes (application switching, drag start,
modal dialogs opening) produced one COM round-trip per event — each one a
race opportunity.

The drag-guard was also missing: nothing prevented a virtual-desktop move
while `CellWindow._drag_started` was True.

## Fix / recipe (a70)

### 1 — Debounce the follow via a dedicated 120 ms QTimer

```python
# _FocusWatcher.__init__:
self._follow_debounce = QTimer(self)
self._follow_debounce.setSingleShot(True)
self._follow_debounce.setInterval(120)
self._follow_debounce.timeout.connect(self._fire_follow)
```

`_on_focus_changed` starts (or restarts) the timer instead of calling
`_follow_user_across_desktops` directly:

```python
def _on_focus_changed(self, _new_window):
    if self._on_focus_changed_for_follow is not None:
        self._follow_debounce.start()   # <-- debounce restart
    if not self._enabled or self._suppressed:
        return
    self._debounce.start()
```

`_fire_follow` fires ~120 ms after the LAST focus change in the burst, so
a single COM move replaces N:

```python
def _fire_follow(self):
    if self._on_focus_changed_for_follow is None:
        return
    try:
        self._on_focus_changed_for_follow()
    except Exception as exc:
        _log(f"_fire_follow: {exc!r}")
```

The 120 ms interval is enough to absorb the platform focus shuffle that
accompanies modal-dialog open/close without being noticeable as a delay
when the user genuinely switches desktops.

Implementation: `scriptree/shell/forest_visibility.py` — `_FocusWatcher`
class, `_follow_debounce` QTimer (~line 326), `_on_focus_changed` (~line
353), `_fire_follow` (~line 365).

### 2 — Skip while the hub is being dragged

In `_follow_user_across_desktops`, guard against mid-drag calls:

```python
# a70: never move the hub across desktops while the user is
# actively dragging it.  A drag generates focus churn, and a
# mid-drag cross-desktop move is the most likely way the hub
# "disappears" out from under the user.
if getattr(self._forest_window, "_drag_started", False):
    return
```

`CellWindow._drag_started` is set True in `mousePressEvent` and cleared
in `mouseReleaseEvent`. The `getattr` with default False is safe even if
the attribute is missing (e.g. on teardown).

Implementation: `scriptree/shell/forest_visibility.py` —
`_follow_user_across_desktops` (~line 1089).

### 3 — Verify-and-log after the move

After the COM `MoveWindowToDesktop` call, the code re-checks
`is_window_on_current_desktop` and logs if the move did not land:

```python
if not wvd.is_window_on_current_desktop(hwnd):
    _log(
        "_follow_user_across_desktops: hub move did NOT land "
        "on the current desktop (possible COM race) -- hub may "
        "be stranded; capture the [win_virtual_desktops:debug] "
        "HRESULT line"
    )
```

Implementation: `scriptree/shell/forest_visibility.py` —
`_follow_user_across_desktops` (~line 1109).

## The separate auto-hide debounce

`_FocusWatcher._debounce` (80 ms, `_fire`) is the EXISTING auto-hide timer
and is independent of `_follow_debounce`. The two timers run in parallel.
`_follow_debounce` fires regardless of `_enabled` (auto-hide can be off
while follow-the-user is always on).

## How future-me detects it

Symptom: hub follows user across desktops but cells are left behind on the
old desktop (COM race in the descendant loop); OR hub "disappears" mid-drag
(MoveWindowToDesktop called while drag was active). Look for
`_follow_user_across_desktops: hub move did NOT land` in the debug log
(`[win_virtual_desktops:debug]` entries carry the HRESULT).

If the 120 ms debounce proves too long (noticeable lag on desktop switch),
the interval is `_follow_debounce.setInterval(120)` in
`forest_visibility.py:328`. The auto-hide debounce is the separate
`_debounce.setInterval(80)`.
