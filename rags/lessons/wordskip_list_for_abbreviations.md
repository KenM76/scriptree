---
topic: v3-architecture
date: 2026-05-07
status: recipe
related: [camelcase_precedence_in_label]
---
# Word-skip list for multi-word abbreviations

## What happened

"the cat" auto-abbreviated to "Tc".  "Tools for Windows"
became "Tf".  Stop-word noise polluted the derived labels.

## Root cause

The multi-word first-letter branch was indiscriminate — it
took the first letter of every word, including English
articles and short prepositions that should never contribute
a label letter.

## Fix / recipe

A small skip list, case-insensitive:

```python
# scriptree/shell/cell_window.py
_SKIP_WORDS = {
    "a", "an", "and", "or", "the", "of", "to",
    "in", "on", "for", "at", "by", "as", "is", "if",
}
```

After the CamelCase check (see camelcase_precedence_in_label),
filter words against this set:

```python
keep = [w for w in words if w.lower() not in _SKIP_WORDS]
if len(keep) >= 2:
    return (keep[0][:1] + keep[1][:1]).upper()
# fall through: single-word case "the cat" → "cat" → "CA"
```

So "the cat" → kept = ["cat"] → only one word → fall through
to single-word logic → "CA".  "Tools for Windows" → kept =
["Tools", "Windows"] → "TW".

## How future-me detects it

A label that starts with "T" or "O" or "A" because the source
name began with a stop word.  Or a user complaint that an
auto-label "looks dumb" — the fix is usually adding a word
to `_SKIP_WORDS`, not changing logic.
