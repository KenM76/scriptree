---
topic: v3-architecture
date: 2026-05-23
status: bug
related: [link_dock_graph_split]
---
# Freshly-spawned masters must be wired to the snap engine via `_wire_hex_to_snap`

## What happened

Bug 2 (v0.8.0a1): dragging a freshly-spawned ring (just formed via
Case 1 in `_try_spawn_master`) fired `snap_engine.attach_drag`
correctly but no snap preview overlay appeared during the drag. The
ring docked at whatever pixel the user released at — no snap.

## Root cause

`_try_spawn_master` (the dynamic-spawn path that fires when two
cells dock) created the master CellWindow, called `master.show()`,
and returned. The snap engine has a per-cell wiring step
`_wire_hex_to_snap(master)` that connects `snap_engine.snapPreview`
emissions to the master's preview-rendering slot. Without that step,
the snap engine fires the signal but no listener is connected for
this master's id — preview never renders, even though the engine is
otherwise computing the snap correctly.

`ring_io.load_ring` already calls `_wire_hex_to_snap` on every
loaded master. `forest_controller` does the same on forest spawn.
Only the runtime dynamic-spawn path was missing the call.

## Fix

In `_try_spawn_master` after `master.show()`:

```python
master.show()
ring_main._wire_hex_to_snap(master)   # <-- this was missing
```

(`ring_main` here is the module containing the wiring helper; same
helper used by `ring_io.load_ring` and `forest_controller`.)

## How future-me detects it

* Symptom: a master can be dragged but no snap preview overlay
  appears, only on freshly-spawned masters — load-from-file and
  forest masters work fine. Compare the spawn path against
  `ring_io.load_ring` and look for the missing call.
* In dev: add a print at `snap_engine.snapPreview.emit` (or trace
  via `layout_trace`) — the signal IS firing, no listener is
  attached. That narrows it to a wiring issue, not engine logic.
* Same trap will return any time a new code path creates a master
  imperatively (e.g. a "spawn ring with these N cells" command).
  Always pair `master.show()` with `_wire_hex_to_snap(master)` at
  every spawn site.
