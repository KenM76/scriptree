# Environment variables and PATH

ScripTree lets you set environment variables and PATH prepends on three
levels:

1. **Global** — set in **Edit → Settings**. Applied to every tool run.
   See [settings.md](settings.md).
2. **Tool-level** — stored in the `.scriptree` file. Applied to every run
   of the tool, regardless of which configuration is active.
3. **Configuration-level** — stored in the sidecar. Layered on top of the
   tool-level values for the active configuration only.

Default merge order (highest priority last):

```
os.environ → Global settings → Tool env → Config env
```

With the "Override" checkbox in Settings, global takes highest priority:

```
os.environ → Tool env → Config env → Global settings
```

PATH prepend follows the same pattern — global directories go after
tool/config by default, before them when override is enabled.

At run time the child process receives:

```
os.environ  →  tool.env  →  configuration.env   (highest priority wins)
```

PATH prepend entries from the tool and the configuration are both
concatenated (tool first, config second) and prepended to the child's
`PATH` before spawn.

## Tool-level (editor)

Open the tool editor and click **Edit environment...** next to the
Environment row in the Tool group box. A popup opens with two text
boxes:

```
Environment variables
  One KEY=value per line. Lines starting with # are comments.

  MY_VAR=hello
  # this is a comment
  API_KEY=secret

PATH prepend (directories)
  One directory per line.

  C:/tools/bin
  ./vendor
```

OK parses the text and writes the new env / path_prepend back onto the
`ToolDef`. Cancel discards the edit. The label next to the button
updates to show a short summary like "2 vars, 1 path" or "no overrides".

The tool-level env is saved as part of the `.scriptree` file when you
click Save in the main editor.

## Configuration-level (runner)

In the runner, click **Env...** on the configurations bar. The same dialog
opens, but edits the *active configuration's* env/path_prepend instead
of the tool's. OK writes the changes back to the active `Configuration`
and persists the sidecar immediately.

## Layering rules

1. Start with `os.environ` (the ScripTree process's own environment).
2. Apply `tool.env` on top — any variable in `tool.env` overrides the
   ambient value.
3. Apply `configuration.env` on top — any variable in the active config
   overrides both the tool and the ambient.

For PATH prepends: tool entries come first, then configuration entries,
then whatever PATH was already set. So a tool-level `./vendor` and a
config-level `./debug-bin` produce:

```
./debug-bin ; ./vendor ; <original PATH>
```

(Config entries have higher priority — they're earlier in the PATH
search order.)

## Relative paths

Directories in the PATH prepend list can be absolute or relative. Relative
directories are resolved against:

1. The tool's `working_directory` if one is set, else
2. The executable's parent directory.

So `./vendor` in a tool whose working directory is `C:/projects/foo`
becomes `C:/projects/foo/vendor` in the child's PATH.

## Comments and blank lines

The env editor supports `# comment` lines and blank lines in both text
boxes. They're preserved when you re-open the editor but stripped when
building the child environment — they exist as a "notes" channel for
you, not for the child process.

## When there are no overrides

If both `tool.env` and `configuration.env` are empty *and* both
`path_prepend` lists are empty, ScripTree passes `env=None` to
`subprocess.Popen`, which means the child simply inherits the parent
environment unchanged. This is the default state and produces cleaner
error messages when debugging (no giant env block in the process dump).

## Example: pinning a Python tool to a venv

Suppose you want `mytool.py` to run with a specific virtualenv's Python
on PATH:

**Tool-level env** (applies to every run):
```
VIRTUAL_ENV=C:/projects/mytool/venv
```

**Tool-level PATH prepend**:
```
C:/projects/mytool/venv/Scripts
```

Now every invocation finds the venv's `python.exe` first and sets
`VIRTUAL_ENV` correctly.

## Example: dev vs. prod configs

Two configurations — **dev** and **prod** — with different API keys:

**dev config env**:
```
API_URL=https://dev.api.example.com
API_KEY=dev_abcdef
LOG_LEVEL=debug
```

**prod config env**:
```
API_URL=https://api.example.com
API_KEY=prod_xyz
LOG_LEVEL=info
```

Switch between them with the configurations combo box. The right API key
flows into the child process every time.
