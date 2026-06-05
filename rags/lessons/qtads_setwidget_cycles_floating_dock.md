# QtAds `CDockWidget.setWidget(new)` re-shows a floating dock as a "new popup"

**Tag**: `pyside6`
**Date**: 2026-06-05
**Versions affected**: v0.8.0a39 / a40 — fixed in v0.8.0a41

## TL;DR

`QtAds.CDockWidget.setWidget(new_widget)` on a CDockWidget that is
**currently floating** does not just swap the inner content — it
re-triggers the dock-frame's show path, which to the user reads as
"a new popup window appeared." This is independent of the
`toggleView(True/False)` antipattern documented in
`qtads_toggleview_off_on_cycles_floating_dock.md`. Even when both
`toggleView` calls are guarded behind `isVisible()`, the bare
`setWidget` is enough to spawn a fresh floating frame on every
content swap.

**Fix**: don't call `setWidget` after the dock is constructed.
Wrap a permanent **host widget** (`QWidget` + zero-margin
`QVBoxLayout`) into the dock once, and reparent runner-owned panels
in and out of the host's layout instead. The dock's widget reference
never changes → QtAds never sees a content swap → the floating
frame stays exactly where the user put it.

## How we hit it

In ScripTree's V1 developer editor, the bottom "Run controls" and
"Output" panels live in two `ads.CDockWidget`s. Each tool the user
clicks builds a fresh `ToolRunnerView` whose `bottom_panel` and
`output_panel` were being installed via:

```python
self._run_controls_dock.setWidget(runner.bottom_panel)
self._output_dock.setWidget(runner.output_panel)
```

When the user detached either dock to float it, every subsequent tool
click spawned a brand-new floating window of the dock's chrome
(title bar + the new panel content) on top of the existing floating
window. The first click after launch was fine because the dock was
docked, not floating — the bug only manifested from the second click
onward and only for users who had detached the dock.

`a39` and `a40` chased the wrong root cause (the `toggleView` off→on
cycle). Guarding those calls with `isVisible()` didn't help because
the `setWidget` itself is what re-shows the frame.

## The fix (v0.8.0a41)

```python
# In MainWindow.__init__, after creating each dock:
self._output_host = QWidget()
_oh_layout = QVBoxLayout(self._output_host)
_oh_layout.setContentsMargins(0, 0, 0, 0)
_oh_layout.setSpacing(0)
self._output_dock.setWidget(self._output_host)   # ← set ONCE, never again

# In _install_runner_panels:
output = runner.output_panel
output.setParent(None)
self._output_host.layout().addWidget(output)     # ← reparent INTO host

# In _uninstall_runner_panels:
output = runner.output_panel
output.setParent(None)                            # ← detach from host
runner._inner_splitter.addWidget(output)
```

The host's layout is the only thing that changes. The dock keeps the
same widget reference for its entire lifetime, so QtAds has nothing
to "re-show."

## When to apply this pattern

ANY time a `CDockWidget`'s content needs to change at runtime AND the
dock might be floating. Setup the dock once with a persistent host
container, then reparent children in and out of the host.

If the dock's content is fixed for its lifetime (e.g. ScripTree's
Tools launcher), no host is needed — the first and only `setWidget`
call is safe.

## Cross-reference

- `rags/lessons/qtads_toggleview_off_on_cycles_floating_dock.md` —
  the sibling antipattern. Both are needed for "floating dock that
  stays put across UI changes." A39 guarded `toggleView` but kept
  using `setWidget`; A41 ditches `setWidget` entirely.
- `scriptree/ui/main_window.py` — see the `_output_host` /
  `_run_controls_host` setup in `__init__` and the install/uninstall
  pair that uses `host.layout().addWidget()` instead of
  `dock.setWidget()`.

## User report (verbatim)

> "It is still happening, but it doesn't happen when I click on a
> tool for the first time in the tree, but it happens with every
> subsequent click."

> "The bug is still in the developer editor. When I first click on a
> tool in the tree no pop up shows, but if I click on another tool
> The popup to the right of the screenshot appears, and will keep
> popping up a new instance with clicking on a any tool."

Screenshot showed a free-floating window titled "ScripTree" with the
Extra-arguments collapsible + Command-line collapsible — i.e. the
detached Run-controls dock had been re-shown as a fresh floating
frame on every click.
