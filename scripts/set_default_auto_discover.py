"""One-shot batch updater: stamp ``auto_discover: {}`` on every
``.scriptreetree`` file that's still in the "user has never been
asked" state.

## For humans

Walks each path given on the command line and:

* Loads every ``.scriptreetree`` it finds (recursively).
* If the tree's ``auto_discover`` is ``None`` (= no JSON key
  present), sets it to ``TreeAutoDiscoverConfig()`` (all
  defaults: ``enabled=True``, ``roots=["."]``,
  ``include_sibling_trees=True``, ``update_mode="prompt"``).
* Saves back via ``save_tree`` -- the IO layer emits the
  block as ``"auto_discover": {}`` (an empty dict because
  every field equals its default).
* Reports per-file: ``[STAMPED]`` / ``[ALREADY SET]`` / ``[ERR]``.

The empty-block form is what tells the v0.8.0a21+ runtime
"the user has been asked, do NOT re-fire the first-load
chooser".  Since the cell-shell now respects this, every
tree stamped here will stop nagging the user on startup --
the prompt only re-fires if a *real* discovery diff finds
something new on disk.

## For maintainers / LLMs

* Idempotent: a second run is a no-op (every tree reports
  ``[ALREADY SET]``).
* Pure I/O; no Qt; safe to run from headless shells.
* Honours the project's standard load_tree/save_tree round-
  trip -- byte-identical for every part of the tree the
  script doesn't touch (the round-trip guard in
  ``test_tree_auto_discover_io.py`` covers that contract).
* Robust to broken files: a load/parse error on one tree
  emits an ``[ERR]`` line + the exception's repr and
  continues to the next file rather than crashing the batch.

Usage::

    python scripts/set_default_auto_discover.py PATH [PATH ...]

Example::

    python scripts/set_default_auto_discover.py \\
        D:/Dev/ScripTree/ScripTreeApps \\
        R:/Scriptree \\
        R:/Scriptreeapps
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make ``scriptree`` importable when run from a repo checkout.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from scriptree.core.discovery import TreeAutoDiscoverConfig  # noqa: E402
from scriptree.core.io import load_tree, save_tree  # noqa: E402


def _stamp_one(path: Path) -> str:
    """Update a single ``.scriptreetree``.

    Returns a tag for the report line:

    * ``"stamped"``     -- tree was None, now defaulted
    * ``"already_set"`` -- tree already had a non-None config
    * ``"error: <msg>"``-- load or save failed
    """
    try:
        tree = load_tree(path)
    except Exception as exc:  # noqa: BLE001 -- summary tag, not propagation
        return f"error: load failed: {exc!r}"
    if tree.auto_discover is not None:
        return "already_set"
    tree.auto_discover = TreeAutoDiscoverConfig()
    try:
        save_tree(tree, path)
    except Exception as exc:  # noqa: BLE001
        return f"error: save failed: {exc!r}"
    return "stamped"


def main(roots: list[str]) -> int:
    """Walk each root, stamp every ``.scriptreetree`` under it.

    Reports a per-file line and a final summary.  Exit code is
    0 unless every root failed to enumerate -- a single
    broken file doesn't fail the batch.
    """
    if not roots:
        print(
            "usage: set_default_auto_discover.py PATH [PATH ...]",
            file=sys.stderr,
        )
        return 2

    counts: dict[str, int] = {
        "stamped": 0, "already_set": 0, "error": 0,
    }
    for root in roots:
        root_path = Path(root)
        if not root_path.exists():
            print(f"[SKIP] {root_path} -- does not exist")
            continue
        # The recursive glob below picks up both top-level and
        # nested ``.scriptreetree`` files.  Order is OS-dependent;
        # we don't rely on it.
        trees = sorted(root_path.rglob("*.scriptreetree"))
        if not trees:
            print(f"[SKIP] {root_path} -- no .scriptreetree files")
            continue
        print(f"\n=== {root_path} ({len(trees)} trees) ===")
        for t in trees:
            result = _stamp_one(t)
            if result.startswith("error"):
                counts["error"] += 1
                tag = "ERR"
            elif result == "stamped":
                counts["stamped"] += 1
                tag = "STAMPED"
            else:
                counts["already_set"] += 1
                tag = "ALREADY SET"
            # Trim the path for readability.
            try:
                rel = t.relative_to(root_path)
            except ValueError:
                rel = t
            print(f"  [{tag}] {rel}")
            if result.startswith("error"):
                print(f"           {result}")

    print("\n--- summary ---")
    print(f"  stamped:     {counts['stamped']}")
    print(f"  already set: {counts['already_set']}")
    print(f"  errors:      {counts['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
