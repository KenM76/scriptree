---
topic: v3-architecture
date: 2026-05-08
status: feature
related: [cell_window, cell_metadata]
---
# Cell fill-colour picker with synced RGB / hex / hue rainbow (v0.3.6)

## What happened / rule

User feature: "We also need to be able to change the cell colours
with RGB entry and rainbow slider that updates when one or the
other is changed."

v0.3.6 adds a per-cell fill-colour override stored in the
catalog JSON's ``cell.fill_color`` field, plus a Settings-dialog
group with four mutually-synced controls: hex entry, R/G/B
spinboxes, a hue rainbow slider, and a reset button.

## Schema

* ``ToolDef.cell_fill_color: str = ""`` (and same on ``TreeDef``).
* Empty string → branding default.  Non-empty must be ``#RRGGBB``
  lowercase (canonicalised by ``cell_metadata._normalise_hex_rgb``).
* Per-cell, NOT group-uniform — a master and its members can each
  carry a different fill so a ring can colour-code its tools.

## Hex parser (`_normalise_hex_rgb`)

Single source of truth for "is this a valid colour?" used by
the catalog writer, the cell-window apply method, and the
Settings dialog.  Accepts:

* ``"#RRGGBB"`` / ``"RRGGBB"`` (any case).
* ``"#RGB"`` / ``"RGB"`` (3-digit shorthand expanded to 6).

Rejects:

* 4 or 8-digit alpha-included variants (alpha is owned by the
  ``transparency`` slider, not the fill).
* Anything not parseable as hex.
* Empty input → empty result (clears the override).

Invalid input returns ``""`` rather than raising — keeps the
catalog file safe from typos at every boundary.

## Alpha-preservation rule

The user's RGB controls *just* the colour.  ``apply_fill_color_change``
reads the existing alpha off ``self._fill_color`` and re-applies
it to the new RGB tuple:

```python
existing_alpha = self._fill_color.alpha()
self._fill_color = QColor(r, g, b, existing_alpha)
```

That way the transparency slider drift never bleeds through
when the user picks a new hue.  The two axes (colour vs alpha)
stay independent.

## Settings-dialog sync logic

Four controls all reflect the same underlying ``_fill_color``.
Each one emits a Qt signal on change; the handler:

1. Computes the new colour (hex / RGB tuple / hue → fully-saturated
   full-value RGB).
2. Updates the OTHER controls (signal-blocked to prevent feedback
   loops).
3. Calls ``self._hex.apply_fill_color_change(hex_rgb)`` which
   updates ``_fill_color`` + ``_fill_color_hex``, repaints the
   cell, and writes through to the bound catalog.

The signal-block helper:

```python
def _block(widgets, fn):
    blockers = [w.blockSignals(True) for w in widgets]
    try:
        fn()
    finally:
        for w, prev in zip(widgets, blockers):
            w.blockSignals(prev)
```

Without this, ``setValue(...)`` on the spinbox during sync would
re-fire the change handler and create infinite ping-pong.

## Hue slider semantics

The hue slider always picks a fully-saturated full-value colour
at the chosen hue (`QColor.fromHsv(hue, 255, 255)`).  S/V
variation is intentionally NOT exposed — the rainbow slider is
a quick picker, not a full HSV editor.  When the user enters a
muted RGB via the spinboxes, the slider's thumb moves to the
hue closest to that RGB (computed via `QColor.hsvHue()`).
Sliding the thumb after that re-saturates to full S/V at the
new hue.

This is a deliberate UX trade-off: most users want "pick a hue"
and don't care about saturation/value.  Power users wanting
specific muted colours can type the hex directly.

## Rainbow groove gradient

The hue slider's groove uses a Qt stylesheet gradient with six
stops at every 60°:

```css
QSlider::groove:horizontal {
    background: qlineargradient(
        x1:0,y1:0, x2:1,y2:0,
        stop:0    #ff0000, stop:0.166 #ffff00,
        stop:0.333 #00ff00, stop:0.5   #00ffff,
        stop:0.666 #0000ff, stop:0.833 #ff00ff,
        stop:1    #ff0000
    );
}
```

Pure CSS, no custom widget — survives Qt theme changes and
HiDPI scaling automatically.

## Import-path trap

Initial implementation had ``from .cell_metadata import _normalise_hex_rgb``
inside ``cell_window.py`` (which lives in ``scriptree.shell``),
but ``cell_metadata`` is in ``scriptree.core``.  Tests caught
this immediately — the dialog interaction triggered a
``ModuleNotFoundError: No module named 'scriptree.shell.cell_metadata'``.

Fix: ``from ..core.cell_metadata import _normalise_hex_rgb``
(or use the absolute ``scriptree.core.cell_metadata`` form).

When adding new cross-package helpers, double-check the relative-
vs-absolute import path — stack-trace-driven discovery is the
fast loop.

## Catalog-load applies the override

``_refresh_label_from_catalog`` runs every time the cell's
``_catalog_path`` changes (Load…, drop, etc.).  v0.3.6 extends
it to also read ``cell.fill_color`` and:

* Non-empty → apply via direct ``QColor`` mutation (NOT via
  ``apply_fill_color_change`` — that would re-write the catalog
  with what we just read, no-op but wasteful disk I/O).
* Empty → reset ``_fill_color`` to ``_branding_fill_color``
  copy, clear ``_fill_color_hex``.

The reset path is critical: without it, a previously-overridden
cell that re-binds to a catalog with no override would keep the
stale colour.  Tests pin this via
``test_refresh_label_from_catalog_resets_when_unset``.

## How future-me detects it

* If the four controls de-sync (spinboxes show one colour, hex
  shows another), the signal-block helper isn't fully covering
  one of the change paths — check that every "I'm updating
  others" branch wraps the relevant widget set.
* If colour changes leak alpha (transparency drifts on hue
  pick), ``apply_fill_color_change`` lost the
  ``existing_alpha`` capture.
* If the hue slider doesn't move when RGB changes, look at the
  ``QColor(r, g, b).hsvHue()`` call — pure greys return ``-1``
  (clamped to 0 here for the slider).

## Tests

28 tests in ``tests/test_cell_fill_color.py``:

- ``_normalise_hex_rgb`` parser (6): six-digit + lowercase,
  hashless, 3-digit expansion, invalid input → empty,
  empty → empty, alpha variants rejected.
- Schema round-trip (5): defaults stay out of JSON; explicit
  values preserved on both ToolDef and TreeDef.
- ``cell_metadata`` API (4): default read, write/read round-trip,
  invalid-value silent clear, 3-digit expansion.
- ``apply_fill_color_change`` (5): basic set, alpha preservation
  across changes, invalid → reset, empty → branding default,
  persist to bound catalog.
- Catalog-load applies (2): catalog with fill_color sets the
  cell; catalog with empty fill_color resets a previously-
  overridden cell.
- Settings-dialog sync (6): initial state matches branding
  default; RGB → hex + hue; hex → RGB + hue; hue → RGB + hex;
  reset button reverts everything; invalid hex typing doesn't
  crash.

Suite at v0.3.6: 1090/1090 (was 1062 at v0.3.5).
