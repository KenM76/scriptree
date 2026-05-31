# ScripTree Help

Welcome to ScripTree — a universal GUI generator for command-line tools.

**ScripTree V3 ships with three launchers and a headless screenshot tool in one installation:**

- **`run_scriptreeforest.bat`** (PRIMARY) — the **forest workspace**:
  a persistent root cell plus every other cell linked under it.
  Auto-discovers nearby `.scriptreering` / `.scriptreetree` /
  `.scriptree` catalogs at startup, restores the saved layout. The
  recommended double-click entry point for most users. See
  **[The cell + ring shell](cell_shell.md)**.
- **`run_scriptreering.bat`** — the **cell + ring shell**: floating
  cell launchers (hexagons or squares) on your desktop. Click a cell
  to pop up its tool menu, dock two together to form a multi-tool
  ring, drag-drop catalogs and rings onto cells. Layouts save as
  `.scriptreering` files.
- **`run_scriptree.bat`** — the classic **V1 editor**: tool runner,
  configurations, parser, save/load. The shells (forest / ring)
  shell out to this whenever you click a tool, so it's the same
  editor you've always had.
- **`run_screenshooter.bat`** — the **headless screenshot tool**.
  Renders cells, parameter forms, popup trees, the full editor, and
  forest composites as PNG without ever flashing a window onto the
  user's desktop.

This folder contains all the documentation, split into five sections:

## Quick start

New here? Start with **[quickstart.md](quickstart.md)** — get a tool running
in under two minutes. Then read **[cell_shell.md](cell_shell.md)** for the
cell launcher and how it plugs into the editor.

## For humans

Read these in order for the full picture:

1. **[Quickstart](quickstart.md)** — project layout, first tool, 60-second
   walkthrough.
2. **[Getting started](getting_started.md)** — the two workflows, standalone
   mode, where to go next.
3. **[The tool runner](tool_runner.md)** — the day-to-day view: form, command
   preview, Run button, undo/redo, output pane, custom menus, input
   sanitization.
4. **[The tool editor](tool_editor.md)** — how to build a `.scriptree` file
   from scratch or refine one that was auto-parsed.
5. **[Sections](sections.md)** — grouping parameters under collapsible headers
   or tabs.
6. **[Configurations](configurations.md)** — saved configurations, UI
   visibility, hidden parameters, credential prompts, tree configurations,
   permissions.
7. **[Environment variables](environment.md)** — tool-level, per-configuration,
   and global (Settings) environment and PATH overrides.
8. **[File formats](file_formats.md)** — what `.scriptree`, `.scriptreetree`,
   sidecar, and permission files contain.
9. **[Settings](settings.md)** — global app settings: layout memory,
   environment, PATH, permissions path.
10. **[Security](security.md)** — permissions system, injection prevention,
    credential handling, read-only enforcement.
11. **[Vendored dependencies](vendored_dependencies.md)** — how ScripTree's
    own `lib/pypi/` works, the matching per-tool `lib/` pattern for apps
    that need their own deps, the four management scripts (`update_lib.py`,
    `audit_vendored.py`, `make_portable.py`, `make_shortcut.py`), and the
    `ScripTreeManagement.scriptreetree` that wraps them in a GUI.
12. **[Portable Python install](portable_python.md)** — when ScripTree
    can't find Python 3 on PATH it can drop a self-contained Python
    into `lib/python/` (Windows / macOS, automated; Linux, manual via
    package manager or python-build-standalone). Tools then reference
    it via `%SCRIPTREE_LIB_PYTHON%`.
13. **[The cell + ring shell](cell_shell.md)** — V3's cell
    launcher: gestures, ring docking, drag-drop, cell labels and
    icons, autostart, the `.scriptreering` file format. The shell
    calls the editor as a subprocess for every tool launch, so V1
    stays untouched.
14. **[Icon generator (`make_icon.py`)](make_icon.md)** — maintainer
    tool for rebuilding the app icon + cell-shell forest hub glyph.
    Two modes (full publish / single-shot), four palette flags
    (concept 10), ten concept variants, optional auto-install of
    Pillow.

## For LLMs (and humans using AI to generate tools)

The [`LLM/`](LLM) subfolder contains the complete JSON schemas, field
rules, and invariants for `.scriptree` and `.scriptreetree` files. You
can point any AI assistant at this folder and ask it to generate tool
files for you — see [getting_started.md](getting_started.md) for
details.

AI coding agents working on ScripTree's own codebase should start with
[`LLM/README.md`](LLM/README.md).

## For tool authors — writing help text that parses cleanly

The [`parsers/`](parsers) subfolder explains how ScripTree's parser plugins
(argparse, click, PowerShell, Windows help, generic heuristic) consume help
output:

- [`parsers/python_scripts.md`](parsers/python_scripts.md) — Python CLIs
- [`parsers/windows_exe.md`](parsers/windows_exe.md) — Windows `/flag` tools
- [`parsers/powershell.md`](parsers/powershell.md) — PowerShell cmdlets
- [`parsers/gnu_tools.md`](parsers/gnu_tools.md) — GNU-style long help
