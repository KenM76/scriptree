---
topic: v3-architecture
date: 2026-05-07
status: pattern
related: [merged_tree, ring_io]
---
# Explode a `.scriptreetree` into a multi-cell ring

## What happened / rule

Feature: V1 editor's File → **Open tree in ring shell** —
each top-level item of the loaded `.scriptreetree` becomes
its own cell, all docked into a ring around a master.

Implementation choice: **don't try to drive the cell shell
imperatively** ("spawn cell, move it, dock it, repeat").
Instead, materialise a synthetic `.scriptreering` file in
`%TEMP%` with N members at honeycomb positions and hand
that to `run_scriptreering.py` as a positional arg.  The
shell's existing `load_ring` path does the rest.

## Why this works

`load_ring` already:

- Spawns the master cell.
- Spawns each member cell at its saved position.
- Wires `master._members[member_id] = preferred_qpoint`.
- Triggers an edge-fold so positions clamp to screen.

We get all of that for free by writing a valid
`.scriptreering` document.  No new imperative API needed.

## Top-level materialisation

Each top-level node becomes one member's `catalog_path`:

| Source node | Materialised member catalog                         |
|---|---|
| Top-level `.scriptree` leaf      | the leaf path itself (resolved to absolute) |
| Top-level `.scriptreetree` leaf  | the leaf path itself (resolved to absolute) |
| Top-level **folder**             | a fresh temp `.scriptreetree` in `%TEMP%` containing just that folder's children, with leaf paths resolved to absolute |

Folders MUST be flattened to absolute paths before writing
to `%TEMP%` because the temp file's directory has no
relationship to the source tree's directory.

## Honeycomb positions

Reuse the offsets from `snap_engine._FLAT_TOP_OFFSETS`.  For
≤6 members, place each at `master_centre + offset * size_px`.
For >6 members, use a second concentric ring at radius 2×
(rough — the snap engine compresses on first interaction).

Convert centre → top-left for the ring file:
`(round(cx - size_px / 2), round(cy - size_px / 2))`.

## Determinism

Hash the source tree path + top-level catalog list to derive
the temp filename.  Re-exploding the same tree produces the
same temp ring path → any QFileSystemWatcher attached on the
shell side stays attached.

```python
sig = hashlib.sha1(
    f"{src}|{len(items)}|{[c for _, c in items]}".encode("utf-8")
).hexdigest()[:12]
out = Path(tempfile.gettempdir()) / f"scriptreering_explode_{sig}.scriptreering"
```

## How future-me detects it

If you're tempted to add a new "spawn N cells and dock them"
RPC to the cell shell, stop.  Build a temp ring file, hand
it to the shell as argv, let `load_ring` do the work.

If the temp ring path keeps changing across calls for the
same input, the hash isn't stable — check what's in the
seed string (don't include `datetime.now()` etc).
