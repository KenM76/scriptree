# Settings

Access via **Edit → Settings...**. Application-wide preferences that
persist across sessions. Settings live in **`scriptree.ini`** in the
project root (next to `run_scriptree.py`) — zero registry on Windows,
zero `~/.config` files on Linux. Move the project folder and the
settings travel with it.

## Layout

**Remember window layout on exit** — when enabled, ScripTree saves
the window position, size, and dock arrangement on close and restores
them on next startup.

## Permissions path

Custom path to the `permissions/` folder. By default, ScripTree
auto-detects it by walking up from the application directory.

Two ways to change it:

1. **Environment variable (no permission needed):** set
   `SCRIPTREE_PERMISSIONS_DIR=/path/to/perms` before launching
   ScripTree. This always works — handy for testing, CI, and
   air-gapped deployments where modifying capability files isn't
   convenient.
2. **GUI (requires the `change_permissions_path` capability):**
   - Add a `change_permissions_path` file to the **current**
     permissions folder
   - Ensure the file is writable for your user
   - Open Settings and edit the path field (disabled until the
     permission is granted)

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

- Settings are stored in `scriptree.ini` in the project root (Qt
  `QSettings` running in `IniFormat` mode — explicitly opted out of
  the native-registry backend so settings travel with the
  application folder)
- Set `SCRIPTREE_SETTINGS_PATH=/some/other/path.ini` to redirect
  the file at launch time
- Blank lines and lines starting with `#` are ignored in both the
  env and PATH editors
- The `access_settings` permission must be granted for the user to
  open the Settings dialog
