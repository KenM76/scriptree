# Portable Python install

ScripTree can run against a Python that lives entirely under its own
`lib/python/` folder — no system-wide install, no admin rights, no
PATH changes. This page explains how the portable install works, when
to use it, and how to do it manually if the automated path doesn't
fit your situation.

## When this matters

The portable zip ships **without** Python — just ScripTree's own
code, the vendored PySide6 libraries, and a few shell scripts. The
launcher (`run_scriptree.bat` / `run_scriptree.sh`) needs Python 3.11
or later to start the application.

If a user double-clicks `run_scriptree.bat` on a clean Windows machine
that doesn't have Python yet, the launcher pops a dialog:

```
No Python 3 was found on this machine. ScripTree needs Python 3.11
or later.

[ Yes ]    Install a portable Python into lib\python\ (recommended)
[ No ]     Open python.org download page in your browser
[ Cancel ] Quit
```

Picking **Yes** runs `lib/install_python.ps1`, which downloads the
python.org embeddable distribution and drops it under `lib/python/`.
After that one-time setup, the launcher always uses the portable
copy — moving the ScripTree folder to a different machine of the
same OS / arch keeps working without any further install steps.

## How the launcher finds Python

Both `run_scriptree.bat` and `run_scriptree.sh` walk this priority
list:

1. **Portable** — `lib/python/pythonw.exe` (Windows) or
   `lib/python/bin/python3` (macOS / Linux).
2. **System on PATH** — `pythonw.exe` then `python.exe` on Windows,
   `python3` then `python` on Unix.
3. **Prompt the user** — the dialog described above.

You can deploy ScripTree alongside an already-installed Python and
the launcher just uses it; or you can ship the portable folder cold
and let users install via the dialog.

## Windows: `lib/install_python.ps1`

What the script does:

1. Queries python.org's release feed for the latest stable Python 3
   (falls back to a hard-coded known-good version if the API is
   unreachable — currently `3.13.1`).
2. HEAD-checks the embeddable zip URL to confirm the version actually
   has a published embed for the host architecture (amd64 or arm64).
3. Downloads the embed zip to `%TEMP%`.
4. Extracts to `lib/python/`.
5. Patches `pythonXX._pth` to uncomment `import site` — without this
   line, `python -m pip` can't find installed packages.
6. Downloads `get-pip.py` from `bootstrap.pypa.io`, runs it under the
   new portable Python.
7. Runs `lib/update_lib.py --trim` to populate vendored ScripTree
   deps (PySide6 + QtAds, trimmed to ~50 MB).
8. Cleans up the temp zip + `get-pip.py`.

To run it manually (e.g. to override the version):

```powershell
# From the ScripTree install root:
powershell -ExecutionPolicy Bypass -File .\lib\install_python.ps1 -PythonVersion 3.13.0
```

## macOS: `lib/install_python.sh`

The .pkg path:

1. Downloads `python-X.Y.Z-macos11.pkg` from python.org.
2. Runs `pkgutil --expand-full` to unpack the .pkg without the system
   installer (no `sudo`, no global install).
3. Copies the framework's `Versions/X.Y/` directory contents into
   `lib/python/`.
4. Adds a `bin/python` symlink (the embed sometimes ships only
   `bin/python3` / `bin/python3.X`) for parity with the launcher.
5. Runs `python -m ensurepip --upgrade` to bootstrap pip.
6. Runs `lib/update_lib.py --trim`.

To run it manually:

```bash
bash lib/install_python.sh           # latest stable
bash lib/install_python.sh 3.13.0    # specific version
```

## Linux: package-manager nudge or python-build-standalone

There's no official "embeddable" python.org build for Linux, so
`install_python.sh` on Linux **prints instructions and exits** —
it doesn't try to install anything itself.

### Easiest path — distro package manager

```bash
# Debian / Ubuntu:
sudo apt install python3.11 python3.11-venv

# Fedora / RHEL / Rocky:
sudo dnf install python3.11

# Arch:
sudo pacman -S python

# openSUSE:
sudo zypper install python311
```

Then re-run `bash run_scriptree.sh`.

### Truly portable Linux Python — `python-build-standalone`

Astral / Anthropic / Posit and others maintain
[`indygreg/python-build-standalone`](https://github.com/indygreg/python-build-standalone/releases),
which publishes static-linked, fully portable Python builds for
Windows, macOS, and Linux. They're not python.org-official, but
they're production-grade (used by `uv`, Anaconda, RStudio, etc.).

Manual install on Linux:

```bash
cd path/to/ScripTree/lib

# Find a release that matches your arch on the GitHub releases page:
#   x86_64-unknown-linux-gnu        (most x64 Linux)
#   aarch64-unknown-linux-gnu       (ARM64 Linux, e.g. Raspberry Pi 4+)
#
# Look for the file ending in "-install_only.tar.gz" — that's the
# pre-built tree ready to drop in (vs the "-debug-tarball.tar.gz"
# variants which are for debugging interpreter bugs).

curl -fLO 'https://github.com/indygreg/python-build-standalone/releases/download/<DATE>/cpython-<VERSION>+<DATE>-x86_64-unknown-linux-gnu-install_only.tar.gz'

tar xzf cpython-*-install_only.tar.gz
# The extracted top folder is named "python" — it should land at
# <ScripTree>/lib/python/

cd ..
bash run_scriptree.sh
```

The same trick works on Windows and macOS too if you prefer
`python-build-standalone` builds over python.org's embed / .pkg —
just pick the matching `-install_only.tar.gz` for your host triple.

## Verifying the install

After the script finishes:

```
<ScripTree>/lib/python/
├── python.exe          (Windows; or bin/python3 on Unix)
├── pythonw.exe         (Windows; no console window)
├── pythonXX.dll
├── Lib/
│   └── site-packages/
│       ├── pip/
│       └── ...
└── ...
```

Quick sanity check:

```
# Windows:
"<ScripTree>\lib\python\python.exe" -V
"<ScripTree>\lib\python\python.exe" -m pip --version

# Unix:
"<ScripTree>/lib/python/bin/python3" -V
"<ScripTree>/lib/python/bin/python3" -m pip --version
```

Both should report a Python 3.11+ version and a pip from the new
install.

## Removing the portable install

It's just a folder — delete it:

```
# Windows:
rmdir /s /q lib\python

# Unix:
rm -rf lib/python
```

The launcher will fall back to system Python (or to the install
prompt) on the next run.

## Path discovery from tools

Once a portable Python is installed, ScripTree publishes
`SCRIPTREE_LIB_PYTHON` on the environment for every tool subprocess.
A tool's `.scriptree` file can reference it via env-var expansion:

```json
{
  "executable": "%SCRIPTREE_LIB_PYTHON%/python.exe",
  "argument_template": ["./helper.py", "{input}"]
}
```

The same `.scriptree` works on a machine where ScripTree uses the
system Python (no portable install) — `%SCRIPTREE_LIB_PYTHON%` just
isn't set there, and your tool's executable resolution can fall
back to whatever else you specify. See
[environment.md](environment.md) for the full list of
`SCRIPTREE_*` variables.
