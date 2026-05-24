---
topic: v3-architecture
date: 2026-05-23
status: pattern
related: [ring_dirty_membership_only, close_member_uses_membership_not_source_id]
---
# Shake-to-close fires Save / Discard / Cancel prompt; members relink to forest

## What happened

Bug 5 (v0.8.0a1): the v0.6.x behaviour was "if the user shakes a
ring master vigorously, auto-close it once quorum drops to 1." The
new v0.8.0 spec is more user-controlled: shake should prompt the
user (Save / Discard / Cancel) and on disband, members re-link to
the forest (per the always-linked invariant).

## Root cause / context

In v0.6.x, the shake handler would silently break up the ring once
the quorum-loss condition was met. v0.8.0's always-linked spec means
cells can't be left orphan — they must re-link to *something*. And
the destruction needs a confirmation step (consistent with the close
paths) so a stray shake doesn't lose unsaved work.

## Fix / recipe

New handler `_close_ring_via_shake_with_prompt` at
`scriptree/shell/cell_window.py:7745`:

```python
def _close_ring_via_shake_with_prompt(self) -> None:
    # Save / Discard / Cancel
    if not self._ring_needs_save_prompt():
        self._disband_ring_relink_members()
        return
    btn = QMessageBox.question(
        self, "Ring shaken",
        "This ring has not been saved. Save, discard, or cancel?",
        QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
    )
    if btn == QMessageBox.Save:
        if not self._save_ring_dialog():
            return                 # save cancelled — keep ring
        self._disband_ring_relink_members()
    elif btn == QMessageBox.Discard:
        self._disband_ring_relink_members()
    # Cancel — do nothing

def _disband_ring_relink_members(self) -> None:
    for mid in list(self._members.keys()):
        member = registry.get(mid)
        if member is not None:
            # Re-link to the forest, per always-linked invariant
            member._link_parent_id = forest_id()
    self.close()
```

Shake handler in `mouseMoveEvent` extended to fire for
`role == "master" and not _is_forest_master` (forests excluded —
shaking the forest never closes it).

## Edge cases

* If save dialog is cancelled (Save → cancel save), the ring stays
  open. The shake prompt is dismissed but ring is unaffected.
* Multiple shakes during the prompt are ignored — the prompt is
  modal.
* Forest shake does nothing (excluded from the shake-detected branch).

## How future-me detects it

* Symptom: ring auto-closes on a small mouse-jostle without asking —
  the prompt branch isn't firing, or the shake detection threshold
  is too low. Check `_on_shake_detected` and the new
  `_close_ring_via_shake_with_prompt` call site.
* Members end up link-orphaned (`_link_parent_id is None`) after a
  shake-close — `_disband_ring_relink_members` skipped the re-link
  step. The always-linked invariant L1 (in `link_dock_audit.py`)
  will flag this at idle.
* Forest closes on shake — the `_is_forest_master` exclusion is
  missing.
