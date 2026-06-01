# No-bytecode policy (MANDATORY — do not weaken this guard)

**Audience:** human developers AND LLM contributors editing the ScripTree
source tree, build scripts, launchers, or packaging tooling.

**TL;DR:** ScripTree must never write `.pyc` files into `__pycache__/`
folders inside its install tree.  Every entry-point sets
`sys.dont_write_bytecode = True` before any import.  The launcher
`.bat` files also set `PYTHONDONTWRITEBYTECODE=1` as a first line of
defence.  If you find yourself disabling, weakening, or working around
either of these, **stop and re-read this document** — there is
almost certainly a different fix.

---

## Why this matters

ScripTree installs commonly live in cloud-synced folders — Dropbox,
OneDrive, Google Drive, iCloud Drive — because the user wants the
same workspace across multiple machines.  This is a supported and
expected deployment.

Cloud-sync clients react badly to bulk file writes.  Specifically, a
fresh ScripTree launch with default bytecode caching enabled:

1. **Read storm** — Python opens every imported `.py` file.  The
   cloud client's filesystem filter driver intercepts each open,
   hashes the file, and decides whether to re-upload it.  This roughly
   doubles the effective I/O of startup.
2. **Write storm** — Python compiles each imported module and writes
   the result as `__pycache__/<module>.cpython-<ver>.pyc`.  On a first
   launch (or after any source update) this produces *hundreds* of
   new files within a few seconds.  The cloud client detects them all,
   floods its sync queue, and goes effectively unresponsive for
   **15-30 seconds per launch** while it hashes and queues them all.

To the user, this looks like ScripTree just broke Dropbox.  The only
reliable workaround prior to this guard was for the user to **pause
sync manually before every single launch** — unacceptable UX.

Setting `sys.dont_write_bytecode = True` (or its environment-variable
equivalent `PYTHONDONTWRITEBYTECODE=1`) eliminates the write storm
entirely.  Python recompiles modules in memory on each launch and
discards them — a few extra milliseconds of CPU on a modern SSD,
imperceptible in practice.

---

## How the guard is layered

Defence-in-depth: three layers, each independent so the policy holds
even if one layer is bypassed.

| Layer | File(s) | What it does |
|---|---|---|
| 1. Launcher env var | `run_*.bat`, `run_*.cmd` (any future cmd/sh wrappers) | `set PYTHONDONTWRITEBYTECODE=1` BEFORE invoking Python.  Caught by Python at interpreter startup, before any module loads. |
| 2. Entry-point flag | `run_scriptree.py`, `run_scriptreeforest.py`, `run_scriptreering.py`, `screenshooter.py` | `import sys; sys.dont_write_bytecode = True` as the first executable statement (after the module docstring).  Catches the case where someone runs `python run_scriptree.py` directly without the `.bat` wrapper, or invokes from a different shell. |
| 3. Package guard | `scriptree/__init__.py` | Sets the flag again, immediately after the docstring.  Catches `python -m scriptree`, library import via `from scriptree import X`, REPL probes, and pytest collection. |

All three layers must stay in place.  Removing one is a regression
even if the other two cover most cases — testers and packagers regularly
invoke ScripTree in ways that bypass two of the three.

---

## ❌ Things you MUST NOT do

These will reintroduce the sync storm and have been ruled out as
acceptable approaches.  If a task seems to require one of these,
the task is wrong — flag it and ask.

### 1. Do not flip `sys.dont_write_bytecode` back to False anywhere

Not in tests, not in dev shims, not "just for the editor."  Once any
module flips it to False, every subsequent compile in the same
process writes a `.pyc`.  There is no legitimate reason ScripTree
needs cached bytecode.

### 2. Do not delete `PYTHONDONTWRITEBYTECODE=1` from the launchers

Do not "clean up" the env var from the `.bat`/`.cmd` files because
"the .py guard already covers it."  The env var catches the case
where Python is started with a sub-module path on the command line
(e.g. `python lib\install_python.ps1`-derived calls) where module
imports happen BEFORE the entry-point's first statement runs.

### 3. Do not set `PYTHONPYCACHEPREFIX` to a path inside the install tree

`PYTHONPYCACHEPREFIX` redirects `.pyc` writes to a single tree.
Setting it INSIDE the install (`%~dp0__pycache_root__\` or similar)
would put the writes BACK into the cloud-synced folder.  If you want
to redirect bytecode anywhere, it has to be a per-user OUTSIDE the
sync root (e.g. `%LOCALAPPDATA%\ScripTree\pycache\`) — but in practice
the no-write guard is simpler, faster to set up, and avoids stale-
cache invalidation bugs.

### 4. Do not pre-compile `.pyc` files at packaging time

Do not run `compileall`, do not invoke `py_compile`, do not let
PyInstaller / Nuitka emit cached bytecode into the bundle directory
that will be deployed to Dropbox.  Pre-compiled `.pyc` files at the
TIME OF DEPLOYMENT trigger an immediate sync storm the next time
the cloud client wakes up — the user's first interaction with
ScripTree is then Dropbox going unresponsive, and the no-write
runtime guard doesn't help.

`make_portable.py` MUST strip any `__pycache__/` folders before
zipping.  If you change the packaging script, preserve this rule.

### 5. Do not introduce a new launcher that skips the guard

Any new `.bat`/`.cmd`/`.sh` wrapper, any new `.py` entry-point, any
new packaging tool that invokes Python on the install tree, must
include the env var (in the shell wrapper) AND the
`sys.dont_write_bytecode = True` line (in any new `.py` entry-point).
The CI test `tests/test_no_bytecode_guard.py` will fail if you add a
launcher that omits it.

### 6. Do not exclude this test from CI

The test that pins the guard in place (`tests/test_no_bytecode_guard.py`)
must stay in the default test run.  Do not `@pytest.mark.skip` it,
do not move it into a manual suite, do not delete it.

---

## ✅ Verifying the guard

After making any change to a launcher, entry-point, packaging script,
or `scriptree/__init__.py`:

```bash
python -m pytest tests/test_no_bytecode_guard.py -q
```

Must pass with **no skips and no warnings**.  Additionally, after a
clean launch (preferably from a Dropbox folder):

```bash
# 1. Delete all cached bytecode in the install tree first
find . -type d -name __pycache__ -exec rm -rf {} +

# 2. Launch ScripTree normally
run_scriptree.bat

# 3. Quit ScripTree

# 4. Check no __pycache__ folders were created
find . -type d -name __pycache__
# Output should be empty.
```

---

## Frozen-executable note (PyInstaller / Nuitka)

When ScripTree gets packaged into a single-file or one-dir
executable, the `.bat` launchers are no longer in the path —
but the `sys.dont_write_bytecode = True` lines in the entry-point
`.py` files survive the freeze and continue to fire at startup.

If you ever change the entry-point arrangement:

- **PyInstaller one-file**: bundle extracts to `%TEMP%` and runs from
  there.  No `.pyc` writes land in the install tree.  Safe by
  construction.
- **PyInstaller one-dir**: the runtime DOES write `.pyc` files into
  the install directory unless the entry-point sets
  `sys.dont_write_bytecode = True` before any other import.  This is
  exactly the case the entry-point guard exists for — don't disturb
  it.
- **Nuitka**: compiles to native code, no `.pyc` writes regardless.
  Still, leave the guards in: a future re-bundle as PyInstaller would
  need them.

---

## History

This policy was promoted to mandatory after a user-reported issue:
ScripTree v0.8.0a20 deployed at `R:\ScripTree\` (a `subst` alias for
`D:\Stanley Dropbox\Resource\`) caused Dropbox to become unresponsive
for 15-30 seconds at every launch, with no warning and no error.  The
user's workaround was to pause Dropbox sync manually before each
launch.  After investigation, every imported ScripTree module was
producing a `.pyc` write into a `__pycache__/` folder inside the
Dropbox tree.  The guard documented above was added at v0.8.0a24 and
will remain in place permanently.
