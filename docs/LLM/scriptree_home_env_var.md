# `SCRIPTREE_HOME` — the env-var contract for tools that need bundled binaries

**Audience:** anyone (human or LLM) authoring a ScripTree tool that
needs to find a binary, library, plugin, or asset that ships INSIDE
the ScripTree install tree (e.g. `lib/combridge/combridge.exe`).

**Status:** stable since v0.8.0a25. The runner sets it on every
spawned tool's environment. Tools that need it READ it; tools that
don't need it can ignore it entirely.

---

## What ScripTree guarantees

When the runner spawns ANY tool subprocess (Python, PowerShell,
.bat, native exe, ...), it injects these environment variables
before launch:

| Variable | Value | Set when |
|---|---|---|
| `SCRIPTREE_HOME` | Absolute path to the ScripTree install root (where the `scriptree` package lives). | Always. |
| `SCRIPTREE_LIB` | `SCRIPTREE_HOME/lib`. | Always, when `lib/` exists on disk. |
| `SCRIPTREE_TOOL_DIR` | Absolute path to the `.scriptree` file's containing folder. | Always, for spawns that have a `.scriptree`. |
| `PATH` (prepended) | `SCRIPTREE_HOME/lib/combridge` is prepended to the inherited `PATH` so `combridge.exe` resolves by bare name. | Always, when `lib/combridge/` exists. |

These are guarantees the runner will keep. Tools can rely on them
across:

- Personal-apps installs (`%LOCALAPPDATA%\ScripTree\Apps\…`)
- Shared installs (`<install>\ScripTreeApps\…`)
- Portable installs on a USB drive
- Any future install location

The values are **per-process**: the running ScripTree's location is
captured at spawn time. If two different ScripTree installs are on
the same machine, each one's spawned tools see THAT install's
`SCRIPTREE_HOME`.

---

## What this REPLACES — old "walk upward" pattern

The historical pattern for finding `combridge.exe` from a Python
tool was:

```python
COMBRIDGE_REL = Path("lib") / "combridge" / "combridge.exe"

def find_combridge(start: Path) -> Path | None:
    for base in [start, *start.parents]:
        candidate = base / COMBRIDGE_REL
        if candidate.is_file():
            return candidate
    return None
```

That works only when the tool's own folder is INSIDE the ScripTree
install tree — e.g. `<install>/ScripTreeApps/MyApp/`. It **fails**
when the tool lives at `%LOCALAPPDATA%/ScripTree/Apps/MyApp/`
because the upward walk runs off the C: root without ever reaching
`<install>/lib/combridge/combridge.exe`.

The replacement pattern checks `SCRIPTREE_HOME` first:

```python
import os
from pathlib import Path

COMBRIDGE_REL = Path("lib") / "combridge" / "combridge.exe"

def find_combridge(start: Path) -> Path | None:
    # Prefer the runner-supplied install root. This works regardless
    # of where the tool was installed on disk.
    home = os.environ.get("SCRIPTREE_HOME")
    if home:
        candidate = Path(home) / COMBRIDGE_REL
        if candidate.is_file():
            return candidate
    # Fall back to the upward walk for legacy launches (manual
    # `python tool.py ...` outside ScripTree's runner).
    for base in [start, *start.parents]:
        candidate = base / COMBRIDGE_REL
        if candidate.is_file():
            return candidate
    return None
```

Two-tier: env var first (the runtime contract), upward walk second
(legacy / direct-invocation fallback).

---

## Authoring rules

### DO

- **Read `SCRIPTREE_HOME` first** when your tool needs anything
  from the ScripTree install tree (`lib/combridge/`,
  `lib/python/`, bundled plugin DLLs, branding icons, etc.).
- **Fall through to a legacy strategy** (upward walk, bare-name
  PATH lookup, etc.) so the tool stays useful when invoked
  directly without ScripTree's runner.
- **Use `os.environ.get("SCRIPTREE_HOME")`** with `.get` so an
  unset env var returns `None` instead of raising `KeyError`.
  ScripTree always sets it, but defensive coding survives
  edge cases (a test harness running the tool directly,
  someone debugging in an IDE, etc.).
- **Trust bare-name binary lookup** for any executable inside
  `<install>/lib/combridge/`. ScripTree prepends that folder to
  the spawned tool's `PATH`, so:
  ```python
  subprocess.run(["combridge.exe", "--help"])
  ```
  resolves to the bundled binary even without `SCRIPTREE_HOME`.

### DO NOT

- **Don't hard-code the install path.** `r"D:\Dev\ScripTree\lib\…"`
  is brittle — works on Ken's dev machine, breaks on every
  other install.
- **Don't require `SCRIPTREE_HOME` to be set.** Always have a
  fallback so direct CLI invocation outside ScripTree still works.
- **Don't override `SCRIPTREE_HOME`** in your tool. The runner
  knows where it is; you don't.
- **Don't write to anything under `SCRIPTREE_HOME`** at runtime
  unless you really mean to modify the install. User data goes
  in `SCRIPTREE_TOOL_DIR`, `%LOCALAPPDATA%`, or wherever the user
  picked — not in the program tree.

---

## What ScripTree does NOT promise

- **`SCRIPTREE_HOME` is read-only from the tool's perspective.**
  Don't `os.environ["SCRIPTREE_HOME"] = "..."` and expect future
  ScripTree behaviour to track the change.
- **Hard-wired paths in your tool are untouched.** If you call
  `r"C:\Program Files\Foo\bar.exe"` explicitly, the env var doesn't
  alter it. Env vars are inert until read.
- **No magic on `argv[0]` or `__file__`.** Your tool's `__file__` is
  still the real on-disk path Python opened. The env var doesn't
  change discovery patterns that anchor on `__file__`.

---

## PowerShell / .bat / native-exe tools

The same contract applies. From PowerShell:

```powershell
$home = $env:SCRIPTREE_HOME
$combridge = Join-Path $home 'lib\combridge\combridge.exe'
& $combridge word run-script $scriptPath
```

From a `.bat` file:

```bat
"%SCRIPTREE_HOME%\lib\combridge\combridge.exe" word run-script "%1"
```

From any program that respects `PATH`:

```cmd
combridge word run-script script.csx
```

(Resolves via the `PATH` prepend the runner does.)

---

## Why this is better than the alternatives

| Alternative considered | Why we didn't | 
|---|---|
| **Walk upward from `__file__`** | Works only when the tool lives inside the install tree — breaks for personal-apps installs. |
| **Create a directory junction** at the personal-apps root pointing at `<install>/lib`. | OS-level filesystem trick. User explicitly rejected this approach (2026-06-02) in favour of a pure-in-process mechanism. |
| **Copy `lib/` into the personal-apps root** at install time. | Wasteful (100+ MB duplicated per user); stale on combridge updates; sync-storm hazard on cloud-backed install folders. |
| **Inject `SCRIPTREE_HOME` env var** (this contract). | One-line read; works on every OS; survives moves and re-installs; zero filesystem footprint; tools that don't need it ignore it; legacy upward-walk still works inside-install. |

---

## Implementation pointers

- Runner side: `scriptree/core/runner.py` → `inject_tool_dir_env()`
  sets `SCRIPTREE_HOME`, `SCRIPTREE_LIB`, `SCRIPTREE_TOOL_DIR`, and
  prepends `lib/combridge` to `PATH`.
- Tool-authoring reference: every Office tool under
  `D:\Dev\ScripTreeAppProjects\MSOffice\…` carries the
  two-tier `find_combridge` shown above.
- This doc lives at `docs/LLM/scriptree_home_env_var.md` and is
  the canonical contract; the implementation in `runner.py` is
  expected to honour every guarantee here.
