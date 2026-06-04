---
topic: v3-architecture
date: 2026-06-04
status: recipe
related: [merged_tree_pushback_to_origins, merged_tree_inline_subtrees_at_build_time]
---
# Merged-tree de-dup must consider display name AND path

## What happened

Pre-v0.8.0a36 the merged-tree builder de-duped its constituent
sources only by source PATH. That was insufficient: two distinct
`.scriptreetree` files (different paths on disk) that both
internally name themselves `"MSOffice"` produced two top-level
folders in the merged tree both labelled `"MSOffice"`. Visually
identical, semantically distinct — the user couldn't tell which
was which, and right-clicking the wrong one would touch the wrong
source file.

## Root cause

A `.scriptreetree`'s display name is just the root folder name
inside the JSON, not a function of its file path. Different files
can absolutely choose the same display name (and often will, for
catalogs of the same product line installed in different
locations). Path-only de-dup catches "same file referenced twice"
but misses "two different files with colliding display names."

## Fix / recipe

When a `top_name` collides with one already used in the merged
tree, disambiguate by appending the source's parent-folder name
in parens. Fall back to a numeric counter if even THAT collides
(both `MSOffice` files happen to live under same-named parent dirs).

```python
def _disambiguate(top_name, source_path, used_names):
    if top_name not in used_names:
        return top_name
    # First try: append parent folder
    parent = source_path.parent.name
    candidate = f"{top_name} ({parent})"
    if candidate not in used_names:
        return candidate
    # Fallback: numeric counter
    n = 2
    while f"{top_name} ({n})" in used_names:
        n += 1
    return f"{top_name} ({n})"
```

Names like `"MSOffice (a_apps)"` and `"MSOffice (b_apps)"`, falling
back to `"MSOffice (2)"`, `"MSOffice (3)"` if needed. Order-stable
across rebuilds: iterate sources in a deterministic order (sorted
or insertion-order from the forest) so the same source always gets
the same disambiguated label.

Pinned by
`D:\Dev\ScripTree\tests\test_editor_unhappy_paths_a36.py` (name-
collision case with two same-named sources under different parent
dirs).

## How future-me detects it

- Symptom: forest-in-editor shows two folders with identical
  labels, and right-clicking either touches the wrong file. The
  builder's dedup pass is path-only.
- Any other aggregation/merge surface that builds a UI label per
  source needs the SAME two-stage disambiguation (parent-folder,
  then counter). Display labels are NOT guaranteed unique across
  sources.
- The sidecar at
  `<merged>.scriptreetree.origins.json` keys by the disambiguated
  name, so the same disambiguation must produce stable output
  build-over-build, or push-back will fail to find sources.
