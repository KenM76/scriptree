# Portable-bundle trim silently stripped a REQUIRED Qt submodule (QtNetwork) — a111

**Tag:** [packaging] [pyside6] [vendored-deps] [release] [single-instance]
**Version:** v0.8.0a111
**Files:** `lib/update_lib.py` (the dependency builder), `lib/pypi/PySide6/`
(the vendored bundle), `make_portable.py` (the release-zip builder),
`scriptree/shell/single_instance.py` (the importer).

## Symptom

The released portable zip (and the live `R:\ScripTree` install) had
single-instance / second-launch handoff silently disabled:
`[shell.main] single-instance handoff errored: ModuleNotFoundError("No module
named 'PySide6.QtNetwork'"); falling through to start a primary anyway`.
Every launch started a fresh primary — relaunch never revealed the existing
forest. The app otherwise ran fine, so it went unnoticed.

## Root cause — the `--trim` step strips any Qt module not in the keep-list

ScripTree ships a **minimal** vendored PySide6 (only the Qt modules it uses) to
keep the portable zip small. `lib/update_lib.py --trim` deletes every Qt
submodule **not** in `TRIM_KEEP_MODULES` (was `{QtCore, QtGui, QtWidgets}`), and
`make_portable.py` *requires* a trimmed `lib/pypi/` before it builds the zip.
But `scriptree/shell/single_instance.py` does `from PySide6.QtNetwork import
QLocalServer, QLocalSocket` — and `QtNetwork` was **missing from the keep-list**.
So the trim stripped `QtNetwork.pyd` + `Qt6Network.dll` out of every build,
breaking the import. (Only the `.pyi` type stub survived, because `*.pyi` is in
`TRIM_ALWAYS_KEEP` — a red herring that makes the dir *look* like it has
QtNetwork.)

## The TWO-part fix (one alone is not enough)

The trim has **two independent removal paths**, and QtNetwork was caught by both:

1. **`_iter_module_related` (keep-list-driven):** removes any `Qt<Name>.pyd` /
   `Qt6<Name>.dll` whose module isn't in `TRIM_KEEP_MODULES`. → Fix: add
   `"QtNetwork"` to `TRIM_KEEP_MODULES`. This keeps `QtNetwork.pyd` AND maps
   `Qt6Network.dll` → module `QtNetwork` → kept.
2. **`TRIM_REMOVE_GLOBS` (explicit strip-glob, NOT keep-list-aware):** had
   `"Qt6Network*.dll"` + `"libQt6Network*.so*"`. This sweep runs first and
   overrode the keep-list, so the `.dll` was deleted while the `.pyd` survived →
   an unimportable QtNetwork. → Fix: **remove** the two `Qt6Network*` entries
   from `TRIM_REMOVE_GLOBS` so the keep-list is the single source of truth.

After both: `python lib/update_lib.py --trim --dry-run` reports **0 items would
be removed** (both Network files survive). `make_portable.py` copies `lib/pypi/`
wholesale (its `EXCLUDE_DIRS` skips `tests/docs/scripts/user_configs/...` but
NOT `lib`/`pypi`/`PySide6`), so the zip now ships QtNetwork and single-instance
works in the release.

## The durable guard

**`TRIM_KEEP_MODULES` must equal the set of PySide6 submodules the code
imports.** Audit it with:
```
grep -rhoE "from PySide6\.(Qt[A-Za-z]+) import|import PySide6\.(Qt[A-Za-z]+)" \
  scriptree/ --include=*.py | grep -oE "Qt[A-Za-z]+" | sort -u
```
As of a111 that is exactly `{QtCore, QtGui, QtWidgets, QtNetwork}`. Any new
`from PySide6.QtXxx import` REQUIRES adding `QtXxx` to `TRIM_KEEP_MODULES`
(and making sure `QtXxx`/`Qt6Xxx` isn't in `TRIM_REMOVE_GLOBS`), or the next
trimmed release will `ModuleNotFoundError` at runtime.

## Reusable takeaways

1. **A minimal/pruned vendored bundle is a standing liability:** a new
   `from PySide6.QtXxx` import works on the dev machine (full PySide6 installed)
   but breaks in the trimmed release. The keep-list is the contract; treat it
   like one.
2. **When a pruner has two removal paths (keep-list + explicit deny-glob), an
   item can be in both** — fixing only the keep-list leaves the deny-glob
   winning. Check for an explicit deny entry too.
3. **A surviving `.pyi` stub hides a stripped binary** — `ls PySide6/QtNetwork*`
   showing `QtNetwork.pyi` does NOT mean the module is importable; check for the
   `.pyd` + its `Qt6<Name>.dll`.
4. PySide6 wheels use the **stable abi3** ABI, so a `QtXxx.pyd` from any
   matching-version install works across CPython 3.9–3.14 — handy for hand-
   patching a bundle (verify the `Qt6Core.dll` md5 matches to confirm same Qt
   build before mixing DLLs).
