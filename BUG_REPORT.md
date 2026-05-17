# ScripTree — bug audit (2026-05-16)

> ## ✅ ALL RESOLVED in v0.6.3 (2026-05-16)
>
> Every finding below — **2 HIGH, 7 MEDIUM, 18 LOW/latent** — was
> fixed. Each fix carries an inline ``# H1/M3/L9 fix:`` comment at
> the site explaining the change. Regression tests for the
> behaviourally-checkable ones live in
> ``tests/test_bugfixes_v063.py``; the full suite (1400+ tests)
> is green with zero regressions. A pre-fix snapshot is archived at
> ``ScripTree4-v0.6.2-pre-bugfix-20260516_203818.zip``.
>
> Notes on a few: **L7** became an exit-time Save/Discard prompt for
> transient forests (was silent loss). **L9** added a copy-fallback
> so a locked legacy forest is never orphaned. **L13** corrected the
> legacy ``apps.shell.main`` module path to ``scriptree.shell.ring_main``
> so system-scope autostart elevation actually works. **M6** reordered
> to listen-then-recover so a live primary's socket is never blindly
> unlinked. The original report text is preserved below for context.

---

Produced during the codebase-wide dual-section docstring pass. Each
source file was read for **real defects** (logic errors, resource
leaks, races, swallowed failures, security/encoding issues) — not
style.

> Line numbers shifted because every module's top docstring grew.
> Findings are anchored to **function / symbol names**; treat any
> line number as approximate.

---

## Fixed during this audit

- **`tests/test_core_purity.py::test_providers_module_is_totally_qt_free`**
  — was `assert "PySide6" not in src`, a naive substring check. Once
  `core/providers.py`'s docstring correctly *documents* its Qt-free
  invariant (the word "PySide6" appears in prose), the test
  false-positived on the documentation of the rule it enforces.
  **Fixed**: rewritten as an AST scan for actual `import` /
  `from … import` of PySide6 (any scope). Tests the real invariant;
  the subprocess `test_headless_path_does_not_import_qt` remains the
  behavioural backstop.
- **`scriptree/core/app_settings.py`** module docstring — an invalid
  escape sequence `\`` (DeprecationWarning today, **SyntaxError** in
  a future Python). **Fixed**: reworded the shell-meta example.

---

## HIGH

### H1 — `core/runner.py` · run-as-different-user: process-handle use-after-close
`spawn_streaming_as_user` builds a `_ProcProxy` around
`pi.hProcess`, then unconditionally calls
`kernel32.CloseHandle(pi.hProcess)` before returning. The proxy
retains the now-invalid handle, so a later **Stop** click
(`proxy.terminate()` / `poll()`) operates on a closed handle. Net
effect: **Stop is broken for any tool launched via "run as different
user"** (the regular `spawn_streaming` path is unaffected — it keeps
the Popen alive for the caller).
*Fix sketch:* don't `CloseHandle` until the proxy is done with it
(close in the proxy's terminate/cleanup), or duplicate the handle
for the proxy.

### H2 — `ui/main_window.py` · `closeEvent` skips the editor dirty-guard
`closeEvent` guards a dirty **tree** (`_confirm_discard_tree`) and
warns about running child processes, but never checks
`self._active_editor.is_dirty()`. Closing the app (window ✕ or
File→Exit) while a `ToolEditorView` has unsaved edits **silently
discards them** — the v0.6.2 unsaved-changes guard only covers
navigate-away (Close/Cancel buttons), not window close. (The
maintainer docstring added this pass already flags this.)
*Fix sketch:* in `closeEvent`, if `_active_editor and
_active_editor.is_dirty()`, run the same Save/Discard/Cancel prompt
and `event.ignore()` on Cancel.

---

## MEDIUM

### M1 — `cli/migrate.py` · `migrate_one` force-downgrades future files
`if cur_version != _TARGET_SCHEMA_VERSION:` rewrites a file whose
`schema_version` is **greater** than 3 down to 3 — silent
data-corruption the day a v4 exists, and a latent idempotency hole.
*Fix:* `if cur_version < _TARGET_SCHEMA_VERSION:`.

### M2 — `cli/migrate.py` · non-atomic in-place write
`path.write_text(...)` truncates then writes the user's source
file; an interruption (disk full, kill) leaves a zero/partial
`.scriptree`. A migrator that mutates user files should write a temp
file and `os.replace`.

### M3 — `core/parser/plugins/winhelp.py` · section-end off-by-one
The post-header section-end scan uses `if i > start`; when the
first line of the block is itself a colon/sub-header (`i == start`)
it is *not* treated as the section end and gets parsed as flag
content → spurious params for some `/?`-style help layouts.

### M4 — `shell/forest_controller.py` · `_spawn_item` recovers the wrong cell
After `_drop_spawn_member_and_link`, it does
`next(reversed(self.forest_window._members))` and assumes that key
is the just-added member. If that method adds ≠1 member or reuses an
id, the **wrong** CellWindow is recorded in `_spawned`; later
`remove_item` / position-sync then act on the wrong cell. Fragile
coupling to CellWindow dict insertion order.
*Fix:* have `_drop_spawn_member_and_link` return the member id/handle
explicitly.

### M5 — `shell/single_instance.py` · `try_handoff` can hang the secondary
In the read-ack loop, `deadline_left -= 200` only happens in the
timeout branch. When `waitForReadyRead` returns True but delivers no
newline (partial write from a stalled primary), the deadline never
decrements → the secondary spins forever instead of failing open to
a fresh primary.

### M6 — `shell/single_instance.py` · `removeServer`→`listen` TOCTOU
Non-atomic on POSIX: two simultaneous launches can both
`removeServer` and the second can unlink the first's just-bound
socket, leaving no/locked primary; subsequent handoffs then spawn
isolated processes. Inherent single-instance-guard race; consider an
atomic bind or a lockfile.

### M7 — `ui/tree_config_editor.py` · OK writes sidecar even when read-only
The constructor disables Save/Save-As/Delete when `read_only=True`,
but `_on_accept` still calls `_save_current()` →
`save_tree_configs`. Clicking **OK** on a dialog opened against a
locked/vendored tree silently overwrites the tree-config sidecar,
defeating the read-only contract.
*Fix:* early-return from `_on_accept`'s save when `read_only`.

---

## LOW / latent

| ID | Location | Issue |
|---|---|---|
| L1 | `core/runner.py` · run-as-user cmdline build | Naive quoting `f'"{a}"' if " " in a or '"' in a else a` doesn't escape an embedded `"` → malformed command line for `CreateProcessWithLogonW`. Non-elevated path correctly uses `subprocess.list2cmdline`; mirror that. |
| L2 | `core/runner.py` · `resolve` cwd default | Bare exe (`python`) → parent `.`, whose `as_posix()` is truthy, so cwd becomes `"."` not `None`; diverges from documented intent & `build_env`. |
| L3 | `core/permissions.py` · `PermissionConflict` | `app_source`/`file_source` built as top-level `dir/cap` but the capability was resolved via recursive `rglob`; the path shown to the admin can point at a non-existent file. |
| L4 | `core/parser/plugins/powershell.py` | Section-end regex `^[A-Z][A-Z]+\s*$` misses 1-char / digit-containing headers and is skipped for `i == 0`. Low impact (real PS headers are multi-letter). |
| L5 | `core/parser/plugin_api.py` · `load_plugins_from_dir` | Dead `loaded = 0` (real counter is in the inner fn). Maintenance hazard, not a runtime bug. |
| L6 | `shell/cell_window.py` · `moveEvent` | Throttled-log branch is dead (`_last_move_log_time` set ~10 lines earlier same call); one shared timestamp across 3 throttle sites (1.0/0.1/1.0 s) makes all 3 logs irregular. |
| L7 | `shell/forest_controller.py` · transient `save()` | When `loaded_from` unset and `fallback_to_default=False`, `save()`/`_autosave_flush` no-op and leave `_dirty=True`; at process exit the user's never-saved-as forest is lost with only a stderr log. Design-intended but **no UI warning** — add one. |
| L8 | `shell/forest_io.py` · `save_forest` | Redundant identical ternary `X if not Path(it.path).is_absolute() else X` — dead/confusing; the `is_absolute()` check has no effect. |
| L9 | `shell/forest_io.py` · `migrate_legacy_autoload_path` | If `legacy.rename(new)` raises (file locked), it logs+returns None; the launcher then treats it as "no migration" and `start()` creates a **fresh empty** `default.scriptreeforest`, silently orphaning the user's previous forest. Add a copy-fallback or surface loudly. |
| L10 | `shell/forest_dialogs.py` · `ForestSettingsDialog._save` | Catches only `OSError`; a non-OSError (serialization/`TypeError`) escapes the modal dialog, unlike the deliberately-swallowed label path. |
| L11 | `shell/single_instance.py` · `messages_from_argv` | `arg.lower().rsplit(".",1)[-1]` misclassifies a path with a dot in a *directory* name + no extension → silently becomes `spawn_cell`. |
| L12 | `shell/ring_io.py` · `load_ring` single-member | Emits `masterSpawned(mid, first_id, first_id)` — same id as both docked partners; degenerate pair for consumers that assume distinct a/b. |
| L13 | `shell/ring_io.py` · `elevate_for_system_autostart` | Builds args for module `apps.shell.main` while `_build_autostart_cmd` uses `scriptree.shell.ring_main`. The UAC-elevated "runas" path targets a legacy/nonexistent module → **system-scope autostart registration silently no-ops** (child dies on import after ShellExecuteW returns >32). |
| L14 | `shell/merged_tree.py` | Temp `scriptreering_merged_*.scriptreetree` files are never deleted by this module; relies entirely on the launcher's startup sweep + OS. Asserted, not enforced here → known leaked-temp hazard. |
| L15 | `ui/tool_runner.py` · `_init_providers` | `self._provider_debounce[p.id] = timer` is inside the `for dep in p.depends_on` loop, so for a multi-dependency provider only the **last** dep's `QTimer` is tracked; the others are orphaned (cascades still fire via the per-dep closure). |
| L16 | `ui/tool_runner.py` · provider rebuild | A config change that alters `hidden_params` re-runs `_init_providers`, reassigning `_provider_debounce` to a fresh dict; prior `QTimer`s are never `stop()`/`deleteLater()`'d → unbounded accumulation across repeated config switches in a long-lived runner (benign per-timer, but a slow leak). |
| L17 | `scriptree/main.py` | Top-level `from PySide6.QtWidgets import QApplication, QStyleFactory` forces a Qt import even on the headless `validate`/`migrate` dispatch branch. The dispatch *ordering* is correct (before `QApplication()`), and the documented CLI form `python -m scriptree.cli.migrate` doesn't import `scriptree.main`, so `test_core_purity` still passes — but `python -m scriptree validate` on a headless box with no Qt platform plugin can fail at import. Move the Qt import inside the non-CLI branch. |
| L18 | `ui/widgets/param_widgets.py` · `DropdownWidget.set_choices` | Empty provider result: combo cleared, `get_value()` → `""`; if previous value was also `""` no `valueChanged` fires, leaving the form believing the old value is set with nothing selectable. `CheckboxListWidget` handles the empty case explicitly with a placeholder; dropdown doesn't. |

---

## Clean

No confident defects found in: `core/model.py`, `core/io.py`,
`core/sanitize.py`, `core/sanitize_suppression.py`,
`core/visible_when.py`, `core/configs.py`, `core/credentials.py`,
`core/providers.py`, `core/path_env.py`, `core/cell_metadata.py`,
`core/branding.py`, `core/_runtime_shim.py`, `core/parser/probe.py`
& the argparse/click/heuristic plugins, `cli/validate.py`,
`shell/branding_loader.py`, `shell/cell_registry.py`,
`shell/click_to_run.py`, `shell/explode_tree.py`,
`shell/forest_discover.py`, `shell/snap_engine.py`,
`shell/group_layout.py`, `shell/recent_files.py`,
`shell/tree_popup.py`, `shell/v1_launcher.py`,
`ui/tool_editor.py`, `ui/tree_view.py`, `ui/standalone_window.py`,
`ui/settings_dialog.py`, `ui/provider_editor.py`,
`ui/env_editor.py`, `ui/menu_editor.py`, `ui/recovery_dialog.py`,
`ui/credential_dialog.py`, `ui/flow_layout.py`, `ui/help_dialog.py`,
`ui/permission_guards.py`, `ui/visibility_editor.py`,
`ui/wrapping_tab_bar.py`, and the package markers.

The `probe._sanitize_parsed_tool` "shell metacharacters are safe"
stance is **correct** given the audited `shell=False` invariant; the
`permission_guards.perm_check` fail-open-on-error is **intentional**
and correctly implemented.
