"""category_catalog.py — the canonical ScripTree category vocabulary + the
soft near-duplicate matcher used by ``python -m scriptree validate`` and the
tree-editor's category autocomplete.

v0.8.0a112.

Why this exists
---------------
The ``category`` field on a ``.scriptree`` / ``.scriptreetree`` is FREE-FORM
(the loader never enforced a vocabulary), and the forest folds 2+ tools that
share a top segment into ONE cell.  That means two people — or two LLMs —
categorising similar tools can pick near-miss strings (``Demo`` vs ``Demos``,
``DevTools`` vs ``Developer Tools``) and the forest silently fragments into
separate cells instead of folding them together.

This module is the *soft* guard against that drift:

  * It loads the **canonical category catalog** — a curated, extensive
    controlled vocabulary — from ``scriptree/resources/category_catalog.json``
    (the human-readable companion is ``docs/LLM/category_catalog.md``).
  * It offers ``nearest()`` / ``lint_category()`` to find when a candidate
    category is a *near-duplicate* of a canonical one (or of a sibling already
    in the same forest) so tooling can say "did you mean ``Demos``?".

It is deliberately ADVISORY: nothing here rejects a category.  Free-form
categories still work; the catalog just keeps the common cases consistent.

Contract / shapes
-----------------
``category_catalog.json`` shape::

    {
      "version": "0.8.0a112",
      "top_levels": ["SolidWorks", "MSOffice", "DevTools", ...],
      "categories": ["SolidWorks/Drawings", "MSOffice/Word", "DevTools/Git", ...]
    }

``top_levels`` is the set of blessed first segments; ``categories`` is the flat
set of full canonical paths.  Both are case-sensitive Title-Case house style.

The JSON is loaded lazily and cached.  If the file is missing or malformed the
catalog degrades to EMPTY — every public function then returns "no opinion"
(no suggestion, no warning), so a missing data file can never break validation.

Matching algorithm (``nearest``)
--------------------------------
Given a candidate path and a pool of known paths, return the single closest
pool entry **only if** the candidate is a genuine near-duplicate, classified
(in priority order) as:

  1. ``"case"``   — same path, different capitalisation (``devtools`` vs
                    ``DevTools``).
  2. ``"plural"`` — segments match after stripping a trailing ``s`` on each
                    (``Demo`` vs ``Demos``, ``Driver`` vs ``Drivers``).
  3. ``"typo"``   — high fuzzy similarity on the whole normalised path
                    (``difflib`` ratio ≥ ``_FUZZY_CUTOFF``), catching small
                    spelling slips (``SoldWorks`` vs ``SolidWorks``).

If none apply the candidate is considered genuinely new (not a near-dup) and
``nearest`` returns ``(None, None)``.
"""

from __future__ import annotations

import difflib
import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable

#: Whole-path fuzzy-similarity threshold for the "typo" class.  Tuned high so
#: only true near-misses fire (``SolidWorks`` vs ``SoldWorks`` ~0.94), never
#: distinct categories that merely share a domain.
_FUZZY_CUTOFF = 0.86

#: Location of the machine-readable catalog, shipped inside the package so it is
#: available in every install (dev tree, portable zip, deployed runtime).
_CATALOG_PATH = Path(__file__).resolve().parent.parent / "resources" / "category_catalog.json"


@lru_cache(maxsize=1)
def _load_raw() -> dict:
    """Load + cache the catalog JSON.  Returns an empty catalog on any error so
    a missing/broken data file degrades to 'no opinion' rather than breaking
    callers (validation must never hard-fail because the advisory list is
    absent)."""
    try:
        data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"top_levels": [], "categories": []}
        return data
    except Exception:  # noqa: BLE001 -- missing file / bad JSON -> empty catalog
        return {"top_levels": [], "categories": []}


def canonical_paths() -> tuple[str, ...]:
    """The flat tuple of every canonical category path, Title-Case house style."""
    return tuple(_load_raw().get("categories", []) or [])


def canonical_top_levels() -> frozenset[str]:
    """The blessed first segments (e.g. ``SolidWorks``, ``DevTools``)."""
    return frozenset(_load_raw().get("top_levels", []) or [])


def is_empty() -> bool:
    """True when no catalog data is loaded (missing/broken JSON) — callers can
    skip category linting entirely and stay silent."""
    return not canonical_paths()


# ---------------------------------------------------------------------------
# Normalisation + near-duplicate matching
# ---------------------------------------------------------------------------

def _norm(path: str) -> str:
    """Normalise a category path for case-insensitive comparison: lowercase,
    strip whitespace around each ``/`` segment, drop empty segments."""
    if not path:
        return ""
    segs = [s.strip().lower() for s in str(path).split("/")]
    return "/".join(s for s in segs if s)


def _singular(seg: str) -> str:
    """Crude singular form: strip ONE trailing ``s`` (Demos->Demo, Drivers->
    Driver).  Good enough to catch the plural/singular drift class; not a real
    inflector (leaves ``ss`` words mostly alone since we only strip one)."""
    return seg[:-1] if len(seg) > 1 and seg.endswith("s") else seg


def nearest(category: str, pool: Iterable[str] | None = None) -> tuple[str | None, str | None]:
    """Return ``(closest_pool_entry, reason)`` if ``category`` is a near-
    duplicate of something in ``pool``, else ``(None, None)``.

    ``pool`` defaults to the canonical catalog.  ``reason`` is one of
    ``"case"`` / ``"plural"`` / ``"typo"`` (see module docstring).  An EXACT
    match (same string) returns ``(None, None)`` — an exact canonical hit is
    not a problem, so there is nothing to suggest.
    """
    if not category:
        return None, None
    pool_list = list(pool) if pool is not None else list(canonical_paths())
    if not pool_list:
        return None, None

    nc = _norm(category)
    if not nc:
        return None, None

    # 1) case-only difference (normalised-equal but not byte-equal)
    for p in pool_list:
        if _norm(p) == nc:
            return (p, "case") if p != category else (None, None)

    # 2) plural/singular per segment (same segment count, each matches after
    #    stripping a trailing 's')
    cseg = nc.split("/")
    for p in pool_list:
        pseg = _norm(p).split("/")
        if len(pseg) == len(cseg) and all(
            _singular(a) == _singular(b) for a, b in zip(cseg, pseg)
        ):
            return p, "plural"

    # 3) whole-path fuzzy match (small typo / transposition)
    norm_pool = {_norm(p): p for p in pool_list}
    hit = difflib.get_close_matches(nc, list(norm_pool), n=1, cutoff=_FUZZY_CUTOFF)
    if hit:
        return norm_pool[hit[0]], "typo"

    return None, None


_REASON_BLURB = {
    "case": "differs only in capitalisation from the canonical",
    "plural": "is a singular/plural variant of the canonical",
    "typo": "looks like a near-miss spelling of the canonical",
}


def lint_category(category: str, *, siblings: Iterable[str] = ()) -> list[str]:
    """Advisory warnings for a single ``category`` string.

    Returns a (possibly empty) list of human-readable warning lines.  Never
    raises; never rejects — purely advisory, matching the rest of
    ``validate.py``'s lint philosophy.

    Checks, in order:
      1. **Sibling near-duplicate** (highest value): if ``category`` is a
         near-dup of another category in the SAME forest/run (``siblings``),
         warn to consolidate — this is the ``Demo`` vs ``Demos`` "two cells
         that should be one" case, caught even when neither is canonical.
      2. **Canonical near-duplicate**: if it isn't canonical but is a near-dup
         of a catalog entry, suggest the canonical ("did you mean …").
      3. **Unknown top-level**: if its first segment isn't a blessed domain,
         a soft pointer to the catalog (free-form is still allowed).

    All checks are skipped when the catalog is empty (no data) for #2/#3;
    #1 only needs the siblings, so it still works with no catalog.
    """
    cat = (category or "").strip()
    if not cat:
        return []  # uncategorised is perfectly fine

    out: list[str] = []

    # 1) sibling near-duplicate (consolidation) — works without the catalog.
    sib_pool = [s for s in siblings if s and s.strip() and _norm(s) != _norm(cat)]
    sib, sib_reason = nearest(cat, sib_pool)
    if sib is not None:
        out.append(
            f"category {cat!r} {_REASON_BLURB.get(sib_reason, 'is a near-duplicate of')} "
            f"sibling {sib!r}.  These fold into SEPARATE forest cells — "
            f"consolidate to ONE spelling."
        )

    if is_empty():
        return out  # no canonical data -> only the sibling check applies

    if cat not in canonical_paths():
        canon, reason = nearest(cat, canonical_paths())
        if canon is not None:
            # 2) near-duplicate of a canonical entry -> suggest the blessed
            #    spelling, UNLESS the sibling warning above already pointed the
            #    user at the SAME target (e.g. Demo, sibling Demos, canonical
            #    Demos) -- one nudge is enough.  A canonical near-dup NEVER
            #    falls through to the top-level check below.
            if sib is None or _norm(canon) != _norm(sib):
                out.append(
                    f"category {cat!r} {_REASON_BLURB.get(reason, 'is close to')} "
                    f"catalog entry {canon!r}.  Use {canon!r} (or keep yours "
                    f"intentionally).  See docs/LLM/category_catalog.md."
                )
        else:
            # 3) genuinely new (no canonical near-dup) -> softest nudge if the
            #    top-level domain isn't a known one.
            top = cat.split("/", 1)[0]
            if top not in canonical_top_levels():
                out.append(
                    f"category top-level {top!r} isn't in the canonical catalog "
                    f"(free-form is allowed, but a known domain keeps the forest "
                    f"from fragmenting).  See docs/LLM/category_catalog.md."
                )

    return out


def all_categories_for_completion() -> list[str]:
    """The sorted canonical paths, for the tree-editor's category autocomplete
    (a ``QCompleter`` model).  Empty when no catalog is loaded."""
    return sorted(canonical_paths())
