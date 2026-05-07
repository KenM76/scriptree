---
topic: v3-architecture
date: 2026-05-07
status: recipe
related: [wordskip_list_for_abbreviations]
---
# CamelCase precedence in label derivation

## What happened

"SolidWorks toolkit" auto-derived to "St" (first letter of
each word) when it should have been "SW" (the CamelCase
abbreviation of the dominant word).  Same problem for
"PowerShell scripts" → "Ps" instead of "PS".

## Root cause

Initial label-derivation logic checked multi-word first-
letters before checking CamelCase.  A name with one
CamelCase word + a generic trailer ("toolkit", "scripts",
"tools") fell into the multi-word branch and produced a
nonsense abbreviation.

## Fix / recipe

Check ALL words for CamelCase first; only fall through to
multi-word logic if no word qualifies.  CamelCase = starts
with a capital AND contains a second capital somewhere
inside.

```python
# scriptree/shell/cell_window.py:_derive_letters
def _derive_letters(name: str) -> str:
    words = [w for w in re.split(r"[\s_\-]+", name) if w]
    # 1. CamelCase wins outright
    for w in words:
        if w[:1].isupper() and any(c.isupper() for c in w[1:]):
            return "".join(c for c in w if c.isupper())[:2].upper()
    # 2. Multi-word first letters (with skip list)
    keep = [w for w in words if w.lower() not in _SKIP_WORDS]
    if len(keep) >= 2:
        return (keep[0][:1] + keep[1][:1]).upper()
    # 3. Single word fallback: first two letters
    return (keep[0] if keep else words[0])[:2].upper()
```

## How future-me detects it

An auto-derived label that takes the first letter of a
generic-trailer word ("Sw" → "St" because "toolkit" follows)
is a sign CamelCase isn't being checked first.  The fix is
strictly priority-of-rules, not new logic.
