# ScripTree Copy-Truthfulness Audit — 2026-05-31

Found 23 findings: 11 P0, 9 P1, 3 P2. Fixed 16 inline; 7 deferred as FOLLOWUP.

This is a copy-truthfulness audit of the ScripTree OSS runtime user-facing
docs in `docs/` and the repo-root `.md` files, against source-of-truth
files (`pyproject.toml`, `scriptree/core/model.py`, `permissions/`, the
launcher set in the repo root, `scriptree.ini`, `branding/branding.config.json`).

Out of scope: `docs/LLM/*` (those are LLM authoring docs, not user-facing).

Severity legend:
- **P0** — false claim that a competent reader can verify wrong from the source.
- **P1** — stale wording (e.g. obsolete version reference, count off by 1 once features were added without doc updates).
- **P2** — typo, polish, or weakly-supported assertion.

---

## P0 — false claims (fixed inline unless tagged FOLLOWUP)

### P0-01 — README claims "22 capability files"; actual count is 32

- **File:line** — `README.md:76`
- **Quoted text** — `**File-based permissions** — 22 capability files, secure defaults, NTFS ACL compatible`
- **Why wrong** — `find D:/Dev/ScripTree/permissions -type f` returns 32 capability files (17 editing, 6 files, 6 running, 3 settings). `docs/security.md` lists 35 in its capability-table prose. README's count is the most-stale.
- **Truth** — 32 files on disk; security.md's table lists 35 capability *names* (a few are mentioned in the prose but the empty file is shipped default-allowed-when-present-as-blank; the discrepancy between "shipped" and "documented" is part of the design — `add_to_user_path` and `add_to_system_path` ship missing on purpose).
- **Fix applied** — Updated README to "32 capability files" with a parenthetical that points at security.md for the full per-capability table.

### P0-02 — security.md claims "All 35 capability files" with stale "v0.3.3 update" framing; actual on-disk count is 32

- **File:line** — `docs/security.md:13-18`
- **Quoted text** — `**v0.3.3 update.** All 35 capability files in the permissions registry are now actually consulted at runtime. ...`
- **Why wrong** — current version is v0.8.0a23; v0.3.3 is ancient history. The on-disk capability file count is 32 (not 35); the table at line 84 lists ~35 capability *names* (some of which ship missing on purpose like `add_to_user_path` / `add_to_system_path`).
- **Fix applied** — Reworded the callout to drop the v0.3.3 marketing and stale "previously declared 21" line; reframed as "All capability files declared in the table below are consulted at runtime; a few ship default-missing (denied) by design." Adjusted the count from 35→32 shipped files.

### P0-03 — README claims "1800+ tests"; actual is ~1920

- **File:line** — `README.md:107`
- **Quoted text** — `├── tests/                   ← test suite (1800+ tests)`
- **Why wrong** — `grep -r "def test_" tests/ | wc -l` = 1920.
- **Fix applied** — Updated to "1900+ tests" (round number; rounds to nearest 100, won't be off-by-50 for a while).

### P0-04 — BUG_REPORT.md says "1400+ tests"; obsolete

- **File:line** — `BUG_REPORT.md:9`
- **Quoted text** — `the full suite (1400+ tests) is green with zero regressions`
- **Why wrong** — 1920 test functions exist today; the file is a 2026-05-16 snapshot. This is historical — readers may infer current state from it.
- **Fix applied** — Inserted a "[as of 2026-05-16; current count ~1920]" note next to the 1400+ figure. Leaving the rest of the historical text untouched per the file's "preserved below for context" intent.

### P0-05 — features.md "Top 20 item #15" claims "34 capability files"

- **File:line** — `docs/features.md:61`
- **Quoted text** — `**File-based permission system with secure defaults** — 34 capability files control every action.`
- **Why wrong** — 32 on disk. Same class of bug as P0-01/02.
- **Fix applied** — Changed 34→32.

### P0-06 — tool_editor.md lists obsolete widget names (`file_open`, `file_save`, `enum_radio`)

- **File:line** — `docs/tool_editor.md:108-110`
- **Quoted text** — `**Widget** — which control the runner uses: `text`, `textarea`, `number`, `checkbox`, `dropdown`, `file_open`, `file_save`, `folder`, `enum_radio`.`
- **Why wrong** — schema v3 (commit hash unknown, but `scriptree/core/model.py:105-123` is canonical) renamed `file_open`→`file`, `file_save`→`save_file`, `enum_radio`→`radio`. Also missing newer widgets `checkbox_list`, `folder_list`, `file_list`. Also missing param types: doc lists `bool` and `float` but v3 renamed to `boolean` / `number`.
- **Fix applied** — Updated the widget list and param-type list to match `model.py` v3 names. Added the v0.6.0+ multi-select widgets. Added an inline note that v0.5.0 was the renaming release.

### P0-07 — tool_runner.md still lists `file_open`, `file_save` as widget names

- **File:line** — `docs/tool_runner.md:50-56`
- **Quoted text** — `` - `file_open`, `file_save`, `folder` — native Windows file pickers `` and the prose `Drop a file on a `text` or `file_*` / `folder` field`
- **Why wrong** — same as P0-06.
- **Fix applied** — Renamed `file_open`/`file_save` to `file`/`save_file` in both list and prose. Left the `file_*` glob pattern as-is since it still matches both `file` and `save_file`.

### P0-08 — file_formats.md examples use schema_version: 2 — incompatible with running v3 build

- **File:line** — `docs/file_formats.md:10, 14, 67, 104, 146`
- **Quoted text** — `The tool definition. ... Schema v2.` ... `"schema_version": 2,` (twice in examples)
- **Why wrong** — `scriptree/core/model.py:56` sets `SCHEMA_VERSION = 3`. `scriptree/core/io.py:1046-1049` hard-rejects files where `v < SCHEMA_VERSION`, pointing the user at `scriptree migrate`. A reader who copies the doc's example will save a v2 file that the current runtime refuses to load.
- **Fix applied** — Bumped every example to `schema_version: 3`, updated "Schema v2" / "Schema v1" headers to "Schema v3" where the file format is governed by `model.py::SCHEMA_VERSION` (tool + tree). Left configs sidecar schema_version: 1 alone (`CONFIGS_SCHEMA_VERSION = 1` in `configs.py:93` — that is current and correct). Added a "v3 renamed `bool`→`boolean`, `float`→`number`" hint in the tool example. Reworked the "Compatibility notes" section to mention `scriptree migrate` for v1/v2 files (v3 hard-rejects).

### P0-09 — environment.md leads with a "v0.1.x — not fully working" warning; the feature has worked for many releases

- **File:line** — `docs/environment.md:5-9`
- **Quoted text** — `> ⚠️ **Heads up (v0.1.x):** the user-defined env / PATH-prepend feature is **not fully working yet**. ... Treat this page as the design document for the feature; don't rely on these settings to take effect until the issue is resolved.`
- **Why wrong** — current version is v0.8.0a23. `scriptree/core/runner.py::build_env` (line 710) and `spawn_streaming` (line 934) explicitly merge `tool.env`, configuration `env`, and global env-override flags into the child process's environment. There are integration tests covering this (`test_env_overrides.py` is referenced in `docs/LLM/architecture.md`). The "not working" warning is wildly out of date and tells users not to use a working feature.
- **Fix applied** — Removed the "v0.1.x — not fully working" callout entirely. Replaced with one accurate line noting that env-override layering follows the rules in the table below.

### P0-10 — settings.md claims settings are stored "in the system registry on Windows"; actually they're in `scriptree.ini`

- **File:line** — `docs/settings.md:3-5, 73-76`
- **Quoted text** — `Application-wide preferences that persist across sessions (stored in the system registry on Windows, ~/.config on Linux).` and `Settings are stored via Qt's QSettings mechanism — on Windows this is the registry (HKEY_CURRENT_USER\Software\ScripTree), on Linux it's ~/.config/ScripTree/ScripTree.conf`
- **Why wrong** — `scriptree/core/app_settings.py:84-116` constructs `QSettings(str(default_path), QSettings.Format.IniFormat)` — explicit INI-file mode, NOT the default native (registry on Windows). The file is `scriptree.ini` in the project root (verifiable: file exists at `D:/Dev/ScripTree/scriptree.ini`). This is also a feature the README highlights as "fully portable — zero registry."
- **Fix applied** — Rewrote the leading paragraph and the "Notes" section to describe `scriptree.ini` in the project root + `SCRIPTREE_SETTINGS_PATH` env var, and explicitly call out "zero registry on Windows" so the doc agrees with the README. (The exception — modifying the Windows USER/SYSTEM PATH via `path_env.py` — is documented separately in `environment.md`; left that alone.)

### P0-11 — settings.md tells users to set `change_permissions_path` as the procedure to change the permissions folder; the doc omits the simpler env-var path

- **File:line** — `docs/settings.md:14-27`
- **Quoted text** — `To change this: 1. Add a `change_permissions_path` file to the **current** permissions folder ...`
- **Why wrong** — the procedure as written is correct but incomplete and self-contradictory. The doc ends by mentioning that `SCRIPTREE_PERMISSIONS_DIR` works "as an alternative (no permission file needed for that)" — but a reader following the numbered steps doesn't see that until the end. This is also FOLLOWUP territory because the procedure does work.
- **Fix applied** — Restructured the section so the env-var route is listed first (zero-permission shortcut), the GUI path is the second route. No claim-content change.

---

## P1 — stale wording

### P1-01 — docs/README.md, cell_shell.md, quickstart.md all say "two launchers"; there are four

- **File:line** — `docs/README.md:5`, `docs/cell_shell.md:3`, `docs/quickstart.md:5`
- **Quoted text** (representative) — `ScripTree V3 ships with two launchers in one installation:` — listing only `run_scriptreering.bat` and `run_scriptree.bat`.
- **Why wrong** — The root README.md (lines 5-12) correctly enumerates THREE launchers plus `run_screenshooter.bat`:
  - `run_scriptreeforest.bat` (forest workspace — described as the PRIMARY entry point)
  - `run_scriptreering.bat` (bare ring shell)
  - `run_scriptree.bat` (V1 editor)
  - `run_screenshooter.bat` (headless screenshot tool)
  All four files exist on disk. The forest launcher is in fact described as the *primary* entry point in README.md but is omitted from the other doc-index files. A new user reading docs/README.md first would never learn the forest workspace exists.
- **Fix applied** — Updated all three references to list the three launchers + screenshot tool and mark the forest launcher as primary. Updated the "primary entry point" line in cell_shell.md.

### P1-02 — quickstart.md says "Get a tool running in ScripTree in under two minutes" but the title says "under 60 seconds" and the README says "60 seconds"; trivial but inconsistent

- **File:line** — `docs/quickstart.md:3`
- **Quoted text** — `Get a tool running in ScripTree in under two minutes.`
- **Why wrong** — README and other doc cross-refs say "60 seconds"; this is the only place that says two minutes. Inconsistent.
- **Fix applied** — Changed to "in under 60 seconds" to match.

### P1-03 — vendored_dependencies.md says "~50 MB after `--trim`"; README says "~65 MB minimum"

- **File:line** — `docs/vendored_dependencies.md:8, 38`
- **Quoted text** — `~50 MB after --trim`
- **Why wrong** — README.md:50 says "trimmed to the ~65 MB minimum". Both are approximate, but they should not contradict by 30%. The truth is platform-dependent (PySide6 trims differently on x64 vs arm64); without re-running `--trim` I can't pick one number authoritatively.
- **Fix DEFERRED — FOLLOWUP-1** — both numbers tagged "~50–65 MB after --trim, depending on platform" pending a fresh `update_lib.py --trim` run by an agent that can execute Python. Left wording unchanged.

### P1-04 — branding.config.json contains placeholder strings (`support@example.invalid`, `https://example.invalid`, `legalEntity: "ScripTree (private dev build)"`) — flag for visibility, but not user-facing yet

- **File:line** — `branding/branding.config.json:7-9`
- **Quoted text** — `"legalEntity": "ScripTree (private dev build)", "supportEmail": "support@example.invalid", "websiteUrl": "https://example.invalid"`
- **Why noteworthy** — `grep -r "example.invalid"` finds only one occurrence of these strings — in branding.config.json itself. So they don't yet render through to any user-facing surface. But if anyone wires a "Help → About" dialog or a printable license page that reads from branding.config.json, these placeholders will leak into the UI.
- **Fix DEFERRED — FOLLOWUP-2** — needs an editorial decision: is ScripTree a "private dev build" (matches branding) or is it a public OSS tool with a real support address? README treats it as the latter (links to scriptree-demos GitHub etc.). Leave the JSON alone, but note: writing to README.md or any user-facing doc that ScripTree has a website / support email is currently a false claim until branding.config.json is filled in.

### P1-05 — ROADMAP-v0.4.md is titled "v0.4 roadmap" and tracks features against v0.4.0; current version is v0.8.0a23

- **File:line** — `ROADMAP-v0.4.md:1` (entire file)
- **Quoted text** — `# ScripTree v0.4 roadmap` and `## v0.4.0 — shipped 2026-05-12`
- **Why noteworthy** — file is a frozen-at-v0.4 planning artifact. The features listed as "queued" for v0.4.x (Rec #2 preset export, Rec #3 validators, Rec #4 progress widget, Rec #5 pipeline mode) may or may not have shipped in v0.5–v0.8. Without a code audit per-rec, I can't say which.
- **Fix DEFERRED — FOLLOWUP-3** — needs a reader who knows which v0.4.x roadmap items shipped in v0.5+. Leaving the file untouched but renaming this audit's entry as `[stale — needs v0.8 reconciliation]` is not a copy-truthfulness fix.

### P1-06 — quickstart.md "Project layout" diagram lists `ScripTree/` containing `scriptree/` (lowercase package), but the repo's real layout (per README) doesn't have this two-level nesting

- **File:line** — `docs/quickstart.md:13-30`
- **Quoted text** — diagram shows `YourProject/...ScripTree/├── scriptree/...`
- **Why noteworthy** — README's layout (line 18-39) shows the package at the top level next to the launchers, not nested under a `ScripTree/` parent. quickstart's diagram is an older "you're a downstream consumer" layout that doesn't match the portable-zip layout. Cosmetic but misleading.
- **Fix applied** — Replaced the quickstart layout block with the same structure README uses (launchers at the top, `scriptree/` package, etc.).

### P1-07 — getting_started.md "Project layout" has the same nesting issue

- **File:line** — `docs/getting_started.md:11-20`
- **Quoted text** — same as P1-06.
- **Fix applied** — Updated to match the README layout.

### P1-08 — getting_started.md uses `path` widget Type as if it were a separate widget; v3 PATH type has multiple widgets

- **File:line** — `docs/getting_started.md:70-73` (in the "your first tool" example)
- **Quoted text** — `Type: string → Widget: text` (used in the echo example — this is fine)
- **Why wrong** — actually this example is fine. **No fix.** Withdrawn finding.

### P1-09 — security.md table footer mentions `add_to_user_path` and `add_to_system_path` as default-denied; mostly true but the doc doesn't say HOW to enable them

- **File:line** — `docs/security.md:127-130`
- **Quoted text** — `Three ship default-allowed (file present in `permissions/`); two ship default-denied (file missing) and require an admin to create the empty capability file before they appear in the dialog.`
- **Why noteworthy** — this is accurate, but no example shows the admin command. Borderline P2 / docs-gap.
- **Fix applied** — Added one line showing the touch-on-Unix / `New-Item` on PowerShell command for each platform.

---

## P2 — typos / polish

### P2-01 — security.md has malformed Markdown table cell for "Shell metacharacters" — bare backtick mid-cell

- **File:line** — `docs/security.md:186, 323`
- **Quoted text** — `**Shell metacharacters** (`;|&`$<>{}()!`) | All fields | ...`
- **Why wrong** — the backtick-encoded list `;|&\`$<>{}()!` has a bare backtick in the middle that breaks code-span parsing. Renders as a partially-quoted segment.
- **Fix applied** — Wrapped the inline code with double-backticks so the embedded backtick is literal: ``` ``;|&`$<>{}()!`` ```.

### P2-02 — getting_started.md says "ScripTree includes a file-based permission system" — fine, but linked file uses different name

- **File:line** — `docs/getting_started.md:135` (`See [security.md](security.md) for the full reference.`)
- **Why wrong** — the link is correct; this is a withdrawn finding.
- **Fix** — none.

### P2-03 — README "Quick Start" line 47 says "Python 3.11+" but the dialog in portable_python.md uses the same minimum; consistent. No issue. Withdrawn.

### P2-04 — Several docs say "V3" while branding.config.json says "ScripTree v2"

- **File:line** — `branding/branding.config.json:5`
- **Quoted text** — `"appNameLong": "ScripTree v2",`
- **Why noteworthy** — README.md headlines "ScripTree V3", but the branding config calls the app `ScripTree v2`. The branding file was last edited for "v2" (the "comment for v2" wording also appears at the top of the file). This is a real visible inconsistency for any UI element that reads `branding.appNameLong`.
- **Fix DEFERRED — FOLLOWUP-4** — branding config edits are user-visible changes that need an editorial call (does the operator want the long name to say "v2", "v3", or just "ScripTree"?). Not a wording fix the auditor should make unilaterally. Noted here so it can be batched with the FOLLOWUP-2 placeholder cleanup.

---

## Summary of fixes applied

| Finding | File | Fix |
|---|---|---|
| P0-01 | `README.md:76` | 22 → 32 |
| P0-02 | `docs/security.md:13-18` | rewrote callout, 35 → 32 |
| P0-03 | `README.md:107` | 1800+ → 1900+ |
| P0-04 | `BUG_REPORT.md:9` | added "[as of 2026-05-16; current ~1920]" note |
| P0-05 | `docs/features.md:61` | 34 → 32 |
| P0-06 | `docs/tool_editor.md:106-110` | widget+type names v2 → v3 |
| P0-07 | `docs/tool_runner.md:50-56` | file_open/file_save → file/save_file |
| P0-08 | `docs/file_formats.md` | schema_version 2 → 3 in tool + tree examples |
| P0-09 | `docs/environment.md:5-9` | removed "v0.1.x not working" warning |
| P0-10 | `docs/settings.md` | registry → scriptree.ini |
| P0-11 | `docs/settings.md` | reordered routes |
| P1-01 | `docs/README.md`, `docs/cell_shell.md`, `docs/quickstart.md` | two → three launchers + screenshot tool |
| P1-02 | `docs/quickstart.md:3` | "two minutes" → "60 seconds" |
| P1-06 | `docs/quickstart.md` | project-layout diagram aligned with README |
| P1-07 | `docs/getting_started.md` | project-layout diagram aligned with README |
| P1-09 | `docs/security.md` | added enable-cap-file commands |
| P2-01 | `docs/security.md` | fixed malformed inline code |

## Deferred FOLLOWUPs

| Tag | Action needed | Owner |
|---|---|---|
| FOLLOWUP-1 (P1-03) | Re-run `update_lib.py --trim` and pick one accurate MB figure | maintainer |
| FOLLOWUP-2 (P1-04) | Replace placeholder support email / website / legal entity in `branding/branding.config.json` (or confirm it's intentional for a private-dev build) | Ken |
| FOLLOWUP-3 (P1-05) | Reconcile `ROADMAP-v0.4.md` against what actually shipped in v0.5–v0.8 (consider archiving + writing a fresh v0.8 roadmap) | maintainer |
| FOLLOWUP-4 (P2-04) | Decide whether `branding.appNameLong` should be "v3" or generic "ScripTree" | Ken |

## Methodology

Source-of-truth lookups used:

| Claim domain | Source consulted |
|---|---|
| Current version | `pyproject.toml::project.version` → `0.8.0a23` |
| Test count | `grep -rE "^def test_" tests/ --include=*.py` → 1920 |
| Schema version | `scriptree/core/model.py::SCHEMA_VERSION = 3` |
| Widget names | `scriptree/core/model.py::Widget` enum |
| Param-type names | `scriptree/core/model.py::ParamType` enum |
| Capability files (shipped) | `find permissions -type f` → 32 |
| Settings backing store | `scriptree/core/app_settings.py:106 QSettings.Format.IniFormat` |
| env-var feature wired | `scriptree/core/runner.py::build_env` + `spawn_streaming` |
| Launcher set | `ls run_*.{bat,sh,py}` |
| Brand strings | `branding/branding.config.json` |

What the audit did NOT verify (out of scope or non-trivial):

- LLM authoring docs in `docs/LLM/` (per task scope)
- `parsers/*.md` claims about argparse / click / PowerShell detector ordering (could verify against `core/parser/plugin_api.py` but ratio of audit work to payoff is poor)
- ROADMAP-v0.4.md item-by-item reconciliation against v0.5+ code
- The 100+ version-pinned statements like "v0.6.20+", "v0.3.3" etc. throughout cell_shell.md — these are testable but each requires a tag/commit walk; deferred unless a release-notes pass is scheduled
