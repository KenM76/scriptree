# `pip install --target <existing_dir>` clobbers sibling files

**Tag**: `v3-process`
**Date**: 2026-06-07
**Versions affected**: vendoring practice from v0.8.0a48 onward

## TL;DR

Running `pip install --target lib/pypi --no-deps <package>` into the
**existing** ScripTree vendor directory wipes parts of the previously-
installed PySide6 console-scripts (`lib/pypi/bin/pyside6-*.exe`) as a
side effect. The exact mechanism is pip's `--target` cleanup of
"files belonging to other packages with the same RECORD-derived
ownership", but the end result is the same: another vendored
package's binaries silently disappear from the working tree.

**Don't install directly into the live vendor dir.** Either:

1. Install into a **temp dir**, then `cp -r tmp/* lib/pypi/`. This is
   what we'll do for future single-package additions:
   ```bash
   STAGE=$(mktemp -d)
   python -m pip install --target "$STAGE" --no-deps Package==X.Y.Z
   cp -r "$STAGE"/* lib/pypi/
   rm -rf "$STAGE"
   ```
2. Use the canonical `python lib/update_lib.py --upgrade` (which
   wipes-and-rebuilds the whole dir on purpose). Stops working when
   another Python process is holding `lib/pypi/bin/*.exe` open —
   close all ScripTree windows first.

## How v0.8.0a48 hit it

Adding `CommonRegex==1.5.4` to `lib/requirements.txt`. The canonical
`update_lib.py --upgrade` aborted with a `PermissionError` on
`lib/pypi/bin` because a running Python (probably an editor or
helper window) had one of the `pyside6-*.exe` files mapped. To work
around, I ran:

```bash
python -m pip install --target lib/pypi --no-deps CommonRegex==1.5.4
```

Install reported success; `lib/pypi/commonregex.py` and its
dist-info appeared as expected. But `git status` then showed 23
**deletions** of `lib/pypi/bin/pyside6-*.exe` files. Each was a
PySide6 console-script entry that pip apparently considered "owned
by some other RECORD" and cleaned up during the install.

Restored from R: before commit. The PySide6 source-of-truth on the
production deploy mirror was intact because nothing had wiped it
there; copying back to D: was a one-liner.

## Detection

Always run `git status --short | grep '^.D'` after a vendored-pip
install. If you see deletions of `lib/pypi/<other_package>/*` or
`lib/pypi/bin/<other_package>-*.exe`, the install collided.

## Recovery

1. `git checkout HEAD -- lib/pypi/` to restore everything from the
   last commit (works when the prior commit had the full vendor
   tree).
2. If the prior commit also missed those files, copy from R:
   (or another machine that still has them) — R: is the deploy
   mirror and tends to stay intact unless explicitly wiped.
3. Re-run the install via the safe temp-dir approach above.

## Cross-reference

- `lib/update_lib.py` — the canonical vendor-refresh script.  Its
  rmtree-and-rebuild design is the reason it's the right tool when
  nothing is holding the dir open.
- `lib/_manifests/CommonRegex.md` — provenance note for the
  v0.8.0a48 addition, explaining why we used the manual install
  path instead of `update_lib.py`.
