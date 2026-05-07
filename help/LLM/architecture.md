# Architecture

ScripTree is a Python 3.11+ / PySide6 application. V3 splits the
package into three layers: a portable `core/` (pure Python, no Qt
imports), a replaceable `ui/` (PySide6, the V1 editor), and a new
`shell/` (PySide6, the V3 cell + ring desktop launcher). A future
Linux/macOS fork swaps out `ui/` and `shell/` without touching
`core/`.

## Package layout (V3)

```
scriptree/
├── core/
│   ├── model.py       # ToolDef, ParamDef, SectionDef, TreeNode dataclasses
│   │                  #   ToolDef and TreeDef carry an optional `cell`
│   │                  #   sub-object (icon / text / scale / opacity).
│   ├── io.py          # .scriptree / .scriptreetree JSON load/save
│   ├── configs.py     # sidecar (Configuration, ConfigurationSet with
│   │                  #   default_name, UIVisibility, TreeConfiguration,
│   │                  #   safetree)
│   ├── credentials.py # session-scoped encrypted credential store
│   ├── runner.py      # argv assembly, env merging, subprocess spawn,
│   │                  #   spawn_streaming_as_user (Windows)
│   └── parser/
│       ├── plugin_api.py      # plugin protocol + registry
│       ├── probe.py           # --help / -h / /? probe sequence
│       └── plugins/
│           ├── argparse.py    # priority 10 — Python argparse
│           ├── click.py       # priority 20 — Python click
│           ├── powershell.py  # priority 25 — PowerShell Get-Help
│           ├── winhelp.py     # priority 30 — Windows /? help
│           ├── heuristic.py   # priority 999 — catch-all fallback
│           └── _core.py       # shared heuristic engine (not a plugin)
├── ui/                         # V1 editor (run via run_scriptree.bat)
│   ├── main_window.py         # menus, recent files, mode switch,
│   │                          #   View → standalone
│   ├── tool_editor.py         # property-panel editor with
│   │                          #   Configurations bar (incl. Default
│   │                          #   checkbox) and Cell label group
│   │                          #   (icon / text / scale / opacity +
│   │                          #   Embed / Unembed)
│   ├── tool_runner.py         # form + output pane + config bar +
│   │                          #   credential prompt + user indicator
│   ├── tree_view.py           # .scriptreetree launcher + Configs...
│   ├── standalone_window.py   # lightweight standalone window
│   ├── visibility_editor.py   # UI visibility + hidden params dialog
│   ├── credential_dialog.py   # username/password prompt dialog
│   ├── tree_config_editor.py  # tree-level configuration editor
│   ├── env_editor.py          # KEY=value text editor dialog
│   └── widgets/               # one file per widget type
├── shell/                      # V3 cell + ring shell
│   │                          #   (run via run_scriptreering.bat)
│   ├── ring_main.py           # entry point: QApplication, primary
│   │                          #   listener, autoload, --new-process
│   ├── single_instance.py     # QLocalServer pipe per user;
│   │                          #   try_handoff() for secondary processes
│   ├── cell_window.py         # CellWindow — frameless hex/square
│   │                          #   widget; click-toggle popup, drag
│   │                          #   snap, drop handling, role-aware
│   │                          #   right-click menu
│   ├── cell_registry.py       # CellRegistry — id → CellWindow lookup
│   ├── snap_engine.py         # honeycomb-neighbour snap detection,
│   │                          #   master spawn, undock-on-shake
│   ├── ring_io.py             # .scriptreering JSON load/save,
│   │                          #   position clamping, autoload list
│   ├── tree_popup.py          # in-process QMenu builder for the
│   │                          #   single-click cell popup; merges
│   │                          #   member sub-folders for masters
│   ├── merged_tree.py         # build_merged_tree_for_master:
│   │                          #   temp .scriptreetree per ring
│   │                          #   membership signature
│   ├── v1_launcher.py         # subprocess spawn into V1 (always
│   │                          #   passes -standalone for .scriptree
│   │                          #   tools)
│   ├── recent_files.py        # JSON-backed MRU per catalog type
│   └── branding_loader.py     # branding.config.json → app name,
│                              #   icon, default catalog folder
└── main.py                    # V1's argparse CLI:
                               #   [file] [-standalone] [-configuration NAME]
```

## V3 layering: core → ui → shell

The three packages form a strict dependency stack:

```
shell/   →   ui/   →   core/
```

- **`core/`** imports nothing from PySide6 (enforced by
  `tests/test_architecture.py`). The cross-platform seam.
- **`ui/`** is V1 — the editor and runner. Imports `core/` freely.
  Self-contained: it can run without `shell/` ever being loaded
  (`run_scriptree.bat`).
- **`shell/`** is V3's desktop launcher. Imports `core/` for model /
  io types but **never** imports `ui/`. The shell launches V1 as
  a subprocess (`v1_launcher.py`), not by importing `ToolRunnerView`
  or `MainWindow`. Two consequences:
  - A crash in the shell can't take down a running V1 editor.
  - A crash in V1 can't take down the cell shell.
  - V1 is updated by replacing the `ui/` package; the shell needs
    no recompile.

## The two launchers

| Launcher | Entry point | What runs |
|---|---|---|
| `run_scriptree.bat` | `scriptree/main.py` (`scriptree.main:main`) | V1 — the editor / runner. Argparse CLI: `[file] [-standalone] [-configuration NAME]`. |
| `run_scriptreering.bat` | `scriptree/shell/ring_main.py` (`scriptree.shell.ring_main:main`) | V3 — the cell shell. CLI: positional `.scriptreering` paths, `--load-ring`, `--autoload-rings`, `--register-autostart-{user,system}`, `--unregister-autostart {user,system}`, `--new-process`. |

Both launchers live in the same install. Users typically run the
shell. Clicking a tool inside the shell shells out to the V1 launcher
as a fire-and-forget subprocess via `sys.executable` (no `cmd.exe`,
no console flash) with the right `-standalone` / `-configuration`
flags built up by `v1_launcher.launch_tool`.

## Single-instance handoff (v0.2.1)

`shell/single_instance.py` provides a per-user `QLocalServer` pipe
named `ScripTreeRing--<sanitised-username>` (overrideable via
`SCRIPTREERING_PIPE_NAME` for tests).

`ring_main.main()` flow:

1. **Try handoff first.** If a primary is already listening, encode
   each positional arg as a JSON command (`spawn_cell`, `load_ring`,
   `load_catalog`), forward over the socket, wait for ack, exit 0.
2. **If no primary**, register `PrimaryServer` after `QApplication`
   construction. Inbound `messageReceived` routes into
   `_handle_primary_message`, which spawns sibling `CellWindow`
   instances in the running process — fully dockable with existing
   cells via the shared `SnapEngine`.
3. **`--new-process`** opts out of *both* halves: skip the handoff
   attempt and skip the primary listen. Useful for diagnostics; not
   recommended for everyday use because the diagnostic instance's
   cells can't dock with the primary's.

The pipe name is per-user so two users on the same machine each get
their own primary process.

## The `core` / `ui` boundary

`core/` is importable standalone. All UI state transitions go through
pure functions in `core/` that take dataclasses in and return
dataclasses out. The UI layer is a view over those dataclasses plus a
bag of Qt-specific event handlers.

Enforced by a grep-based test: `tests/test_architecture.py` greps
`scriptree/core/` for any `PySide6` or `from PyQt` import and fails if
one slips in.

## Data flow — running a tool

1. `tool_runner.py` collects current form values into a `dict[str, Any]`.
2. It calls `core.runner.build_full_argv(tool, values, extras,
   config_env=..., config_path_prepend=...)`.
3. `build_full_argv` substitutes placeholders in `tool.argument_template`,
   appends `extras`, and calls `build_env` to merge `os.environ`,
   `tool.env`, and `config_env` with PATH prepends resolved against the
   tool's working directory.
4. The result is a `ResolvedCommand(argv, cwd, env)`.
5. `spawn_streaming(cmd, on_stdout, on_stderr)` does the Popen and
   streams line by line on a background thread. If the active
   configuration has `prompt_credentials=True`, step 5 uses
   `spawn_streaming_as_user()` instead, launching the process via
   `CreateProcessWithLogonW` (Windows) under the entered user's
   security context.

The UI layer only sees `ResolvedCommand` and line callbacks. It never
builds argv or env itself.

## Standalone mode

`StandaloneWindow` is a lightweight `QMainWindow` that renders tools
without the IDE chrome. `ToolRunnerView._standalone_mode` controls
whether `UIVisibility` flags and `hidden_params` take effect. When
`False` (default, docked in IDE), all controls are always visible.
When `True` (set only by `StandaloneWindow`), the configuration's
visibility flags hide/show individual elements.

CLI: `scriptree file.scriptree -standalone -configuration NAME` opens
directly in standalone mode. `-configuration` implies `-standalone`.
Tab wrapping is enabled in standalone tree mode so tabs don't scroll.

## Undo / redo

The runner stores form snapshots in a per-configuration history stack.
Each successful edit to a form widget or to the editable command preview
pushes a snapshot. Switching configurations wipes the stack — history
belongs to a single configuration.

Snapshots are shallow copies of the values dict plus a copy of the
extras list. They do **not** capture env overrides — those live on the
`Configuration` dataclass and are edited through a separate dialog.

## Parser plugins

Parsers are loaded via a plugin registry (`core/parser/plugin_api.py`).
Built-in plugins live in `core/parser/plugins/`. User plugins from
`SCRIPTREE_PARSERS_DIR` only load when the `load_user_plugins`
permission is granted.

All parser output is post-sanitized by `_sanitize_parsed_tool()` in
`probe.py`: shell metacharacters stripped from literal tokens and
defaults, control characters stripped from cached help text.

`core/parser/probe.py` runs `--help` / `-h` / `/?` / `help` against the
executable, scores the responses, and hands the best one to the registry.
Plugins run in ascending priority order; first non-None result wins.
`heuristic.py` at priority 999 is the catch-all.

Built-in plugin priority order:
1. argparse (10) — Python argparse
2. click (20) — Python click
3. powershell (25) — PowerShell Get-Help
4. winhelp (30) — Windows /? help
5. heuristic (999) — catch-all fallback

Each detector returns a `ToolDef` draft plus a `source` block recording
which detector won and the raw help text. The editor opens on the draft
— nothing is ever committed to disk without user confirmation.

## Testing strategy

- `tests/test_model.py`, `test_io.py`, `test_configs.py` — dataclass
  round-trips with minimal, full, and legacy-format fixtures.
- `tests/test_runner.py` — `build_full_argv` with every placeholder
  form, missing required params, bool flags, flag-value groups.
- `tests/test_env_overrides.py` — tool + config env layering, PATH
  resolution against working directories, the env editor parser.
- `tests/test_parser_*.py` — captured help-text fixtures from real
  tools (pip, ffmpeg, grep).
- `tests/test_powershell_parser.py` — PowerShell parser detection,
  type mapping, template generation.
- `tests/test_tool_runner_env.py` — UI integration with monkeypatched
  dialogs, running under `pytest-qt`.
- `tests/test_visibility.py` — UI visibility, hidden params, standalone
  mode, popup dialogs, CLI args.
- `tests/test_tree_configs.py` — tree configurations, safetree fallback,
  reserved name enforcement.
- `tests/test_credentials.py` — secure byte store, credential store,
  prompt_credentials serialization.

- `tests/test_permissions.py` — WriteAccess, file-level permission checks.
- `tests/test_capability_permissions.py` — capability system, recursive
  search, most-restrictive-wins, per-file inheritance, secure defaults.
- `tests/test_sanitize.py` — input sanitization, shell metacharacters,
  path traversal, UNC detection, split_command.

Aim for >90% coverage of `core/`. UI layer coverage is lower by design
— focus UI tests on state transitions, not pixel layout.

## Security architecture

See `help/security.md` for the full human-readable reference.

Key modules:

- `core/permissions.py` — `WriteAccess` (file-level read-only) +
  `PermissionSet` (capability system with recursive search, secure
  defaults, per-file inheritance, most-restrictive-wins)
- `core/sanitize.py` — `sanitize_value()`, `sanitize_all_values()`,
  `validate_resolved_path()`, `split_command()`
- `core/credentials.py` — `_SecureBytes` (XOR one-time pad),
  `SessionCredentialStore` (in-process encrypted cache)
- `core/runner.py` — `spawn_streaming_as_user()` with `ctypes`
  password buffer zeroization

Permission files are searched recursively by filename under the
permissions directory. Folder structure is organizational only.
App-level missing file = denied. Per-file missing = inherit from app.

Custom menus use `split_command()` (never `shell=True`).
