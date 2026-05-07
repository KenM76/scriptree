# ScripTree V3

A universal GUI generator for command-line tools. Define a tool once — by pointing ScripTree at an executable or building a form from scratch — and run it through a clean GUI with labeled fields, dropdowns, file pickers, and checkboxes.

V3 ships with **two launchers in one installation**:

| Launcher | What it does |
|---|---|
| **`run_scriptreering.bat`** | The **cell + ring shell**: floating hexagonal launchers on your desktop. Single-click pops up the cell's tool menu; double-click opens the full editor on the cell's catalog. Drag two cells close together to dock them into a *ring* whose menu merges their tools. Save layouts as `.scriptreering` files. See [`help/cell_shell.md`](help/cell_shell.md). |
| **`run_scriptree.bat`** | The classic **V1 editor**: tool runner, configurations, parser, save/load. Identical behaviour to v0.1.x. The cell shell shells out to this whenever you click a tool — V1 stays the editor; the cell shell is just a launcher. |

## Installing the portable zip

Download the V3 zip from the Releases page and extract it. The launcher expects this layout:

```
<some-folder>/
├── run_scriptreering.bat   ← cell + ring shell (the usual entry point)
├── run_scriptreering.py
├── run_scriptree.bat       ← V1 editor (called as subprocess from the shell)
├── run_scriptree.py
├── scriptree/              ← Python package
│   ├── main.py
│   ├── shell/              ← cell + ring shell (NEW in V3)
│   └── ...
├── branding/
│   └── branding.config.json
├── lib/
└── ...
```

**Common extraction mistake:** if you right-click the zip and pick "Extract here" while already standing inside a folder named `ScripTree`, Windows produces `ScripTree/ScripTree/...` (the inner one is the zip's own folder). The launcher walks up to four levels deep looking for the package, so this usually still works — but if it doesn't, just move the inner `ScripTree/*` contents up one level so they sit next to `run_scriptree.bat`.

If the launcher still can't find the package, it prints a diagnostic listing exactly which folder it looked in and what it saw — paste that into an issue and it's a one-round fix.

## Quick Start

```bash
# Prerequisites: Python 3.11+

# Option A: vendor into the project, trimmed to the ~65 MB minimum (recommended)
python lib/update_lib.py --trim
python run_scriptreering.py     # cell shell (preferred entry point)
# or:
python run_scriptree.py         # V1 editor directly

# Option B: use your system Python environment
pip install PySide6
python run_scriptreering.py
```

Or on Windows, double-click **`run_scriptreering.bat`** for the cell shell, or `run_scriptree.bat` for the editor directly. Either launcher will offer to fetch a portable Python if none is found.

**Option A makes the folder portable** — after `update_lib.py --trim` runs once, you can zip the entire project folder and drop it on any other machine with the same OS/architecture and Python 3.11+. No pip, no network, no admin rights required. The `--trim` flag strips unused Qt modules (WebEngine, QML, Quick/3D, Multimedia, PDF, Charts, translations, dev tools) — ScripTree only uses `QtCore`/`QtGui`/`QtWidgets`, so you save ~400 MB.

## Key Features

- **Auto-parse any CLI tool** — parses `--help` output from argparse, click, PowerShell, Windows `/flag`, and GNU tools
- **Named configurations** — save multiple form states per tool with environment overrides, UI visibility, and hidden parameters
- **Standalone mode** — strip the IDE down to just the form for end users
- **Tree launchers** — group tools into `.scriptreetree` files with tabbed standalone view
- **Custom menus** — add menu bars to tools and trees
- **AI-compatible** — point any LLM at `help/LLM/` to generate tool files
- **No shell execution** — `shell=False` everywhere, input sanitization on every run
- **File-based permissions** — 22 capability files, secure defaults, NTFS ACL compatible
- **Fully portable** — INI settings, zero registry, copy and run
- **Encrypted credentials** — run-as-different-user with XOR pad, immediate zeroization

## Project Structure

```
ScripTree/
├── run_scriptree.py        ← main launcher
├── run_scriptree.bat       ← Windows launcher
├── run_scriptree.sh        ← Linux / macOS launcher
├── permissions/            ← capability permission files
├── lib/                    ← vendored deps (portable install)
│   ├── requirements.txt    ← pinned versions
│   ├── update_lib.py       ← install / refresh / audit
│   ├── _manifests/         ← provenance notes per package
│   └── pypi/               ← installed packages (gitignored)
├── ScripTree/              ← application code
│   ├── scriptree/          ← Python package
│   ├── tests/              ← test suite (600+ tests)
│   ├── examples/           ← example tools
│   ├── help/               ← documentation
│   └── pyproject.toml
└── ScripTreeApps/          ← user tools and trees
```

## Updating vendored dependencies

When a security advisory drops for one of the pinned packages:

```bash
# 1. Edit lib/requirements.txt, bump the version.
# 2. Refresh + re-trim in one go:
python lib/update_lib.py --upgrade --trim

# Periodically check for CVEs:
python lib/update_lib.py --audit
```

Every installed package gets a provenance note in `lib/_manifests/` showing its version, source, and install timestamp. `--trim` also writes `lib/_manifests/trim_log.md` listing exactly which files were removed and how much space was freed.

### Per-tool vendored dependencies

Tools under `ScripTreeApps/` that need their **own** Python packages (e.g. a DXF-rendering tool that needs `matplotlib` + `ezdxf`, which aren't GUI deps and may even target a different Python interpreter) follow the same pattern, scoped to the tool folder:

```
ScripTreeApps/<tool>/lib/
├── requirements.txt   # "# python: py -3.12" header picks the interpreter
├── _manifests/
└── pypi/              # injected onto sys.path by the tool's own script
```

Refresh every tool's `lib/` at once:

```bash
python lib/update_lib.py --all-apps          # ScripTree's own + every tool's
python lib/update_lib.py --apps-only         # just the tools
python ScripTreeApps/audit_vendored.py       # writes VENDORED_DEPS.md audit
```

The `ScripTreeApps/ScripTreeManagement/ScripTreeManagement.scriptreetree` wraps all four management scripts (`update_lib.py`, `audit_vendored.py`, `make_portable.py`, `make_shortcut.py`) as clickable GUI tools inside ScripTree itself. See [`help/vendored_dependencies.md`](help/vendored_dependencies.md) for the full explanation.

## Building a portable distribution

```bash
# Copies this project into a clean, end-user-ready folder, strips dev
# files (.git, __pycache__, tests, etc.), runs a smoke-test, optionally
# zips the result. Handles existing ScripTreeApps/ with keep/overwrite/backup.
python make_portable.py --force --scriptreeapps=keep

# Generate a platform-native desktop shortcut (.lnk / .desktop / .command):
python make_shortcut.py
```

## Documentation

- **[Quickstart](help/quickstart.md)** — get running in 60 seconds
- **[Features](help/features.md)** — top 10 and top 20 feature lists
- **[Security Guide](help/security.md)** — permissions, sanitization, deployment
- **[Full Help Index](help/README.md)** — all documentation

## For IT Administrators

ScripTree is designed for corporate deployment:

1. Deploy the `permissions/` folder with capability files
2. Set the folder read-only for users via NTFS ACLs
3. Grant write on specific files per AD group
4. Set `.scriptree` files read-only — users can run but not edit

No per-user config, no registry, no cloud, no agents. See the [Security Guide](help/security.md).

## Contributors

**Ken M** — Creator, Product Designer & Architect
**Claude (Anthropic)** — Lead Developer

See [CONTRIBUTORS.md](CONTRIBUTORS.md) for details.

## License

See [LICENSE](LICENSE).
