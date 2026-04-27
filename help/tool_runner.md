# The tool runner

The tool runner is the view you spend most of your time in. It shows:

1. A **header** — the tool's name and description blurb. Collapsible
   (v0.1.12).
2. A **form** built from the tool's parameters (text boxes, file pickers,
   dropdowns, checkboxes, etc.).
3. An **extras box** where you can type raw argv tokens that aren't part of
   the template. Collapsible.
4. A **command preview** showing the exact command that will run.
   Collapsible.
5. An **output pane** that streams stdout and stderr from the child process.
6. A **configurations bar** for saving, loading, and switching between
   named sets of form values.
7. An **action row** with Run, Stop, Copy argv, Undo, Redo, Reset, Clear
   output buttons, and a user indicator (when running as a different user).

## Layout (v0.1.12)

The form panel is split into two regions by a draggable splitter
handle:

- **Top region** — the (collapsible) header followed by the form
  parameters. This is "what the user fills in".
- **Bottom region** — the **Extra arguments** box and the **Command
  line** preview. This is "what actually gets run". Both boxes are
  individually collapsible so you can hide whichever isn't relevant
  (e.g. close the cmd preview when you only ever drive the form).

The bottom region is exposed as its own dock widget — **Run controls**
in the *View* menu — so you can float it, tab it next to Output, or
hide it entirely. The Output pane is its own dock too. With both
floated you can keep just the form on screen while running.

Drag the splitter handle to re-balance the form vs. extras+cmd. Click
the title-bar checkbox of any collapsible group box to fold it down to
just the title.

## The form

Each parameter becomes one widget. Types and widgets are defined in the
editor; here in the runner the widget is just what it is:

- `text` / `textarea` — QLineEdit / multi-line editor
- `number` — spin box
- `checkbox` — boolean flag
- `dropdown` — enum choices, with human-readable labels if the tool author
  defined them (see [tool_editor.md](tool_editor.md))
- `file_open`, `file_save`, `folder` — native Windows file pickers

**Drag-and-drop (v0.1.11):** every text-based widget accepts file/folder
drops from Explorer. Drop a file on a `text` or `file_*` / `folder`
field — its path replaces the field's value. Drop one or more files on
a `textarea` field — the paths are inserted at the cursor, one per line
(handy for the auto-split repeatable-flag pattern: drop three files to
get `--include path1 --include path2 --include path3` after splitting).
Native text drag still works as a fallback for non-file payloads.

**Reordering:** you can drag any form row up or down using the ≡ handle on
the left of the row. The new order is saved back to the `.scriptree` file
immediately. Inside a section, reordering only shuffles that section's rows.

## Sections

If the tool author has grouped parameters into sections, you'll see one
collapsible group box per section. Click the group title to collapse or
expand it — the collapsed state is saved per-tool. See
[sections.md](sections.md).

## The configurations bar

The row at the top with "Configuration: [▾]" lets you save multiple named
sets of form values per tool. See [configurations.md](configurations.md).

The **Env...** button next to the configurations combo box opens a popup
for setting per-configuration environment variables and PATH entries. See
[environment.md](environment.md).

The **Visibility...** button opens a dialog for controlling which UI elements
are visible in standalone mode, hiding individual parameters with locked
values, and enabling the run-as-different-user credential prompt. See
[configurations.md](configurations.md).

## The command preview

Below the form is a single-line editable text field showing the full argv
that will be passed to the child process when you click Run, as a
shell-style display string.

The preview is **two-way editable**:

- Edit a form widget → the preview updates.
- Type directly into the preview → ScripTree parses your edit and pushes
  changes back into the form widgets. Tokens that don't match any template
  entry land in the **extras box** and are appended verbatim to the argv
  at run time.

The **Full path** checkbox on the left controls whether the executable is
shown with its full path or just the basename (cosmetic only — the real
`Popen` call always uses the full path).

### Undo / Redo / Reset

Each successful edit to the command preview snapshots the form state. The
action row below has four buttons for managing that history:

- **Undo** — step back one edit
- **Redo** — step forward one edit (if you haven't overwritten it)
- **Reset** — restore every form field to the tool's original defaults
  and clear all extras. Asks for confirmation.
- **Clear output** — wipe the output pane. Asks for confirmation.

If you undo several steps and then make a new edit, the redo tail is
discarded (standard "fork the timeline" behavior).

Switching configurations via the combo also resets the undo history —
the history belongs to the active configuration, and walking it across a
switch would be confusing.

## Running the tool

Click **Run**. ScripTree:

1. Validates required parameters — missing values produce a warning dialog.
2. If the active configuration has **prompt for credentials** enabled,
   ScripTree checks for cached credentials first. If none are cached,
   a credential dialog appears asking for username, domain, and password.
   Check "Remember credentials for this session" to avoid being prompted
   again until you restart ScripTree.
3. Builds the full argv from the template + form values + extras.
4. Merges `os.environ` with the tool-level env and the active
   configuration's env overrides; prepends PATH entries.
5. Spawns the child process with the resolved argv, cwd, and env.
   If credentials were provided, the process runs under that user's
   security context (Windows only, via `CreateProcessWithLogonW`).
6. Streams stdout and stderr into the output pane line by line.

The Run button is disabled while a process is live. When the process
finishes the exit code and duration are appended in grey.

When running as a different user, a **user indicator** appears on the
right side of the action row showing the active username and domain
(e.g. "Run as: CONTOSO\admin").

### When the executable can't be found

If the resolved `argv[0]` doesn't exist on disk (or, for a bare name,
isn't on PATH), ScripTree intercepts the launch and shows a recovery
dialog instead of letting the spawn fail with a cryptic OSError. You
can either browse / type / drop a replacement file path, or pick a
search-path scope (session-only, this tool's `path_prepend`, the
parent tree's `path_prepend`, user PATH, system PATH) and let the
search-path lookup find it next time. See
[environment.md](environment.md#adding-to-path-from-the-missing-executable-recovery-dialog)
for the per-scope behavior table — non-session scopes also rewrite
`tool.executable` to the basename so PATH lookup is actually consulted
on subsequent runs.

### Output formatting and ANSI colors

ScripTree publishes `NO_COLOR=1`, `TERM=dumb`, `CLICOLOR=0`, and
`FORCE_COLOR=0` to the child process environment so well-behaved
CLIs emit plain text. Any ANSI escape sequences that slip through
anyway (some tools force colors regardless) are stripped from the
output pane via a regex before display, so you never see literal
`@[31m...@[0m` glyphs in your tree output.

## Standalone mode

Use **View → Open in standalone window** (Ctrl+Shift+S) to pop the
current tool out of the IDE into a clean, lightweight window. In
standalone mode, the active configuration's **UI visibility** settings
take effect — hiding the command line, extras box, configuration bar,
or any other element you've turned off.

When the output pane is hidden, popup dialogs appear on error or success
(controlled by the "Popup dialog on error/success" visibility flags).

Hidden parameters are also only hidden in standalone mode. When docked
in the main IDE window, all controls remain visible so you always have
full access.

You can also launch directly into standalone mode from the command line:

```
scriptree my_tool.scriptree -configuration standalone
```

## Custom menus

If the `.scriptree` file defines a `"menus"` array, a menu bar appears
at the top of the form panel. Menu items execute their command when
clicked. Commands are split safely (no shell) via `CommandLineToArgvW`
on Windows or `shlex.split` on other platforms.

## Input sanitization

Before every run, ScripTree checks all form values for:

- Null bytes and control characters
- Shell metacharacters (`;|&`$<>{}()!`)
- Path traversal (`../`) on path-type fields
- UNC paths (`\\server\share`) on path-type fields

If issues are found, a warning dialog appears. You can proceed or cancel.

When the `injection_protection_on_editor` permission file is present
and writable, the extras box and command-line editor are also checked.
If the file is not present, the warning includes instructions on how
to add it.

## Copy argv

The **Copy argv** button copies the current command display to the
clipboard. Useful if you want to paste the command into a terminal to
debug it outside ScripTree.

## The extras box

Above the output pane there's a small monospace box labeled "Extra
arguments". Whatever you type here is appended to the argv at run time,
after the template-resolved tokens. When you edit the command preview
directly, tokens that don't match any `{placeholder}` land here
automatically.

## Read-only files

When a `.scriptree` file or its sidecar is read-only on disk, a
"🔒 Read-only" indicator appears in the configuration bar and all
editing buttons are disabled. Run still works. See
[security.md](security.md).
