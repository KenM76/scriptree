# PowerShell parser plugin (`powershell.py`)

**Priority:** 25 (between click=20 and winhelp=30)

**Detection:** Looks for `NAME` and `PARAMETERS` section headers
(all-caps, left-aligned). These are distinctive to PowerShell's
`Get-Help` output format.

## Input format

```
NAME
    CmdletName

SYNTAX
    CmdletName [-Name] <string> [-Flag] ...

PARAMETERS
    -ParamName <type>

        Required?                    true|false
        Position?                    0|1|Named
        Accept pipeline input?       true|false
        Parameter set name           (All)|SetName
        Aliases                      None|alias
        Dynamic?                     true|false

    -SwitchParam

        Required?                    false
        ...

    <CommonParameters>
        ...

INPUTS
    ...

OUTPUTS
    ...
```

## Extraction rules

1. **Cmdlet name** — first non-blank line after `NAME`.
2. **Parameters** — parsed from the `PARAMETERS` block. Each
   `-FlagName <type>` header starts a param record; metadata
   key-value lines are collected until the next param header.
3. **Switch params** — no `<type>` tag → `ParamType.BOOL`, widget
   `CHECKBOX`, template `{id?-Flag}`.
4. **Value params** — `<type>` tag present → mapped via `_TYPE_MAP`.
   Positional params (Position = digit) → template `{id}`.
   Named params → template `["-Flag", "{id}"]`.
5. **Skipped**: common params (`-Verbose`, `-Debug`, `-WhatIf`,
   `-Confirm`, etc.), `<securestring>`, `<pscredential>`, pipeline-
   only types (`<LocalUser>`, `<LocalGroup>`, etc.).
6. **Multiple parameter sets**: params in non-(All) sets have
   `required` downgraded to `false`.

## Type mapping table

| PS type | ParamType | Widget |
|---------|-----------|--------|
| `string`, `string[]` | STRING | TEXT |
| `int`, `int32`, `int64`, `uint32`, `uint64`, `long` | INTEGER | NUMBER |
| `double`, `float`, `decimal` | FLOAT | NUMBER |
| `bool`, (switch) | BOOL | CHECKBOX |
| `datetime`, `timespan`, `uri`, `guid` | STRING | TEXT |
| `hashtable`, `hashtable[]` | STRING | TEXTAREA |
| `securestring`, `pscredential` | *(skip)* | — |
| `localuser`, `localgroup`, etc. | *(skip)* | — |
| unknown | STRING | TEXT |

## Generated ToolDef

- `name` = cmdlet name (e.g. `New-LocalUser`)
- `executable` = `powershell.exe`
- `argument_template` = `["-NoProfile", "-Command", "CmdletName", ...]`
- `source.mode` = `"powershell"`

## ID synthesis

`AccountNeverExpires` → `account_never_expires` (CamelCase → snake_case).
Uniqueness enforced by appending `_2`, `_3`, etc.

## Label synthesis

`AccountNeverExpires` → `Account Never Expires` (CamelCase → spaced).
