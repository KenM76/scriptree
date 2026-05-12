# ScripTree v0.4 roadmap

The `dxf-export-v2` Claude session sent us a feature-request memo
(saved at `C:\Users\Ken\OneDrive\Kens_Projects\Claude\scriptree_feature_requests.md`).
This document tracks which items shipped in v0.4.0 and which are
queued for follow-on releases.

## v0.4.0 — shipped 2026-05-12

### Editor UX (the user's explicit focus)

- **Universal hover tooltips on runner-form widgets**
  (`scriptree/ui/widgets/param_widgets.py::_apply_tooltip_recursively`).
  Every widget built by `build_widget_for` now carries the param's
  `description` as a rich-text hover tooltip, applied recursively
  to interactive child controls so the help text fires no matter
  which sub-control the user hovers.  HTML-escaped, capped at
  380 px wide.

- **Hover tooltips on every property panel field in the editor**
  (`scriptree/ui/tool_editor.py::_add_prop_row`).  Same rich
  tooltip on both the label and the input.  Hand-authored
  per-field help text covering when each field matters.

- **Conditional property-panel rows** in the tool editor.  Fields
  that aren't relevant to the current param's type are now hidden
  rather than shown disabled (`File filter:` no longer appears
  for `int` params; `Choices:` no longer appears for `string`
  params; `Do not auto-split:` only shows for `string`; etc.).
  Driven by `_refresh_prop_visibility`.

### Rec #1 — `visible_when` / `required_when` (memo's CRITICAL item)

- **New `ParamDef` fields** (`scriptree/core/model.py`):
  `visible_when: str = ""` and `required_when: str = ""`.  Default
  empty strings preserve pre-v0.4.0 behaviour byte-identically.

- **Expression evaluator** at
  `scriptree/core/visible_when.py::evaluate`.  Tiny
  recursive-descent parser over a strict grammar (equality,
  inequality, `in`-list, `AND`/`OR`/`NOT`, parens).  String
  comparisons throughout — `bom_type == 3` works because the
  values dict stringifies on read.  Parse errors fail OPEN
  (return True) so a typo in a tool def can't make a field
  permanently invisible.

- **Runner integration**: `build_full_argv` skips the required
  check for params whose `visible_when` evaluates false, and
  honours `required_when` as a runtime-conditional alternative
  to the static `required` flag.

- **Form integration**: `ToolRunnerView._refresh_visible_when()`
  runs on every value change.  Hidden params are also dropped
  from `_collect_values` so their stored values don't leak into
  argv — but the widget retains the value in memory for
  re-appearance.

- **Schema round-trip**: io emits the fields only when non-empty
  so v0.3.x tools round-trip byte-identical.

- **Tests**: `tests/test_visible_when.py` (20 tests) +
  `tests/test_param_widget_tooltips.py` (11 tests).

## Queued for v0.4.x (in priority order)

### Rec #2 — `.scriptree.preset` import/export   [HIGH]
Shop-share workflow: a double-clickable preset file that wraps
one configuration with `tool_fingerprint` validation.  Two new
menu actions: `Configurations → Export this configuration…` and
`Configurations → Import configuration…`.

**Effort**: small.  New file-extension handler + two menu actions.

### Rec #3 — GUI field validators   [HIGH]
Per-param `validator` block covering `regex`, `regex_compile`,
`min`/`max`, `path_must_exist`/`path_must_not_exist`,
`enum_subset`, `custom_command`.  Red outline on invalid fields +
Run button disabled until valid.  Hidden-by-`visible_when` fields
skip validation regardless.

**Effort**: medium.  Schema field + runtime evaluation hook on
`ParamWidget.valueChanged` + button-disable wiring.

### Rec #4 — Live progress widget   [HIGH]
Opt-in `stdout_protocol: "progress"` attribute on `ToolDef`.
Runner parses `[PROGRESS] step=5 total=22 status=running
message=…` lines into a progress bar + per-row status list.
Companion: cancel button → `SIGTERM`.

**Effort**: medium.  New widget + stdout-line filter + opt-in
config + cancel signal.

### Rec #5 — Pipeline mode in `.scriptreetree`   [MEDIUM, large]
`type: "pipeline"` leaf with sequential `steps` and
output-to-input variable threading.  Merges multiple tools'
param forms into one screen.

**Effort**: large.  New tree-leaf kind, param-merge layout
engine, output-capture from one step into another's environment.

## Honorable mentions (probably not in 0.4.x)

- #6 Per-project preset scopes (`<project>/.scriptree-presets/`)
- #7 Multi-file picker on `path` widgets
- #8 Auto-update mechanism
- #9 Localization stubs
- #10 "Show all" form toggle
- #11 Result summary widget post-run
- #12 Auto-collapse on success

Re-evaluate after v0.4.x ships #2 / #3 / #4 — those three
together would compound into ~80% of the memo's compound use-case
flow, and #11 / #12 are natural follow-ons on top of #4.

## Things explicitly NOT planned

Per the memo's "what I'm NOT asking for" section, and aligned
with this project's positioning:

- No GUI styling / branding framework — that's per-tool work.
- No cross-platform parity beyond what's already there.
- No scripting language inside `.scriptree` files —
  `visible_when` has a tiny declarative grammar but anything more
  complex belongs in the tool's executable.
- No cloud anything — auto-update over HTTP is fine if/when we
  build #8; "ScripTree account" / telemetry / cloud presets are
  off-mission.

## Frozen baseline

v0.3.22 is the last release before this redesign.  Frozen at
`C:\Users\Ken\OneDrive\Kens_Projects\Claude\Software\ScripTree3-v0.3.22-frozen-20260512-172944.zip`.
