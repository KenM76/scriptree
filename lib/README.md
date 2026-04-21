# `lib/` — Vendored Python dependencies

This folder makes a ScripTree installation **self-contained**. Once
populated, the whole project folder can be zipped, moved to another
location (or another machine with the same OS/architecture), and run
without `pip install`. No network, no administrator rights, no
environment setup.

## Layout

```
lib/
├── README.md              ← this file
├── requirements.txt       ← pinned versions of every vendored package
├── update_lib.py          ← one-shot refresh/install script
├── _manifests/            ← auto-generated provenance notes
│   └── <package>.md       ← one file per package: version, source URL,
│                            license summary, date installed
└── pypi/                  ← actual package contents (PyPI-sourced)
    ├── PySide6/           ← vendored package files
    ├── shiboken6/
    └── ...
```

The `pypi/` subfolder is **intentionally gitignored** — binary wheels
for PySide6 alone are ~300 MB and platform-specific, so committing them
to git would bloat the repo and only help one OS. This directory
structure and the update script are committed; the actual binary files
are not.

## First-time setup

On a freshly cloned repo (or any machine where `lib/pypi/` is empty):

```bash
python lib/update_lib.py
```

This runs `pip install --target lib/pypi/ -r lib/requirements.txt`
under the hood, then writes a provenance note for each package to
`lib/_manifests/`.

After this runs, `python run_scriptree.py` will use the vendored libs
automatically. Zip the folder, move it, ship it — it will work as long
as the target machine matches the OS/architecture that ran
`update_lib.py`.

## Refreshing to a newer version (security updates)

1. Edit `lib/requirements.txt` — bump the pinned version.
2. Run `python lib/update_lib.py --upgrade`.

`--upgrade` wipes `lib/pypi/` first so old binaries aren't left lying
around after a downgrade. The default (no flag) is additive: it only
installs what's missing.

## Keeping an eye on vulnerable packages

```bash
python lib/update_lib.py --audit
```

Runs `pip-audit` (installed on demand if missing) against the pinned
versions in `requirements.txt` and prints any known CVEs. Use this to
spot when a pinned version needs bumping.

## Why this design

- **One-time setup** instead of repeated pip calls. After the first
  run, the folder is truly portable.
- **Platform-specific** — binary wheels only work on the OS/arch that
  installed them. Each user runs `update_lib.py` once on their own
  machine.
- **Security-auditable** — every installed package has a manifest file
  describing exactly where it came from, when, and what version.
- **Git-friendly** — binaries stay out of the repo; only the recipe
  and provenance structure is tracked.
- **Release-friendly** — you can ship a pre-populated `lib/` in a
  release zip for users who don't want to run a script.

## Override: use pip-installed deps instead

If you already have PySide6 installed globally and would rather use
that copy, set an environment variable:

```
SCRIPTREE_USE_SYSTEM_DEPS=1
```

With this set, `run_scriptree.py` skips the `lib/pypi/` path injection
and uses whatever your Python environment provides.
