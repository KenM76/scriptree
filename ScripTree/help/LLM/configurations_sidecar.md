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
`prompt_credentials` is omitted when `false`. Readers must treat missing
fields as empty collections / default values.

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
