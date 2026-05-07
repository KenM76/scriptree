---
topic: v3-process
date: 2026-05-07
status: workflow
related: []
---
# Auto-dismiss QMessageBox in tests

## What happened / rule

The user's standing instruction: tests must NOT block on
expected error dialogs.  If a UI path under test would
normally pop a `QMessageBox.warning`, the test must auto-OK
it — never freeze the suite waiting for a human click.

## Root cause / rationale

`QMessageBox.warning(...)` etc. are static methods that block
the event loop until the user clicks a button.  In a pytest
run with no human, that's a hang.  CI never recovers; local
runs eat the suite slot.

## Fix / recipe

At module load (top of every test file that exercises UI
paths that might pop a dialog):

```python
from PySide6.QtWidgets import QMessageBox

# Auto-dismiss any modal dialog the code-under-test pops up.
QMessageBox.warning = staticmethod(
    lambda *a, **kw: QMessageBox.StandardButton.Ok)
QMessageBox.information = staticmethod(
    lambda *a, **kw: QMessageBox.StandardButton.Ok)
QMessageBox.critical = staticmethod(
    lambda *a, **kw: QMessageBox.StandardButton.Ok)
QMessageBox.question = staticmethod(
    lambda *a, **kw: QMessageBox.StandardButton.Yes)
```

Yes for `question` because most code-under-test treats Yes
as the affirmative "proceed" answer; flip per-test if a
specific path needs No.

If a test specifically wants to assert a dialog WAS shown,
override with a counter-recording lambda instead and assert
on the counter at the end.

## How future-me detects it

A test that hangs forever (or until pytest's overall
timeout) when run headlessly.  Add the auto-dismiss lines
at module load — usually fixes it on the next run.  If
you're tempted to "just answer the dialog manually," stop;
that's a sign the test file is missing the boilerplate.
