# Configurations

A configuration is a named snapshot of the form values (and extras) for a
single tool. Configurations live in a **sidecar file** next to the
`.scriptree` file: if your tool is `foo.scriptree`, the configurations are
saved in `foo.scriptree.configs.json`.

## Why configurations?

Most tools get run with the same two or three variations over and over:

- A dev run and a prod run
- A "quick test" invocation and a "full batch" invocation
- A per-customer variant with different paths and credentials

Rather than re-typing the values every time, save each variant as a
configuration and switch between them with a single click.

## The configurations bar

In the runner view, the top strip looks like:

```
Configuration: [default ▾]  [Save] [Save as...] [Delete] [Edit...] [Env...]
```

- **The combo box** lists every saved configuration. Selecting one loads
  its values into the form. Switching configurations also resets the
  undo history — the undo stack belongs to the configuration you were
  editing.
- **Save** — overwrite the *active* configuration with the current form
  values. No prompt; it just saves.
- **Save as...** — prompt for a new name and create a new configuration
  with the current values. If a configuration with that name already
  exists, you're asked whether to overwrite it.
- **Delete** — remove the active configuration. Asks for confirmation.
  Disabled when only one configuration remains (the set must always have
  at least one entry).
- **Edit...** — open a popup to rename and reorder configurations.
- **Env...** — open the environment editor for the active configuration.
  See [environment.md](environment.md).
- **Visibility...** — open the visibility editor to control which UI
  elements appear in standalone mode, which parameters are hidden with
  locked values, and whether to prompt for alternate credentials before
  each run.

## The Edit popup

The Edit dialog shows a list of all configurations:

- **Drag** any row up or down to reorder.
- **Double-click** a row (or select it and hit **Rename**) to change its
  name inline.
- **Move up / Move down** buttons on the same row offer keyboard-friendly
  reordering.
- **OK** applies the changes; **Cancel** discards them.

Empty names and duplicate names are rejected with a warning dialog.
Reordering preserves each configuration's stored values and environment
overrides — the dialog tracks each row by an internal index, so renames
and reorders both survive cleanly.

## When configurations are disabled

The whole configurations bar is disabled when the tool was opened from an
in-memory `ToolDef` (no file path). Configurations need a stable disk
anchor to write the sidecar file; without one, they'd get lost as soon
as the view closed.

In practice this only happens transiently — as soon as you Save the tool
to disk, the bar lights up.

## Sidecar file format

The sidecar is a small JSON file:

```json
{
  "schema_version": 1,
  "active": "verbose",
  "configurations": [
    { "name": "default", "values": { "name": "hello" }, "extras": [] },
    {
      "name": "verbose",
      "values": { "name": "world" },
      "extras": ["--debug"],
      "env": { "LOG_LEVEL": "debug" }
    }
  ]
}
```

- `active` is the currently-selected configuration.
- Each configuration has `name`, `values` (keyed by param ID), `extras`
  (a list of raw argv tokens to append), and optional `env` /
  `path_prepend` for environment overrides.
- Empty `env` / `path_prepend` fields are omitted from the on-disk form
  to keep sidecar files compact.

Additional per-configuration fields (omitted when at their defaults):

- `ui_visibility` — which UI elements to show/hide in standalone mode.
  See **UI visibility** below.
- `hidden_params` — parameter IDs whose widgets are hidden in standalone
  mode. Their values come from the `values` dict instead.
- `prompt_credentials` — when `true`, clicking Run prompts for a
  username and password before spawning the child process.

The sidecar is separate from the `.scriptree` file so editing the tool
definition in one place and adjusting values in another can't conflict.
You can safely commit a `.scriptree` to version control and keep the
sidecar out of it (local per-user state), or vice-versa.

## UI visibility

Each configuration can control which UI elements appear when the tool is
opened in **standalone mode** (View → Open in standalone window or CLI
with `-configuration`). In the main IDE window, all elements are always
visible.

Open the **Visibility...** dialog from the configuration bar to toggle.
A note at the top reminds you that these settings only apply in
standalone mode — when docked in the IDE, all elements stay visible.

| Flag | Controls | Default |
|------|----------|---------|
| Output pane | The stdout/stderr output panel | on |
| Extra arguments box | The extras input area | on |
| Command line editor | The editable command preview | on |
| Copy argv button | The "Copy argv" action button | on |
| Clear output button | The "Clear output" action button | on |
| Configuration bar | Checkbox + dropdown (see below) | on / Read-Write |
| Environment button | The "Env..." button | on |
| Tools sidebar | The launcher tree (main window only) | on |
| Popup dialog on error | Show error popup when output hidden | off |
| Popup dialog on success | Show success popup when output hidden | off |

### Configuration bar modes

The configuration bar has three modes, set via a checkbox and dropdown:

- **Unchecked** — the entire config bar is hidden in standalone
- **Read only** — only the config dropdown is shown; users can switch
  between configurations to view them, but cannot save, delete, or edit
- **Read / Write** — full config bar with all buttons

The **Visibility button itself is always hidden in standalone mode** —
it's an IDE-only control. Edit visibility settings from the main window.

When the output pane is hidden, enabling the popup flags ensures the user
still sees the result.

## Hidden parameters

In the same Visibility dialog, you can check individual parameters to
**hide** them from the form. Their values are locked to whatever you set
in the dialog's "locked value" field. This is useful for:

- Hiding an output path that's always the same
- Locking a "mode" dropdown to a specific value
- Removing expert-only flags from a simplified standalone interface

Hidden parameters only take effect in standalone mode. When docked in
the IDE, all parameters remain visible and editable.

## Run as different user (credential prompt)

Enable "Prompt for alternate credentials before each run" in the
Visibility dialog. When you click Run, a credential dialog appears with:

- **Domain** — DOMAIN or computer name (blank = local machine)
- **Username** — the account to run as
- **Password** — the account's password
- **Remember for this session** — caches the credentials (encrypted in
  memory with a one-time pad) until ScripTree restarts

When credentials are cached, a blue indicator appears on the action row
showing the active user (e.g. "Run as: CONTOSO\admin").

This feature uses `CreateProcessWithLogonW` on Windows. On other
platforms it falls back to a normal spawn with a warning.

## Tree configurations

When a `.scriptreetree` file groups multiple tools, you can assign a
configuration to each sub-tool for standalone mode. Use **View → Open in
standalone window** with a tree loaded — each tool appears on its own
tab with its assigned configuration applied.

Tree configurations are stored in a separate sidecar:
`<name>.scriptreetree.treeconfigs.json`.

If a referenced configuration gets deleted from a tool's sidecar,
ScripTree automatically creates a reserved `safetree` configuration that
hides all UI elements and enables popup dialogs. The name `safetree` is
reserved — users cannot create or rename to it.

## CLI arguments

```
scriptree [file] [-standalone] [-configuration NAME]
```

- `file` alone → opens the main IDE with the file loaded
- `file` + `-standalone` → opens a standalone window with the tool's
  active configuration
- `file` + `-configuration NAME` → opens a standalone window with the
  named configuration (implies `-standalone`)
- No arguments → normal IDE startup

## Permissions

The configurations bar buttons are also controlled by the permission
system. See [security.md](security.md) for the full reference.

## Settings

Global environment variables and PATH entries from **Edit → Settings**
are merged into every tool run. See [settings.md](settings.md).
