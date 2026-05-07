# Security Guide

ScripTree wraps command-line tools in GUI forms and launches them as
child processes. Any tool that launches executables carries inherent
risk. This document explains what ScripTree does to minimize that risk,
how administrators can lock down deployments, and what risks remain
that users and IT should be aware of.

---

## Overview of protections

| Layer | What it does |
|---|---|
| **Permissions system** | File-based capability control — denies actions by default |
| **Input sanitization** | Checks form values for injection characters before every run |
| **No shell execution** | All process launches use `shell=False` with argv lists |
| **Read-only enforcement** | Files marked read-only on disk disable all editing in the UI |
| **Credential encryption** | Passwords encrypted in memory, zeroed after use |
| **Plugin gating** | User parser plugins only load with explicit permission |
| **Template sanitization** | Parser-generated tool files are scrubbed of dangerous characters |
| **Settings in INI file** | No registry usage — settings travel with the application |

---

## Permissions system

### Concept

ScripTree uses blank files in a `permissions/` folder to control what
users can do. Each file's **name** is a capability. Its **filesystem
write permission** determines whether the current user has that
capability.

| File state | Result |
|---|---|
| File exists and is writable by the user | **Allowed** |
| File exists but is read-only for the user | **Denied** |
| File does not exist | **Denied** (secure default) |
| No `permissions/` folder found at all | Everything allowed (developer mode) |

The "missing = denied" default is critical: if someone copies ScripTree
to a local machine and deletes permission files, they lose access rather
than gaining it.

### Folder organization

IT can organize permission files into any subfolder structure — by
department, role, site, or any scheme that makes sense. ScripTree
searches **recursively by filename**. The folder hierarchy is purely
for human organization.

```
permissions/
├── engineering/
│   ├── save_scriptree          (writable → allowed for engineers)
│   └── edit_configurations     (writable)
├── operators/
│   ├── run_tools               (writable)
│   └── save_scriptree          (read-only → denied for operators)
├── admin/
│   ├── change_permissions_path (writable)
│   └── load_user_plugins       (writable)
└── security/
    ├── allow_symlinks          (read-only → denied for everyone)
    └── allow_path_traversal    (read-only → denied for everyone)
```

### Most-restrictive-wins

When the same filename appears in multiple subfolders (e.g. a user
belongs to both "engineering" and "operators"), the **most restrictive**
result wins. If any copy of the file is read-only, the capability is
denied for that user.

### All capability files

| Category | File name | Controls |
|---|---|---|
| **Files** | `create_new_scriptree` | Creating new .scriptree files |
| | `create_new_scriptreetree` | Creating new .scriptreetree files |
| | `save_scriptree` | Saving .scriptree files |
| | `save_scriptreetree` | Saving .scriptreetree files |
| | `save_as_scriptree` | Save As for .scriptree files |
| | `save_as_scriptreetree` | Save As for .scriptreetree files |
| **Editing** | `edit_tool_definition` | Opening the tool definition editor |
| | `read_configurations` | Switching between saved configurations (read-only) |
| | `write_configurations` | Creating, saving, deleting, renaming configurations |
| | `edit_configurations` | Modifying saved configurations |
| | `edit_environment` | Changing environment variable overrides |
| | `add_to_scriptree_path_prepend` | Appending to a `.scriptree`'s `path_prepend` via the missing-executable recovery dialog (default-allowed) |
| | `add_to_scriptreetree_path_prepend` | Appending to a `.scriptreetree`'s `path_prepend` via the missing-executable recovery dialog (default-allowed) |
| | `edit_visibility` | Changing UI visibility and hidden parameters |
| | `edit_tree_structure` | Adding, removing, or reordering tree items |
| | `reorder_parameters` | Drag-drop reordering of form parameters |
| | `command_line_editor` | Accessing the command-line preview editor |
| | `injection_protection_on_editor` | Enabling injection checks on the command-line editor and extras box |
| **Running** | `run_tools` | Executing tools via the Run button |
| | `run_as_different_user` | Using the alternate credentials feature |
| | `access_settings` | Opening the Settings dialog |
| | `load_user_plugins` | Loading parser plugins from external directories |
| | `access_sensitive_paths` | Accessing paths outside the tool's own directory |
| | `add_to_session_path` | Adding a directory to the running session's `os.environ['PATH']` via the missing-executable recovery dialog (default-allowed) |
| **Settings** | `change_permissions_path` | Changing where permissions are loaded from |
| | `change_settings_path` | Changing the settings INI file location |
| | `add_to_user_path` | Modifying the current user's PATH via the registry (default-**denied** — admin must opt in) |
| | `add_to_system_path` | Modifying the system-wide PATH via the registry; requires admin elevation (default-**denied** — admin must opt in) |
| **Security** | `allow_symlinks` | Allowing symlinks in tool/tree path resolution |
| | `allow_path_traversal` | Allowing `../` in tree leaf paths |

#### PATH-add scopes — secure-by-default

The five `add_to_*_path*` capabilities all gate the missing-executable recovery dialog's "add folder to a search path" options. Three ship default-allowed (file present in `permissions/`); two ship default-denied (file missing) and require an admin to create the empty capability file before they appear in the dialog. The default-denied set is the high-blast-radius pair: modifying the user's PATH or the system PATH would persist across sessions and affect every program the user runs, not just ScripTree.

Denied scopes appear in the dialog as greyed-out radio buttons with a "Disabled by IT — to enable, ask an admin to create..." note, so users always understand why an option isn't available.

### Per-file permissions

Individual `.scriptree` and `.scriptreetree` files can have their own
`permissions/` folder alongside them. These per-file permissions:

- Can only **restrict** capabilities — they cannot grant anything the
  app-level permissions deny
- **Inherit** from the app-level when a file is missing (no restriction
  from this source)
- When both levels exist and disagree, a conflict is recorded and the
  result is always the more restrictive (denied)

This lets administrators distribute tools with locked-down per-file
permissions while still allowing broader access at the application level
for other tools.

### Setting up permissions for a server deployment

1. Create the `permissions/` folder with all capability files you want
   to manage
2. Set the entire folder tree to **read-only** for the "Users" or
   "Domain Users" group via NTFS ACLs
3. Grant **write** permission on specific files to specific Active
   Directory groups
4. Users who can write to a capability file have that capability;
   everyone else is denied

No per-user configuration is needed — it's all driven by the same NTFS
ACLs your organization already uses.

### Technical details

The permission check uses `os.access(path, os.W_OK)` as a fast check,
followed by a non-destructive `os.open(O_APPEND | O_WRONLY)` + immediate
`os.close()` on Windows to catch NTFS ACL denials that `os.access`
misses. This approach:

- Does **not** trigger security audit events in most configurations
- Does **not** modify the file or its timestamps
- Does **not** cause UAC prompts or credential dialogs
- Works with both `attrib +R` and NTFS ACL deny rules

---

## Input sanitization (anti-injection)

### What is checked

Before every tool run, ScripTree scans all form values for dangerous
content:

| Check | Applies to | Action |
|---|---|---|
| **Null bytes** (`\x00`) | All fields | Warned — can truncate strings at the OS level |
| **Control characters** (`\x01`–`\x1F`) | All fields | Warned — can confuse terminals and log parsers |
| **Shell metacharacters** (`;|&`$<>{}()!`) | All fields | Warned — dangerous if child process re-interprets them |
| **Path traversal** (`../`, `..\`) | Path-type fields only | Warned — may access files outside expected directory |
| **UNC paths** (`\\server\share`) | Path-type fields only | Warned — can trigger NTLM credential harvesting |

When warnings are detected, a dialog appears listing every issue. The
user can choose to proceed or cancel.

### Command-line editor and extras box

By default, the command-line editor and extras box are **not** checked
for injection — users with access to those fields are assumed to be
trusted (they can type arbitrary commands).

To enable injection checking on those fields too, add the
`injection_protection_on_editor` permission file to your permissions
folder and make it writable. When this file is missing, the warning
dialog includes instructions on how to add it.

### Why warn instead of block?

Some legitimate tool arguments contain characters that look suspicious
(e.g. a regex with `|`, a PowerShell command with `$`). Blocking them
outright would break real workflows. The warning gives the user a chance
to review and confirm.

---

## No shell execution

ScripTree **never** passes commands through a shell interpreter:

- **Tool runs** use `subprocess.Popen(argv_list, shell=False)` — the
  argv is always a Python list, never a string. Shell metacharacters
  in form values are passed as literal arguments to the child process,
  not interpreted by `cmd.exe` or `bash`.
- **Custom menus** split command strings into argv lists using
  `CommandLineToArgvW` on Windows or `shlex.split` on Linux/macOS.
  This handles quoted paths correctly without invoking a shell.
- **Parser-generated templates** are post-sanitized: shell
  metacharacters are stripped from literal tokens and parameter
  defaults after every parser plugin runs.

### What this means in practice

If a malicious `.scriptree` file sets a form default to `hello; rm -rf /`,
the semicolon is passed as part of the literal string to the child
process — it is **not** interpreted as a command separator by a shell.
The child process receives the exact string `hello; rm -rf /` as one
argument.

---

## Read-only file enforcement

When a `.scriptree` or `.scriptreetree` file is marked read-only on
disk (via `attrib +R` on Windows or `chmod a-w` on Linux), ScripTree
disables all editing:

- Save, Save As, Delete, Edit, Env, Visibility buttons → **disabled**
- Configuration rename/reorder dialog → **disabled**
- Section collapse and param reorder → silently skip saving
- Config combo still switches → loads values in-memory only
- A **🔒 Read-only** indicator appears in the configuration bar

**The Run button still works** — read-only status affects editing, not
execution. This is by design: administrators distribute locked-down
tool files that users can run but not modify.

The check covers both the `.scriptree` file itself and its `.configs.json`
sidecar. If either is read-only, editing is disabled.

---

## Credential handling

When "Prompt for alternate credentials" is enabled on a configuration,
ScripTree takes several steps to protect the password:

1. **Encryption in memory** — passwords are stored using a one-time
   XOR pad (random bytes from `os.urandom`). The pad and ciphertext
   are stored as mutable `bytearray` objects, not Python strings.
   Python strings are immutable and may be interned by the runtime;
   `bytearray` can be explicitly zeroed.

2. **Buffer zeroization** — when passing the password to the Windows
   API (`CreateProcessWithLogonW`), ScripTree uses a `ctypes` unicode
   buffer instead of a Python string. The buffer is zeroed immediately
   after the API call returns.

3. **Session-scoped storage** — cached credentials (when "Remember
   for session" is checked) are held in an in-process store. Nothing
   is written to disk, the registry, or any file. Credentials are lost
   when ScripTree exits.

4. **Explicit wipe** — unchecking "Prompt for alternate credentials"
   immediately wipes any cached credentials for that configuration.

### Limitations

- A debugger attached to the ScripTree process can read memory,
  including the brief moment when the password is in plaintext on
  the call stack. This is inherent to any program that uses passwords.
- Python's garbage collector may copy `bytearray` contents during
  reallocation. On CPython with reference-counted GC this is unlikely
  for fixed-size arrays, but not guaranteed.
- The feature is Windows-only (`CreateProcessWithLogonW`). On other
  platforms it falls back to a normal process launch with a warning.

---

## Parser plugin security

### Built-in plugins

The five built-in parsers (argparse, click, PowerShell, Windows help,
heuristic) always load. They ship with ScripTree and are subject to
the same code review as the rest of the application.

### User plugins

Administrators can extend ScripTree with custom parser plugins by
placing Python files in directories listed in the `SCRIPTREE_PARSERS_DIR`
environment variable.

**Risk:** user plugins execute arbitrary Python code when loaded. A
malicious plugin can do anything the user account can do.

**Mitigation:** user plugin loading is gated by the `load_user_plugins`
permission. If the permission file is missing or read-only, only built-in
parsers load. In a locked-down deployment, keep this permission denied.

### Post-parse sanitization

Regardless of which parser plugin runs, all output is automatically
sanitized before being saved to a `.scriptree` file:

- Shell metacharacters (`;|&`$<>{}()!`) are stripped from literal
  tokens in the argument template
- Shell metacharacters are stripped from parameter default values
- Control characters are stripped from cached help text

This prevents a crafted `--help` output from injecting dangerous content
into the generated tool definition.

---

## Symlink and path traversal protection

### Symlinks

Symbolic links can redirect file access to unexpected locations. When
the `allow_symlinks` permission is denied (the default in a locked-down
deployment), ScripTree rejects paths that contain symlinks.

### Path traversal

`../` sequences in `.scriptreetree` leaf paths can reference files
outside the expected directory. When the `allow_path_traversal`
permission is denied, ScripTree rejects leaf paths that resolve outside
the tree file's directory.

Both protections default to denied when the permissions system is
deployed (secure default).

---

## Settings security

ScripTree stores all settings in an INI file (`scriptree.ini`)
inside the application folder. **No registry access is used.** This
means:

- Settings travel with the application when copied to another machine
- No registry keys are created or modified
- The INI file can be made read-only to prevent users from changing
  settings

The INI file location can be customized (for central management on a
server) via the `change_settings_path` permission.

---

## Known risks and mitigations

### Risk: Malicious `.scriptree` files

A `.scriptree` file received from an untrusted source could contain:

- A dangerous executable path (e.g. a backdoor)
- Custom menu commands that exfiltrate data
- Default values designed to trick the user

**Mitigation:**
- The executable path is visible in the editor and runner
- Custom menu commands use `shell=False` — no shell injection
- Input sanitization warns about suspicious default values
- In locked-down deployments, users cannot create or modify tool files
  (permissions deny `save_scriptree`, `edit_tool_definition`, etc.)
- Treat `.scriptree` files like executables — only use files from
  trusted sources

### Risk: UNC path credential harvesting

A form value containing `\\attacker-server\share` can cause Windows
to send the user's NTLM hash to the attacker's SMB server.

**Mitigation:**
- Input sanitization warns about UNC paths in path-type fields
- The `access_sensitive_paths` permission can restrict path access
- Network-level mitigations (SMB signing, outbound SMB filtering) are
  the most effective defense

### Risk: Tool output side effects

ScripTree streams tool output to the output pane. A malicious tool
could emit ANSI escape sequences or extremely large output.

**Mitigation:**
- Output is rendered in a `QPlainTextEdit` which does not interpret
  ANSI escape codes — they appear as literal text
- There is no output size limit, but the output pane is a standard
  Qt text widget with reasonable memory behavior

### Risk: Environment variable manipulation

Global environment variables in Settings, or per-tool env overrides,
could be used to redirect executables (e.g. changing `PATH` to point
to a malicious directory).

**Mitigation:**
- The `access_settings` permission controls who can open Settings
- The `edit_environment` permission controls who can modify per-tool env
- In a locked-down deployment, deny both to prevent env manipulation
- The global env override checkbox requires explicit action

### Risk: Copying ScripTree to bypass permissions

A user could copy the entire ScripTree folder to their own machine
and remove or modify the permission files.

**Mitigation:**
- Missing permission files default to **denied** (not allowed)
- Deleting files only removes access, never grants it
- Per-file permissions inherit from app-level — they can't grant
  beyond what the app allows
- For maximum security, deploy tools on a network share that users
  have read-only access to, and set `SCRIPTREE_PERMISSIONS_DIR` or
  the permissions path in Settings to point to a protected location

### Risk: Memory forensics on credentials

An attacker with access to the machine's memory (e.g. via a debugger
or memory dump) could extract passwords.

**Mitigation:**
- Passwords are XOR-encrypted with a random pad in memory
- The plaintext buffer is zeroed immediately after the Windows API call
- Credentials are never written to disk
- "Remember for session" can be left unchecked for maximum security
  (password is prompted every time and discarded immediately)

---

## Security checklist for IT administrators

1. [ ] Deploy `permissions/` folder with all capability files
2. [ ] Set the permissions folder to read-only for all users via NTFS ACLs
3. [ ] Grant write only on the specific capability files each role needs
4. [ ] Set `.scriptree` and `.scriptreetree` files to read-only
5. [ ] Keep `load_user_plugins` denied unless custom parsers are needed
6. [ ] Keep `allow_symlinks` and `allow_path_traversal` denied
7. [ ] Keep `change_permissions_path` and `change_settings_path` denied
   for regular users
8. [ ] Consider deploying via a network share for maximum control
9. [ ] Train users to treat `.scriptree` files like executables — only
   use files from trusted sources
