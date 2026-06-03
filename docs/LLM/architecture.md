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
│   │                          #   member sub-folders for masters.
│   │                          #   v0.8.0a28+: each leaf QAction
│   │                          #   carries an `_st_context` dict
│   │                          #   ({leaf_path, root_catalog_path,
│   │                          #    node_name, node_display_name});
│   │                          #   `_PerItemContextFilter` is
│   │                          #   installed recursively on every
│   │                          #   QMenu to intercept right-clicks
│   │                          #   on actions (Qt does NOT fire
│   │                          #   customContextMenuRequested for
│   │                          #   per-action right-click — see
│   │                          #   rags/lessons/
│   │                          #   qmenu_per_action_right_click.md).
│   ├── screen_watcher.py      # v0.8.0a26+: hooks every Qt screen-
│   │                          #   change signal (screenAdded /
│   │                          #   Removed / primaryScreenChanged /
│   │                          #   per-screen geometryChanged /
│   │                          #   availableGeometryChanged), 200 ms
│   │                          #   single-shot QTimer debounce, calls
│   │                          #   CellWindow._clamp_to_screen on
│   │                          #   every registered cell.  Installed
│   │                          #   from ring_main.py at startup.
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

## Install / uninstall apps (v0.8.0a23 + a26 + a27 + a28)

Pure-logic install lives in `scriptree.core.app_install`
(Qt-free, stdlib only — `os`, `re`, `shutil`, `zipfile`).
Public surface: `install_app(source, target_root, *,
conflict_mode)` plus the four `ConflictMode` values
(OVERWRITE / UPDATE / RENAME / CANCEL).  Two helpers
(`default_personal_root()` / `default_shared_root()`) return
the canonical install locations, honouring INI overrides at
`install.personal_root` / `install.shared_root` and falling
back to OS-specific defaults (`%LOCALAPPDATA%\ScripTree\Apps`
on Windows, `Library/Application Support/ScripTree/Apps` on
macOS, `XDG_DATA_HOME/ScripTree/Apps` on Linux).

The UI half lives in `shell.cell_window` (drop handler on the
forest master) and `shell.install_dialogs` (the conflict-
resolution + name-edit prompts).  Drop-install is gated on
the forest master only — drops on standalones, rings, or
ring members are ignored.

**Uninstall** lives on `ForestController` with signature:

```
def uninstall_app(
    self, path,
    *,
    remove_local_configs: bool = True,
    remove_shared_configs: bool = True,
) -> tuple[bool, str]
```

Both flags default `True` so legacy callers retain "rm-rf
the whole app folder, including any personal sidecars" — the
defaults match the v0.8.0a25 behaviour before the flags were
added.

Containment guard: refuses unless the catalog's parent
folder is a strict descendant of either install root.  The
ForestItem is removed and the path added to `forest.excluded`
BEFORE the rmtree so auto-discovery doesn't silently re-add
the app while delete is in progress.  Any open cell bound
to the catalog is closed first.

**Personal-sidecar match.**  When `remove_local_configs=True`,
`scriptree.core.configs.find_personal_configs_for_app` is
called: a TWO-PRONG match — sidecar's `source_filename` must
match a `.scriptree` / `.scriptreetree` inside the app folder
AND at least one of its `source_locations` must resolve to a
directory under the app folder.  Without the location prong,
two installs of the same-named tool would sweep each other's
personal data.  Stdlib-only (no Qt) so it's headlessly
testable; accepts an explicit `personal_dir` for hermetic
tests.

**Shared-sidecar backup.**  When `remove_shared_configs=False`,
every `*.scriptree.configs.json` / `*.scriptreetree.
treeconfigs.json` inside the app folder is `shutil.copy2`'d
to a sibling `<app>_uninstalled_configs/` (numbered `-2`,
`-3`... if the path is taken) BEFORE the rmtree.  If the copy
step fails, the whole uninstall is refused — the app folder
is never removed when its configs would otherwise be lost.

**UI entry points** (both pop the same checkbox dialog):

* `forest_controller._populate_forest_menu` adds an
  "Uninstall app from disk…" action to the cell's right-click
  Forest submenu when the right-clicked cell is bound to a
  catalog under an install root.
* `tree_popup._PerItemContextFilter` (per-action right-click
  in the cell's tool-popup tree) reaches the same handler
  via `hex_win._forest_menu_extension.__self__`.  See the
  "Per-action right-click in QMenu" section below.

`ForestController._on_uninstall_app(target)` accepts EITHER
a CellWindow OR a path string and routes both through the
same dialog + `uninstall_app` pipeline.

## Per-action right-click in QMenu (v0.8.0a28)

Pattern used by `tree_popup._PerItemContextFilter` to give
each leaf in the cell's tool-popup tree its own context menu.

Pitfall first: `QMenu` does **not** fire
`customContextMenuRequested` on actions — only on the menu's
empty area.  Setting `setContextMenuPolicy(Qt.CustomContextMenu)`
will silently do nothing per-action.

Working recipe:

1. **Stash context on each QAction** as a Python attribute
   (Qt's `setData` only stores a single QVariant — Python
   attrs let us stash arbitrary structured data):
   ```python
   act._st_context = {
       "leaf_path": str(p),
       "root_catalog_path": str(catalog),  # NOT leaf — tree
                                           # uninstall keys
                                           # off the catalog's
                                           # parent folder
       "node_name": name,
       "node_display_name": display_name,
   }
   ```

2. **A `QObject` event filter** watching both
   `QEvent.ContextMenu` (Windows synthesises this for
   right-click on menus) and `QEvent.MouseButtonPress` with
   `Qt.MouseButton.RightButton` (cross-platform fallback).
   `menu.actionAt(event.pos())` retrieves the QAction
   under the cursor.

3. **Install on every menu in the tree.**  Qt routes mouse
   events to the menu currently under the cursor, NOT the
   top-level menu — a filter only on the top-level catches
   nothing once a submenu opens.  `_install_per_item_context`
   walks `menu.actions()` recursively and re-installs on
   `aboutToShow` for lazily-populated submenus.  Sentinel
   attr `_st_per_item_filter_installed` makes the install
   idempotent.

4. **Parent the filter to the menu** (`flt.setParent(menu)`)
   so it dies with the popup — no leaked QObjects between
   invocations.

5. **For tree catalogs**, every leaf's `root_catalog_path`
   must point at the `.scriptreetree` itself, NOT the
   individual `.scriptree` the leaf launches.  The
   uninstall path scope is the catalog's parent folder; per-
   leaf paths would point at sub-directories that aren't a
   strict descendant of the install root.

## Display-change rescue (v0.8.0a26)

`scriptree.shell.screen_watcher` keeps cells visible across
display reconfigurations.  Hooks every Qt screen-change
signal at startup (via `screen_watcher.install(app)` in
`ring_main.py`):

* `QGuiApplication.screenAdded` / `.screenRemoved`
* `QGuiApplication.primaryScreenChanged`
* Per-screen `geometryChanged` and `availableGeometryChanged`

A 200 ms single-shot `QTimer` debounce — **stored on the
QApplication as `app._screen_rescue_timer`**, not on the
filter object — coalesces the storm of signals Qt fires when
a monitor is plugged in or resolution changes.  Storing the
timer on the app is what makes the debounce span signal
firings; a per-firing local timer would race.

The rescue itself walks `CellRegistry.instance().all()` and
delegates to `CellWindow._clamp_to_screen` — the same helper
drag-end uses — so behaviour stays identical to "drag the
cell off the edge and release."  Cells already on-screen are
left alone (the clamp is a no-op for valid positions).

A manual entry point lives at Forest right-click → "Bring
all cells back on-screen" (`forest_controller._on_rescue_offscreen`),
which calls `screen_watcher.rescue_all_cells()` directly.

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

See `docs/security.md` for the full human-readable reference.

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
