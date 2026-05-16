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

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QMenu


def _log(msg: str) -> None:
    print(f"[tree_popup] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Menu builder
# ---------------------------------------------------------------------------

def _add_node_to_menu(menu: QMenu, node, source_dir: Path) -> None:  # noqa: ANN001
    """Recursively walk a V1 ``TreeNode`` into a QMenu hierarchy.

    Folder nodes become submenus; leaf nodes become actions whose
    triggered() signal launches the V1 standalone runner with the
    leaf's resolved absolute path.

    Label resolution (matches V1's tree view):
      1. ``display_name`` if non-empty
      2. ``name`` if non-empty
      3. for leaves only: file stem of the leaf's path
      4. ``"(unnamed)"`` last resort
    """
    from scriptree.shell.v1_launcher import launch_tool

    if node.type == "folder":
        label = node.display_name or node.name or "(unnamed)"
        sub = menu.addMenu(label)
        for child in node.children:
            _add_node_to_menu(sub, child, source_dir)
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


def _build_menu_for_catalog(menu: QMenu, catalog_path: str | Path) -> bool:
    """Populate ``menu`` from one catalog file.  Returns True iff at
    least one item was added."""
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
            _add_node_to_menu(menu, node, p.parent)
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
        act.triggered.connect(lambda _c=False, leaf=str(p): launch_tool(leaf))
        return True

    menu.addAction(f"(unsupported: {p.suffix})").setEnabled(False)
    return False


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
                if _build_menu_for_catalog(sub, src):
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
            _build_menu_for_catalog(menu, catalog_path)

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

    menu.exec(global_pt)
