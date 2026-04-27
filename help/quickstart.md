# Quickstart

Get a tool running in ScripTree in under two minutes.

## Project layout

```
YourProject/
├── run_scriptree.py        ← double-click or run from terminal
├── run_scriptree.bat       ← Windows launcher
├── run_scriptree.sh        ← Linux / macOS launcher
├── permissions/            ← capability permission files (admin-managed)
│   ├── files/
│   ├── editing/
│   ├── running/
│   └── settings/
├── ScripTree/              ← the application code
│   ├── scriptree/          ← Python package
│   ├── tests/
│   ├── examples/
│   └── help/               ← you are here
└── ScripTreeApps/          ← your tools and tree launchers
```

## Prerequisites

- Python 3.11+
- PySide6 (`pip install PySide6`)

If PySide6 is missing, the launcher will offer to install it for you.

## Launch

```bash
python run_scriptree.py                     # IDE window
python run_scriptree.py tool.scriptree      # open a tool
python run_scriptree.py tool.scriptree -standalone   # standalone window
python run_scriptree.py tree.scriptreetree -standalone  # all tools as tabs
```

Or on Windows, double-click `run_scriptree.bat`.

## Three ways to create a tool

### Option A: Auto-parse from an executable (60 seconds)

1. **File → New tool from executable...**
2. Pick any `.exe`, `.py`, or `.sh` — ScripTree probes it for `--help`
   output and auto-generates a form.
3. Review the draft in the editor, click **Save**.
4. You're in the runner view. Fill in the form, click **Run**.

### Option B: Ask an AI

Point any AI assistant (Claude, ChatGPT, Copilot, etc.) at the
`help/LLM/` folder and ask it to create a `.scriptree` file. The LLM
docs contain complete JSON schemas and rules — the AI can generate
valid tool files on the first try.

Example: *"Read help/LLM/ and create a .scriptree for ffmpeg that
converts video files with resolution and codec options."*

### PowerShell cmdlets

ScripTree also parses PowerShell `Get-Help` output. Run
`Get-Help CmdletName -Full` and paste the output into the editor's
cached help text field.

## Build a tool from scratch (90 seconds)

1. **File → New blank tool**
2. Set **Executable** to the program path (e.g. `robocopy.exe`) — type
   it, click Browse, or drag the binary onto the field from Explorer
3. Add parameters: click **+**, set ID, label, type, widget
4. Write the **Argument template** using `{param_id}` placeholders
5. **Save as...** → `MyTool.scriptree`
6. Click **Run** to test — file/folder paths in form fields can also
   be set by dropping a file from Explorer onto the field

## Configurations

Save multiple sets of form values per tool:

- **Save** — overwrite the current configuration
- **Save as...** — create a new named configuration
- **Env...** — set per-configuration environment variables
- **Visibility...** — hide UI elements for standalone mode

Switch between configurations with the dropdown.

## Standalone mode

Strip away the IDE and show just the tool form:

- **View → Open current tool standalone** (Ctrl+Shift+S)
- **View → Open entire tree standalone** — all tools as tabs
- CLI: `python run_scriptree.py tool.scriptree -standalone`

In standalone mode, the active configuration's visibility settings
take effect — hide the command line, extras box, config bar, etc.

## Custom menus

Add custom menus to any `.scriptree` or `.scriptreetree` file:

```json
"menus": [
  {"label": "Open logs", "menu": "Tools", "command": "notepad C:\\logs\\app.log"},
  {"label": "-", "menu": "Tools"},
  {"label": "Restart service", "menu": "Tools", "command": "sc start MyService"}
]
```

Menus appear at the top of the form panel. Commands are executed
without a shell (safe from injection).

## Permissions

ScripTree uses blank files in a `permissions/` folder to control what
users can do. Each file's name is a capability; its filesystem
write permission determines access:

- **File writable** → capability allowed
- **File read-only** → capability denied
- **File missing** → capability denied (secure default)

IT deploys the folder as read-only, then grants write on specific
files per user/group. See [configurations.md](configurations.md) for
the full permissions reference.

Example: to let a user create new tools but not modify existing ones:

```
permissions/
├── files/
│   ├── create_new_scriptree       ← writable (allowed)
│   ├── save_scriptree             ← read-only (denied)
│   └── ...
```

## Security

- **Input sanitization** — form values are checked for shell
  metacharacters, path traversal, and UNC paths before every run
- **No shell execution** — `Popen` always uses `shell=False`; custom
  menus split commands safely via `CommandLineToArgvW` / `shlex`
- **Parser plugins** — user plugins only load with the
  `load_user_plugins` permission
- **Credentials** — encrypted in memory with one-time XOR pad; zeroed
  via `ctypes` buffer after use
- **Read-only files** — tools marked read-only on disk disable all
  editing and saving in the UI

## Settings

**Edit → Settings...** provides:

- **Layout** — remember window position and dock arrangement
- **Permissions path** — custom location for the permissions folder
- **Global environment** — KEY=VALUE pairs merged into every tool run
- **Global PATH** — directories prepended to PATH for every tool run
- **Override checkboxes** — global env/PATH can override or sit below
  tool-level settings

## Where to go next

- [The tool runner](tool_runner.md) — command preview, undo/redo, configs
- [The tool editor](tool_editor.md) — parameters, templates, sections
- [Configurations](configurations.md) — visibility, credentials, tree configs
- [File formats](file_formats.md) — `.scriptree` and `.scriptreetree` JSON
- [Parsers](parsers/README.md) — auto-parsing `--help` output
