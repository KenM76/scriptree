# Getting started

ScripTree turns command-line tools into simple GUI wrappers. You define a
tool once — either by pointing ScripTree at an executable that has a `--help`
output, or by building a form from scratch — and from then on you run the
tool by filling in form fields and clicking **Run**.

For a 60-second walkthrough, see [quickstart.md](quickstart.md).

## Project layout

```
YourProject/
├── run_scriptree.py        ← main launcher
├── run_scriptree.bat       ← Windows double-click launcher
├── run_scriptree.sh        ← Linux / macOS launcher
├── permissions/            ← capability permission files
├── ScripTree/              ← application code + tests + help
└── ScripTreeApps/          ← your tool files and trees
```

## The two workflows

There are two ways to create a `.scriptree` file:

### 1. Auto-parse from an executable

Use **File → New tool from executable...** and pick an `.exe`, `.py`, `.sh`,
or `.bat`. ScripTree probes the tool with `--help`, `-h`, `/?`, and `help`
(in that order), parses whatever output it gets, and opens the editor with
a draft tool definition. Review it, adjust anything the parser got wrong,
and save.

This path works well for Python scripts using `argparse`, `click`, or
`docopt`, GNU-style Linux tools, Windows-style `/?` executables, and
PowerShell cmdlets (via `Get-Help`). It's less reliable for tools that
don't emit help text at all (many hand-rolled C# `.exe`s) or whose help is
unstructured prose (`ffmpeg`).

If probing produces nothing, ScripTree falls through to workflow 2 with the
executable path pre-filled.

### 2. Blank canvas

Use **File → New blank tool**. You get an empty editor; type the executable
path, add parameters one by one, and write the argument template. This is
the primary workflow for any tool that doesn't emit structured help.

### 3. Ask an AI

You can have an AI assistant (Claude, ChatGPT, Copilot, etc.) generate
`.scriptree` and `.scriptreetree` files for you. Point the AI at the
`help/LLM/` folder in this project and ask it to follow those specs.
The LLM docs contain the complete JSON schemas, field rules, loader
invariants, and argument template grammar — everything an AI needs to
produce valid tool files on the first try.

Example prompt: *"Read the files in help/LLM/ and create a .scriptree
file for robocopy with parameters for source, destination, and common
flags."*

## Your first tool in 90 seconds

Let's wrap the built-in `echo` command.

1. **File → New blank tool**
2. In the editor:
   - **Executable:** `/bin/echo` (or `echo` if it's on your PATH)
   - **Name:** `Echo demo`
3. Click **+** under Parameters to add a param:
   - **ID:** `message`
   - **Label:** `Message`
   - **Type:** `string` → **Widget:** `text`
4. In **Argument template** type: `{message}`
5. **Save as...** → pick a folder, save as `echo.scriptree`.
6. You're now in the runner view. Type something in the Message box and
   click **Run**. The output pane shows what `echo` printed.

## Running tools

Once you have a `.scriptree` file, you can launch the tool any time by using
**File → Open .scriptree...**, or group several tools into a launcher via
**File → Open .scriptreetree...**.

The runner view is described in detail in [tool_runner.md](tool_runner.md).

## Standalone mode

Launch a tool in a clean window that hides developer-facing controls:

- **View → Open current tool standalone** (Ctrl+Shift+S)
- **View → Open entire tree standalone** — all tools as tabs
- CLI: `python run_scriptree.py tool.scriptree -standalone`
- CLI with config: `python run_scriptree.py tool.scriptree -standalone -configuration myconfig`

The `-configuration` flag implies `-standalone`. In standalone mode,
the active configuration's UI visibility settings take effect — hide
the command line, extras box, configuration bar, etc.

See [configurations.md](configurations.md) for visibility and hidden
parameter setup.

## Portable tool folders

You can keep a `.scriptree` file together with its helper scripts,
executables, and vendor directories in one folder, then move that
folder anywhere without breaking anything. Relative paths in the
tool's `executable`, `working_directory`, and `path_prepend` fields
are resolved **against the .scriptree file's own location** — not
against wherever you happened to launch ScripTree from.

Writing them is easy: when you Save the tool in the editor, any
absolute path that sits inside the save folder is automatically
rewritten to `./subpath` form. Paths that point outside (like
`/usr/bin/python` or bare names like `python`) stay as-is.

This is the same self-contained folder model that `.scriptreetree`
files already use for their tool references.

## Custom menus

Add menus to any tool or tree by adding a `"menus"` array to the JSON:

```json
"menus": [
  {"label": "Open docs", "menu": "Help", "command": "start https://docs.example.com"}
]
```

Menus appear at the top of the form. See [file_formats.md](file_formats.md).

## Permissions and security

ScripTree includes a file-based permission system for controlling user
access. See [security.md](security.md) for the full reference.

## Settings

**Edit → Settings...** provides global environment variables, PATH
configuration, layout memory, and permissions path. See
[settings.md](settings.md).

## Where to go next

- [Quickstart](quickstart.md) — the 60-second version
- [The tool runner](tool_runner.md) — command preview, undo/redo, configs,
  menus, sanitization
- [The tool editor](tool_editor.md) — parameters, templates, sections
- [Configurations](configurations.md) — visibility, credentials, tree configs
- [Settings](settings.md) — global env, PATH, layout, permissions path
- [Security](security.md) — permissions, injection prevention, read-only
- [File formats](file_formats.md) — JSON schemas for all file types
