# ScripTree Help

Welcome to ScripTree — a universal GUI generator for command-line tools. This
folder contains all the documentation, split into four sections:

## Quick start

New here? Start with **[quickstart.md](quickstart.md)** — get a tool running
in under two minutes.

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
