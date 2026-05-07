# Settings

Access via **Edit → Settings...**. Application-wide preferences that
persist across sessions (stored in the system registry on Windows,
`~/.config` on Linux).

## Layout

**Remember window layout on exit** — when enabled, ScripTree saves
the window position, size, and dock arrangement on close and restores
them on next startup.

## Permissions path

Custom path to the `permissions/` folder. By default, ScripTree
auto-detects it by walking up from the application directory.

To change this:

1. Add a `change_permissions_path` file to the **current** permissions
   folder
2. Ensure the file is writable for your user
3. Open Settings and set the new path

The field is disabled until the permission is granted. You can also
set the `SCRIPTREE_PERMISSIONS_DIR` environment variable as an
alternative (no permission file needed for that).

## Global environment variables

Enter `KEY=VALUE` pairs, one per line. These are merged into every
tool's child process environment at run time.

```
PYTHONPATH=C:\my\libs
LOG_LEVEL=info
```

**Override tool and configuration environment variables** — when
checked, the global settings env takes the highest priority (overrides
everything). When unchecked, the merge order is:

```
os.environ → Global settings env → tool.env → config.env
```

## Global PATH prepend

Enter directories, one per line. These are prepended to PATH for
every tool run.

```
C:\Tools\bin
C:\PortableApps\Python
```

**Override tool and configuration PATH entries** — when checked, the
global PATH directories are prepended at the highest priority (before
any PATH entries from individual tools or configurations). When
unchecked, they go after tool and config entries.

Default order:
```
[config_paths, tool_paths, global_paths, <original PATH>]
```

Override order:
```
[global_paths, config_paths, tool_paths, <original PATH>]
```

## Notes

- Settings are stored via Qt's `QSettings` mechanism — on Windows
  this is the registry (`HKEY_CURRENT_USER\Software\ScripTree`), on
  Linux it's `~/.config/ScripTree/ScripTree.conf`
- Blank lines and lines starting with `#` are ignored in both the
  env and PATH editors
- The `access_settings` permission must be granted for the user to
  open the Settings dialog
