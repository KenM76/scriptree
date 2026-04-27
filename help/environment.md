# Environment variables and PATH

## Built-in `SCRIPTREE_*` variables

When ScripTree starts, it publishes these variables on its own
environment. They're inherited by every tool subprocess and are
also available as `%VAR%` / `$VAR` references inside tool
`.scriptree` fields (see "Path expansion" below):

| Variable | Value | Always set? |
|---|---|---|
| `SCRIPTREE_HOME` | The launcher directory (the folder holding `run_scriptree.py`) | Yes |
| `SCRIPTREE_LIB` | `<HOME>/lib` | Only if `lib/` exists |
| `SCRIPTREE_LIB_PYPI` | `<HOME>/lib/pypi` (vendored Python packages) | Only if `lib/pypi/` exists |
| `SCRIPTREE_LIB_PYTHON` | `<HOME>/lib/python` (portable Python install) | Only if `lib/python/` exists |
| `SCRIPTREE_APPS` | `<HOME>/ScripTreeApps` | Only if `ScripTreeApps/` exists |

Recommended use in a tool that ships its own Python helper:

```json
{
  "executable": "%SCRIPTREE_LIB_PYTHON%/python.exe",
  "argument_template": ["./my_helper.py", "{input}"],
  "env": {
    "PYTHONPATH": "%SCRIPTREE_LIB_PYPI%"
  }
}
```

Move ScripTree to a different folder and the same `.scriptree` file
keeps working — no path edits required. (See
[vendored_dependencies.md](vendored_dependencies.md) for the per-tool
`lib/` pattern that complements this.)

### Path expansion

`%VAR%` (Windows-style) and `$VAR` (Unix-style) references are expanded
in:

- `executable`
- `working_directory`
- `path_prepend` entries (tool-level, config-level, and global)

Both syntaxes work on every OS — the expansion is done by Python's
`os.path.expandvars`, which understands both forms regardless of host.
Unknown variables are left as the literal `%VAR%` text so the failure
is visible at run time instead of silently disappearing.

Argv tokens themselves are NOT auto-expanded — if you need an env var
in a positional argument, set it via `tool.env` and let the child
process expand it (or hard-code it into the template).

## User-defined env

ScripTree lets you set environment variables and PATH prepends on three
levels:

1. **Global** — set in **Edit → Settings**. Applied to every tool run.
   See [settings.md](settings.md).
2. **Tool-level** — stored in the `.scriptree` file. Applied to every run
   of the tool, regardless of which configuration is active.
3. **Configuration-level** — stored in the sidecar. Layered on top of the
   tool-level values for the active configuration only.

Default merge order (highest priority last):

```
os.environ → Global settings → Tool env → Config env
```

With the "Override" checkbox in Settings, global takes highest priority:

```
os.environ → Tool env → Config env → Global settings
```

PATH prepend follows the same pattern — global directories go after
tool/config by default, before them when override is enabled.

At run time the child process receives:

```
os.environ  →  tool.env  →  configuration.env   (highest priority wins)
```

PATH prepend entries from the tool and the configuration are both
concatenated (tool first, config second) and prepended to the child's
`PATH` before spawn.

## Tool-level (editor)

Open the tool editor and click **Edit environment...** next to the
Environment row in the Tool group box. A popup opens with two text
boxes:

```
Environment variables
  One KEY=value per line. Lines starting with # are comments.

  MY_VAR=hello
  # this is a comment
  API_KEY=secret

PATH prepend (directories)
  One directory per line.

  C:/tools/bin
  ./vendor
```

OK parses the text and writes the new env / path_prepend back onto the
`ToolDef`. Cancel discards the edit. The label next to the button
updates to show a short summary like "2 vars, 1 path" or "no overrides".

The tool-level env is saved as part of the `.scriptree` file when you
click Save in the main editor.

## Configuration-level (runner)

In the runner, click **Env...** on the configurations bar. The same dialog
opens, but edits the *active configuration's* env/path_prepend instead
of the tool's. OK writes the changes back to the active `Configuration`
and persists the sidecar immediately.

## Layering rules

1. Start with `os.environ` (the ScripTree process's own environment).
2. Apply `tool.env` on top — any variable in `tool.env` overrides the
   ambient value.
3. Apply `configuration.env` on top — any variable in the active config
   overrides both the tool and the ambient.

For PATH prepends: tool entries come first, then configuration entries,
then whatever PATH was already set. So a tool-level `./vendor` and a
config-level `./debug-bin` produce:

```
./debug-bin ; ./vendor ; <original PATH>
```

(Config entries have higher priority — they're earlier in the PATH
search order.)

## Relative paths

Directories in the PATH prepend list can be absolute or relative. Relative
directories are resolved against:

1. The tool's `working_directory` if one is set, else
2. The executable's parent directory.

So `./vendor` in a tool whose working directory is `C:/projects/foo`
becomes `C:/projects/foo/vendor` in the child's PATH.

## Comments and blank lines

The env editor supports `# comment` lines and blank lines in both text
boxes. They're preserved when you re-open the editor but stripped when
building the child environment — they exist as a "notes" channel for
you, not for the child process.

## Adding to PATH from the missing-executable recovery dialog

When ScripTree tries to launch a tool whose executable can't be found
(e.g. `gh.exe` got moved or was never installed), the recovery dialog
lets you browse to the file and then choose **how** to remember it:

- **Replace the path stored in this tool's .scriptree** — v1 behavior.
  The tool's `executable` field is rewritten to the absolute path
  you picked. Other tools keep their old paths.
- **Add folder to ScripTree session PATH** — modifies `os.environ`
  for the running ScripTree process. Affects every tool you launch
  this session; lost on exit.
- **Add folder to this tool's .scriptree path_prepend** — appends
  the parent directory to the tool's `path_prepend` list and saves
  the .scriptree file. Future launches of this tool (in any future
  ScripTree session) pick it up.
- **Add folder to this tree's .scriptreetree path_prepend** —
  appends to the tree's `path_prepend` (new in v0.1.11). Inherited
  by every tool launched via this tree.
- **Add folder to user PATH** — modifies `HKCU\Environment\Path`
  via the registry. Persistent, no admin needed.
- **Add folder to system PATH** — modifies `HKLM\...\Environment`
  via the registry. Persistent, **requires admin elevation**.

Per-file scopes (`scriptree` / `scriptreetree`) get an "apply to all
in sidebar" checkbox so a single dialog interaction can fix every
loaded tool/tree at once.

### Permission gates

Each scope has its own capability so IT can deny dangerous ones
while allowing safer ones. Default deployment ships:

| Capability | Default | Notes |
|---|---|---|
| `add_to_session_path` | **Allowed** (file ships) | Lost on exit, no admin |
| `add_to_scriptree_path_prepend` | **Allowed** (file ships) | Per-file, low blast radius |
| `add_to_scriptreetree_path_prepend` | **Allowed** (file ships) | Per-tree, low blast radius |
| `add_to_user_path` | **Denied** (file missing) | Modifies user-wide PATH |
| `add_to_system_path` | **Denied** (file missing) | System-wide; requires admin |

To enable user/system PATH at deployment time, an admin creates the
empty file `permissions/<category>/add_to_user_path` (or
`add_to_system_path`) in the ScripTree install directory. To deny a
default-allowed scope, mark its permission file read-only.

Denied scopes appear in the dialog as greyed-out radio buttons with
a "Disabled by IT — to enable, ask an admin to create..." note, so
users always understand why an option isn't available instead of
wondering whether it just doesn't exist.

### Auto-applied to the current session

Whenever a non-session scope succeeds, ScripTree also applies the
addition to the current session (via `add_to_session_path`) so the
in-progress run can pick up the new executable without waiting for
ScripTree to relaunch. This auto-add is gated by the same
`add_to_session_path` capability — if it's denied, the persistent
change still goes through but the current session won't see it
until the next ScripTree launch.

### What happens to `tool.executable`

The recovery dialog's scopes have different effects on the tool
file's `executable` field — picking a search-path scope is not
the same as just appending to a list:

| Scope | `tool.executable` after | `tool.path_prepend` | .scriptree saved? |
|---|---|---|---|
| Replace path | new absolute path | unchanged | yes |
| .scriptree path_prepend | basename only | += new directory | yes |
| .scriptreetree path_prepend | basename only | unchanged (the dir lands on the tree, not the tool) | yes |
| User PATH | basename only | unchanged | yes |
| System PATH | basename only | unchanged | yes |
| Session PATH | unchanged (transient) | unchanged | **no** |

Why basename rewriting? Windows only consults a search path when
the executable is a *bare* name like `gh.exe`. If `tool.executable`
is still an absolute path that no longer exists, no amount of
PATH editing helps — the OS just tries the absolute path verbatim
and fails. Stripping it to the basename forces resolution through
PATH / `path_prepend` from then on.

For the *current* run, regardless of scope, ScripTree pins the
already-built `argv[0]` to the absolute path you picked in the
dialog. That avoids any race where the search-path edit (registry
broadcast, `.scriptree` save, etc.) hasn't propagated to the
subprocess context yet — the in-progress run launches successfully
and future runs pick the basename up via the search path.

### Editable, drop-aware path field

The "Expected location" field in the recovery dialog is editable
and drop-aware (v0.1.11). You can:

- Type or paste a path directly, then press Enter or click Apply.
- Drag a file from Explorer onto the field — it replaces the text.
- Click **Browse for replacement...** for the native file picker.

In scope-picker mode, entering a path that points to a real file
auto-reveals the scope picker the same way Browse does. Typing
garbage (or erasing the field) hides the picker again until a real
path is supplied.

## When there are no overrides

If both `tool.env` and `configuration.env` are empty *and* both
`path_prepend` lists are empty, ScripTree passes `env=None` to
`subprocess.Popen`, which means the child simply inherits the parent
environment unchanged. This is the default state and produces cleaner
error messages when debugging (no giant env block in the process dump).

## Example: pinning a Python tool to a venv

Suppose you want `mytool.py` to run with a specific virtualenv's Python
on PATH:

**Tool-level env** (applies to every run):
```
VIRTUAL_ENV=C:/projects/mytool/venv
```

**Tool-level PATH prepend**:
```
C:/projects/mytool/venv/Scripts
```

Now every invocation finds the venv's `python.exe` first and sets
`VIRTUAL_ENV` correctly.

## Example: dev vs. prod configs

Two configurations — **dev** and **prod** — with different API keys:

**dev config env**:
```
API_URL=https://dev.api.example.com
API_KEY=dev_abcdef
LOG_LEVEL=debug
```

**prod config env**:
```
API_URL=https://api.example.com
API_KEY=prod_xyz
LOG_LEVEL=info
```

Switch between them with the configurations combo box. The right API key
flows into the child process every time.
