---
topic: v3-process
date: 2026-05-23
status: gotcha
related: [make_portable_non_interactive]
---
# Dropbox catastrophically slows Python startup on `subst` drives

## What happened

Python launches from `R:\` (a `subst` mount, see below) sometimes
took 40+ seconds and occasional file-operation failures, when other
times the same command completed in ~70 ms. The fast/slow split
correlated perfectly with whether Dropbox was running.

`R:` is `subst D:\Stanley Dropbox\Resource` — a virtual drive
letter pointing into a Dropbox-synced folder. While Dropbox is
running it has 10+ processes scanning the tree, which interacts
badly with Python's startup file-walk (sys.path scan, importlib
metadata, etc.).

## Root cause

Dropbox holds file handles or competes for I/O on the
`D:\Stanley Dropbox\` subtree. Python startup hits the subtree
through the `subst` mount, gets queued behind Dropbox's own scans,
and waits 40+ seconds. Other times Dropbox happens to be quiet and
the launch is normal — making the slowness intermittent and hard to
diagnose.

`R:` itself is the canonical deployment target for ScripTreeApps
(`R:\Scriptreeapps\`), so this is hit constantly when running the
real app from the deployed location.

## Fix / recipe

Before any release build, deploy, or systematic test run from `R:`:

```powershell
Get-Process Dropbox -ErrorAction SilentlyContinue | Stop-Process -Force
```

Then Python startup from R:\ drops back to ~70 ms.

If a particular `make_portable.py` or release recipe is mysteriously
slow, this is the first thing to check. The CLAUDE.md "launch
discipline" already mentions Dropbox; this lesson records the
empirical timings so the magnitude is documented.

## Timings (empirical)

| Dropbox state | `python -c "print(1)"` from R:\ |
|---|---|
| Running (10+ processes) | 40+ seconds, sometimes 60+, occasional file-op failures |
| Killed | ~70 ms |

Difference is ~600× — not a marginal optimization, a functional
blocker.

## How future-me detects it

* "Why is my Python launch slow today" + working from R:\ →
  `Get-Process Dropbox` → if non-empty, kill it.
* `make_portable.py` running on R:\ taking minutes instead of
  seconds — same root cause.
* Same trap applies to any `subst` drive into a Dropbox-synced
  folder, not just R:. If you map another letter to `D:\Stanley
  Dropbox\X`, you'll see identical behaviour.
* Not specific to Python — applies to any tool that file-walks the
  tree during startup (pytest, npm, dotnet restore). Killing
  Dropbox helps all of them.

This sits in v3-process because the slowness materially affects the
release build cadence; future maintainers running scheduled or
unattended build jobs need to know.
