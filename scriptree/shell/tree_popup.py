"""
tree_popup.py — lightweight in-process tree popup for cell single-clicks.

## For humans

The cell shell exposes two distinct gestures with different UX:

* **Single left click** → THIS MODULE shows a quick popup ``QMenu`` of
  the cell's catalog right next to the hexagon.  Click a leaf → fire
  the V1 standalone runner (``v1_launcher.launch_tool``).  No editor
  window pops up.
* **Double left click** → the v1_launcher polyfill spawns the full V1
  editor with the cell's catalog loaded.  Heavier but full-featured.

For master cells the popup is the **union** of every member's catalog,
each one a top-level submenu named after its source.

The tree is parsed via V1's ``load_tree`` / ``load_tool`` so the
``.scriptreetree`` and ``.scriptree`` formats Just Work — no V2-format
duplication, no schema drift between launchers.

## For maintainers / LLMs

* Leaf-action closures MUST bind ``leaf=str(p)`` and ``config=cfg`` as
  default args (``_on_trigger(_checked=False, leaf=..., config=...)``).
  This defeats Python's late-binding-in-loop trap — without it every
  action would launch the LAST leaf.  Same pattern in the
  ``.scriptree`` single-action branch.
* Label resolution order is fixed and mirrors V1's tree view:
  ``display_name`` → ``name`` → (leaves only) file stem → ``"(unnamed)"``.
  Keep this in sync with V1 or the popup and the editor disagree on
  names.
* Leaf paths are resolved relative to the *catalog's directory*
  (``source_dir / p``), NOT the CWD.  ``_build_menu_for_catalog``
  passes ``p.parent`` as ``source_dir``; preserve that or relative
  leaves break when launched from elsewhere.
* Every failure is degraded into a *disabled* placeholder action
  (``(missing: …)``, ``(error: …)``, ``(empty tree)``,
  ``(unsupported: …)``) rather than raised — a broken member must not
  prevent the rest of a master's union from showing.  ``launch_tool``
  exceptions are caught and logged in the trigger handler.
* ``master._members`` is ``dict[member_id, QPoint]``; ids are resolved
  through ``CellRegistry``.  The list/tuple fallback is for synthetic
  test masters only.
* The menu is stashed on ``hex_win._tree_popup_menu`` and
  ``aboutToHide`` records ``hex_win._tree_popup_closed_at`` (monotonic)
  — this is the second-click-toggle mechanism: the click handler uses
  the "just closed" timestamp to suppress an immediate Qt
  outside-click → re-open. Do not remove the stash or toggling breaks.
* ``menu.exec(global_pt)`` is modal/blocking by design (popup, not
  modeless).  Positioned below-centre of the hex; falls back to the
  primary screen centre if ``mapToGlobal`` raises.
* Lazy imports (``v1_launcher``, ``scriptree.core.io``,
  ``CellRegistry``) are intentional to keep import cost off the
  non-popup path; do not hoist.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QLineEdit, QMenu, QWidgetAction,
)


def _log(msg: str) -> None:
    print(f"[tree_popup] {msg}", file=sys.stderr)


# Don't paint a flat result list longer than this — a launcher menu
# with hundreds of visible rows is unusable and slow to lay out.
_MAX_RESULTS = 60


# ---------------------------------------------------------------------------
# Menu builder
# ---------------------------------------------------------------------------

def _add_node_to_menu(  # noqa: ANN001
    menu: QMenu,
    node,
    source_dir: Path,
    *,
    collector: list | None = None,
    path_prefix: str = "",
) -> None:
    """Recursively walk a V1 ``TreeNode`` into a QMenu hierarchy.

    Folder nodes become submenus; leaf nodes become actions whose
    triggered() signal launches the V1 standalone runner with the
    leaf's resolved absolute path.

    Label resolution (matches V1's tree view):
      1. ``display_name`` if non-empty
      2. ``name`` if non-empty
      3. for leaves only: file stem of the leaf's path
      4. ``"(unnamed)"`` last resort

    ``collector`` (optional, keyword-only) — when given, every leaf
    is also appended as a ``(display, search_text, trigger)`` tuple
    so the caller can build a flat live-search result list.
    ``path_prefix`` accumulates the folder breadcrumb for that
    search text / disambiguation.  Both default to "off" so the
    nested-menu behaviour (and the existing tests) are byte-identical.
    """
    from scriptree.shell.v1_launcher import launch_tool

    if node.type == "folder":
        label = node.display_name or node.name or "(unnamed)"
        sub = menu.addMenu(label)
        # ASCII '/' breadcrumb (not a unicode arrow): this string can
        # reach cp1252 logs / serialisation, and this codebase has
        # been bitten by mojibake before — keep it 7-bit.
        child_prefix = f"{path_prefix}{label} / "
        for child in node.children:
            _add_node_to_menu(
                sub, child, source_dir,
                collector=collector, path_prefix=child_prefix,
            )
        return

    # Leaf — resolve the path relative to the catalog's directory.
    if node.path is None:
        return
    p = Path(node.path)
    if not p.is_absolute():
        p = (source_dir / p).resolve()
    label = node.display_name or node.name or p.stem or "(unnamed)"
    cfg = node.configuration  # may be None
    act = menu.addAction(label)
    # Capture p, cfg in default args so the closure doesn't bind to
    # the loop variable.
    def _on_trigger(_checked=False, leaf=str(p), config=cfg):  # noqa: ANN001
        try:
            launch_tool(leaf, configuration=config)
        except Exception as exc:  # noqa: BLE001
            _log(f"launch_tool({leaf!r}) failed: {exc!r}")
    act.triggered.connect(_on_trigger)
    if collector is not None:
        # 4-tuple: (display = breadcrumbed label for the result row,
        # name = the bare leaf label that ranking prefixes against,
        # search_text = full lowercased haystack incl. folder path +
        # filename for the weakest "matches anywhere" tier, trigger).
        # Ranking on the bare name (not the breadcrumbed display) is
        # what makes typing "a" surface tools NAMED a*, like the
        # Start menu / Spotlight.
        search_text = f"{path_prefix}{label} {p.stem}".lower()
        collector.append((
            f"{path_prefix}{label}" if path_prefix else label,
            label,
            search_text,
            _on_trigger,
        ))


def _build_menu_for_catalog(  # noqa: ANN001
    menu: QMenu,
    catalog_path: str | Path,
    *,
    collector: list | None = None,
    path_prefix: str = "",
) -> bool:
    """Populate ``menu`` from one catalog file.  Returns True iff at
    least one item was added.

    ``collector`` / ``path_prefix`` (keyword-only, optional) feed the
    flat live-search index — see :func:`_add_node_to_menu`.  Defaults
    keep the nested-menu behaviour identical for existing callers."""
    from scriptree.core.io import load_tool, load_tree

    p = Path(catalog_path).resolve()
    if not p.is_file():
        menu.addAction(f"(missing: {p.name})").setEnabled(False)
        return False

    ext = p.suffix.lower()
    if ext == ".scriptreetree":
        try:
            tree = load_tree(str(p))
        except Exception as exc:  # noqa: BLE001
            _log(f"load_tree({p}) failed: {exc!r}")
            menu.addAction(f"(error: {p.name})").setEnabled(False)
            return False
        if not tree.nodes:
            menu.addAction("(empty tree)").setEnabled(False)
            return False
        for node in tree.nodes:
            _add_node_to_menu(
                menu, node, p.parent,
                collector=collector, path_prefix=path_prefix,
            )
        return True

    if ext == ".scriptree":
        # A single-tool catalog renders as one action — clicking it
        # launches that tool.
        try:
            tool = load_tool(str(p))
            label = tool.name or p.stem
        except Exception as exc:  # noqa: BLE001
            _log(f"load_tool({p}) failed: {exc!r}")
            label = p.stem
        from scriptree.shell.v1_launcher import launch_tool
        act = menu.addAction(label)

        def _on_trigger(_c=False, leaf=str(p)):  # noqa: ANN001
            launch_tool(leaf)
        act.triggered.connect(_on_trigger)
        if collector is not None:
            collector.append((
                f"{path_prefix}{label}" if path_prefix else label,
                label,
                f"{path_prefix}{label} {p.stem}".lower(),
                _on_trigger,
            ))
        return True

    menu.addAction(f"(unsupported: {p.suffix})").setEnabled(False)
    return False


# ---------------------------------------------------------------------------
# Live search (Windows/Mac-style flat filtering)
# ---------------------------------------------------------------------------

def _rank(query: str, name: str, search_text: str) -> int | None:
    """Match score, lower = better; ``None`` = no match.

    Ranks against the tool's *bare* name (not the breadcrumbed
    display), so typing ``a`` surfaces tools NAMED ``a*`` first —
    the Start-menu / Spotlight relevance order:

      0 = name starts with the query
      1 = query is a substring of the name
      2 = query matches only the folder breadcrumb / filename
          (``search_text``)
    """
    nl = name.lower()
    if nl.startswith(query):
        return 0
    if query in nl:
        return 1
    if query in search_text:
        return 2
    return None


def _install_live_search(menu: QMenu, leaves: list) -> QLineEdit:
    """Prepend a live-filter ``QLineEdit`` to ``menu`` and a flat
    pool of result actions.

    Empty box → the original nested submenu structure shows.
    Non-empty → the nested items hide and a ranked flat list of
    matching tools replaces them, refreshed on every keystroke.

    Returns the ``QLineEdit`` so the caller can focus it once the
    modal menu is up.

    Design notes (for maintainers / LLMs):
    * The result rows are a FIXED reusable pool (``QAction`` ×
      min(#leaves, _MAX_RESULTS)).  Each filter pass reassigns text
      + the bound trigger to the top matches and shows exactly that
      many — this gives ranked order without reordering QMenu
      actions (QMenu has no public reorder).
    * ``_current`` maps a pool action → its currently-bound leaf
      trigger; a single dispatcher connected once at creation reads
      it, so we never disconnect/reconnect per keystroke.
    * Structural actions (the nested menu built before this call)
      are snapshotted and toggled en masse — never destroyed — so
      clearing the box restores the exact original menu.
    """
    structural = list(menu.actions())

    # --- search field -------------------------------------------------
    edit = QLineEdit()
    edit.setPlaceholderText("Type to filter…")
    edit.setClearButtonEnabled(True)
    edit.setMinimumWidth(240)
    edit.setStyleSheet("QLineEdit { margin: 4px 6px; padding: 3px; }")
    wa = QWidgetAction(menu)
    wa.setDefaultWidget(edit)
    # Target order: [search] [sep] [structural…] [pool…] [overflow].
    if structural:
        first = structural[0]
        menu.insertAction(first, wa)       # → [wa, structural…]
        menu.insertSeparator(first)        # → [wa, sep, structural…]
    else:
        menu.addAction(wa)
        menu.addSeparator()

    # --- reusable flat result pool -----------------------------------
    pool_size = min(len(leaves), _MAX_RESULTS)
    pool: list[QAction] = []
    current: dict[QAction, object] = {}

    def _fire(act: QAction) -> None:
        fn = current.get(act)
        if callable(fn):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                _log(f"live-search launch failed: {exc!r}")

    for _ in range(pool_size):
        a = QAction(menu)
        a.setVisible(False)
        a.triggered.connect(lambda _c=False, _a=a: _fire(_a))
        menu.addAction(a)
        pool.append(a)

    overflow = menu.addAction("")
    overflow.setEnabled(False)
    overflow.setVisible(False)

    def _apply(text: str) -> None:
        q = text.strip().lower()
        if not q:
            for act in structural:
                act.setVisible(True)
            for a in pool:
                a.setVisible(False)
            overflow.setVisible(False)
            return
        # Query active: hide the nested structure, show ranked flat
        # matches in the reusable pool.
        for act in structural:
            act.setVisible(False)
        scored = []
        for display, name, search_text, trig in leaves:
            s = _rank(q, name, search_text)
            if s is not None:
                # Tie-break within a score tier by the bare name so
                # the order is stable + name-alphabetical.
                scored.append((s, name.lower(), display, trig))
        scored.sort(key=lambda t: (t[0], t[1]))
        shown = scored[:pool_size]
        for i, a in enumerate(pool):
            if i < len(shown):
                _, _, display, trig = shown[i]
                a.setText(display)
                current[a] = trig
                a.setVisible(True)
            else:
                a.setVisible(False)
        extra = len(scored) - len(shown)
        if extra > 0:
            overflow.setText(f"… {extra} more — keep typing")
            overflow.setVisible(True)
        else:
            overflow.setVisible(False)
        if not scored:
            overflow.setText("(no matches)")
            overflow.setVisible(True)

    edit.textChanged.connect(_apply)

    def _on_return() -> None:
        for a in pool:
            if a.isVisible():
                a.trigger()
                return
    edit.returnPressed.connect(_on_return)

    return edit


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def show_tree_popup_for(hex_win) -> None:  # noqa: ANN001 — CellWindow
    """Pop up a tree menu of the cell's catalog (or the master's
    merged catalog list).  Closes when the user picks an action or
    clicks elsewhere.

    Position: just below the hexagon, horizontally centred on it.
    Falls back to the cursor position if mapToGlobal fails.
    """
    role = getattr(hex_win, "role", "standalone")

    menu = QMenu(None)
    # Flat live-search index — every leaf across the whole (possibly
    # master-union) catalog as (display, search_text, trigger).
    leaves: list = []

    if role == "master":
        # ``_members`` is a ``dict[member_id, QPoint]`` per
        # CellWindow's data model — iterate keys, look each id up
        # in the registry to get the actual window, then read its
        # ``_catalog_path``.  Falling back to iterating the value
        # directly when _members is something else (lists, tuples)
        # keeps tests with synthetic data working.
        from scriptree.shell.cell_registry import CellRegistry

        members_dict = getattr(hex_win, "_members", None) or {}
        if isinstance(members_dict, dict):
            member_keys = list(members_dict.keys())
        else:
            member_keys = list(members_dict)

        if not member_keys:
            menu.addAction("(no members)").setEnabled(False)
        else:
            registry = CellRegistry.instance()
            populated_any = False
            for mk in member_keys:
                member = registry.get(mk) if isinstance(mk, str) else mk
                if member is None:
                    continue
                cp = getattr(member, "_catalog_path", None)
                if not cp:
                    sub = menu.addMenu(
                        f"Cell {getattr(member, '_id', '?')[:8]} "
                        f"(no catalog bound)"
                    )
                    sub.setEnabled(False)
                    continue
                src = Path(cp).resolve()
                top_label = src.stem
                # Try to read the .scriptreetree's display name for
                # nicer top-folder label.
                try:
                    if src.suffix.lower() == ".scriptreetree":
                        from scriptree.core.io import load_tree
                        top_label = load_tree(str(src)).name or src.stem
                    elif src.suffix.lower() == ".scriptree":
                        from scriptree.core.io import load_tool
                        top_label = load_tool(str(src)).name or src.stem
                except Exception:  # noqa: BLE001
                    pass
                sub = menu.addMenu(top_label)
                if _build_menu_for_catalog(
                    sub, src,
                    collector=leaves,
                    path_prefix=f"{top_label} / ",
                ):
                    populated_any = True
            if not populated_any:
                menu.addAction(
                    "(no member catalogs — right-click each cell to load one)"
                ).setEnabled(False)
    else:
        # Standalone cell.
        catalog_path = getattr(hex_win, "_catalog_path", None)
        if not catalog_path:
            menu.addAction("(no catalog loaded — right-click → Load…)").setEnabled(False)
        else:
            _build_menu_for_catalog(menu, catalog_path, collector=leaves)

    # ---- Live search bar (Windows/Mac-style flat filtering) --------
    # Only worth showing when there are at least a couple of tools to
    # sift through.  Typing collapses the nested submenu structure
    # into a flat, ranked result list that updates on every
    # keystroke; clearing the box restores the normal nested menu.
    search_edit = None
    if len(leaves) >= 2:
        search_edit = _install_live_search(menu, leaves)

    # Position: below-centre of the hex.
    try:
        global_pt = hex_win.mapToGlobal(
            QPoint(hex_win.width() // 2, hex_win.height())
        )
    except Exception:  # noqa: BLE001
        cursor_pos = QApplication.instance().primaryScreen().geometry().center()
        global_pt = cursor_pos

    # Stash the menu on the cell + record close time so click handlers
    # can implement second-click-toggle ("click cell again hides menu").
    # Without this, Qt's outside-click-dismisses-popup behaviour would
    # close the menu AND dispatch the click to the cell, which would
    # re-open the menu instantly. Giving the cell a "menu just closed"
    # window short-circuits the re-open.
    import time as _time
    hex_win._tree_popup_menu = menu
    def _on_about_to_hide(_h=hex_win, _now=_time.monotonic):
        try:
            _h._tree_popup_closed_at = _now()
            _h._tree_popup_menu = None
        except Exception:  # noqa: BLE001
            pass
    menu.aboutToHide.connect(_on_about_to_hide)

    # Focus the search field once the modal menu loop is running so
    # the user can type immediately (Spotlight/Start-menu feel).
    # QMenu forwards key events to a focused QWidgetAction widget;
    # the 0-ms timer defers until after exec() has shown the menu.
    if search_edit is not None:
        QTimer.singleShot(0, search_edit.setFocus)

    menu.exec(global_pt)
