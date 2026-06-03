---
topic: v3-architecture
date: 2026-06-03
status: recipe
related: [personal_sidecar_two_prong_match, controller_api_cell_or_path]
---
# Uninstall keep/remove flags + safety-backup of shared configs before rmtree

## What happened

Adding "Uninstall app..." needed to give the user explicit control
over two side-effect questions:

1. Keep or delete the user's *personal* (local) sidecar configs
   for the tools in this app?
2. Keep or delete the *shared* sidecar configs that live next to
   each catalog (i.e. `*.scriptree.configs.json`, `*.scriptreetree.treeconfigs.json`)?

Shared configs are inside the app folder itself, so they vanish
when `shutil.rmtree(app_dir)` runs. If the user wants to keep them
(perhaps to re-install later, or because they're under version
control elsewhere), the uninstall has to *physically copy* them out
to a sibling folder BEFORE the rmtree.

## Root cause

Two reasons the backup step is mandatory when `remove_shared_configs=False`:

1. `shutil.rmtree(app_dir)` is atomic-ish — once it starts, anything
   inside is gone. You cannot "keep" files that live under the
   directory you're about to delete unless you move them first.
2. If the backup copy *fails* (disk full, permission denied, name
   collision, etc.), the uninstall must REFUSE — never delete the
   app folder when its configs would be lost. Half-completing the
   user's "keep" request is worse than refusing the action.

## Fix / recipe

`ForestController.uninstall_app` in
`D:\Dev\ScripTree\scriptree\shell\forest_controller.py:925-` (approximate
range) gains two keyword-only flags, both defaulting True so existing
callers behave unchanged:

```python
def uninstall_app(
    self,
    path: str | Path,
    *,
    remove_local_configs: bool = True,
    remove_shared_configs: bool = True,
) -> None:
    app_dir = Path(path).resolve()

    # 1. Enumerate personal sidecars BEFORE doing anything destructive
    personal = find_personal_configs_for_app(app_dir)

    # 2. If asked to keep shared configs, copy them to a backup sibling
    if not remove_shared_configs:
        backup_dir = _next_backup_sibling(app_dir)  # <app>_uninstalled_configs[-2,-3...]
        try:
            for shared in _iter_shared_sidecars(app_dir):
                rel = shared.relative_to(app_dir)
                dest = backup_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(shared, dest)
        except OSError as exc:
            # REFUSE — never proceed to rmtree if the backup failed.
            raise UninstallAborted(
                f"Could not back up shared configs to {backup_dir}: {exc}"
            )

    # 3. Now safe to delete the app folder
    shutil.rmtree(app_dir)

    # 4. Optionally clean personal sidecars (enumerated up-front
    #    because the app folder is already gone by now)
    if remove_local_configs:
        for sidecar in personal:
            sidecar.unlink(missing_ok=True)
```

Backup-folder naming: a sibling of `app_dir` called
`<app>_uninstalled_configs`. If that path already exists, suffix
`-2`, `-3`, etc. The user can spelunk it later; we never
silently overwrite.

UI in `ForestController._on_uninstall_app`: a custom `QDialog` with
two `QCheckBox`es. The labels show a **live count of affected files**
computed BEFORE the dialog opens, e.g.

> ☑ Also remove my local saved configurations (3 files)
> ☑ Also remove shared per-app configurations (5 files) — kept copies
>   go to `<app>_uninstalled_configs/`

The Uninstall button uses
`QDialogButtonBox.ButtonRole.DestructiveRole` so platforms that
style destructive actions (e.g., macOS, some Linux themes) render
it red.

## How future-me detects it

* Symptom: user uninstalls an app and complains that "their saved
  setup is gone" — check that the dialog's two checkboxes are
  wired through to the keyword flags and that the file counts
  match what the helper finds.
* If the backup folder is missing after a "keep shared" uninstall,
  either the copy raised and the uninstall refused (good) OR the
  backup-folder branch was skipped (bug — verify call site passed
  `remove_shared_configs=False`).
* Any new "destructive bulk action" in the controller should follow
  the same shape: enumerate-before-mutate, copy-out-before-delete,
  refuse-on-backup-failure, show counts in the confirmation UI.
