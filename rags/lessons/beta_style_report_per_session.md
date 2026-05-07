---
topic: v3-process
date: 2026-05-07
status: workflow
related: []
---
# Beta-style report after each multi-fix session

## What happened / rule

After a session that lands more than a one-line fix —
especially a multi-symptom debug pass — write a beta-style
report to `D:/Dev/ScripTree3/docs/beta-reports/` capturing
what the user reported, what was wrong, what was fixed, what
was tested, and what's still left for the user to smoke-test.

## Root cause / rationale

Multi-fix sessions accumulate context faster than commit
messages can capture.  A single beta report ties the whole
session — user complaint, root cause analysis, fix
decisions, remaining unknowns — into one searchable
document.  Future sessions grep these and pick up where the
last one left off.

## Fix / recipe

Filename pattern: `YYYY-MM-DD__claude__<slug>.md`.

Frontmatter:

```markdown
---
date: 2026-05-07
persona: claude
feature: cell-shell
build: v0.2.7
verdict: ship | needs-followup | broken
---
```

Sections (in this order):

1. **What the user reported** — verbatim quote of the
   complaint.  Don't paraphrase.
2. **Findings** — root causes with `file.py:line` refs to the
   exact code that was wrong.
3. **Fixes** — what landed, with commit refs if applicable.
4. **Tests added** — new pytest files and what they cover.
5. **Diagnostics added** — new `_log()` lines or other
   instrumentation.
6. **Manual smoke** — explicit list of things handed back to
   the user for click-through verification.

The verbatim user quote in #1 is non-negotiable — it's what
makes the report greppable later by remembered phrases.

## How future-me detects it

A multi-fix session ended without a beta report → search
will fail to surface the work next time it's relevant.
Write the report before closing the session, even if it's
short.
