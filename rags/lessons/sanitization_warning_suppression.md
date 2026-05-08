---
topic: v3-architecture
date: 2026-05-08
status: feature
related: [sanitize, permissions, tool_runner]
---
# Sanitization-warning suppression with three-scope opt-out (v0.3.4)

## What happened / rule

User feedback: "I got nagged about having regex stuff in a field
and had to click an OK box to run.  We need a way to turn off the
warnings about that from the nag popup — a checkbox just for this
field, or for the ScripTree, or for the whole software."

v0.3.4 adds three "Don't warn me again" checkboxes to the
injection-warning dialog, each with a different scope, all gated
behind a single new permission file
(``suppress_sanitization_warnings``).

## Three scopes of suppression

| Scope | Storage key | UI |
|---|---|---|
| **Per-field** | ``sanitize_suppress/fields`` (JSON map ``tool_path -> [param_id]``) | "For field 'x'" / "For these N field(s)" checkbox |
| **Per-tool** | ``sanitize_suppress/tools`` (JSON list of tool paths) | "For this tool (every field)" checkbox |
| **Global** | ``sanitize_suppress/global`` (bool) | "For all tools, everywhere" checkbox |

All three checkboxes appear together in the injection-warning
dialog.  The user can tick any combination before clicking
Proceed; choices are persisted via ``QSettings`` and consulted on
the next Run.

## The single permission gate

A new capability ``suppress_sanitization_warnings`` controls
whether the three checkboxes appear at all.  When the file is
**missing or read-only**, the checkboxes don't render — every
flagged Run forces the user to read and OK the dialog (no
opt-out).  When granted, all three checkboxes appear.

This matches the user's spec: "This capability also needs a
security file, just one for all 3."

## Detection / filter pipeline (in order)

In ``ToolRunnerView._start_run``:

1. ``sanitize_all_values_detailed`` produces ``[(text, field_id),
   ...]`` — parallel to the legacy flat output but each warning
   now carries the source field for per-field suppression.
2. Symlink / extras / cmd-line warnings are appended with
   synthetic field ids ``__exe__`` / ``__extras__`` / ``__cmdline__``.
   These are skipped by the per-field UI control (only concrete
   form-param ids are offered for muting).
3. ``sanitize_suppression.should_skip_dialog(tool_path)`` checks
   the global + per-tool flags.  If True, ``detailed_warnings``
   is cleared and the dialog never opens.
4. Otherwise ``sanitize_suppression.filter_warnings(...)`` drops
   warnings whose ``field_id`` is in the per-field mute list.
5. If anything remains, the dialog shows.  On Proceed, any ticked
   checkboxes are persisted before returning ``True``.

## Re-enable surface

Edit → Sanitization warnings… opens a dedicated dialog with:

* A toggleable global-mute checkbox.
* A scrollable list of muted tools, each with a "Re-enable
  selected tool" button.
* A tree of muted fields per tool, with "Re-enable selected
  field" (works on both individual fields and the parent tool
  row).
* A "Re-enable everything" button (with a confirm dialog) that
  clears all three storage keys.

Always available regardless of permission state — re-enabling
warnings is the safe direction (more warnings, not fewer), so no
gate.

## Storage layout

Under the ``sanitize_suppress/`` namespace in ``QSettings``:

```ini
sanitize_suppress/global = false
sanitize_suppress/tools = ["C:/path/to/tool.scriptree", "..."]
sanitize_suppress/fields = {"C:/path/to/tool.scriptree": ["param1", "param2"]}
```

JSON over Qt's native list/dict roundtrip to dodge INI quoting
quirks on Windows.  Path normalisation via ``Path.resolve()`` so
forward-slash and back-slash variants of the same path collapse
to one key.

## Edge cases

* **Cancel preserves state.**  Ticking a checkbox then clicking
  No leaves the suppression state untouched.  Persistence only
  happens on Yes / Proceed.

* **Per-field box disabled when no on-disk path.**  An unsaved
  tool (``self._file_path is None``) has no canonical key for
  per-tool / per-field state.  Both per-field and per-tool boxes
  show but the per-tool one is greyed out with a tooltip
  explaining why.

* **Synthetic field ids are not offered for per-field mute.**
  Symlink-warning rows with ``__exe__`` and similar synthetic
  ids are excluded from the "fields" set displayed on the
  checkbox label.  If the ONLY warnings are synthetic, the
  per-field checkbox doesn't appear — only per-tool / global do.

## How future-me detects it

* If the checkboxes don't appear when expected: check the
  ``suppress_sanitization_warnings`` capability state (file
  exists + writable in deployed permissions/ folder).
* If a previously-muted warning re-fires: ``filter_warnings``
  uses the field id, not the warning text.  When new warning
  variants are added (e.g. a new sanitize check), the field id
  stays the same so the mute still applies.
* If tests pollute real ScripTree config: use the autouse
  ``isolated_settings`` fixture (env-var-pinned QSettings INI in
  tmp_path) — see ``tests/test_sanitize_suppression.py``.

## Tests

22 tests in ``tests/test_sanitize_suppression.py``:

- Storage layer (6): default state, set/get for all three scopes,
  path normalisation, clear-all.
- Filter predicates (4): should_skip_dialog truth table,
  filter_warnings correctness.
- sanitize_all_values_detailed (2): field-id parallel to flat
  variant, count parity.
- Dialog capability gate (6): no checkboxes when denied; three
  checkboxes when granted; each scope's "tick → persist" behaviour
  end-to-end through ``_show_injection_warning``; cancel doesn't
  persist.
- Re-enable dialog (4): construct, list, unmute, clear-all.

Suite at v0.3.4: 1038/1038 (was 1016 at v0.3.3).
