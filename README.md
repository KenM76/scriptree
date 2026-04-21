# ScripTree

A universal GUI generator for command-line tools. Define a tool once — by pointing ScripTree at an executable or building a form from scratch — and run it through a clean GUI with labeled fields, dropdowns, file pickers, and checkboxes.

## Quick Start

```bash
# Prerequisites: Python 3.11+

# Option A: vendor everything into the project (portable, recommended)
python lib/update_lib.py        # one-time install into lib/pypi/
python run_scriptree.py

# Option B: use your system Python environment
pip install PySide6
python run_scriptree.py
```

Or on Windows, double-click `run_scriptree.bat`. If PySide6 is missing, the launcher will offer to install it.

**Option A makes the folder portable** — after `update_lib.py` runs once, you can zip the entire project folder and drop it on any other machine with the same OS/architecture and Python 3.11+. No pip, no network, no admin rights required.

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
# 2. Refresh:
python lib/update_lib.py --upgrade

# Periodically check for CVEs:
python lib/update_lib.py --audit
```

Every installed package gets a provenance note in `lib/_manifests/` showing its version, source, and install timestamp.

## Documentation

- **[Quickstart](ScripTree/help/quickstart.md)** — get running in 60 seconds
- **[Features](ScripTree/help/features.md)** — top 10 and top 20 feature lists
- **[Security Guide](ScripTree/help/security.md)** — permissions, sanitization, deployment
- **[Full Help Index](ScripTree/help/README.md)** — all documentation

## For IT Administrators

ScripTree is designed for corporate deployment:

1. Deploy the `permissions/` folder with capability files
2. Set the folder read-only for users via NTFS ACLs
3. Grant write on specific files per AD group
4. Set `.scriptree` files read-only — users can run but not edit

No per-user config, no registry, no cloud, no agents. See the [Security Guide](ScripTree/help/security.md).

## Contributors

**Ken M** — Creator, Product Designer & Architect
**Claude (Anthropic)** — Lead Developer

See [CONTRIBUTORS.md](CONTRIBUTORS.md) for details.

## License

See [LICENSE](LICENSE).
