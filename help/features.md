# ScripTree Features

## Top 10

1. **Turn any CLI tool into a GUI form in seconds** — point ScripTree at an executable and it auto-parses `--help` output into a working form with labeled fields, dropdowns, file pickers, and checkboxes. Supports argparse, click, PowerShell, Windows `/flag`, and GNU-style tools.

2. **No shell execution, ever** — all tool launches use `subprocess.Popen` with argument lists, never `shell=True`. Shell metacharacters in form values are passed as literal strings, not interpreted. Custom menus are split safely via `CommandLineToArgvW` / `shlex`.

3. **Named configurations with one-click switching** — save multiple sets of form values per tool. Each configuration can have its own environment variables, PATH overrides, UI visibility, and hidden parameters. Switch between them with a dropdown.

4. **File-based permission system with secure defaults** — blank files in a `permissions/` folder control every user action. Missing file = denied. IT sets the folder read-only and grants write on specific files per AD group. No database, no license server, no cloud dependency.

5. **Standalone mode for end users** — strip away the IDE and show just the form. Hide the command line, extras box, config bar, or any element per-configuration. End users see a clean app; developers see the full toolbox.

6. **Input sanitization on every run** — form values are scanned for null bytes, control characters, shell metacharacters, path traversal, and UNC paths before every execution. Users see a clear warning and can cancel.

7. **Tree launchers** — group multiple tools into a `.scriptreetree` file. Open as a sidebar tree in the IDE or pop out as a standalone tabbed window. Custom menus on both tools and trees.

8. **Read-only enforcement from file permissions** — mark a `.scriptree` file read-only on disk and all editing is disabled in the UI. Users can run tools but not modify them. Works with both `attrib +R` and NTFS ACLs.

9. **Editable command preview with undo/redo** — see the exact command that will run, edit it directly, undo/redo changes. Edits are reconciled back into form values automatically. Copy argv to clipboard for external debugging.

10. **Fully portable — zero registry, zero install** — settings live in an INI file inside the application folder. Copy the folder to another machine and it works. No installer, no registry keys, no admin rights to run. One dependency (PySide6), auto-detected and auto-installed.

---

## Top 20

**User features:**

1. **Turn any CLI tool into a GUI form in seconds** — auto-parses `--help` output from argparse, click, PowerShell, Windows `/flag`, and GNU tools into a working form.

2. **Named configurations with one-click switching** — multiple saved form states per tool, each with its own environment variables, PATH overrides, visibility, and hidden parameters.

3. **Standalone mode for end users** — hide developer controls per-configuration. End users see a polished single-purpose app. Developers keep full access when docked in the IDE.

4. **Tree launchers with tabbed standalone** — group tools into `.scriptreetree` files. Open as a sidebar tree or pop out as a standalone window with each tool on its own tab.

5. **Editable command preview with undo/redo** — see the exact argv, edit it inline, undo/redo freely. Changes reconcile back into form values and extras automatically.

6. **Custom menus on tools and trees** — add menu bars with commands, submenus, shortcuts, and tooltips to any `.scriptree` or `.scriptreetree` file.

7. **AI-generated tool files** — point any LLM at the `help/LLM/` folder and it can generate valid `.scriptree` files from a plain-English description. Complete schemas and invariants included.

8. **Drag-and-drop everywhere** — rearrange form fields by dragging the row handle, drop files from Explorer onto any text or path widget to fill in the path, drop multiple files onto a textarea to insert one path per line. Collapsible sections and tabbed layouts.

9. **Global environment and PATH settings** — application-wide env vars and PATH entries with override checkboxes that control merge priority over tool-level settings.

10. **Fully portable — zero registry, zero install** — INI-based settings, no admin rights, one dependency. Copy the folder to another machine and run. Windows, Linux, macOS.

**Security features:**

11. **No shell execution, ever** — `shell=False` on every `Popen` call. Argument lists, not command strings. Custom menus split safely. Parser output post-sanitized.

12. **File-based permission system with secure defaults** — 34 capability files control every action. Missing file = denied. Recursive search by filename, most-restrictive-wins on duplicates.

13. **Input sanitization on every run** — null bytes, control chars, shell metacharacters, path traversal, UNC paths checked before execution. Warning dialog with proceed/cancel.

14. **Read-only enforcement from file permissions** — read-only `.scriptree` files disable all editing. Catches both `attrib +R` and NTFS ACLs without triggering audit events.

15. **Encrypted credential storage with immediate zeroization** — one-time XOR pad in memory, `ctypes` buffer zeroed after the Windows API call, session-scoped only, never written to disk.

16. **Per-file permission inheritance** — tools can bundle their own `permissions/` folder. Per-file can only restrict, never grant. Missing files inherit from app level. Conflicts resolve to most restrictive.

17. **Parser plugin gating** — user plugins from external directories only load when the `load_user_plugins` permission is granted. Built-in parsers always load. All parser output is post-sanitized.

18. **Symlink and path traversal protection** — controlled by permission files. Both default to denied when the permission system is deployed. Prevents redirecting tool paths to unexpected locations.

19. **Run as different user with secure handling** — launch tools under a different user's security context. Credentials encrypted in memory, cached per-session or prompted every time, wiped on checkbox uncheck.

20. **IT deployment in four steps** — deploy permissions folder read-only, grant write per AD group, set tool files read-only, done. No per-user config, no GPOs, no agents, no cloud.
