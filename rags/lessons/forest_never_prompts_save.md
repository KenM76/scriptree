---
topic: v3-architecture
date: 2026-05-23
status: bug
related: [ring_dirty_membership_only]
---
# Forest never prompts to save — and exit-all walks rings once

## What happened

User report (Bug 11, v0.8.0a1): clicking "Close all" on the forest
showed the "This ring has not been saved" prompt **twice** for the
same ring before quitting. The forest itself was also entering the
ring-save prompt code path even though forests don't save.

## Root cause

`_ring_needs_save_prompt` in `cell_window.py:7657` returns True when
the cell is a master with members and no `_saved_ring_path`. The
forest cell is also a master with members and no path — it matched
the predicate and asked to save itself. Worse, `_close_all_related`
walked descendants and prompted the inner ring twice (once via the
forest's own quasi-save path, once via the per-ring walk).

## Fix / recipe

Two small changes:

1. `_ring_needs_save_prompt` skips forest masters explicitly:

   ```python
   def _ring_needs_save_prompt(self) -> bool:
       if getattr(self, "_is_forest_master", False):
           return False
       if self.role != "master":
           return False
       if not self._members:
           return False
       return self._ring_dirty or self._saved_ring_path is None
   ```

2. `_close_all_related` pre-walks rings nested inside the forest and
   prompts each unsaved ring **exactly once** before tearing the
   forest down. The walk uses `_link_parent_id` (the group graph),
   not `_dock_partner_id` — see `link_dock_graph_split.md`. After
   the walk, the forest is closed without any save attempt.

## How future-me detects it

* User sees the save-ring prompt twice in a row with identical text —
  one walker is hitting the same ring through two relationships.
  Audit `_close_all_related` for double-walks.
* Forest somehow ends up with a `_saved_ring_path` set — something
  treated it as a ring. The forest master should never receive
  ring-save plumbing; if you see it set, the call site is wrong.
* Reproducer: spawn a ring, do NOT save it, click forest's "Close
  all" — should prompt exactly once.
