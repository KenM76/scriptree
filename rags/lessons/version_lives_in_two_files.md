---
topic: v3-process
date: 2026-06-03
status: gotcha
related: [controller_api_cell_or_path, sweep_replace_pattern_for_renames]
---
# Version lives in TWO files; pyproject.toml alone is invisible to the runtime

## What happened

Shipped v0.8.0a26, a27, a28 in one session.  Each release bumped
`pyproject.toml` from `0.8.0a25` → a26 → a27 → a28 and deployed
the file to `R:\ScripTree\`.  The user later relaunched R: and
reported "doesn't look like it updated" — the About dialog was
still showing the old version.

## Root cause

There are TWO version constants in the ScripTree tree and **the
one the user actually sees is NOT in `pyproject.toml`**:

| File | Read by | What sees it |
|---|---|---|
| `D:\Dev\ScripTree\scriptree\__init__.py` lines 60 + 71 | `from scriptree import __version__, __build_date__` | **Runtime About dialog** (`scriptree/ui/help_dialog.py:351`), cell-window About code (`scriptree/shell/cell_window.py:7759`).  The file's own comment block calls it "the single source of truth for the runtime." |
| `D:\Dev\ScripTree\pyproject.toml` `version = "..."` | `pip`, `setuptools`, `make_portable.py` | Build / packaging metadata only.  Invisible to the running app. |

I'd internalised "bump pyproject.toml" from earlier release rituals
(the file is alphabetically first; it's at the project root; it
LOOKS like the canonical version source) and bumped only that
file across three sequential releases.  The `__init__.py` constant
stayed at `0.8.0a25` the whole time — so every R: deploy was
"complete" by every other metric (hash-matched files, current code
on disk) yet the user's About dialog reported the version from
five commits ago.

This is the most insidious deploy gap because every diagnostic
short of opening the About dialog says everything is fine:

* `git log` shows the version bumps committed.
* `pyproject.toml` on R: matches D: (`0.8.0a28`).
* Every code file hash-matches D: → R:.
* `pip show scriptree` on R: would (correctly) report `0.8.0a28`.

The only failing surface is the one the user actually looks at.

## Fix / recipe

**Bump BOTH files together, in the same commit, every release:**

```python
# scriptree/__init__.py
__version__   = "0.8.0aXX"          # bump together
__build_date__ = "YYYY-MM-DD HH:MM EDT"   # current local wall-clock time
```

```toml
# pyproject.toml
[project]
version = "0.8.0aXX"
```

Use PowerShell to get the current EDT/EST timestamp (the codebase
switched from UTC at v0.6.36 per user direction — see the
`__init__.py` comment block):

```powershell
Get-Date -Format "yyyy-MM-dd HH:mm 'EDT'"   # use EST in winter
```

Deploy both files to R:.  Note that `__init__.py` is NOT at the
project root (where robocopy targeting subtrees misses it), so it
needs an explicit targeted copy:

```powershell
robocopy D:\Dev\ScripTree\scriptree R:\ScripTree\scriptree __init__.py /NJH /NJS /NDL /NP
Copy-Item D:\Dev\ScripTree\pyproject.toml R:\ScripTree\pyproject.toml -Force
```

## How future-me detects it

* The user reports "R: doesn't look updated" after a release that
  hash-verified clean.
* `git log -p pyproject.toml` shows version bumps but
  `git log -p scriptree/__init__.py` shows the version constant
  hasn't moved in N releases.
* `grep -n __version__ scriptree/__init__.py` returns a number
  that's behind the latest tag.

The lead-engineer contract
(`D:\Dev\ScripTree\.claude\agents\scriptree-lead-engineer.md`)
now carries this rule under "The version lives in TWO files — bump
both" and in the "always" list.  If a future session reads the
contract and STILL bumps only `pyproject.toml`, this lesson is the
explanation of the symptom.

## Diagnostic command

To verify a release is fully shipped:

```powershell
$dInit = (Get-Content D:\Dev\ScripTree\scriptree\__init__.py | Select-String '^__version__').Line
$dPy   = (Get-Content D:\Dev\ScripTree\pyproject.toml      | Select-String '^version =').Line
$rInit = (Get-Content R:\ScripTree\scriptree\__init__.py   | Select-String '^__version__').Line
$rPy   = (Get-Content R:\ScripTree\pyproject.toml          | Select-String '^version =').Line
Write-Host "D __init__:    $dInit"
Write-Host "D pyproject:   $dPy"
Write-Host "R __init__:    $rInit"
Write-Host "R pyproject:   $rPy"
```

All four lines must reference the same version string.
