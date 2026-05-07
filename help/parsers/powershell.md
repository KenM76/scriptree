# PowerShell cmdlets

ScripTree includes a dedicated parser for PowerShell `Get-Help` output.
It detects the distinctive `NAME` / `SYNTAX` / `PARAMETERS` section
layout and builds a `.scriptree` tool that wraps the cmdlet via
`powershell.exe -NoProfile -Command`.

## What it detects

The parser looks for the standard structured output from `Get-Help`:

```
NAME
    New-LocalUser

SYNTAX
    New-LocalUser [-Name] <string> -Password <securestring> ...

PARAMETERS
    -AccountExpires <datetime>

        Required?                    false
        Position?                    Named
        ...

    -Disabled

        Required?                    false
        Position?                    Named
        ...
```

## What ScripTree extracts

- **Switch parameters** (no type tag, like `-Disabled`) become boolean
  checkboxes with conditional flags (`{disabled?-Disabled}`).
- **Typed parameters** (`-Name <string>`) become text boxes, number
  spin boxes, or checkboxes depending on the PowerShell type.
- **Positional parameters** (Position = 0, 1, ...) are placed directly
  in the template without the `-Flag` prefix.
- **Required/optional** is preserved. Parameters in non-default
  parameter sets are treated as optional.
- **Common parameters** (`-Verbose`, `-Debug`, `-ErrorAction`, `-WhatIf`,
  `-Confirm`, etc.) are automatically stripped.
- **Unsupported types** (`<securestring>`, `<pscredential>`,
  `<LocalUser>`, `<LocalGroup>`, etc.) are skipped — they require
  pipeline input and can't be passed as command-line strings.

## Type mapping

| PowerShell type | ScripTree type | Widget |
|-----------------|----------------|--------|
| `string`, `string[]` | string | text |
| `int`, `int32`, `int64` | integer | number |
| `double`, `float` | float | number |
| `bool` | bool | checkbox |
| (switch, no type) | bool | checkbox |
| `datetime` | string | text |
| `securestring` | *(skipped)* | — |

## The generated tool

The executable is set to `powershell.exe` and the argument template
starts with `-NoProfile -Command CmdletName`. This means:

- The tool runs without loading the user's PowerShell profile (faster,
  more predictable).
- The cmdlet name is a literal in the template, not editable.
- Parameters are appended after the cmdlet name.

## Probing PowerShell cmdlets

ScripTree's standard probe sends `--help`, `-h`, `/?`, and `help` to
executables. PowerShell cmdlets don't respond to these — you need to
use `Get-Help CmdletName -Full` to generate the help text.

The recommended workflow:

1. Run `Get-Help CmdletName -Full` in PowerShell and copy the output.
2. Use **File → New tool from executable...** and paste the help text
   into the cached help field (or save it to a file and re-parse).
3. Alternatively, use the PowerShell parser programmatically in a
   script that generates `.scriptree` files from cmdlet help.

## Example

The `examples/user_management/` directory contains a complete set of
15 tools for Windows local user and group management, all generated
from PowerShell `Get-Help` output:

- `get_localuser.scriptree` — List users
- `new_localuser.scriptree` — Create user (with sections)
- `set_localuser.scriptree` — Modify user (with sections)
- `remove_localuser.scriptree` — Delete user
- `enable_localuser.scriptree` — Enable user
- `disable_localuser.scriptree` — Disable user
- `rename_localuser.scriptree` — Rename user
- `get_localgroup.scriptree` — List groups
- `new_localgroup.scriptree` — Create group
- `set_localgroup.scriptree` — Modify group
- `remove_localgroup.scriptree` — Delete group
- `rename_localgroup.scriptree` — Rename group
- `get_localgroupmember.scriptree` — List group members
- `add_localgroupmember.scriptree` — Add group member
- `remove_localgroupmember.scriptree` — Remove group member

These are bundled with a `user_management.scriptreetree` launcher that
groups them into Users, Groups, and Group Membership folders.
