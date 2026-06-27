# Headless screenshooter: skip blocking runner I/O + force off-screen layout (a88)

**Tag:** [pyside6] / [v3-process]
**Version:** v0.8.0a88
**Files:** `screenshooter.py` (`_ensure_app`, `_capture`),
`scriptree/ui/tool_runner.py` (`HEADLESS_CAPTURE`,
`_load_personal_configs_with_collision_prompt`, `_run_provider`)
**Tests:** `tests/test_screenshooter_headless_a88.py` (5),
`tests/test_screenshooter.py` (18, all still green)

## Symptom

Running the headless screenshooter (`python screenshooter.py tabs …`) on a
SolidWorks tool — specifically the **DXF Export Suite** — **hung forever**.
The operator's only workaround was to hand-write a throwaway script that
monkeypatched the tool runner before each capture. Screenshots of any tool
with a personal-config sidecar collision OR an on-open choice provider could
not be produced by the shipped utility.

A *second*, subtler defect surfaced after the hang was fixed: the rendered
form's **currently-selected inner tab was empty**. The DXF "Input" sub-tab
showed none of its Assembly / Configuration / Output-folder fields while every
other piece of chrome (description, tab bar, Configuration row, Command line,
Output box) rendered perfectly.

## Root cause #1 — the hang (blocking runner I/O with no event loop / no user)

`ToolRunnerView.__init__` → `_load_or_init_configs` does two things that block
when there is no Qt event loop and no human present:

1. **The modal personal-config collision prompt.**
   `_load_personal_configs_with_collision_prompt` opens a
   `PersonalConfigCollisionDialog` and calls `.exec()` when a tool has personal
   sidecar *candidates* but none match the tool's on-disk location.
   `exec()` spins a **nested modal loop that never returns headless** — a hard
   hang, pinned with faulthandler to `tool_runner.py:4296`.
2. **On-open choice providers.** `_init_providers` runs every param whose
   `choices_provider.refresh in ("on_open","on_change")` through
   `_run_provider`, which shells out via `resolve_provider` (a subprocess —
   e.g. a SolidWorks/combridge query). With nothing there to answer, the
   subprocess hangs.

## Fix #1 — a `HEADLESS_CAPTURE` module flag the runner honours

Added a module-level `HEADLESS_CAPTURE: bool = False` in `tool_runner.py`. The
screenshooter sets it `True` in `_ensure_app` (the single chokepoint every
render passes through *before* constructing any widget):

```python
from scriptree.ui import tool_runner as _tr
_tr.HEADLESS_CAPTURE = True
```

Two early-returns honour it:

* `_load_personal_configs_with_collision_prompt` returns at the prompt point —
  treated as **"no personal configs loaded"** (the shared/sidecar default
  config is used), exactly like the existing no-candidates path.
* `_run_provider` returns at the **top**, before `resolve_provider`. Top-guard
  is deliberate: it's the single chokepoint for on_open / on_change / manual
  refresh, so one guard covers them all. The combo simply stays unpopulated,
  which is correct for a snapshot.

The normal app leaves the flag `False`, so interactive behaviour is unchanged
(a paired flag-OFF test pins that the dialog / provider IS still reached).

**Why a module flag, not a constructor arg or env var:** the screenshooter
builds runners *indirectly* via `StandaloneWindow.from_tree`/`from_tool`, so
there is no constructor seam to thread a parameter through. A module global set
at the `_ensure_app` chokepoint is in-process, explicit, and trivially
monkeypatch-restorable in tests. An env var would also work but adds string
plumbing for no gain here (the screenshooter always builds runners in its own
process).

**Test-isolation note:** `test_screenshooter.py` runs the screenshooter as a
**subprocess** (deliberately, to isolate Qt state), so `_ensure_app` setting
the global there does NOT leak into the shared pytest process. In-process tests
must save/restore the flag around the call (`_run_with_flag` does this in a
`finally`). If you ever make the screenshooter tests run in-process, the flag
WILL leak into later `ToolRunnerView` tests and silently skip their providers.

## Root cause #2 — empty current inner tab (grab() ≠ full show machinery)

`QWidget.grab()` on an **unshown** top-level fires paint events synchronously
but does NOT run the full show → polish → layout → resize cascade. For a plain
widget that's fine. For a widget with a **nested `QTabWidget`** (the tool
form's param-group tabs: Input / Pipeline stages / BOM source / …), the inner
tab's *current page* — a `QStackedWidget` page wrapped in a `QScrollArea` — is
only given real geometry when the widget is actually shown. Grabbing unshown
caught that page at **zero size** → an empty current tab.

This is why the operator's old hand-render *did* show the fields (its setup
incidentally drove a layout pass) while the clean `screenshooter.py` path did
not — the two were never equivalent.

## Fix #2 — `WA_DontShowOnScreen` + `show()` in `_capture`

The canonical Qt idiom for "lay out a widget exactly as the user would see it
without parking a window on a display":

```python
widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
widget.show()
try:
    for _ in range(settle_ticks):
        app.processEvents()
    pixmap = widget.grab()
finally:
    widget.hide()
```

`WA_DontShowOnScreen` makes `show()` run the **complete** show/layout machinery
(so every nested tab page lays out) while the window never appears on any
monitor — preserving the headless screenshooter's whole reason for existing.
All 18 pre-existing screenshooter tests (cell / form / tree / tabs / editor /
forest / menu) stayed green, so the change is safe across kinds. (The composite
renderer `_capture_composite` calls `w.grab()` directly and is unaffected —
its cell-based widgets have no nested tabs.)

## Honest limitation (by design)

Provider-driven fields render **empty/unpopulated** headless — providers can't
run without their backing app (SolidWorks) live. Fields that are merely
*provider-gated* via `visible_when` may therefore hide. Fields with no provider
and no gating (e.g. DXF `assembly`, `output_dir`) render fully. This is the
correct trade-off: a SolidWorks-tool screenshot now "just works" and shows the
full form *structure* without a live SolidWorks session or any hand-stubbing.

## Reusable takeaways

1. **Headless render of a Qt form = skip every blocking input path.** Modal
   `exec()` and provider subprocesses are the usual culprits. A single
   module-flag honoured at the narrowest set of guard points beats stubbing.
2. **`grab()` on an unshown widget under-lays-out nested tab/scroll content.**
   Use `WA_DontShowOnScreen` + `show()` to get a faithful off-screen render.
3. **Set the headless signal at the one chokepoint before widgets are built**
   (`_ensure_app`), and **save/restore it in in-process tests**.
