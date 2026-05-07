---
topic: v3-process
date: 2026-05-07
status: workflow
related: [sweep_replace_pattern_for_renames]
---
# Backup-first discipline

## What happened / rule

Every risky touch — file moves, sweep regex replaces, large
refactors, anything that mutates many files at once — starts
with a full timestamped zip of the working tree to OneDrive.
Cheap insurance, takes seconds, makes recovery from a botched
sweep trivially `Expand-Archive`.

## Root cause / rationale

`git` is great for tracked changes, but a sweep that touches
166 references across 17 files often gets committed in one
shot — if it goes wrong, untangling it via `git` is more
work than restoring from a zip and re-running with a
corrected pattern.  And uncommitted experimental work (the
common case mid-session) isn't covered by `git` at all.

## Fix / recipe

Before any risky operation:

```powershell
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$dst = "C:\Users\Ken\OneDrive\Kens_Projects\Claude\Software\ScripTree3-backup-$ts.zip"
Compress-Archive -Path D:\Dev\ScripTree3\* -DestinationPath $dst -Force
```

The OneDrive sync gives offsite redundancy for free.  Naming
convention: `ScripTree3-backup-YYYYMMDD-HHMMSS.zip`.

Risky operations include:
- Cross-file regex sweeps
- `git mv` of more than one file at a time
- Renames across the whole tree
- Anything involving `[System.IO.File]::WriteAllText` in a
  loop
- Pre-test runs of new tests that might mutate fixtures

## How future-me detects it

You're about to run a multi-file mutation and you don't have
a backup zip from the last 30 minutes.  Stop, run the
`Compress-Archive`, then proceed.  The 5 seconds saves
hours when (not if) the sweep is wrong.
