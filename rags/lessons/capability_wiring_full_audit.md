---
topic: v3-architecture
date: 2026-05-08
status: bugfix
related: [permissions, tool_runner, main_window, sanitize]
---
# Every declared capability now consulted at runtime (v0.3.3)

## What happened / rule

Pre-v0.3.3 audit found 21 of 35 capabilities in
``CAPABILITIES`` had **zero runtime consumers** — they were
declared, documented in ``help/security.md``, surfaced in admin
tooling, but no code ever called ``perms.can("name")`` for them.
Locking the file did nothing.  v0.3.3 wired every gap.

## Wiring approach

A small helper module ``scriptree/ui/permission_guards.py`` owns
the gating boilerplate:

```python
def apply_widget_perm(widget, capability, *, ps=None, tooltip_when_denied=None) -> bool:
    """setEnabled(False) + tooltip when denied; return state for short-circuit."""

def apply_action_perm(action, capability, ...) -> bool:
    """QAction variant — same semantics."""

def apply_text_readonly(text_edit, capability, ...) -> bool:
    """setReadOnly(True) when denied — for editable previews."""

def perm_check(capability, *, ps=None) -> bool:
    """Thin wrapper around ps.can() with auto-load + safe-default-allowed
    on lookup error (a misconfigured permissions/ folder shouldn't
    lock a user out of basic features)."""
```

All 21 wires sprinkle these into the right widget construction
sites.  Errors during lookup default to **allowed** so a partial
install doesn't leave users locked out.

## Wiring map (one entry per previously-unwired capability)

| Capability | Gate point | UI effect when denied |
|---|---|---|
| ``run_tools`` | ``ToolRunnerView._btn_run`` + ``_start_run`` runtime check | Run button disabled; warning dialog on keyboard / programmatic invocation |
| ``run_as_different_user`` | ``ToolRunnerView._chk_prompt_creds`` + ``_start_run`` | Checkbox disabled; runtime warning + non-interactive run if config slipped through |
| ``access_settings`` | ``MainWindow`` Settings QAction + ``_open_settings`` | Menu item greyed; warning dialog on direct call |
| ``create_new_scriptree`` | "New tool from executable…" + "New blank tool" actions | Both menu items greyed |
| ``create_new_scriptreetree`` | "New scriptree tree" action | Menu item greyed |
| ``save_as_scriptree`` | Editor's ``_btn_save_as`` + main-window ``_act_save_tool_as`` | Button + menu item greyed; runtime status-bar message |
| ``save_as_scriptreetree`` | ``_act_save_tree_as`` action | Menu item greyed; runtime status-bar message |
| ``save_scriptree`` | (was already wired for editor's Edit button; v0.3.3 also wires editor save buttons + main-window action) | Editor Save disabled; menu greyed |
| ``save_scriptreetree`` | ``_act_save_tree`` (Ctrl+S handler) + runtime check | Menu greyed; Ctrl+S blocked at runtime |
| ``edit_environment`` | ``_btn_cfg_env`` | Env... button disabled |
| ``edit_visibility`` | ``_btn_cfg_visibility`` | Visibility... button disabled |
| ``edit_configurations`` | ``_btn_cfg_edit`` | Edit... button disabled |
| ``write_configurations`` | ``_btn_cfg_save`` / ``_btn_cfg_save_as`` / ``_btn_cfg_delete`` | All three buttons disabled |
| ``command_line_editor`` | ``_live_cmd`` QPlainTextEdit | Read-only (still visible) |
| ``reorder_parameters`` | ``ReorderableParamForm`` constructor sets ``DragDropMode.NoDragDrop`` when denied | Drag handles inert |
| ``allow_path_traversal`` | ``sanitize_value`` / ``sanitize_all_values`` get an ``allow_traversal`` kwarg; runner reads ``perms.can(...)`` and forwards | When **denied**, ``../`` warning fires; when granted, suppressed |
| ``access_sensitive_paths`` | Same plumbing + new ``_looks_sensitive`` check that flags paths under ``c:\windows`` / ``/etc`` / etc. | Sensitive-path warning fires |
| ``allow_symlinks`` | Runner calls ``validate_resolved_path`` on the executable when denied | Symlink-component warning fires |

## Notes on the granular config capabilities

The four granular config capabilities (``read_shared_configurations``,
``write_shared_configurations``, ``read_personal_configurations``,
``write_personal_configurations``) **were already wired** in
v0.3.x — through the ``can_read_shared`` / ``can_write_shared`` /
``can_read_personal`` / ``can_write_personal`` helpers in
``permissions.py``.  My initial audit grep for ``"capability_name"``
literals missed these (they're consulted via helper-function calls,
not direct string lookups).  The legacy umbrella
``read_configurations`` / ``write_configurations`` are also
consulted via the ``_granular_or_legacy`` fallback in those
helpers — so when granular files aren't deployed, the legacy
umbrella catches the action.

So the actual final scoreboard:

* **Pre-v0.3.3 reality** — 14 directly-consulted + 6 helper-consulted = **20 wired**, 15 unwired (not 21).
* **v0.3.3 reality** — **all 35 wired**, 0 unwired.

The doc still benefits from being honest: see the wiring map in
``help/security.md`` for what each capability actually gates.

## Path-security trio implementation choices

Three security capabilities required new code paths because no
existing call site read them:

1. **``allow_path_traversal``** — purely a string-level check.
   ``sanitize_value`` already detected ``../`` patterns; v0.3.3
   gates the warning emission on the capability state.

2. **``access_sensitive_paths``** — new feature.  Defined a small
   conservative list of sensitive directories
   (``c:\windows``, ``c:\program files``, ``/etc``, ``/usr/bin``,
   etc.) and added a string-prefix check after path resolution
   (``Path.expanduser().resolve()``).  Conservative on purpose —
   false-positive fatigue would push users to disable the feature.

3. **``allow_symlinks``** — disk I/O required.  We resolve the
   tool's ``executable`` path at run time and walk its parents
   looking for any symlink component.  Limited to the executable
   (not every form-value path) so the run-start stays fast.
   Wider symlink scanning is a future-iteration concern.

## How future-me detects it

If you find yourself adding a new capability to ``CAPABILITIES``,
also write the gate:

1. Identify the right widget / action / runtime path.
2. ``apply_widget_perm`` / ``apply_action_perm`` /
   ``apply_text_readonly`` for UI controls; ``perm_check`` for
   runtime checks.
3. Add a behavioural test in ``tests/test_capability_wiring.py``.

If the capability is registered but no test covers it, you'll
fail the audit.  Run:

```sh
grep -rE "\"$cap_name\"|'$cap_name'" scriptree/ tests/
```

— if the count for production code is 0, the capability is
declared but unwired.  Either wire it or remove it from the
registry.

## Tests

``tests/test_capability_wiring.py`` — 25 tests covering every
newly-wired capability with the "denied → feature disabled" +
(where practical) "allowed → feature works" pattern.  Plus two
smoke tests confirming the UI doesn't crash under full lockdown.

Suite at v0.3.3: 1016/1016 (was 991 at v0.3.2).
