# `emit: "unselected"` — deselect-to-act forms

## What it is

A `ParamDef.emit` mode (v0.8.0a50+) that makes a `multiselect`
field emit the **complement** of the user's selection instead of
the selection itself. Used for "review current state → untick the
items you want flipped → Run" workflows where pre-checking
everything is the most natural way to *display* state and
unticking is the natural way to *act on it*.

Legal on `multiselect` rendered as `checkbox_list` or `dropdown`.
Rejected at load time on any other type/widget combo (catch the
mistake before the runner emits the wrong half).

## The motivating example: SWBomExcluded

A SolidWorks "exclude-from-BOM auditor" needs to:

1. Scan the active assembly and every referenced part for items
   flagged *Exclude from Bill of Materials*.
2. Show the user a checklist of those items, **all pre-checked**
   (checked = "currently excluded, leaving it as-is").
3. Let the user **untick** the items that should go back into the
   BOM.
4. On Run, the back-end clears the exclusion on exactly the
   unticked items via `IComponent2.SetExcludeFromBOM2(false, ...)`.

The author needs argv to receive "the items the user unticked" —
the diff between "what was excluded" and "what the user wants to
keep excluded." Pre-v0.8.0a50 there was no way to express this
cleanly:

- A snapshot side-channel (provider writes the presented list to a
  file, runner re-reads) couples two commands through invisible
  state.
- Inverting to tick-to-act (open all-unchecked) contradicts the
  affordance — a list of "excluded items" should read as ticked
  boxes the user unticks.
- Re-deriving the complement from live state at Run time can act
  on items that weren't visible at form-open (anything newly
  excluded between open and Run).

`emit: "unselected"` is the primitive that makes the natural UX
trivial to implement.

## The catalog

```jsonc
{
  "id": "excluded_items",
  "label": "Items currently excluded from BOM (untick to put back)",
  "type": "multiselect",
  "widget": "checkbox_list",
  "select_all": true,
  "emit": "unselected",
  "default": [],
  "choices_provider": {
    "command": ["combridge.exe", "solidworks", "bom-excluded-scan"],
    "refresh": "on_open"
  }
}
```

Argv template:

```jsonc
"argument_template": [
  ["--unexclude", "{excluded_items}"]
]
```

What happens:

1. **Form opens.** The provider runs and returns `{"choices": [...all excluded items...], "default": [...all excluded items...]}` — same list both fields. Every box is pre-checked. The "Select all" master shows the **checked** state.
2. **User leaves it alone, clicks Run.** Selected = all choices. Complement = `[]`. The token-group expands to zero copies; `--unexclude` doesn't appear in argv. Clean no-op.
3. **User unticks two items.** Selected = `[all − 2]`. Complement = `[those two]`. argv gets `--unexclude itemA --unexclude itemB`.
4. **User unticks the master.** All boxes clear; selected = `[]`. Complement = all choices. argv un-excludes the entire visible set.

## The dismiss matrix (UI behaviour)

| Open state | User action | Selected list | Emitted (complement) |
|---|---|---|---|
| All ticked | (nothing) | All choices | `[]` (no-op Run) |
| All ticked | Untick one | All − that one | The unticked one |
| All ticked | Untick master | `[]` | All choices |
| Mixed | Tick master | All choices | `[]` |
| Mixed | Untick master | `[]` | All choices |

The complement is computed at argv-assembly time from the
**live** widget choice set (so dynamic providers Just Work), and
the result preserves choice order (so token-group fan-out is
deterministic).

## Composition with existing primitives

- **`required: true`** — checks the **emitted** list, not the
  selected one. On `emit: "unselected"` that means "the user must
  untick at least one item before Run is enabled." Perfect for
  acting-on-a-diff tools where doing nothing is meaningless.
- **`select_all`** — recommended for any `emit: "unselected"`
  form. The master becomes a one-click "act on everything" affordance.
- **Token-group fan-out** — `["--flag", "{id}"]` repeats per
  emitted value, same as for regular multiselect. Drop-on-empty
  applies (zero items → group drops; no `--flag` in argv).
- **`visible_when`** — sees the selected list (raw form state),
  not the emitted complement. Predicates like
  `"excluded_items != []"` work as authors expect.
- **Configuration sidecars** — store the SELECTED list, not the
  complement. The complement is recomputed at Run after the
  saved selection is restored to the widget.

## The safety rule: explicit `default`

Shipped alongside `emit`: when `widget` is `checkbox_list` /
`dropdown`-multi AND there is no `choices_provider`, the
`default` key MUST be explicitly present in the JSON.
`scriptree validate` emits a `[WARN]` when it isn't.

### Why force explicitness

A form like SWBomExcluded depends on the initial state being
*deliberately* "all selected" — that's how the deselect-to-act
affordance reads correctly. If the catalog left `default` implicit
and a future ScripTree version changed the implicit default from
`[]` (current) to something else, every deployed catalog using
the implicit-default would silently change what's pre-ticked AND
(with `emit: "unselected"`) what gets ACTED ON. That's the same
class of bug `no_persist` protects against for sensitive fields —
the default's value affects correctness, so the default shouldn't
come from a moving floor.

The rule applies whether `emit` is `"selected"` or `"unselected"`
— any `checkbox_list` / `dropdown`-multi without a provider must
declare its initial state, because either mode is sensitive to
the default.

### Recommended values

- `"default": []` — start all-deselected. Safe for "tick what you
  want to act on" forms.
- `"default": ["a", "b", "c"]` (full choice list) — start all-
  selected. Safe for `emit: "unselected"` forms where doing
  nothing should be a no-op.
- A partial list — pre-tick the common case; the user can adjust.

## Limitations / not in v0.8.0a50

- **Headless / CLI runs with `emit: "unselected"` + a dynamic
  `choices_provider` aren't supported.** The complement needs
  the widget's live choice set; headless mode doesn't
  materialise the widget. Static-choice catalogs work
  headlessly; dynamic catalogs need the UI. (Workaround: provide
  the choice list inline in `choices`, not via the provider.)
- **No "emit both halves" mode.** Some tools might want both the
  selected and unselected lists at once; the v0.8.0a50 primitive
  is one or the other. `"selected"` and `"unselected"` are
  composable across multiple params if the back-end needs both.
- **No editor-side "Default master state" radio picker.** The
  author edits `default` directly in the property panel today.
  An explicit picker that surfaces "All selected / All
  deselected / Custom" is queued for a future release; the
  validation rule already protects against the silent-default
  hazard.

## Files

- Model: `scriptree/core/model.py::ParamDef.emit` + the
  `__post_init__` validation that rejects illegal type/widget
  combos.
- IO: `scriptree/core/io.py::_param_from_dict` reads `emit`;
  `_param_to_dict` writes it omitted-at-default;
  `param_load_warnings` emits the MISSING_EXPLICIT_DEFAULT
  diagnostic.
- Runner: `scriptree/ui/tool_runner.py::_collect_values`
  applies the complement against
  `widget.current_choices()`.
- CLI: `scriptree/cli/validate.py::validate_tree` calls
  `param_load_warnings` per param and prints the `[WARN]` lines.
- Editor: `scriptree/ui/tool_editor.py` adds an `Emit:`
  dropdown + `Select-all master:` checkbox to the property
  panel; both hidden via `_refresh_prop_visibility` when the
  current param doesn't qualify.
- Demo: `ScripTreeApps/Demos/deselect-to-act/` — three fake
  "currently-enabled features" pre-checked; untick to disable;
  showcases the pattern without needing SolidWorks.
- Tests: `tests/test_emit_unselected.py` — 19 cases covering
  model validation, IO round-trip, the explicit-default
  warning, and the complement primitive's invariants.

## Cross-references

- `docs/LLM/param_types_widgets.md` — `emit` row added to the
  widget-specific fields section.
- `docs/LLM/dynamic_providers.md` — the provider's `default`
  key defines the initial selection for provider-backed
  multiselect; the static `default` is irrelevant in that
  case.
- `D:/Dev/FeatureRequests/ScripTree_FeatureRequests/FR_checkbox_list_emit_unchecked.md`
  — the original request that motivated the feature, with the
  SWBomExcluded use case spelled out.
