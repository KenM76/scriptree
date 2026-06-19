---
topic: checkable_action_invariant_restore_sender
date: 2026-06-19
status: recipe
related: [autohide_guard_own_modals]
---
# Restoring the "at least one checked" invariant on checkable QActions: restore only the sender and blockSignals

## What happened

Unchecking the LAST enabled visibility mode (e.g. unchecking "Show always on
top" when it was the only checked mode) silently turned ON all three modes
instead of refusing the uncheck.  Fixed in v0.8.0a66.

## Root cause

The pre-a66 "refuse" path looped over ALL actions and re-checked every
unchecked one:

```python
# WRONG (pre-a66)
if not (new_aot or new_tb or new_tr):
    for action, _attr in _actions:
        if not action.isChecked():
            action.setChecked(True)   # re-emits toggled → re-enters handler
    return
```

When the user unchecks their one remaining mode, all three actions are
momentarily unchecked at the entry point.  The loop calls `setChecked(True)`
on all three.  Each `setChecked` re-emits the `toggled` signal (no
`blockSignals`), which re-enters `_on_visibility_toggle` — which reads the
now-all-True state, passes the invariant check, and calls `update_preferences`
with all three modes enabled.  The bogus all-on state gets persisted.

## Fix / recipe

Three changes:

1. **Pass the firing action explicitly** into the handler.  `self.sender()`
   is unreliable for plain-callable (non-slot) connections; pass it via a
   `lambda` default-arg capture instead:

   ```python
   for action, _attr in _actions:
       action.toggled.connect(
           lambda checked, a=action: _on_visibility_toggle(a, checked)
       )
   ```

2. **Restore ONLY the fired action**, not all unchecked ones:

   ```python
   def _on_visibility_toggle(fired_action, _checked: bool = False) -> None:
       new_aot = a_aot.isChecked()
       new_tb = a_tb.isChecked()
       new_tr = a_tr.isChecked()
       if not (new_aot or new_tb or new_tr):
           fired_action.blockSignals(True)
           fired_action.setChecked(True)
           fired_action.blockSignals(False)
           # optional: show a tooltip explaining why
           return
       ...
   ```

3. **Wrap the restore in `blockSignals`** so the programmatic re-check
   neither re-enters the handler nor triggers an `update_preferences` call.

Implementation: `D:\Dev\ScripTree\scriptree\shell\forest_controller.py`,
`_populate_forest_menu`, `_on_visibility_toggle` closure (~lines 806-857).

## How future-me detects it

Any set of mutually-constrained `QAction.setCheckable(True)` actions (radio-
group emulation, "at least one must stay checked" invariant, "exactly one
checked" enforcer) that tries to restore state inside the `toggled` handler
MUST:

1. Know WHICH action fired (pass explicitly, don't rely on `sender()`).
2. Block that specific action's signals while restoring it.
3. Restore ONLY the one action that fired — do NOT loop over all siblings.
   Looping re-emits `toggled` on siblings, which can re-enter the handler
   and corrupt state.

The general pattern: "restore the exact action the user just changed, block
its signal while restoring, then return before persisting."
