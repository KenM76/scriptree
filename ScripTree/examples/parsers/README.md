# ScripTree user parsers

Drop `.py` files in this directory (or any directory) and point
ScripTree at it by setting the `SCRIPTREE_PARSERS_DIR` environment
variable before launching the app:

```powershell
# PowerShell
$env:SCRIPTREE_PARSERS_DIR = "C:\Users\Ken\OneDrive\Kens_Projects\Claude\Software\ScripTree\examples\parsers"
python -m scriptree.main
```

```bash
# bash / WSL
export SCRIPTREE_PARSERS_DIR="/mnt/c/Users/Ken/.../examples/parsers"
python -m scriptree.main
```

Multiple directories can be listed, separated by `;` on Windows or `:`
on Unix — the same convention as `PATH`.

## Plugin protocol

Each `.py` file is a plugin if it exposes three attributes:

| Attribute        | Type                        | Required | Notes |
|------------------|-----------------------------|----------|-------|
| `NAME`           | `str`                       | yes      | Unique id. Reusing a built-in name (e.g. `"winhelp"`) overrides that built-in. |
| `PRIORITY`       | `int`                       | yes      | Lower runs first. Built-ins use 10 (argparse), 20 (click), 30 (winhelp), 999 (heuristic fallback). |
| `detect(text)`   | `ToolDef \| None`           | yes      | The parser itself. Return `None` to pass. |
| `DESCRIPTION`    | `str`                       | no       | Human-readable blurb for the UI. |
| `ENABLED`        | `bool` (default `True`)     | no       | Set to `False` to ship a disabled plugin. |

Files whose names start with an underscore (`_helpers.py`) are **not**
loaded as plugins — use that convention for shared helper modules
inside a plugins directory.

## Behavior

- Plugins run in priority order; the first one that returns a
  non-None `ToolDef` wins.
- If a plugin raises an exception, it is logged and the next plugin
  is tried — one bad plugin can't kill the pipeline.
- The built-in `heuristic` plugin at priority 999 always returns a
  result, so a probe never falls through to nothing unless you
  explicitly disable it.

See `example_uppercase.py` in this directory for a worked example.
