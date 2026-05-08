---
topic: v3-architecture
date: 2026-05-08
status: feature
related: [cell_window, cell_metadata, v1_launcher, permissions]
---
# Cell click-to-run mode (v0.3.5)

## What happened / rule

User feature request: "Let's make it so the cells have a setting
option to be a single click button that runs the scriptree it is
attached to, or runs the scriptrees in order or option in parallel
if they are a scriptreetree."

v0.3.5 adds two new fields to the catalog `cell` sub-object plus
a new permission gate:

* ``cell.click_action`` — ``"menu"`` (default, pre-v0.3.5
  behaviour) or ``"run"``.
* ``cell.click_run_mode`` — ``"sequential"`` (default) or
  ``"parallel"``.  Only meaningful when ``click_action == "run"``
  AND the catalog is a ``.scriptreetree``.

## Five-step wiring pattern

| Layer | File | Change |
|---|---|---|
| Schema | ``core/model.py`` | ``ToolDef.cell_click_action`` / ``ToolDef.cell_click_run_mode`` (and same on ``TreeDef``).  Defaults preserve byte-identical round-trip for v0.3.4 catalogs. |
| Round-trip | ``core/io.py`` | Emit + read both fields under the ``cell`` sub-object.  Default-omit so legacy files stay clean. |
| Metadata | ``core/cell_metadata.py`` | ``CellMetadata`` carries the two new fields; ``write_for`` accepts them as kwargs and coerces unknown values to safe defaults. |
| Permission | ``core/permissions.py`` | New ``cell_click_to_run`` capability — default-allowed; locking the file disables the Settings dropdown and forces ``"menu"`` at dispatch. |
| V1 CLI | ``main.py`` | New ``-run`` flag that auto-clicks the active runner's Run button via ``QTimer.singleShot(0, ...)``. |
| Launcher | ``shell/v1_launcher.py`` | ``launch_tool`` gains ``run_on_open: bool`` kwarg that appends ``-run`` to the V1 command line. |
| Click dispatcher | ``shell/click_to_run.py`` (new) | ``run_catalog_on_click(path, run_mode)`` — picks the right path based on catalog extension; ``collect_leaf_tool_paths`` for tree walk; ``_run_parallel`` and ``_run_sequential``. |
| Cell window | ``shell/cell_window.py`` | ``CellWindow._read_click_action`` / ``_read_click_run_mode`` consult the catalog metadata + capability; ``click("single")`` dispatches to ``run_catalog_on_click`` when action is ``"run"``. |
| Settings dialog | ``shell/cell_window.py`` (``SettingsDialog``) | New "Single-click action" group with two dropdowns; ``_on_click_action_changed`` / ``_on_click_run_mode_changed`` write through to the catalog via ``cell_metadata.write_for``. |

## Sequential mode implementation

Sequential mode uses ``subprocess.Popen`` directly (not via the
fire-and-forget ``v1_launcher.launch_tool``).  An in-flight
state dict keyed by a per-invocation UUID tracks the current
process; a ``QTimer.singleShot(500ms)`` polls ``proc.poll()``.
On exit, the next leaf spawns.  Module-level dict so two cells
running their own sequences don't collide.

```python
_inflight_runs: dict[str, dict] = {}  # run_id -> {queue, current_proc, started_at}

def _run_sequential(leaf_paths):
    run_id = str(uuid.uuid4())
    _inflight_runs[run_id] = {
        "queue": list(leaf_paths),
        "current_proc": None,
        "started_at": time.monotonic(),
    }
    _advance_sequential(run_id)

def _advance_sequential(run_id):
    state = _inflight_runs[run_id]
    if not state["queue"]:
        del _inflight_runs[run_id]; return
    next_leaf = state["queue"].pop(0)
    state["current_proc"] = _spawn_v1_standalone(next_leaf)
    QTimer.singleShot(500, lambda: _poll_sequential(run_id))
```

"Process exit" means the user closed the V1 standalone window —
that's the lifecycle granularity that makes sense for an
interactive GUI launcher.  Tracking the underlying tool's
subprocess (which V1 owns) would require IPC we don't have.

## Test isolation gotcha

The test for sequential mode initially used real ``QTimer``
polling, which doesn't work in pytest without an active Qt
event loop.  Solution: ``click_to_run._schedule_poll`` falls
through to a synchronous ``proc.wait() + advance`` path when
``PySide6.QtCore.QTimer`` isn't importable.  Tests then patch
``sys.modules["PySide6.QtCore"]`` to ``None`` to force the
sync path:

```python
with patch.dict(sys.modules, {"PySide6.QtCore": None}):
    click_to_run.run_catalog_on_click(tp, run_mode="sequential")
```

The tests' fake Popens have ``poll() == 0`` (already exited)
so ``proc.wait()`` returns immediately.  Validates the
sequencer logic without needing a real event loop.

## Local-import shadowing trap

The cell-window ``SettingsDialog.__init__`` body has a
``from PySide6.QtWidgets import (QGroupBox, ...)`` block
half-way through (for the cell-label section).  Python's
lexical scoping marks ``QGroupBox`` as a function-local
binding, so any earlier reference to ``QGroupBox`` in the
same function body raises ``UnboundLocalError`` — even though
the same name is imported at module level.

Fix in v0.3.5: my new section above the lazy import re-imports
under aliases (``QGroupBox as _QGroupBox``, ``QComboBox as
_QComboBox``).  Awkward but unambiguous.  The alternative —
converting the lazy imports to module-level ones — would be a
broader refactor.

## How future-me detects it

* If a cell with ``click_action: "run"`` opens the menu
  instead, check the ``cell_click_to_run`` capability state.
* If sequential mode never advances past the first leaf, check
  whether QTimer is firing — in test contexts, force the sync
  fallback by patching out ``PySide6.QtCore``.
* If the Settings dialog's ``QGroupBox`` use is greeted by an
  ``UnboundLocalError``, the lazy-import-shadowing trap is back
  — alias-import the symbol locally.

## Tests

24 tests in ``tests/test_cell_click_to_run.py``:

- Schema round-trip (5): defaults stay out of JSON; explicit
  values preserved on both ToolDef and TreeDef.
- ``cell_metadata`` API (4): read defaults, write/read round-trip,
  invalid-value coercion to safe defaults.
- ``collect_leaf_tool_paths`` (4): top-level leaves, folder
  recursion, relative-path resolution, missing-file error.
- ``run_catalog_on_click`` dispatch (4): single tool gets
  ``run_on_open=True``; tree parallel spawns every leaf at once;
  tree sequential advances on Popen exit; unknown extension
  no-ops.
- ``CellWindow._read_click_action`` capability gate (3): granted
  → "run"; denied → "menu"; unbound cell → "menu".
- Settings dialog dropdowns (4): initial state matches catalog;
  both dropdowns disabled when capability denied; run-mode
  disabled when action is "menu"; toggling persists to catalog.

Suite at v0.3.5: 1062/1062 (was 1038 at v0.3.4).
