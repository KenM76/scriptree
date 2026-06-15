# Dynamic choice / value providers (v0.6.0)

A parameter's choices (or its scalar value) usually come from a
static `choices` list baked into the `.scriptree`. A **provider**
instead runs an external command at *form-open / refresh* time and
uses what it prints. Use this when the valid options aren't knowable
when the tool is authored — they only exist when the form opens and
change while it's up:

- the drawings currently open in a long-running app (SolidWorks via
  a side `sw_bridge.exe`),
- running Docker containers, then a checkbox list of their volumes,
- git remotes, then a checkbox list of branches,
- databases, then a checkbox list of tables,
- the active document's path auto-detected into a `path` field.

This is general-purpose. Nothing here is SolidWorks-specific.

## Schema (all optional; absent ⇒ today's static behaviour)

Add to any `ParamDef`:

```jsonc
{
  "id": "source_drawing",
  "label": "Source drawing",
  "type": "enum",
  "widget": "dropdown",

  "choices_provider": {
    "command": ["../sw_bridge/sw_bridge.exe", "list-open-drawings", "--json"],
    "working_directory": ".",      // optional; resolved like `executable`
    "refresh": "on_open",          // on_open | manual | on_change
    "timeout_sec": 15,             // default 15
    "cache": "form_session"        // form_session | none
  }
}
```

```jsonc
{
  "id": "pages",
  "label": "Pages to copy",
  "type": "multiselect",
  "widget": "checkbox_list",       // see param_types_widgets.md
  "depends_on": ["source_drawing"],
  "select_all": true,
  "choices_provider": {
    "command": ["../sw_bridge/sw_bridge.exe", "list-sheets", "--json"],
    "refresh": "on_change"         // re-run when an upstream value changes
  }
}
```

| Field | Type | Default | Meaning |
|---|---|---|---|
| `choices_provider` | object \| null | null | Run `command` to populate this param. **Mutually exclusive** with a non-empty static `choices` (loader rejects the file if both). |
| `depends_on` | list[str] | `[]` | Upstream param ids forwarded to the provider on stdin; a change re-runs the provider when `refresh: "on_change"`. A cycle or unknown id is a **load error**. |
| `select_all` | bool | false | Only valid with `widget: "checkbox_list"` — adds a tri-state select-all/none master. |

`choices_provider` keys:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `command` | list[str] | **required** | Argv list (NOT a shell string). First entry resolves against the `.scriptree` dir like `executable`; bare names via PATH. |
| `working_directory` | str \| null | null | Resolved like `ToolDef.working_directory`. |
| `refresh` | enum | `on_open` | `on_open` (run at form build), `manual` (only on Refresh click), `on_change` (re-run ~250 ms after any `depends_on` value changes; a Refresh button is shown too). |
| `timeout_sec` | int | 15 | Provider killed past this → soft error state. |
| `cache` | enum | `form_session` | `form_session` memoizes per (command + upstream values) for one open form; `none` always re-runs. An explicit Refresh always bypasses the cache. |

## Provider contract

ScripTree spawns `command` (list argv, **no shell**) and writes a
single JSON object to its **stdin**:

```json
{"depends_on": {"source_drawing": "TR-0353-05.SLDDRW"}, "param_id": "pages"}
```

(Always sent, even with no `depends_on`. A provider may ignore stdin
and use its own flags instead.)

The provider **must** print one JSON document to **stdout**:

- For `enum` / `multiselect` / `checkbox_list` params:

  ```json
  {"choices": ["A.SLDDRW", "B.SLDDRW"],
   "choice_labels": ["A (30 sheets)", "B (7 sheets)"],
   "default": ["A.SLDDRW"]}
  ```

  `choices` required (flat string list — becomes argv verbatim).
  `choice_labels` optional, parallel. `default` optional (a list for
  multiselect, a string for enum).

- For any other type (`string` / `path` / `number` / …) — a **value
  provider**:

  ```json
  {"value": "C:/Users/Ken/Documents/active.SLDPRT"}
  ```

Exit 0 + valid JSON ⇒ applied. Anything else (non-zero exit,
timeout, malformed JSON, empty `choices`) ⇒ the param shows a **soft
error state** (error + provider stderr in the tooltip; choice
widgets show `(no items)`); the rest of the form stays usable; Run
is blocked only if that param is `required`.

**Sanitisation:** provider output is scrubbed exactly like parser
output — NUL bytes and control characters are stripped; every other
character (including shell metacharacters) is preserved, which is
safe because every spawn is `shell=False`.

## Behaviour

- **on_open**: providers run once during form build, in
  `depends_on` topological order (upstream first).
- **on_change**: ~250 ms debounce after any upstream value changes,
  then re-run. A prior selection is kept if still present in the new
  choices; otherwise it falls back to the provider's `default`.
- **manual / Refresh**: every provider param gets a per-field `⟳`
  button; the form also gets a **Refresh dynamic fields** button
  (for "the user opened another drawing after the form was up").
- `build_full_argv` is **never** involved — by argv time the chosen
  value is an ordinary string. Purity preserved.
- Cascades compose with `visible_when` / `required_when` unchanged.

## Security

Running an arbitrary command to build a form is gated by the
`dynamic_choices` capability (see `docs/security.md`). Shipped
**allowed** by default; an admin denies it by making
`permissions/running/dynamic_choices` read-only. When denied, a tool
with `choices_provider` still loads but the dynamic params render
disabled with a one-line note (usable if they aren't required —
same fallback as `interactive`).

## v1 limitations (documented, not bugs)

- Providers run **synchronously** (bounded by `timeout_sec`); there
  is no background spinner yet.
- The provider's environment is the inherited process environment —
  `tool.env` / `path_prepend` layering is **not** applied to the
  provider (only to the tool itself). Use absolute or
  `.scriptree`-relative `command` paths; don't rely on a
  tool-specific PATH prepend inside the provider.
- A stored config value no longer present in freshly-pulled choices
  is dropped by the widget rather than preserved-and-flagged.

## Authoring rules (for AI agents)

1. Prefer a static `choices` list. Reach for a provider **only**
   when the options genuinely don't exist until form-open time.
2. `command` is a list, never a shell string. No user input is ever
   interpolated into it.
3. If `depends_on` is set, the provider must read stdin JSON
   (`depends_on[<id>]`) — don't assume flags.
4. The provider must exit non-zero on failure so ScripTree shows the
   error instead of treating garbage as choices.
5. `select_all` only with `widget: "checkbox_list"`. A static
   `choices` list and a `choices_provider` are mutually exclusive.
6. Trace one real run by hand: open the form, confirm the provider
   populates, pick values, confirm the emitted argv is what the
   underlying tool expects.

## Composing with `emit: "unselected"` (v0.8.0a50+)

A provider's response carries `{"choices": [...], "default": [...]}`.
When the response sets `default` equal to `choices` (every box
pre-checked), pairing with `emit: "unselected"` gives you a
deselect-to-act form for free: open all-checked → emit is `[]` →
Run is a no-op until the user unticks something.

Static-choice catalogs honour `emit: "unselected"` in both the UI
AND headless / CLI runs. Provider-backed catalogs honour it in
the UI only (v0.8.0a50 limitation — the complement requires the
widget's live choice set, which only exists in the UI path).
Worked example with full SWBomExcluded walkthrough:
[`checkbox_list_emit.md`](checkbox_list_emit.md).
