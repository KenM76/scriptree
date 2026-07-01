# Canonical category catalog + soft near-duplicate validator (a112)

**Tag:** [v3-architecture] [taxonomy] [validate] [ux] [workflow-generated]
**Version:** v0.8.0a112
**Files:** `scriptree/core/category_catalog.py` (matcher), `scriptree/resources/category_catalog.json`
(machine-readable list), `docs/LLM/category_catalog.md` (human/LLM doc),
`scriptree/cli/validate.py` (integration), `scriptree/ui/category_completer.py`
+ `tool_editor.py` / `tree_view.py` (editor autocomplete),
`tests/test_category_catalog.py`.

## Problem

The `.scriptree`/`.scriptreetree` `category` field is FREE-FORM and the codebase
never enforced a vocabulary (`category_authoring.md` literally says so). The
forest folds 2+ tools that share a TOP segment into ONE cell — so any near-miss
spelling fragments the forest. Real evidence already on disk: the shipped Demos
catalog had `Demo` (deselect-to-act, regex-tester) AND `Demos` (find-replace) →
**two separate cells that should have been one.** With LLMs increasingly picking
categories, the drift risk compounds (`DevTools` vs `Developer Tools` vs `Dev`).

## What was built

1. **An extensive controlled vocabulary** — 799 categories across 185
   top-levels (CAD/Office/Media/DevTools/Data/Security/AI/Science/...). Generated
   by a **27-agent Workflow**: one agent per software domain produced a deep
   sub-taxonomy under the shared conventions (Vendor/App vs Domain/Sub, Title
   Case, depth ≤4, "top segment is what grows"), plus a guide-synthesis agent for
   the intro/how-to-choose/conventions front-matter. Two SYNCED artifacts:
   * `docs/LLM/category_catalog.md` — the human/LLM reference (read-first).
   * `scriptree/resources/category_catalog.json` — `{version, top_levels,
     categories}`, loaded by the matcher. A test asserts every JSON category
     appears in the doc so they can't drift.
2. **A soft near-duplicate matcher** (`category_catalog.py`, pure stdlib via
   `difflib`): `nearest(cat, pool)` classifies a candidate vs a pool as
   `case` / `plural` / `typo` (in that priority); `lint_category(cat, siblings)`
   returns ADVISORY warnings (never rejects — free-form still works). It loads
   the JSON lazily + cached, and degrades to "no opinion" if the file is missing
   so validation can never hard-fail on a missing data file.
3. **`python -m scriptree validate` integration**: per-file canonical-near-dup
   warnings + a CROSS-FILE sibling check (pre-scan all categories in the run,
   warn when two differ only by case/plural/typo). Applies to BOTH `.scriptree`
   and `.scriptreetree`. Correctly flags the live `Demo`/`Demos` drift.
4. **Editor autocomplete**: a `QCompleter` (MatchContains, case-insensitive,
   popup) seeded from the catalog, attached to the Category `QLineEdit` in both
   the tool editor and the tree-properties dialog — so the GUI nudges users onto
   the vocabulary too.

## Gotchas / decisions worth keeping

* **Two removal-class bug in the de-dupe lint** (same shape as the trim bug):
  the canonical-near-dup check and the unknown-top-level check shared an
  `if/else`. When I de-duped (skip the canonical warning because a sibling
  warning already pointed at the same target), control fell into the `else` and
  fired a SPURIOUS top-level warning. Fix: a canonical near-dup must consume the
  branch entirely — only `canon is None` (genuinely new) may reach the
  top-level check.
* **Plural matcher is deliberately crude** (`_singular` strips ONE trailing `s`):
  enough to catch Demo/Demos, Driver/Drivers without a real inflector.
* **Fuzzy cutoff 0.86** (difflib ratio) — tuned so only true typos fire
  (`SoldWorks`→`SolidWorks` ~0.94), never two distinct categories sharing a
  domain prefix.
* **Advisory, not enforcing** — matches `validate.py`'s existing `[WARN]`
  philosophy. Categories stay free-form; the catalog only keeps the common
  cases consistent.
* **Distribution**: the JSON sits in `scriptree/resources/` alongside the icons,
  so it ships via `make_portable.py`'s wholesale tree copy (no wheel, so no
  `package_data` needed). Loaded by file path relative to `__file__`.

## Durable maintenance rule

When adding a new app domain: add the category to BOTH
`docs/LLM/category_catalog.md` AND `scriptree/resources/category_catalog.json`
(the consistency test enforces it). A category's top segment should be a known
domain/vendor from the catalog; new domains go in the catalog FIRST so humans +
LLMs converge.

## Reusable takeaway

A **Workflow fan-out (one agent per domain) + a synthesis pass** is an excellent
fit for "make a very extensive, well-structured list" — far broader and more
consistent than writing it inline, and the structured-output schema makes the
result directly consumable as a data file. Pair any generated controlled
vocabulary with a SOFT validator (advisory near-dup detection) + editor
autocomplete so the list actually gets used instead of drifting.
