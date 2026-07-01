# ScripTree V3

A universal GUI generator for command-line tools. Define a tool once — by pointing ScripTree at an executable or building a form from scratch — and run it through a clean GUI with labeled fields, dropdowns, file pickers, and checkboxes.

V3 ships with **three launchers and a headless screenshot tool in one installation**:

| Launcher | What it does |
|---|---|
| **`run_scriptreeforest.bat`** | **Primary entry point.** The **forest workspace**: a persistent root cell on your desktop plus every other cell linked under it.  Auto-discovers nearby `.scriptreering` / `.scriptreetree` / `.scriptree` catalogs at startup, restores the saved layout, and adopts new tools as they appear in the workspace folder.  This is what most users double-click after install.  Internally chains into `run_scriptreering.py` with `SCRIPTREE_FOREST_MODE=1` — same Python search, same dependency check, same self-healing.  See [`docs/cell_shell.md`](docs/cell_shell.md). |
| **`run_scriptreering.bat`** | The **bare cell + ring shell** (no forest workspace).  Floating hexagonal launchers with no implicit root: each cell stands alone unless you drag two together to dock them into a *ring*.  Single-click pops up the cell's tool menu; double-click opens the full editor on the cell's catalog.  Save layouts as `.scriptreering` files.  Useful when you want a one-off cell on the desktop without the workspace persistence. |
| **`run_scriptree.bat`** | The classic **V1 editor**: tool runner, configurations, parser, save/load.  Identical behaviour to v0.1.x.  All three shells (forest / ring / cell) shell out to this whenever you click a tool — V1 stays the editor; the shells are just launchers. |
| **`run_screenshooter.bat`** | The **headless screenshot tool**.  No arguments → opens the screenshooter's GUI form via the V1 editor (labeled fields, dropdowns, file picker — pick what to render and click Run).  With arguments → CLI passthrough to `screenshooter.py` for batch / scripted use.  Captures cells, parameter forms, popup trees, the full editor MainWindow (tree + form + output + cmd-line), the tabbed StandaloneWindow view, the forest hub + cell composite, and the forest hub + merged menu composite — every view ScripTree ships, rendered as PNG without ever flashing a window onto the user's desktop.  Used to generate the per-demo previews on [`scriptree-demos`](https://github.com/KenM76/scriptree-demos) and the documentation screenshots in `docs/`. |

## Installing the portable zip

Download the V3 zip from the Releases page and extract it. The launcher expects this layout:

```
<some-folder>/
├── run_scriptreeforest.bat ← forest workspace (PRIMARY — double-click this)
├── run_scriptreeforest.py
├── run_scriptreering.bat   ← bare ring shell (no workspace)
├── run_scriptreering.py
├── run_scriptree.bat       ← V1 editor (called as subprocess from the shells)
├── run_scriptree.py
├── run_screenshooter.bat   ← headless screenshot tool (no args → GUI form)
├── screenshooter.py        ← (CLI; `python screenshooter.py --help` for kinds)
├── scriptree/              ← Python package
│   ├── main.py
│   ├── shell/              ← cell + ring shell (NEW in V3)
│   └── ...
├── branding/
│   └── branding.config.json
├── lib/
│   ├── combridge/          ← bundled COM-automation runtime
│   ├── python/             ← portable Python (after install_python.ps1)
│   └── pypi/               ← vendored PySide6 + deps
└── ...
```

**Common extraction mistake:** if you right-click the zip and pick "Extract here" while already standing inside a folder named `ScripTree`, Windows produces `ScripTree/ScripTree/...` (the inner one is the zip's own folder). The launcher walks up to four levels deep looking for the package, so this usually still works — but if it doesn't, just move the inner `ScripTree/*` contents up one level so they sit next to `run_scriptree.bat`.

If the launcher still can't find the package, it prints a diagnostic listing exactly which folder it looked in and what it saw — paste that into an issue and it's a one-round fix.

## Quick Start

```bash
# Prerequisites: Python 3.11+

# Option A: vendor into the project, trimmed to the ~65 MB minimum (recommended)
python lib/update_lib.py --trim
python run_scriptreeforest.py    # forest workspace (preferred entry point)
# or:
python run_scriptreering.py      # bare ring shell (no workspace)
python run_scriptree.py          # V1 editor directly
python screenshooter.py --help   # headless screenshot CLI

# Option B: use your system Python environment
pip install PySide6
python run_scriptreeforest.py
```

Or on Windows, double-click **`run_scriptreeforest.bat`** to launch the forest workspace (the usual entry point), `run_scriptreering.bat` for the bare ring shell, `run_scriptree.bat` for the editor directly, or `run_screenshooter.bat` to render PNGs of any tool / tree / cell / forest / popup-menu without ever showing a window on the desktop. Every launcher will offer to fetch a portable Python if none is found.

**Option A makes the folder portable** — after `update_lib.py --trim` runs once, you can zip the entire project folder and drop it on any other machine with the same OS/architecture and Python 3.11+. No pip, no network, no admin rights required. The `--trim` flag strips unused Qt modules (WebEngine, QML, Quick/3D, Multimedia, PDF, Charts, translations, dev tools) — ScripTree only uses `QtCore`/`QtGui`/`QtWidgets`, so you save ~400 MB.

## Key Features

- **Auto-parse any CLI tool** — parses `--help` output from argparse, click, PowerShell, Windows `/flag`, and GNU tools
- **Named configurations** — save multiple form states per tool with environment overrides, UI visibility, and hidden parameters
- **Standalone mode** — strip the IDE down to just the form for end users
- **Tree launchers** — group tools into `.scriptreetree` files with tabbed standalone view
- **Custom menus** — add menu bars to tools and trees
- **AI-compatible** — point any LLM at `docs/LLM/` to generate tool files
- **No shell execution** — `shell=False` everywhere, input sanitization on every run
- **File-based permissions** — 32 capability files, secure defaults, NTFS ACL compatible (see [`docs/security.md`](docs/security.md) for the full per-capability table)
- **Fully portable** — INI settings, zero registry, copy and run
- **Encrypted credentials** — run-as-different-user with XOR pad, immediate zeroization

## Project Structure

```
ScripTree/
├── run_scriptreeforest.bat  ← forest workspace launcher (PRIMARY)
├── run_scriptreeforest.py
├── run_scriptreering.bat    ← bare cell + ring shell launcher
├── run_scriptreering.py
├── run_scriptree.bat        ← V1 editor launcher (shells out target)
├── run_scriptree.py
├── run_screenshooter.bat    ← headless screenshot tool launcher
├── screenshooter.py         ← screenshot CLI (8 widget kinds — see --help)
├── permissions/             ← capability permission files
├── lib/                     ← vendored deps (portable install)
│   ├── requirements.txt     ← pinned versions
│   ├── update_lib.py        ← install / refresh / audit
│   ├── install_python.ps1   ← portable Python downloader
│   ├── install_combridge.ps1 ← combridge runtime installer
│   ├── _manifests/          ← provenance notes per package
│   ├── combridge/           ← bundled COM-automation runtime
│   ├── python/              ← portable Python (post-install)
│   └── pypi/                ← installed packages (gitignored)
├── scriptree/               ← application code
│   ├── core/                ← schema + IO + runner
│   ├── shell/               ← cell / ring / forest shell (NEW in V3)
│   ├── ui/                  ← V1 editor + standalone window
│   └── plugins/             ← capability plugins
├── tests/                   ← test suite (1900+ tests)
├── docs/                    ← documentation + LLM authoring docs
├── pyproject.toml
└── ScripTreeApps/           ← user tools and trees
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

The `ScripTreeApps/ScripTreeManagement/ScripTreeManagement.scriptreetree` wraps all four management scripts (`update_lib.py`, `audit_vendored.py`, `make_portable.py`, `make_shortcut.py`) as clickable GUI tools inside ScripTree itself. See [`docs/vendored_dependencies.md`](docs/vendored_dependencies.md) for the full explanation.

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

- **[Quickstart](docs/quickstart.md)** — get running in 60 seconds
- **[Features](docs/features.md)** — top 10 and top 20 feature lists
- **[Organizing your tools](docs/LLM/category_authoring.md)** — the `category`
  field groups related tools into one forest cell; lay each tool out so its
  folder mirrors its category (`category: "MSOffice/Word"` → `MSOffice/Word/`).
  When hand-editing a `.scriptree` JSON, fields run stable-at-top →
  most-edited-at-bottom, so `Ctrl+End` jumps you to the form.
- **[Security Guide](docs/security.md)** — permissions, sanitization, deployment
- **[Full Help Index](docs/README.md)** — all documentation

## For IT Administrators

ScripTree is designed for corporate deployment:

1. Deploy the `permissions/` folder with capability files
2. Set the folder read-only for users via NTFS ACLs
3. Grant write on specific files per AD group
4. Set `.scriptree` files read-only — users can run but not edit

No per-user config, no registry, no cloud, no agents. See the [Security Guide](docs/security.md).

## Contributors

**Ken M** — Creator, Product Designer & Architect
**Claude (Anthropic)** — Lead Developer

See [CONTRIBUTORS.md](CONTRIBUTORS.md) for details.

## License

See [LICENSE](LICENSE).
