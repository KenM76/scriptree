---
topic: documentation-debt
date: 2026-05-31
status: workflow
related: [capability_wiring_full_audit.md]
---
# Documentation lags code drastically after schema v3 rename and capability-file expansion

## What happened / rule

Copy-truthfulness audit (T250) found 23 user-facing-doc findings:
11 P0 false claims, 9 P1 stale, 3 P2 polish. The two recurring patterns:

1. **Schema v3 rename (commit ~v0.5.0)** propagated through the code
   (`scriptree/core/model.py::SCHEMA_VERSION = 3`, Widget+ParamType
   enums) but NOT through user-facing docs. As of 2026-05-31:
   - `docs/file_formats.md` used `schema_version: 2` in every example
     (tools refuse to load — the runtime hard-rejects v2 via
     `io._check_schema`).
   - `docs/tool_editor.md`, `docs/tool_runner.md` referenced
     `file_open` / `file_save` / `enum_radio` widget names and
     `bool` / `float` type names — all renamed in v3.

2. **Capability file count drifted** between source (32 on disk),
   security.md table (35 names), features.md prose (34), README
   bullet (22). The "22" figure is so stale it predates the v0.3.3
   permission-wiring audit.

## Root cause / rationale

- **Schema-bump checklist incomplete.** When `SCHEMA_VERSION` bumps
  from 2 → 3 with a rename map, the bump touches: model.py (✓),
  io.py (✓), cli/migrate.py (✓), test_canonical_names_v3.py (✓),
  but NOT the user-facing docs that show example JSON. The
  reconstruction-test bar (rebuild from docs alone, no code) fails
  hard for any v3 user who follows the doc examples literally — the
  v3 runtime would refuse to load their file.
- **Capability count documented in three places** (README bullet,
  features.md numbered list, security.md callout). Updating
  permissions/ tree without updating all three creates a 22/32/34/35
  spread.

## How to prevent

1. **Schema-bump PR checklist** must include a grep for the OLD
   names across `docs/`: `grep -rn "file_open\|file_save\|enum_radio\|schema_version.*[12]" docs/`. Ban-merge if any
   hit lands outside an explicit "v1/v2 historical" callout.
2. **Capability-file count** should appear in ONE place
   (security.md's table). Other surfaces (README, features.md) link
   to the table instead of restating the number. A grep-test in CI
   (`docs/scripts/check-capability-count.py`) could compare the
   table-row count vs `find permissions -type f` and fail on
   mismatch.
3. **Settings storage claim** ("zero registry") was true in code
   (`QSettings.Format.IniFormat` explicitly opted into) but
   contradicted in `docs/settings.md` ("stored in the system
   registry"). This is a "the doc was written before the code
   landed" classic. Pinning a doc-test that grep-asserts every doc
   claim against the relevant code constant would catch it.

## How to detect now

```bash
# Check schema_version examples in docs
grep -rn 'schema_version.*[12]' D:/Dev/ScripTree/docs/ \
  --include='*.md'

# Check obsolete widget names in user-facing docs
grep -rn 'file_open\|file_save\|enum_radio' D:/Dev/ScripTree/docs/ \
  --include='*.md' --exclude-dir=LLM

# Count capability files actually shipped
find D:/Dev/ScripTree/permissions/ -type f | wc -l
```

## Audit deliverables

- Report: `D:/Dev/ScripTree/docs/COPY_AUDIT_2026-05-31.md`
- 16 inline fixes across README, BUG_REPORT, features, security,
  tool_editor, tool_runner, file_formats, environment, settings,
  docs/README, cell_shell, quickstart, getting_started
- 4 FOLLOWUPs deferred: vendored-deps size, branding placeholders,
  ROADMAP-v0.4 staleness, branding `appNameLong: "v2"` mismatch

## Related lessons

- `capability_wiring_full_audit.md` — original capability-file
  audit that uncovered the 35→32 wiring landscape.
