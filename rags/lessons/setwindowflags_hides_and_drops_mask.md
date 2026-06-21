---
topic: setwindowflags_hides_widget_and_drops_mask
date: 2026-06-21
status: gotcha
related: [forest_visibility_apply_no_reveal, collapse_expand_route_through_layout_engine]
---
# `setWindowFlags()` HIDES the widget and DROPS the mask — capture visibility first, re-assert chrome after

## What happened (user-reported, fixed v0.8.0a71)

The user reported the forest hub "lost its icon, and eventually just disappeared
from the screen." Two distinct defects in the window-flag helpers
(`CellWindow._apply_always_on_top_flag` / `_apply_taskbar_flag`, cell_window.py
~5279/5294), both rooted in Qt-on-Windows `setWindowFlags()` behaviour:

1. **Silent hide ("disappeared").** `setWindowFlags()` calls `setParent()`, which
   **hides the widget**. So `isVisible()` is already **False** immediately after
   `setWindowFlags()`. The helpers re-showed with `if self.isVisible(): self.show()`
   — evaluated AFTER `setWindowFlags()` — so the guard was always False and the
   re-show was **dead code**. A runtime visibility-mode toggle therefore left the
   hub hidden with nothing to re-show it.

2. **Lost mask / "lost its icon".** On Win11 the flag change recreates the native
   HWND, which discards `setMask()` (the custom hex clip region) and can reset
   `WA_TranslucentBackground`. The cell then renders as an opaque, unclipped
   rectangle — the painted hex glyph is gone.

## Root cause

- `setWindowFlags()` → `setParent()` → widget hidden synchronously, so
  `isVisible()` reads False right after it. Any `if isVisible(): show()` placed
  AFTER `setWindowFlags()` never fires.
- The recreated HWND has no mask and (sometimes) no translucent-background
  attribute until re-applied.

## Fix / recipe

```python
def _apply_taskbar_flag(self, on):
    was_visible = self.isVisible()          # capture BEFORE setWindowFlags hides it
    flags = self.windowFlags()
    ... modify flags ...
    self.setWindowFlags(flags)              # this HIDES the widget
    if was_visible:
        self.show()                         # actually re-show now
        self._reassert_window_chrome()      # re-apply mask + translucent bg

def _reassert_window_chrome(self):
    self.setAttribute(Qt.WA_TranslucentBackground, True)
    self._apply_hex_mask(self._size_px)     # setMask(QRegion(hex polygon))
    self.update()
```

The two rules:
- **Capture `isVisible()` BEFORE `setWindowFlags()`** — never test it after.
- **Re-assert mask + translucent background AFTER the re-show** — `setMask` needs
  the (recreated) native window to exist, so it must run after `show()`.

Implementation: `scriptree/shell/cell_window.py` — `_apply_always_on_top_flag`,
`_apply_taskbar_flag`, and the new `_reassert_window_chrome` (next to
`_apply_hex_mask`).

## How future-me detects it

Any code that calls `setWindowFlags()` on a live widget must (1) snapshot
`isVisible()` first and re-`show()` if it was visible, and (2) re-apply
`setMask` / `WA_TranslucentBackground` afterward. A bare
`setWindowFlags(...); if self.isVisible(): self.show()` is doubly wrong: the
guard is dead AND the chrome is never restored. This compounds with the separate
`forest_visibility.apply()`-has-no-reveal-path gap — both can leave the hub
hidden after a visibility change.
