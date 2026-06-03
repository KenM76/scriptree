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

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication, QLineEdit, QMenu, QStyle, QWidgetAction,
)


def _log(msg: str) -> None:
    print(f"[tree_popup] {msg}", file=sys.stderr)


# --- icons (v0.6.5) --------------------------------------------------------
#
# A tool/app row shows its catalog's configured ``cell`` icon; tools
# with none, and folder submenus, fall back to the OS-native standard
# file/folder icons so every row is iconned "like they should".

def _std_icon(which) -> QIcon:  # noqa: ANN001
    app = QApplication.instance()
    if app is None:
        return QIcon()
    return app.style().standardIcon(which)


def _file_icon() -> QIcon:
    return _std_icon(QStyle.StandardPixmap.SP_FileIcon)


def _folder_icon() -> QIcon:
    return _std_icon(QStyle.StandardPixmap.SP_DirIcon)


_BUNDLED_QICON_CACHE: dict[str, QIcon] = {}


def _bundled_qicon(icon_name: str) -> QIcon | None:
    """A ``QIcon`` for a shipped ``icons/`` glyph by name, cached.
    Returns ``None`` if the set or that glyph can't be located."""
    if icon_name in _BUNDLED_QICON_CACHE:
        return _BUNDLED_QICON_CACHE[icon_name]
    ic: QIcon | None = None
    try:
        from scriptree.shell.icon_assets import bundled_icon_png_path
        p = bundled_icon_png_path(icon_name)
        if p is not None:
            cand = QIcon(str(p))
            if not cand.isNull():
                ic = cand
    except Exception:  # noqa: BLE001
        ic = None
    _BUNDLED_QICON_CACHE[icon_name] = ic  # cache misses too
    return ic


def _node_icon(node) -> QIcon | None:  # noqa: ANN001
    """Resolve a per-``TreeNode`` icon override (v0.6.26+).

    Priority (only the first non-empty source wins):

      1. ``node.icon_data`` — base64-encoded PNG bytes; decoded into
         a ``QPixmap`` and wrapped as a ``QIcon``.
      2. ``node.icon`` — first tried as a bundled-icon name
         (``"build"`` → ``icons/icon-build.png``); on miss, treated
         as a file path relative or absolute.

    Returns ``None`` when the node has no override, the override is
    unresolvable, or anything in the resolution raises.  Callers
    that need a fallback (folder glyph, leaf-catalog icon) supply
    their own.

    Used by ``_add_node_to_menu`` for BOTH folder submenu icons and
    leaf override icons — same precedence rules, same fallback.
    """
    icon_data = getattr(node, "icon_data", "") or ""
    if icon_data:
        try:
            import base64
            from PySide6.QtGui import QPixmap
            raw = base64.b64decode(icon_data, validate=False)
            pm = QPixmap()
            if pm.loadFromData(raw):
                ic = QIcon(pm)
                if not ic.isNull():
                    return ic
        except Exception as exc:  # noqa: BLE001
            _log(f"_node_icon: icon_data decode failed: {exc!r}")

    name_or_path = getattr(node, "icon", "") or ""
    if name_or_path:
        # First try as a bundled glyph name.
        try:
            bundled = _bundled_qicon(name_or_path)
            if bundled is not None and not bundled.isNull():
                return bundled
        except Exception:  # noqa: BLE001
            pass
        # Otherwise treat as a path.
        try:
            p = Path(name_or_path)
            if p.is_file():
                cand = QIcon(str(p))
                if not cand.isNull():
                    return cand
        except Exception:  # noqa: BLE001
            pass

    return None


def _catalog_icon(path, label: str = "") -> QIcon:  # noqa: ANN001
    """The catalog's own icon; failing that, a category glyph chosen
    by keyword from the tool's name/filename (v0.6.9 — variety, so a
    menu isn't a wall of identical generic rows); failing *that*, the
    OS file icon so a row is never bare."""
    try:
        from scriptree.core.cell_metadata import qicon_for_catalog
        ic = qicon_for_catalog(path)
        if ic is not None and not ic.isNull():
            return ic
    except Exception:  # noqa: BLE001
        pass
    # No embedded/linked icon — classify by name for variety.
    try:
        from scriptree.shell.icon_assets import classify_icon
        stem = Path(path).stem if path else ""
        guess = classify_icon(name=label, filename=stem)
        bundled = _bundled_qicon(guess)
        if bundled is not None:
            return bundled
    except Exception:  # noqa: BLE001
        pass
    return _file_icon()


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
    root_catalog: Path | None = None,
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
        # v0.6.26+ — honour a per-node icon override, falling back
        # to the OS folder icon when the node carries no glyph.
        folder_override = _node_icon(node)
        sub.setIcon(folder_override if folder_override is not None else _folder_icon())
        # ASCII '/' breadcrumb (not a unicode arrow): this string can
        # reach cp1252 logs / serialisation, and this codebase has
        # been bitten by mojibake before — keep it 7-bit.
        child_prefix = f"{path_prefix}{label} / "
        for child in node.children:
            _add_node_to_menu(
                sub, child, source_dir,
                collector=collector, path_prefix=child_prefix,
                root_catalog=root_catalog,
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
    # v0.6.26+ — honour a per-node icon override; otherwise use the
    # leaf catalog's own icon (or a classified fallback).
    leaf_override = _node_icon(node)
    leaf_icon = leaf_override if leaf_override is not None else _catalog_icon(p, label)
    act.setIcon(leaf_icon)
    # Capture p, cfg in default args so the closure doesn't bind to
    # the loop variable.
    def _on_trigger(_checked=False, leaf=str(p), config=cfg):  # noqa: ANN001
        try:
            launch_tool(leaf, configuration=config)
        except Exception as exc:  # noqa: BLE001
            _log(f"launch_tool({leaf!r}) failed: {exc!r}")
    act.triggered.connect(_on_trigger)
    # v0.8.0a28 -- stash per-item context so the popup's
    # right-click event filter can offer "Uninstall app...",
    # "Open containing folder", etc. without having to walk
    # back through the source dir to find the catalog.  See
    # ``_install_per_item_context`` below.
    try:
        act._st_context = {  # type: ignore[attr-defined]
            "leaf_path": str(p),
            "root_catalog_path": (
                str(root_catalog) if root_catalog is not None
                else str(p)
            ),
            "node_name": getattr(node, "name", "") or "",
            "node_display_name": (
                getattr(node, "display_name", "") or ""
            ),
        }
    except Exception:  # noqa: BLE001
        pass
    if collector is not None:
        # 5-tuple: (display = breadcrumbed label for the result row,
        # name = the bare leaf label that ranking prefixes against,
        # search_text = full lowercased haystack incl. folder path +
        # filename for the weakest "matches anywhere" tier, trigger,
        # icon = the leaf's QIcon so flat results stay iconned).
        # Ranking on the bare name (not the breadcrumbed display) is
        # what makes typing "a" surface tools NAMED a*, like the
        # Start menu / Spotlight.
        search_text = f"{path_prefix}{label} {p.stem}".lower()
        collector.append((
            f"{path_prefix}{label}" if path_prefix else label,
            label,
            search_text,
            _on_trigger,
            leaf_icon,
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
                root_catalog=p,
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
        leaf_icon = _catalog_icon(p, label)
        act.setIcon(leaf_icon)

        def _on_trigger(_c=False, leaf=str(p)):  # noqa: ANN001
            launch_tool(leaf)
        act.triggered.connect(_on_trigger)
        # v0.8.0a28 -- per-item context for the right-click handler.
        # Single-tool catalogs are their own root; the leaf IS the
        # catalog file.
        try:
            act._st_context = {  # type: ignore[attr-defined]
                "leaf_path": str(p),
                "root_catalog_path": str(p),
                "node_name": label,
                "node_display_name": label,
            }
        except Exception:  # noqa: BLE001
            pass
        if collector is not None:
            collector.append((
                f"{path_prefix}{label}" if path_prefix else label,
                label,
                f"{path_prefix}{label} {p.stem}".lower(),
                _on_trigger,
                leaf_icon,
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


def _compute_menu_font_and_icon():  # noqa: ANN202
    """Resolve the menu font (as a QFont) and icon-size in pixels
    from the live menu-appearance settings.  Returns
    ``(QFont | None, int | None)`` — None means "leave alone."

    Pulled out as a helper so ``apply_menu_appearance`` and its
    recursive form share the same resolution + computation logic.
    """
    try:
        from scriptree.shell.menu_appearance import load_menu_appearance
        from scriptree.shell.branding_loader import load_branding
        ma = load_menu_appearance(load_branding())
    except Exception as exc:  # noqa: BLE001
        _log(f"_compute_menu_font_and_icon: resolve failed: {exc!r}")
        return (None, None)

    # Font.
    qfont = None
    try:
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication
        # Start from the application's default *menu* font so we
        # apply a known baseline — using QMenu().font() picks up
        # whatever the platform stylesheet has set, which for some
        # Win11 styles is already non-default and led to the
        # submenu-inheritance bug.
        app = QApplication.instance()
        base = QFont(app.font("QMenu")) if app is not None else QFont()
        if ma.font_pt is not None and ma.font_pt > 0:
            base.setPointSize(int(ma.font_pt))
        else:
            base_pt = base.pointSizeF()
            if base_pt <= 0:
                base_px = base.pixelSize()
                if base_px > 0:
                    base.setPixelSize(
                        max(6, int(base_px * (ma.font_pct / 100.0)))
                    )
            else:
                base.setPointSizeF(base_pt * (ma.font_pct / 100.0))
        qfont = base
    except Exception as exc:  # noqa: BLE001
        _log(f"_compute_menu_font_and_icon: font compute failed: {exc!r}")

    # Icon size.
    icon_px = None
    try:
        from PySide6.QtWidgets import QApplication, QStyle
        app = QApplication.instance()
        base_px = 16
        if app is not None:
            try:
                base_px = app.style().pixelMetric(
                    QStyle.PixelMetric.PM_SmallIconSize,
                )
            except Exception:  # noqa: BLE001
                pass
        icon_px = max(8, int(base_px * (ma.icon_pct / 100.0)))
    except Exception as exc:  # noqa: BLE001
        _log(f"_compute_menu_font_and_icon: icon compute failed: {exc!r}")

    return (qfont, icon_px)


def apply_menu_appearance(menu: QMenu) -> None:
    """v0.6.21 — scale this menu's font + icon size from the
    user-configured menu-appearance settings (cell Settings →
    Shape & Size tab → "Menu font & icon scale").  Defaults: 125%
    font, 125% icon; settable per-local and per-shared
    (machine-wide).

    v0.6.22 — walks INTO every submenu recursively so the scale
    propagates to ``addMenu``-created child menus.  Qt's font
    inheritance through addMenu doesn't reliably carry to child
    QMenus on Win11, hence the explicit recursion.  Idempotent —
    safe to call after the build (recommended) or both before and
    after.

    Falls back silently to Qt's stock appearance if anything in
    the resolution chain raises.
    """
    qfont, icon_px = _compute_menu_font_and_icon()
    _apply_menu_appearance_recursive(menu, qfont, icon_px)


def _apply_menu_appearance_recursive(  # noqa: ANN001
    menu: QMenu, qfont, icon_px,
) -> None:
    """Apply the precomputed font + icon-size to ``menu`` and
    recurse into every submenu reachable from it.  Called by
    ``apply_menu_appearance``; kept private so callers don't have
    to pre-compute the values."""
    if qfont is not None:
        try:
            menu.setFont(qfont)
        except Exception as exc:  # noqa: BLE001
            _log(f"_apply_menu_appearance_recursive: setFont: {exc!r}")
    if icon_px is not None:
        try:
            menu.setStyleSheet(
                f"QMenu {{ icon-size: {icon_px}px; }}"
            )
        except Exception as exc:  # noqa: BLE001
            _log(f"_apply_menu_appearance_recursive: setStyleSheet: {exc!r}")
    # Recurse into submenus.  Walk actions; an action whose menu()
    # is non-None is a submenu trigger.  Belt-and-suspenders also
    # force-set the font on each action so per-action overrides
    # (e.g. the bold header _make_header_action sets) don't lose
    # the size scale.
    try:
        for act in menu.actions():
            sub = act.menu()
            if sub is not None and sub is not menu:
                _apply_menu_appearance_recursive(sub, qfont, icon_px)
            elif qfont is not None:
                # Preserve weight/italic the action may have set,
                # but adopt the menu's point size.  This is what
                # was missing for submenu actions and for the bold
                # header on the popup.
                try:
                    act_font = act.font()
                    if qfont.pointSizeF() > 0:
                        act_font.setPointSizeF(qfont.pointSizeF())
                    else:
                        act_font.setPixelSize(qfont.pixelSize())
                    act.setFont(act_font)
                except Exception:  # noqa: BLE001
                    pass
    except Exception as exc:  # noqa: BLE001
        _log(f"_apply_menu_appearance_recursive: submenu walk: {exc!r}")


def _make_header_action(  # noqa: ANN001
    menu: QMenu, text: str, hex_win=None,
) -> "QWidgetAction":
    """A bold header row naming what this popup is for (the
    catalog / forest / ring) — sits ABOVE the live-search field
    and is never hidden by filtering (it's chrome, not a
    structural item).

    v0.6.24 — also carries two tool-buttons in the top-right
    corner:

      * ``□`` opens the full editor view loaded with whatever this
        popup is showing.  Standalone cell → editor on the bound
        catalog; ring / forest → editor on the merged tree (every
        member's catalog as a top-level folder).
      * ``✕`` closes the popup (same as clicking outside it).

    ``hex_win`` is the cell that owns the popup; when ``None`` the
    expand button is hidden (caller didn't pass enough context to
    open the editor).
    """
    from PySide6.QtWidgets import (
        QHBoxLayout, QLabel, QToolButton, QWidget, QWidgetAction,
    )

    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(8, 4, 4, 4)
    h.setSpacing(6)

    # Title label.
    lbl = QLabel(text)
    f = lbl.font()
    f.setBold(True)
    lbl.setFont(f)
    lbl.setSizePolicy(
        lbl.sizePolicy().horizontalPolicy(),
        lbl.sizePolicy().verticalPolicy(),
    )
    h.addWidget(lbl, stretch=1)

    # Open-in-editor button (□).
    if hex_win is not None:
        open_btn = QToolButton()
        open_btn.setText("□")  # WHITE SQUARE — "open in editor"
        open_btn.setToolTip(
            "Open in the full editor view (same as a double-left "
            "click on the cell)"
        )
        open_btn.setAutoRaise(True)
        # Slightly bump the font size so the glyph is visible.
        of = open_btn.font()
        of.setPointSizeF(max(of.pointSizeF(), 11.0))
        open_btn.setFont(of)

        def _on_open_clicked(_checked=False, h_w=hex_win, m=menu):
            try:
                m.hide()
            except Exception:  # noqa: BLE001
                pass
            try:
                _open_full_editor_for(h_w)
            except Exception as exc:  # noqa: BLE001
                _log(f"_make_header_action: open failed: {exc!r}")
        open_btn.clicked.connect(_on_open_clicked)
        h.addWidget(open_btn)

    # Close-popup button (✕).
    close_btn = QToolButton()
    close_btn.setText("✕")  # MULTIPLICATION X
    close_btn.setToolTip("Close this popup")
    close_btn.setAutoRaise(True)
    cf = close_btn.font()
    cf.setPointSizeF(max(cf.pointSizeF(), 11.0))
    close_btn.setFont(cf)

    def _on_close_clicked(_checked=False, m=menu):
        try:
            m.hide()
        except Exception:  # noqa: BLE001
            pass
    close_btn.clicked.connect(_on_close_clicked)
    h.addWidget(close_btn)

    hdr = QWidgetAction(menu)
    hdr.setDefaultWidget(w)
    return hdr


def _open_full_editor_for(hex_win) -> None:  # noqa: ANN001
    """Open the full editor view loaded with what ``hex_win``
    represents.  Dispatches by role:

      * Standalone → ``v1_launcher.show_tree_for(hex_win,
        mode="lock-open")`` — loads the bound catalog (a
        .scriptree → standalone runner; a .scriptreetree → editor
        with the tree).  Blank editor when no catalog bound.
      * Master (ring or forest) → build a merged .scriptreetree
        from every member's catalog and open the editor on it.

    The "V1" in ``v1_launcher`` is a historical module name from
    when the editor and the shell were separate codebases — both
    are now one product, so the function is just "open the full
    editor."
    """
    role = getattr(hex_win, "role", "standalone")
    if role == "master":
        # Build merged temp tree from every member's catalog and
        # open the editor on it.  ``build_merged_tree_for_master``
        # already walks the master's members and resolves their
        # catalog paths, so we can just hand it the master.
        from scriptree.shell.merged_tree import build_merged_tree_for_master
        from scriptree.shell.v1_launcher import (
            launch_editor_blank, launch_editor_with_tree,
        )
        try:
            merged = build_merged_tree_for_master(hex_win)
        except Exception as exc:  # noqa: BLE001
            _log(f"_open_full_editor_for master: merged build raised {exc!r}")
            launch_editor_blank()
            return
        if merged is None:
            launch_editor_blank()
        else:
            launch_editor_with_tree(merged)
        return

    # Standalone (or any non-master role) — defer to the existing
    # lock-open helper which routes by catalog suffix.
    from scriptree.shell.v1_launcher import show_tree_for
    show_tree_for(hex_win, mode="lock-open")


def _install_live_search(  # noqa: ANN001
    menu: QMenu, leaves: list, header_text: str = "", hex_win=None,
) -> "QLineEdit | None":
    """Prepend a bold header label, then (when there are ≥2 tools)
    a live-filter ``QLineEdit`` + flat result pool, to ``menu``.

    Empty box → the original nested submenu structure shows.
    Non-empty → the nested items hide and a ranked flat list of
    matching tools replaces them, refreshed on every keystroke.

    The header is added even when there's no search field, so a
    1-tool / no-catalog popup is still titled.

    Returns the ``QLineEdit`` (or ``None`` when no search field was
    added) so the caller can focus it once the modal menu is up.

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
    structural = list(menu.actions())  # real items only (pre-chrome)
    first = structural[0] if structural else None

    # --- header (always) ---------------------------------------------
    hdr = _make_header_action(menu, header_text or "ScripTree", hex_win)

    has_search = len(leaves) >= 2
    edit = None
    if has_search:
        edit = QLineEdit()
        edit.setPlaceholderText("Type to filter…")
        edit.setClearButtonEnabled(True)
        edit.setMinimumWidth(240)
        edit.setStyleSheet(
            "QLineEdit { margin: 4px 6px; padding: 3px; }"
        )
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(edit)

    # Target order: [header] [search] [sep] [structural…] [pool…].
    # Each insertAction(first, X) puts X immediately before the
    # original first item, so issuing them in order preserves it.
    if first is not None:
        menu.insertAction(first, hdr)
        if has_search:
            menu.insertAction(first, wa)
        menu.insertSeparator(first)
    else:
        menu.addAction(hdr)
        if has_search:
            menu.addAction(wa)
        menu.addSeparator()

    if not has_search:
        return None

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
        for display, name, search_text, trig, icon in leaves:
            s = _rank(q, name, search_text)
            if s is not None:
                # Tie-break within a score tier by the bare name so
                # the order is stable + name-alphabetical.
                scored.append((s, name.lower(), display, trig, icon))
        scored.sort(key=lambda t: (t[0], t[1]))
        shown = scored[:pool_size]
        for i, a in enumerate(pool):
            if i < len(shown):
                _, _, display, trig, icon = shown[i]
                a.setText(display)
                a.setIcon(icon if icon is not None else QIcon())
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


def _populate_menu_from_member(
    parent_menu,  # noqa: ANN001 — QMenu
    member,  # noqa: ANN001 — CellWindow
    leaves: list,
    registry,  # noqa: ANN001 — CellRegistry instance
    _depth: int = 0,
) -> bool:
    """v0.8.0a1+ramps Bug 9 — add ``member``'s contribution to
    ``parent_menu``.  Returns True iff anything was actually added.

    Branches:

    * ``member`` is itself a master (a nested ring inside the forest,
      or — in future — a nested ring inside a ring): add a sub-menu
      titled with ``_popup_header_text(member)`` (so it picks up the
      Bug 8 auto-name or the saved file name), then RECURSE into its
      members.  Always returns True for masters even when the ring is
      empty, so a brand-new ring shows up on the forest menu and the
      user can see it exists.  Empty rings get a single disabled
      "(empty)" hint inside their sub-menu.
    * ``member`` is a standalone cell with no catalog: skip silently
      (per Bug 8 — empty cells shouldn't clutter the menu).
    * ``member`` is a standalone cell with a catalog: add the
      catalog's contents as a sub-menu, exactly as the legacy code
      did.

    Cycle guard: ``_depth`` caps recursion at 8 to avoid runaway in
    case the link graph ever forms a cycle (the audit module is
    supposed to prevent this, but we don't want to hang the menu if
    the audit failed silently).
    """
    if _depth > 8:
        return False
    role = getattr(member, "role", "")
    if role == "master":
        label = _popup_header_text(member)
        sub = parent_menu.addMenu(label)
        # Sub-menu icon: use bundled ring/forest glyph if available,
        # else fall back to a generic folder.
        try:
            is_forest = bool(getattr(member, "_is_forest_master", False))
            glyph_name = "forest" if is_forest else "ring"
            icon = _bundled_qicon(glyph_name)
            if icon is not None:
                sub.setIcon(icon)
        except Exception:  # noqa: BLE001
            pass
        # Recurse into the master's own members.
        inner_dict = getattr(member, "_members", None) or {}
        if isinstance(inner_dict, dict):
            inner_keys = list(inner_dict.keys())
        else:
            inner_keys = list(inner_dict)
        inner_populated = False
        for ik in inner_keys:
            inner_member = registry.get(ik) if isinstance(ik, str) else ik
            if inner_member is None:
                continue
            if _populate_menu_from_member(
                sub, inner_member, leaves, registry, _depth + 1,
            ):
                inner_populated = True
        if not inner_populated:
            sub.addAction("(empty)").setEnabled(False)
        # We added the master's sub-menu; the user can SEE the ring
        # in the parent menu even when it's empty.  That's the point
        # of Bug 9: "the newly formed tree ring now doesn't show up
        # on the forest menu at all (it should)."
        return True

    # Standalone (or unknown) cell — populate from its catalog.
    cp = getattr(member, "_catalog_path", None)
    if not cp:
        # Per Bug 8: skip empty cells silently.
        return False
    src = Path(cp).resolve()
    top_label = src.stem
    try:
        if src.suffix.lower() == ".scriptreetree":
            from scriptree.core.io import load_tree
            top_label = load_tree(str(src)).name or src.stem
        elif src.suffix.lower() == ".scriptree":
            from scriptree.core.io import load_tool
            top_label = load_tool(str(src)).name or src.stem
    except Exception:  # noqa: BLE001
        pass
    sub = parent_menu.addMenu(top_label)
    sub.setIcon(_catalog_icon(src))
    if _build_menu_for_catalog(
        sub, src,
        collector=leaves,
        path_prefix=f"{top_label} / ",
    ):
        return True
    return False


def _popup_header_text(hex_win) -> str:  # noqa: ANN001
    """A human title for the popup header: the bound catalog's name,
    else the user's text label, else a role-based default
    (Forest / Tree Ring / ScripTree)."""
    role = getattr(hex_win, "role", "standalone")
    # Real CellWindows store this as ``_is_forest_master``; synthetic
    # test doubles may use the un-prefixed name — accept either.
    is_forest = bool(
        getattr(hex_win, "_is_forest_master", None)
        if getattr(hex_win, "_is_forest_master", None) is not None
        else getattr(hex_win, "is_forest_master", False)
    )
    base = (
        "Forest" if is_forest
        else "Tree Ring" if role == "master"
        else "ScripTree"
    )
    cp = getattr(hex_win, "_catalog_path", None)
    if cp:
        try:
            p = Path(cp)
            if p.suffix.lower() == ".scriptreetree":
                from scriptree.core.io import load_tree
                return load_tree(str(p)).name or p.stem
            if p.suffix.lower() == ".scriptree":
                from scriptree.core.io import load_tool
                return load_tool(str(p)).name or p.stem
            return p.stem
        except Exception:  # noqa: BLE001
            pass
    tl = getattr(hex_win, "_text_label", None)
    if tl:
        return str(tl)
    # v0.8.0a1+ramps Bug 8 — ring masters get an auto-name like
    # "Ring 3" so the menu / tooltip header shows something
    # distinguishable instead of the generic "Tree Ring" base.  The
    # forest never gets an auto serial (it's a singleton, "Forest"
    # is meaningful by itself).
    auto = getattr(hex_win, "_auto_ring_name", None)
    if auto and not is_forest:
        return str(auto)
    return base


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_tree_popup_menu(hex_win) -> QMenu:  # noqa: ANN001 — CellWindow
    """Build (but do not show) the tree-popup ``QMenu`` for ``hex_win``.

    Factored out of :func:`show_tree_popup_for` so the menu can be
    captured by ``screenshooter.py`` (which never calls
    ``widget.show()``).  The returned menu has its header label,
    catalog items, search bar, and (for masters) nested-ring
    sub-menus all attached.  Caller is responsible for ``exec()``-ing
    or ``popup()``-ing the menu — or for ``grab()``-bing it for a
    PNG capture.

    The implementation mirrors ``show_tree_popup_for`` exactly up to
    the show step; ``show_tree_popup_for`` calls this and then
    positions / pops up.
    """
    role = getattr(hex_win, "role", "standalone")

    menu = QMenu(None)
    # v0.6.23 — bring the popup above any always-on-top cell
    # widgets that surround the master.  Without this, a forest
    # whose ring is expanded had its popup stacked UNDERNEATH the
    # member cells (cells are Qt.Tool + Qt.WindowStaysOnTopHint;
    # QMenu's default Qt.Popup doesn't outrank them on Win11
    # composition).  Result: "double-clicking the forest when the
    # other cells are slid out doesn't bring up the menu" —
    # actually the menu DID open, you just couldn't see it.
    # Setting StaysOnTop on the menu's window puts it above the
    # cells while the popup is active; closes naturally on outside
    # click as before.
    try:
        menu.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    except Exception:  # noqa: BLE001
        pass
    # v0.6.21 — pull the user-configured font/icon scale before
    # adding items so the QFont propagates from the menu to every
    # action and the icon-size stylesheet is in place at paint time.
    apply_menu_appearance(menu)
    # Flat live-search index — every leaf across the whole (possibly
    # master-union) catalog as (display, search_text, trigger).
    leaves: list = []

    if role == "master":
        from scriptree.shell.cell_registry import CellRegistry
        registry = CellRegistry.instance()

        members_dict = getattr(hex_win, "_members", None) or {}
        if isinstance(members_dict, dict):
            member_keys = list(members_dict.keys())
        else:
            member_keys = list(members_dict)

        if not member_keys:
            menu.addAction("(no members)").setEnabled(False)
        else:
            populated_any = False
            for mk in member_keys:
                member = registry.get(mk) if isinstance(mk, str) else mk
                if member is None:
                    continue
                if _populate_menu_from_member(
                    menu, member, leaves, registry,
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

    # ---- Header label + live search bar ----------------------------
    # The bold header (the catalog / forest / ring name) is ALWAYS
    # added — it's the title that was lost when the search bar
    # arrived.  The live filter is added on top of it only when
    # there are ≥2 tools to sift; both are chrome, never hidden by
    # filtering.
    search_edit = _install_live_search(
        menu, leaves,
        header_text=_popup_header_text(hex_win),
        hex_win=hex_win,
    )

    # v0.6.22 — re-apply the menu-appearance scale AFTER the menu
    # is fully built so submenus added by _add_node_to_menu /
    # _build_menu_for_catalog get the same font + icon size.
    # The pre-build call (early in this function) only catches the
    # top level + the live-search QWidgetAction; the recursive
    # walk here covers every submenu added by the builders above.
    try:
        apply_menu_appearance(menu)
    except Exception as exc:  # noqa: BLE001
        _log(f"build_tree_popup_menu: re-apply after build failed: {exc!r}")

    # Stash a reference to the search edit on the menu so callers
    # that show the menu can focus it after exec() begins.
    menu._search_edit = search_edit  # type: ignore[attr-defined]
    return menu


# ---------------------------------------------------------------------------
# Per-item right-click context menu
# ---------------------------------------------------------------------------
#
# v0.8.0a28+ -- each leaf QAction added to the popup tree menu gets
# a dict stashed on it under ``_st_context`` (see ``_add_node_to_menu``
# and the single-tool branch of ``_build_menu_for_catalog``).  When
# the user RIGHT-clicks an action, the event filter below opens a
# small per-item context menu so the user can do per-item things --
# starting with "Uninstall app..." but designed as the extension
# point for any future per-tool setting (open containing folder,
# hide from menu, edit in V1, etc.).
#
# The filter is installed on every QMenu in the popup tree (the top
# menu plus every submenu) -- Qt routes mouse events to the menu
# under the cursor, NOT the top-level menu, so we need filters on
# all of them.  The recursive install happens in
# ``_install_per_item_context``; for submenus opened lazily by Qt
# we ALSO install via ``aboutToShow`` so freshly-opened submenus
# pick up the filter too.

class _PerItemContextFilter(QObject):
    """QObject event filter that intercepts right-clicks on actions
    inside a QMenu and dispatches to a per-item context menu.

    Parameters (constructor)
    ------------------------
    hex_win:
        The cell window that owns the popup.  Used to reach the
        forest controller via the standard
        ``hex_win._forest_menu_extension.__self__`` walk -- same
        pattern as ``_post_install_refresh_forest``.

    Why an event filter and not ``customContextMenuRequested``?
    Qt's QMenu doesn't fire ``customContextMenuRequested`` on
    actions; the signal is only emitted on the menu's empty area.
    The mouse-button-press event filter is the documented way to
    catch right-clicks on actions.
    """

    def __init__(self, hex_win) -> None:  # noqa: ANN001 -- CellWindow
        super().__init__()
        self._hex_win = hex_win

    def eventFilter(self, obj, event) -> bool:  # noqa: ANN001
        if not isinstance(obj, QMenu):
            return False
        et = event.type()
        # ContextMenu is what Qt synthesises for right-click presses
        # on menus on Windows; MouseButtonPress with RightButton is
        # the cross-platform fallback we also accept.
        is_context = (
            et == QEvent.Type.ContextMenu
            or (
                et == QEvent.Type.MouseButtonPress
                and getattr(event, "button", lambda: None)()
                == Qt.MouseButton.RightButton
            )
        )
        if not is_context:
            return False
        try:
            act = obj.actionAt(event.pos())
        except Exception:  # noqa: BLE001
            act = None
        if act is None:
            return False
        ctx = getattr(act, "_st_context", None)
        if not ctx:
            return False
        # Compose the globally-positioned point for the context
        # menu.  ``globalPos`` is available on both events.
        try:
            global_pt = event.globalPos()
        except Exception:  # noqa: BLE001
            try:
                global_pt = event.globalPosition().toPoint()
            except Exception:  # noqa: BLE001
                global_pt = QPoint(0, 0)
        # Close the host menu before showing the context one so the
        # context menu is visually on top and doesn't fight with
        # the host's keyboard / focus state.  We collect the root
        # menu (the highest ancestor) and close it.
        try:
            root = obj
            while True:
                parent_menu = root.parent()
                if isinstance(parent_menu, QMenu):
                    root = parent_menu
                else:
                    break
            root.close()
        except Exception:  # noqa: BLE001
            pass
        self._show_for_action(ctx, global_pt)
        return True

    # ---- per-item context menu construction ------------------

    def _show_for_action(self, ctx: dict, global_pt: QPoint) -> None:
        """Build + exec the per-item context menu.

        Designed so adding a new entry is a single ``menu.addAction``
        + slot binding.  Each entry runs against the leaf's
        ``ctx`` dict so they're independent of menu position or
        which cell originated the popup.
        """
        menu = QMenu()
        # Header showing which tool / catalog the context is for.
        # Disabled action so it acts as a label.
        label = (
            ctx.get("node_display_name")
            or ctx.get("node_name")
            or Path(ctx.get("leaf_path", "")).stem
            or "(item)"
        )
        hdr = menu.addAction(label)
        hdr.setEnabled(False)
        menu.addSeparator()

        # --- Open containing folder ---
        a_open = menu.addAction("Open containing folder")
        a_open.setIcon(
            QApplication.style().standardIcon(
                QStyle.StandardPixmap.SP_DirOpenIcon
            )
        )
        a_open.triggered.connect(
            lambda _c=False, p=ctx.get("leaf_path", ""):
            self._on_open_folder(p)
        )

        # --- Uninstall app (when the root catalog lives under
        # an install root). ---
        root_cat = ctx.get("root_catalog_path") or ""
        if root_cat and self._catalog_is_uninstallable(root_cat):
            menu.addSeparator()
            a_uninstall = menu.addAction("Uninstall app from disk...")
            a_uninstall.setIcon(
                QApplication.style().standardIcon(
                    QStyle.StandardPixmap.SP_TrashIcon
                )
            )
            a_uninstall.triggered.connect(
                lambda _c=False, p=root_cat:
                self._on_uninstall_by_path(p)
            )
        menu.exec(global_pt)

    # ---- handlers --------------------------------------------

    def _on_open_folder(self, leaf_path: str) -> None:
        """Open the leaf's containing folder in the OS file manager.

        Uses ``QDesktopServices.openUrl`` so the same code path
        works on Windows / macOS / Linux without per-platform
        ``subprocess.Popen`` branches.
        """
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            folder = Path(leaf_path).parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        except Exception as exc:  # noqa: BLE001
            _log(f"_on_open_folder({leaf_path!r}) failed: {exc!r}")

    def _catalog_is_uninstallable(self, catalog_path: str) -> bool:
        """True iff ``catalog_path`` lives under one of the install
        roots AND its parent is not the root itself.

        Mirrors the containment check in
        ``ForestController.uninstall_app`` -- we don't want to
        offer the action when the controller would refuse it.
        """
        try:
            from scriptree.core.app_install import (
                default_personal_root, default_shared_root,
            )
            parent = Path(catalog_path).resolve().parent
            roots = []
            for fn in (default_personal_root, default_shared_root):
                try:
                    roots.append(Path(fn()).resolve())
                except Exception:  # noqa: BLE001
                    continue
            for root in roots:
                try:
                    rel = parent.relative_to(root)
                except ValueError:
                    continue
                # Refuse to show when parent == root (the catalog
                # was dropped directly in the install root, which
                # is unusual and would mean uninstalling the root).
                if len(rel.parts) >= 1:
                    return True
            return False
        except Exception:  # noqa: BLE001
            return False

    def _on_uninstall_by_path(self, catalog_path: str) -> None:
        """Dispatch to the forest controller's existing uninstall
        flow, passing the catalog path directly.

        Reaches the controller via the standard
        ``_forest_menu_extension.__self__`` walk; bails silently
        when no controller is wired up (e.g. standalone-cell mode).
        """
        try:
            hook = getattr(
                self._hex_win, "_forest_menu_extension", None,
            )
            controller = getattr(hook, "__self__", None) if hook else None
            if controller is None:
                _log(
                    "uninstall requested but no forest controller "
                    "is attached to this cell -- skipping"
                )
                return
            handler = getattr(controller, "_on_uninstall_app", None)
            if not callable(handler):
                return
            handler(catalog_path)
        except Exception as exc:  # noqa: BLE001
            _log(f"_on_uninstall_by_path failed: {exc!r}")


def _install_per_item_context(menu: QMenu, hex_win) -> None:  # noqa: ANN001
    """Recursively install ``_PerItemContextFilter`` on ``menu`` and
    every submenu it currently contains.

    Newly-shown submenus get the filter via ``aboutToShow`` so the
    handler is in place by the time the user's first right-click
    fires inside the submenu.

    Idempotent: re-installing on a menu that already has a filter
    is harmless (Qt deduplicates installed filter targets per
    ``installEventFilter`` call -- the user is responsible for not
    calling this twice, but we guard with a sentinel attribute).
    """
    sentinel = "_st_per_item_filter_installed"
    if getattr(menu, sentinel, False):
        return
    flt = _PerItemContextFilter(hex_win)
    # Parent the filter to the menu so it dies with the popup --
    # no lingering QObjects to leak between popup invocations.
    flt.setParent(menu)
    menu.installEventFilter(flt)
    setattr(menu, sentinel, True)
    # Stash the filter on the menu so the parent walk can find it
    # if needed; not strictly required for the filter to fire.
    menu._st_per_item_filter = flt  # type: ignore[attr-defined]

    # Recurse into current submenus.
    for act in menu.actions():
        sub = act.menu()
        if sub is not None:
            _install_per_item_context(sub, hex_win)

    # Catch submenus opened lazily later (Qt builds them eagerly
    # in our case, but the aboutToShow hook is cheap insurance
    # against future lazy-population changes).
    try:
        menu.aboutToShow.connect(
            lambda m=menu, h=hex_win: _install_per_item_context(m, h)
        )
    except Exception:  # noqa: BLE001
        pass


def show_tree_popup_for(hex_win) -> None:  # noqa: ANN001 — CellWindow
    """Pop up a tree menu of the cell's catalog (or the master's
    merged catalog list).  Closes when the user picks an action or
    clicks elsewhere.

    Position: just below the hexagon, horizontally centred on it.
    Falls back to the cursor position if mapToGlobal fails.
    """
    menu = build_tree_popup_menu(hex_win)
    # v0.8.0a28+ -- right-click on any item brings up a per-item
    # context menu (Uninstall app..., Open containing folder, and
    # whatever per-tool settings we add later).  See
    # ``_install_per_item_context`` for the recursive install
    # rules + filter logic.
    try:
        _install_per_item_context(menu, hex_win)
    except Exception as exc:  # noqa: BLE001
        _log(f"per-item context install failed: {exc!r}")

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
    search_edit = getattr(menu, "_search_edit", None)
    if search_edit is not None:
        QTimer.singleShot(0, search_edit.setFocus)

    menu.exec(global_pt)
