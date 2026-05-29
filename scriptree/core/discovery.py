"""Shared discovery-config dataclasses for ``.scriptreetree`` files.

## For humans

This module holds the *data shapes* that govern ScripTree's
"new-tool-found" behaviour for tree files.  It is intentionally
small, pure-Python, and Qt-free — the same constants are reachable
from the headless ``python -m scriptree validate`` CLI, the
graphical editor (``MainWindow``), and the cell-shell launcher.

The behaviour itself — walking the filesystem, diffing what was
found against what the tree already has, prompting the user, and
mutating the in-memory ``TreeDef`` — lives in companion modules
(``core/tree_discover.py`` for the walker, ``core/tree_diff.py``
for the diff/apply pair, and ``ui/discovery_diff_dialog.py`` for
the prompt).  This file is the contract those modules agree on.

The parallel feature for ``.scriptreeforest`` files already exists
in ``scriptree.shell.forest_io.AutoDiscoverConfig``.  We do not
share that dataclass directly because:

* Forest discovery filters by *item kind* (``"ring" | "tree" |
  "tool"``); tree discovery has no such filter — there is only one
  thing to look for (``.scriptree`` files) plus an optional
  sibling-tree surfacing toggle.
* Forest scans named root folders (``ScripTreeApps``,
  ``../ScripTreeApps``).  Tree scanning defaults to "this tree's
  containing folder" — a fundamentally different anchor.
* Forest exclusion is a flat list of paths the user has removed.
  Tree exclusion is the same shape but stored on the
  ``.scriptreetree`` itself, alongside this config.

What IS shared is the ``UpdateMode`` literal (``"off" | "auto" |
"prompt"``).  Both surfaces use the exact same three-mode contract
and we want the type to compare equal across them.

## For maintainers / LLMs

* This module imports ONLY from the standard library.  Do not add
  Qt imports, Pillow imports, or any heavyweight dependency — the
  ``validate`` / ``migrate`` CLI path imports
  ``scriptree.core.io`` which imports ``scriptree.core.model``
  which imports this file.  See ``tests/test_core_purity.py``
  for the enforcement test.
* The defaults on ``TreeAutoDiscoverConfig`` are tuned for the
  most common case: a hand-curated tree the author wants kept
  in sync with a single folder of tools, prompting the user
  before changing anything.  See each field's docstring for the
  rationale on the chosen default.
* When ``TreeDef.auto_discover is None`` the *runtime* treats
  that as "this tree has never been configured; on first load,
  ask the user which mode they want".  That is distinct from
  ``TreeAutoDiscoverConfig(update_mode="off")`` which means "the
  user explicitly opted out; do not ask again".  See
  ``MainWindow._open_tree`` for the dispatcher.
* The choice to keep ``excluded[]`` on ``TreeDef`` rather than on
  this dataclass is deliberate: exclusion is *state* the user
  has built up over time (paths they have removed and don't
  want re-suggested), while this dataclass is *settings*
  (which folders to scan, what kind of prompt to use).  Keeping
  them separate makes "reset settings to default" a sensible
  operation that doesn't wipe accrued exclusions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# --- shared with forest -----------------------------------------------------

UpdateMode = Literal["off", "auto", "prompt"]
"""How a discovery pass applies the diff it produces.

* ``"off"`` — discovery does not run.  The walker, diff, and prompt
  are all skipped.  Used both as the explicit user opt-out and as
  the implicit default for legacy files (rare — most legacy paths
  use ``TreeDef.auto_discover is None`` to mean "ask the user
  next time", not ``"off"``).
* ``"auto"`` — discovery runs and applies adds/removes/re-includes
  silently.  No dialog.  Suits authoritative trees where the
  on-disk folder IS the source of truth and the ``.scriptreetree``
  is just a serialised cache of it.  The user can still inspect
  the result in the editor; nothing destructive happens (re-adding
  a removed leaf is one click).
* ``"prompt"`` — discovery runs but mutations go through the diff
  dialog.  The user picks which adds to accept and confirms each
  remove.  Default for hand-curated trees.

The same literal type is used by the forest's
``AutoDiscoverConfig.update_mode`` so a future refactor can unify
the two surfaces if/when that becomes useful.
"""


# --- tree-specific config ---------------------------------------------------

@dataclass
class TreeAutoDiscoverConfig:
    """Discovery settings for a single ``.scriptreetree`` file.

    Serialised under the ``auto_discover`` key of the
    ``.scriptreetree`` JSON.  All four fields are optional on
    deserialise and round-trip byte-identically when set to their
    defaults (the I/O code omits the block when the whole
    dataclass equals ``TreeAutoDiscoverConfig()``, so legacy trees
    written before this feature stay diff-clean on a no-op save).

    The data shape is consumed by:

    * ``scriptree.core.tree_discover.discover_for_tree`` — uses
      ``roots`` to drive the walker and ``include_sibling_trees``
      to decide whether to surface sub-trees.
    * ``scriptree.ui.discovery_diff_dialog`` — uses ``update_mode``
      to decide whether to show, auto-apply, or skip.
    * ``scriptree.ui.main_window.MainWindow._open_tree`` — uses the
      presence of the block (rather than its contents) to decide
      whether this is a "first load" that needs the
      ``ChooseUpdateModeDialog`` instead of the diff dialog.
    """

    enabled: bool = True
    """Master kill switch.  When ``False`` the walker is not
    invoked and the menu's "Scan tree for new tools" entry is
    disabled (with a tooltip explaining why).  Distinct from
    ``update_mode == "off"`` in semantics only: ``enabled=False``
    is meant to be a long-term "this tree is frozen" toggle (the
    author actively does not want discovery to consider it at
    all, even on manual trigger); ``update_mode="off"`` is the
    user's "stop asking me but keep the manual menu available"
    setting.  Most users will only ever set ``update_mode`` and
    leave ``enabled`` alone.
    """

    roots: list[str] = field(default_factory=lambda: ["."])
    """Folders to scan, relative to the tree file's directory.

    The default ``["."]`` means "scan the tree file's own
    containing folder and walk down".  The walker treats this as
    a starting point: it walks every subdirectory below each
    root, with the priority rule defined in
    ``scriptree.core.tree_discover`` (descend until a
    ``.scriptreetree`` is found, then stop — that subtree is
    owned by that other file).

    Paths are resolved against ``Path(tree_file).parent`` every
    time discovery runs, so moving the tree file picks up the
    new sibling folder automatically.  Absolute paths are
    honoured but not recommended (they make the file
    non-portable across machines).

    Multiple roots are allowed for the unusual case where a tree
    aggregates tools from two parallel folders, e.g.
    ``roots=["./shared", "../bespoke"]``.  Folders that don't
    exist are skipped silently — handy when one of several
    siblings is conditionally present.
    """

    include_sibling_trees: bool = True
    """Whether to surface ``.scriptreetree`` files encountered
    during the walk as candidate sub-tree leaves in the current
    tree.

    When ``True`` (default), the walker emits a candidate for
    each ``.scriptreetree`` it finds (and *does not* descend
    into that subtree's directory — the boundary rule still
    applies).  The diff dialog shows them in the "Add" section
    so the user can choose to nest them as leaves in the
    current tree.

    When ``False``, sibling trees are skipped entirely (no
    candidate, no descent into their directories).  Useful for
    trees that should remain flat — e.g. a master ``ToolKit``
    tree that just aggregates direct ``.scriptree`` files and
    never wants to grow nested sub-trees.

    Phase-2 implementation note: the walker's priority rule
    *always* stops descending at a ``.scriptreetree`` boundary
    regardless of this flag.  The flag only controls whether the
    boundary file itself becomes a candidate.
    """

    update_mode: UpdateMode = "prompt"
    """How the discovery pass applies its diff.  See the
    ``UpdateMode`` module-level docstring for the full
    contract."""


__all__ = [
    "TreeAutoDiscoverConfig",
    "UpdateMode",
]
