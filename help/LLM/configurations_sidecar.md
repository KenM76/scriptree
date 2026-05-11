# Configurations sidecar format (schema v1)

Per-tool saved form values, stored next to the `.scriptree` file as
`<full-name>.configs.json`. For example, `echo.scriptree` pairs with
`echo.scriptree.configs.json`.

Keeping per-user state out of the tool definition means a `.scriptree`
file can be committed to version control while the sidecar stays local.

## Shape

```json
{
  "schema_version": 1,
  "active": "string — name of the currently-selected configuration",
  "default_name": "string, optional — name of the set's default configuration (v0.2.2+)",
  "configurations": [
    {
      "name": "string, non-empty, unique within configurations[]",
      "values": { "param_id": "value", "...": "..." },
      "extras": ["raw argv token", "..."],
      "env": { "KEY": "value" },
      "path_prepend": ["directory", "..."],
      "ui_visibility": { "command_line": false },
      "hidden_params": ["param_id", "..."],
      "prompt_credentials": true
    }
  ]
}
```

### Field rules

- `schema_version` — int, currently `1`.
- `active` — must match one of `configurations[*].name`. If it doesn't,
  the loader falls back to the first configuration.
- `default_name` (v0.2.2+) — optional. Names the set's **default
  configuration** for standalone-mode launches. The runner / cell
  shell calls `ConfigurationSet.default_config()` which resolves in
  this order: (1) `default_name` if it points at a real configuration,
  (2) `active`, (3) first configuration. Empty string or absent field
  = no explicit default; fall through to `active`. The loader clears
  `default_name` when it points at a deleted/renamed configuration so
  legacy code that reads the field directly never gets a stale value.
  Omitted from the on-disk JSON when empty.
- `configurations` — always non-empty. The editor enforces "at least
  one" by disabling the Delete button when only one remains.
- `name` — unique within the set. The name `safetree` is reserved by
  ScripTree and cannot be used by users. Renames must preserve the
  index so the active selection survives.
- `values` — keyed by `ParamDef.id`. Keys that don't match any current
  param are preserved but ignored at run time (tolerates param renames
  or removals without data loss).
- `extras` — extra argv tokens appended after the template-resolved
  argv. These are raw, shell-style tokens but passed to Popen as a list
  — ScripTree does not split them further.
- `env` — per-configuration environment overrides, layered on top of
  `ToolDef.env`. Highest priority.
- `path_prepend` — per-configuration PATH prepends, layered on top of
  `ToolDef.path_prepend`. Configuration entries go earlier in the final
  PATH than tool entries (higher search priority).
- `ui_visibility` — dict controlling which UI elements are visible in
  standalone mode. Only non-default values are stored. Boolean keys:
  `output_pane`, `extras_box`, `tools_sidebar`, `command_line`,
  `copy_argv`, `clear_output`, `env_button`, `popup_on_error`,
  `popup_on_success`. All default to `true` except `popup_on_error`
  and `popup_on_success` (default `false`).
  String key: `config_bar` — `"hidden"`, `"read"`, or `"readwrite"`
  (default `"readwrite"`). Legacy `true`/`false` values auto-migrate
  to `"readwrite"`/`"hidden"`.
  The Visibility button is always hidden in standalone mode.
- `hidden_params` — list of param ID strings. These params are hidden
  from the form in standalone mode; their values come from `values`.
- `prompt_credentials` — boolean, default `false`. When `true`, clicking
  Run shows a credential dialog. The process is spawned under the entered
  user's security context via `CreateProcessWithLogonW` (Windows only).

### Compactness

Empty `env` and `path_prepend` fields are omitted from the on-disk JSON
to keep the sidecar small and stable under version control. Empty
`extras` and `values` are also omitted. `ui_visibility` is omitted when
all values are at defaults. `hidden_params` is omitted when empty.
`prompt_credentials` is omitted when `false`. `default_name` is
omitted when empty. Readers must treat missing fields as empty
collections / default values.

## Standalone-mode recipe (recommended for new tools)

**When you build a `.scriptree` for an end user (not a developer
testing the form), ship a "standalone" configuration that hides
the developer-facing controls and surfaces clear feedback.**

The Visibility button is already hidden in standalone mode, but
nine other UI elements default to *visible* because the runner
also serves as a tool-author IDE.  For end-user invocations
(launched from ScripTreeRing / the cell shell / the forest),
those controls are noise — and worse, they invite the user to
poke at the command line, copy argv, edit env vars, etc.

### Recommended `ui_visibility` for a standalone-launched tool

Drop this into the configuration the user will run from
ScripTreeRing.  Don't repeat it in every config — the sidecar
omits default values, so this configuration's `ui_visibility`
block will only carry the diffs from `true`.

```json
{
  "name": "standalone",
  "values": { /* per-param defaults */ },
  "ui_visibility": {
    "extras_box":       false,
    "command_line":     false,
    "copy_argv":        false,
    "env_button":       false,
    "tools_sidebar":    false,
    "popup_on_error":   true,
    "popup_on_success": true
  }
}
```

Mark it as the sidecar's default with the top-level
`default_name` field so a click-to-run cell picks it up::

```json
{
  "schema_version": 1,
  "active": "standalone",
  "default_name": "standalone",
  "configurations": [
    { "name": "default",    "values": {...} },
    { "name": "standalone", "values": {...},
      "ui_visibility": { ... as above ... } }
  ]
}
```

### Why each element is off by default in this recipe

| Element            | End-user-relevant? | Rationale for hiding |
|--------------------|--------------------|----------------------|
| `extras_box`       | No                 | Free-text additional argv tokens are a footgun for non-authors.  If the tool exposes a power-user flag it should be a typed `ParamDef`, not a raw token field. |
| `command_line`     | No                 | The live argv preview is a developer-IDE feature.  Showing it to end users invites manual editing of a string the param widgets already drive. |
| `copy_argv`        | No                 | Copying argv from the GUI is a debug-the-tool-author affordance. |
| `env_button`       | No                 | Per-run env overrides are a power-user knob; if the tool needs an env tweak, bake it into the configuration's `env` field. |
| `tools_sidebar`    | No                 | The list of other tools belongs in the cell shell's tree popup, not inside an end-user tool launch. |
| `popup_on_error`   | **Yes**            | When the output pane is hidden (or the user isn't watching it), a popup is how they learn the run failed.  Always on for standalone. |
| `popup_on_success` | **Yes**            | Same rationale — close-the-loop feedback for an end-user-friendly run.  If the tool prints meaningful stdout the user wants to read, keep `output_pane: true` AND `popup_on_success: true` so they get both. |

### When to deviate

Some tools genuinely need one of these elements visible.  Use
judgement, not the recipe verbatim, when:

* **`extras_box`** — keep visible if the tool wraps something
  whose flag surface is too large to model as `ParamDef`s
  (e.g. an `ffmpeg` passthrough wrapper that has to accept
  arbitrary argv from power users).
* **`command_line`** — keep visible (and `config_bar`
  `"readwrite"`) for **diagnostic** tools where seeing the exact
  argv is part of the workflow (e.g. a "show me what would run"
  smoke-test tool).
* **`copy_argv`** — leave on for tools end users want to
  reproduce in a shell (e.g. a CLI-tutor / cheatsheet tool).
* **`env_button`** — leave on if the user is expected to point
  the tool at different environments at run time and a typed
  param doesn't capture the dimension.
* **`tools_sidebar`** — leave on for "launcher hub" tools whose
  job is to navigate among related tools.
* **`popup_on_success`** — turn off for **fast / batch** tools
  the user fires repeatedly; popups become alert fatigue.
* **`output_pane`** — turn off for **silent** tools whose only
  output is a file on disk or a side effect; an empty output pane
  is just dead screen space.

The default should always be "hide it, justify exceptions."

### Hidden params

`hidden_params` lists param IDs the user shouldn't see in the
standalone form.  The values come from the configuration's
`values` block.  Use this for:

* Constants the configuration pins (e.g. a `mode` enum the
  standalone wires to `"production"`).
* Power-user knobs the standalone config doesn't expose (e.g.
  `--verbose`, debug flags).

Hidden params still apply to argv generation — they're hidden,
not unset.

## Default configuration set

When a `.scriptree` file is first saved and no sidecar exists, the
runner creates one with a single `default` configuration whose `values`
are the param defaults from the tool definition:

```json
{
  "schema_version": 1,
  "active": "default",
  "configurations": [
    { "name": "default", "values": { "message": "hello" } }
  ]
}
```

## Example with overrides

```json
{
  "schema_version": 1,
  "active": "verbose",
  "configurations": [
    {
      "name": "default",
      "values": { "message": "hi" }
    },
    {
      "name": "verbose",
      "values": { "message": "hello" },
      "extras": ["--debug"],
      "env": { "LOG_LEVEL": "debug" },
      "path_prepend": ["./debug-bin"]
    }
  ]
}
```

## Loader invariants

`configs_from_dict` enforces:

1. `schema_version` is an int and ≤ current.
2. `configurations` is a non-empty list.
3. Every `name` is non-empty and unique.
4. `active`, if given, is one of the names; otherwise the first entry
   becomes active.
5. `values` is a dict; `extras` / `path_prepend` are lists; `env` is a
   `dict[str, str]`.

## Environment merge order

At run time, `core.runner.build_env` produces the child environment in
this order (later wins):

1. `os.environ` (parent process env)
2. `tool.env` (from the `.scriptree`)
3. `configuration.env` (from the active sidecar entry)

For PATH prepends, the order is:

```
[config.path_prepend..., tool.path_prepend..., <original PATH>]
```

Config entries are earliest (highest search priority), then tool
entries, then whatever PATH was inherited. Relative entries are
resolved against `tool.working_directory` (or the executable's parent
if unset).

When all four sources of overrides are empty, `build_env` returns
`None`, which Popen treats as "inherit parent env unchanged" — cleaner
error output and no pointless env block in process dumps.

## Tree-level configurations sidecar

Tree files (`.scriptreetree`) have their own sidecar:
`<name>.scriptreetree.treeconfigs.json`. This maps each sub-tool to
a configuration name for standalone mode.

```json
{
  "schema_version": 1,
  "active": "default",
  "configurations": [
    {
      "name": "default",
      "tool_configs": {
        "./tools/backup.scriptree": "production",
        "./tools/restore.scriptree": "verbose"
      }
    }
  ]
}
```

- `tool_configs` maps relative tool paths (as they appear in the
  `.scriptreetree` file) to configuration names.
- When a tree is opened in standalone mode, each sub-tool tab uses
  the mapped configuration.
- If a referenced configuration no longer exists in the tool's sidecar,
  ScripTree creates a reserved `safetree` configuration with all UI
  hidden and popup dialogs enabled.

## Reserved configuration name: `safetree`

The name `safetree` (case-insensitive) is reserved by ScripTree. Users
cannot create, rename to, or save-as this name. ScripTree creates it
automatically as a fallback when a tree references a config that no
longer exists. The reserved config has all UI hidden and popup dialogs
enabled.

## Credential prompt

When `prompt_credentials` is `true` on a configuration, clicking Run
triggers a credential dialog before process spawn. The dialog collects:

- Domain (blank = local machine)
- Username
- Password
- "Remember for this session" checkbox

If remembered, credentials are stored encrypted in memory using a
one-time XOR pad (`core.credentials.SessionCredentialStore`). The
store key is `{tool_path}::{config_name}`. Credentials are never
written to disk; they live only until ScripTree exits.

On Windows, `spawn_streaming_as_user()` uses
`advapi32.CreateProcessWithLogonW` to launch the process under the
entered user's security context. On non-Windows, a warning is emitted
and the process runs normally.
