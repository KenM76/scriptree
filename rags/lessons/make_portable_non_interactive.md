---
topic: v3-process
date: 2026-05-23
status: recipe
related: [combridge_bundle_workflow]
---
# `make_portable.py` hangs without `--scriptreeapps` in non-TTY runners

## What happened

Releases launched from PowerShell `Start-Process`, scheduled tasks,
CI runners, or any non-interactive parent process would silently hang
during portable-zip builds. The script was prompting for input on
whether to keep / overwrite / back up the existing `ScripTreeApps/`
directory in the destination — but the parent had no stdin attached
to type a response.

## Root cause

`make_portable.py` defaults to interactive disposition of the
existing `ScripTreeApps/` directory. With no TTY, the prompt waits
forever.

## Fix / recipe

Always pass `--scriptreeapps` explicitly in release scripts:

```powershell
python make_portable.py D:\Builds\ScripTree-vX.X.X `
    --force `
    --no-smoke-test `
    --zip `
    --scriptreeapps overwrite
```

Acceptable values: `keep | overwrite | backup`.

Recipe produces folder + zip in ~25 s on a warm cache. `--force`
skips the destination-already-exists prompt, `--no-smoke-test` skips
the post-build python launch (smoke test needs a graphical session;
useless in CI).

If you also want combridge bundled:

```powershell
python make_portable.py D:\Builds\ScripTree-vX.X.X `
    --force --no-smoke-test --zip `
    --scriptreeapps overwrite `
    --bundle-combridge
```

## How future-me detects it

* "I started a release build via `Start-Process` and it's been
  running 10 minutes" — check with `Get-Process python | Select Id,
  CPU` — if CPU is near zero, it's blocked on stdin.
* The script is fine to run interactively without the flag — it'll
  just ask. The hang only triggers in non-interactive parents.
* Same trap applies to any new prompt added to `make_portable.py` —
  give every prompt a CLI flag override at the same time you add the
  prompt.
