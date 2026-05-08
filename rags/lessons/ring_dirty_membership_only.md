---
topic: v3-architecture
date: 2026-05-07
status: pattern
related: [cell_window, ring_io, master_cells_no_catalog_path]
---
# Ring dirty-flag tracks **membership**, not position

## What happened / rule

User report (paraphrased): "When I right-clicked the ring I had
made and not saved and closed it, it didn't ask me to save."  And
the spec: prompt to save iff the ring is unsaved OR membership
changed since save — but stay quiet for pure position changes
(drag, repack, drift snap-back).

The fix landed as a `_ring_dirty: bool` flag on every CellWindow,
plus a per-master `_saved_ring_path: Path | None`.  Together they
drive `_ring_needs_save_prompt`, which the close paths consult
before invoking the master tear-down.

## Why "membership only", not "anything that mutates _members"

Several `_members` mutation sites flip what's in the dict but
don't actually represent a meaningful user-visible change:

| Site | What changes | Dirty? |
|---|---|---|
| Case 1 master spawn | new dict with 2 members | **Yes** (brand-new ring) |
| Case 2/3 add | new id appears | **Yes** |
| Case 4 transfer-out | id removed from old master, added to new | **Yes** for both |
| Case 5 same-group re-snap | id was already there | No (position-only) |
| `_close_this` member-leave | id removed | **Yes** |
| `_explicit_leave_group` | id removed | **Yes** |
| `_on_shake_detected` | id removed | **Yes** |
| `_repack_members` | positions in dict updated | No (position-only) |
| `_shift_positioned_members` (drag) | positions in dict updated | No (position-only) |
| Drift detection (`_check_undock`) | position updated when member drifts away | No (position-only) |
| Collapse target tracking | positions in dict updated | No |
| `ring_io.load_ring` | dict populated from file | **No, then reset** (matches on-disk state) |
| `_check_master_validity` empty-out | dict cleared as master closes | No (master is dying anyway) |

The rule is: **flip the bit only at sites where a key is added
or removed**.  Re-assigning a value at an existing key is a
position-only event.

## Reset paths

* `_write_ring_to_path` clears `_ring_dirty` after `save_ring`
  succeeds.  Sets `_saved_ring_path = path`.
* `ring_io.load_ring` clears `_ring_dirty` at the very end.
  Repacking during load (which we do to canonicalise hand-edited
  files) runs in a transient dirty state that we wipe before
  returning the master.

## Close-prompt logic

```python
def _ring_needs_save_prompt(self) -> bool:
    if self.role != "master":
        return False
    if not self._members:
        return False  # empty master — nothing worth saving
    return self._ring_dirty or self._saved_ring_path is None
```

`_saved_ring_path is None` covers brand-new rings even when the
dirty flag was somehow cleared (e.g. through a code path that
forgot to flip it).  Belt + braces.

The dialog is Save / Discard / Cancel (standard pattern, matches
V1 editor's `_confirm_discard_tree`).  Cancel aborts the close.
Save delegates to `_save_ring_dialog` — for a never-saved ring
that runs Save-As; for a saved-but-dirty ring that overwrites.
Discard closes without writing.

Hooks in three close paths:

* `_close_ring_undock_all` (right-click menu "Close ring")
* `_close_all_related` (right-click menu "Close all related")
* The master branch of `_close_this` (rare path; defensive)

## Initialisation gotcha

`_saved_ring_path` was a lazy attribute pre-v0.3.1 — only set
after the first `save_ring`.  `getattr(self, "_saved_ring_path",
None)` was the idiom everywhere it was read.  When tests asserted
`master._saved_ring_path is None` directly, they failed with
`AttributeError`.  Fix: initialise to `None` in `__init__` so the
attribute always exists and tests can compare with `is None`.

## How future-me detects it

* If a position-only event starts triggering save prompts, check
  whether you accidentally added a `self._ring_dirty = True` to a
  position-update site (drag, repack, drift, collapse).
* If a real membership change *doesn't* trigger a prompt, check
  the corresponding case branch in `_try_spawn_master` /
  `_close_this` / `_explicit_leave_group` / `_on_shake_detected`
  for a missing flag-set.
* If a saved-clean ring still prompts on close, `_write_ring_to_path`
  isn't clearing the flag (or `load_ring` isn't clearing it).

## Tests

`tests/test_ring_dirty_flag.py` — 19 tests:

- Initial state (clean on construction).
- All four "should-be-dirty" sites (Case 1 spawn, Case 2 add,
  member close, explicit leave).
- Save / load reset.
- Position-only events stay clean (repack, group-drag).
- `_ring_needs_save_prompt` truth table (brand-new, saved+clean,
  saved+dirty, non-master, empty master).
- Close-path dialog wiring (3 close methods, all 3 button outcomes).

All pass.  Full suite: 47/47 in the close+ring+load+group subset.
