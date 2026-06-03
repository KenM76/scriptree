---
topic: pyside6
date: 2026-06-03
status: recipe
related: [hover_tooltip_screen_clamp]
---
# Debounce Qt screen-change signals with a single timer stored on QApplication

## What happened

When a monitor was plugged or unplugged (or a resolution change
fired), the off-screen "rescue all cells" pass ran 5+ times in a
row in a tight burst. Each plug event made Qt fan out a storm of
related signals: `screenAdded`, `primaryScreenChanged`, plus per-
screen `geometryChanged` and `availableGeometryChanged`. Doing the
rescue work on every fire was visibly janky and racey (cells got
clamped, then re-clamped against a still-changing geometry).

## Root cause

Two things compounded:

1. Qt emits a *cluster* of overlapping signals for any single
   physical screen-topology change. There is no consolidated
   "topology settled" signal — you have to debounce.
2. A naive "create a single-shot QTimer in the signal handler" does
   NOT debounce: each fire makes a fresh local timer object, all of
   which fire 200 ms later in parallel. The timer has to live in a
   shared place that the handler can find and re-stop on each fire.

The chosen home is the QApplication instance itself
(`app._screen_rescue_timer`). It outlives any individual signal
fire and is the natural process-singleton that all signal handlers
can reach.

## Fix / recipe

New module `D:\Dev\ScripTree\scriptree\shell\screen_watcher.py` (~180
lines). Public entry point `screen_watcher.install(app)`:

```python
def install(app: QGuiApplication) -> None:
    app._screen_rescue_timer = QTimer(app)
    app._screen_rescue_timer.setSingleShot(True)
    app._screen_rescue_timer.setInterval(200)  # ms
    app._screen_rescue_timer.timeout.connect(lambda: rescue_all_cells(app))

    def _schedule_rescue(*_args, **_kw):
        app._screen_rescue_timer.start()  # restarts if already running

    app.screenAdded.connect(_schedule_rescue)
    app.screenRemoved.connect(_schedule_rescue)
    app.primaryScreenChanged.connect(_schedule_rescue)
    for scr in app.screens():
        scr.geometryChanged.connect(_schedule_rescue)
        scr.availableGeometryChanged.connect(_schedule_rescue)

    # Screens added AFTER install need their per-screen signals
    # hooked too — re-hook in the screenAdded handler:
    def _hook_new_screen(scr):
        scr.geometryChanged.connect(_schedule_rescue)
        scr.availableGeometryChanged.connect(_schedule_rescue)
        _schedule_rescue()
    app.screenAdded.connect(_hook_new_screen)
```

Install it once at startup, near the layout-trace init block in
`D:\Dev\ScripTree\scriptree\shell\ring_main.py` (~line 414):

```python
from scriptree.shell import screen_watcher
screen_watcher.install(app)
```

The rescue itself walks `CellRegistry.instance().all()` and reuses
each cell's `CellWindow._clamp_to_screen(pos)` — so the on-topology-
change behaviour matches the existing drag-end clamp behaviour
exactly. No new geometry policy invented.

The same `rescue_all_cells` function is also wired as a *manual*
Forest right-click action: `forest_controller._populate_forest_menu`
adds a "Bring all cells back on-screen" entry whose slot is
`forest_controller._on_rescue_offscreen` → `screen_watcher.rescue_all_cells`.

## How future-me detects it

* Symptom: any "do thing on screen-change" handler that fires many
  times in a row when you plug or unplug a monitor. The fix shape is
  always the same — one QTimer on the QApplication, single-shot, ~200 ms.
* Same pattern applies to *any* Qt signal cluster (dock changes, app
  state changes, palette changes…) where Qt emits a storm and you
  want one settled callback. Don't make per-fire local timers; one
  shared timer on a process-singleton object.
* If new screens added later don't trigger the rescue, you forgot to
  hook their per-screen `geometryChanged` / `availableGeometryChanged`
  in the `screenAdded` closure.
