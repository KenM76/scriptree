#!/usr/bin/env python3
"""ScripTree headless screenshot tool.

Renders ScripTree widgets (cells, forms, tree popups) to PNG files
**without showing them on the user's desktop**.

Useful for:

  * Generating documentation screenshots in batch.
  * Visual-regression baselines for the test suite.
  * Producing thumbnail / preview images of tools for catalog UI.
  * Quick visual sanity checks after a CSS / branding tweak
    without spinning up the full GUI.

Usage::

    python screenshooter.py <kind> <input> [options]

Where ``kind`` is one of:

    cell    — render a single standalone cell bound to ``input``
              (a ``.scriptree`` / ``.scriptreetree`` catalog file).
    form    — render the parameter form view of a ``.scriptree``
              tool (the widget the standalone runner shows).
    tree    — render the popup menu view of a ``.scriptreetree``.
    editor  — full editor (``MainWindow``) with tree / form /
              output / command-line docks visible.  v0.8.0a2+:
              shows the same window an end-user gets when they
              ``run_scriptree.bat`` an existing ``.scriptree`` or
              ``.scriptreetree`` from the desktop.
    tabs    — ``StandaloneWindow`` built from a ``.scriptreetree``
              with one tab per leaf tool.  v0.8.0a2+: the in-window
              view a user sees when launching a tree from a cell
              via single-click.
    forest  — composite image: a forest hub cell with the catalog's
              cell docked next to it, showing "as it would look
              attached to the forest on the desktop".  v0.8.0a2+.
    menu    — composite image: a forest hub cell with its merged
              tree-popup menu rendered below it, showing the menu
              the user gets by double-clicking the forest.
              v0.8.0a2+.

Examples::

    # One PNG of the make_portable tool's form view.
    python screenshooter.py form ScripTreeApps/ScripTreeManagement/make_portable.scriptree \\
        --out docs/screenshots/make_portable_form.png

    # A whole folder of cell PNGs, one per catalog.
    python screenshooter.py --batch ScripTreeApps/ScripTreeManagement/ \\
        --out docs/screenshots/

How the "no flash" works
------------------------
First-pass attempt used ``QT_QPA_PLATFORM=offscreen`` to suppress
windows entirely.  Problem: Qt's offscreen platform plugin reports
ZERO available fonts on Windows (it doesn't enumerate
``C:\\Windows\\Fonts\\``), so every glyph rasterises as ``□``.

The fix is simpler: use the default platform plugin (which has
full font access) but **never call ``widget.show()``**.
``QWidget.grab()`` renders unshown widgets fine — Qt fires
``resizeEvent`` + ``paintEvent`` synchronously inside ``grab``.
No window ever appears on the user's desktop.

Implementation notes
--------------------
* We call ``adjustSize()`` and ``QApplication.processEvents()`` a
  few times before ``grab()`` so deferred layout / sizing settles.
  Otherwise the first grab on a fresh widget catches the un-laid
  state (zero-size labels, etc.).
* For widgets that need explicit sizing (forms, trees), the caller
  passes ``--width`` / ``--height`` and we ``resize()``.  ``cell``
  uses ``apply_size_change`` so the geometry-mask updates correctly.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# v0.8.0a4 — inject the vendored ``lib/pypi/`` onto ``sys.path``
# the same way ``run_scriptreering.py`` does, so the bundled PySide6
# is picked up when the user double-clicks ``run_screenshooter.bat``
# (which calls system Python directly without the editor's import
# prelude).  Mirror the editor launcher's logic in miniature:
# prepend lib/pypi if it exists and is non-empty, and also set
# QT_PLUGIN_PATH so Qt finds its bundled platform / image plugins.
def _inject_vendored_pypi() -> None:
    pypi = HERE / "lib" / "pypi"
    if not pypi.is_dir():
        return
    entries = [p for p in pypi.iterdir() if p.name != ".gitkeep"]
    if not entries:
        return
    pypi_str = str(pypi)
    if pypi_str not in sys.path:
        sys.path.insert(0, pypi_str)
    import os
    qt_plugin_dir = pypi / "PySide6" / "plugins"
    if qt_plugin_dir.is_dir():
        os.environ.setdefault("QT_PLUGIN_PATH", str(qt_plugin_dir))


_inject_vendored_pypi()


from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402


def _log(msg: str) -> None:
    print(f"[screenshooter] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# QApplication bootstrap
# ---------------------------------------------------------------------------

def _ensure_app() -> QApplication:
    """Return the singleton QApplication, constructing if needed.

    We do NOT force ``QT_QPA_PLATFORM=offscreen``: that plugin has
    no fonts on Windows so every glyph would render as tofu.  The
    default platform gives us proper text + we skip ``show()`` to
    keep windows off-screen.
    """
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    return app


# ---------------------------------------------------------------------------
# Capture helper — renders an UNSHOWN widget to PNG.
# ---------------------------------------------------------------------------

def _capture(
    widget: QWidget,
    out_path: Path,
    *,
    settle_ticks: int = 3,
) -> None:
    """Render ``widget`` to a PNG at ``out_path``.

    The widget MUST NOT be visible.  ``QWidget.grab()`` will fire
    the necessary paint events synchronously; ``show()`` would
    park a window on the user's desktop and defeat the whole point.

    We call ``adjustSize()`` + ``processEvents()`` a few times so
    deferred layout settles before the grab — otherwise the first
    capture on a fresh widget catches zero-size sub-widgets.
    """
    app = _ensure_app()
    # If the caller didn't size the widget themselves, ask Qt for
    # its size hint.  Safe to call on already-sized widgets.
    if widget.size().width() == 0 or widget.size().height() == 0:
        widget.adjustSize()
    # Let Qt's event loop settle any deferred layout / sizing.
    for _ in range(max(1, settle_ticks)):
        app.processEvents()

    pixmap: QPixmap = widget.grab()
    if pixmap.isNull():
        raise RuntimeError(
            f"_capture: grab() returned a null pixmap for "
            f"{widget.__class__.__name__}"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ok = pixmap.save(str(out_path), "PNG")
    if not ok:
        raise RuntimeError(f"_capture: failed to write {out_path}")
    _log(
        f"wrote {out_path} "
        f"({pixmap.width()}x{pixmap.height()} px)"
    )
    # No show() was called, so no close() needed — Qt cleans up
    # the unparented widget when it goes out of scope.


# ---------------------------------------------------------------------------
# Kind: cell — a standalone CellWindow bound to a catalog
# ---------------------------------------------------------------------------

def _render_cell(catalog_path: Path, out: Path, size_px: int) -> None:
    """Render one standalone ``CellWindow`` bound to a catalog."""
    _ensure_app()
    from scriptree.shell.branding_loader import load_branding
    from scriptree.shell.cell_window import CellWindow

    branding = load_branding()
    cell = CellWindow(branding, catalog_path=str(catalog_path.resolve()))
    if size_px > 0:
        try:
            cell.apply_size_change(int(size_px))
        except Exception:  # noqa: BLE001
            cell.resize(size_px, size_px)
    _capture(cell, out)


# ---------------------------------------------------------------------------
# Kind: form — the ToolRunnerView for a .scriptree
# ---------------------------------------------------------------------------

def _render_form(
    catalog_path: Path,
    out: Path,
    width: int,
    height: int,
    *,
    config: str | None = None,
    standalone: bool = False,
    show_output: bool = False,
    show_extras: bool = False,
    show_command_line: bool = False,
) -> None:
    """Render the parameter form view of a single tool.

    **Default behaviour (post v0.8.0a23 doc-screenshot policy):**
    the extra-args box, command-line preview, and output pane are
    **hidden** unless the caller opts in with the matching
    ``show_*`` flag.  This matches the "marketing screenshot" use
    case — show only what the user fills in to run the tool, not
    the developer chrome that surrounds it.  Pass any of the
    ``show_*`` flags to put a section back.

    The form panel auto-grows to its ``sizeHint`` so every parameter
    is visible without scrolling.  ``height`` is treated as a
    *minimum* height when the sections are hidden — the captured
    image grows downward to fit all parameters if the form's natural
    height exceeds the requested ``height``.

    Optional flags:
      * ``config`` — name of a sidecar configuration to activate
        before capture.  ``None`` uses the sidecar's default
        (matching what standalone mode picks at boot).  Unknown
        names fall through to the default with a stderr warning.
      * ``standalone`` — when True, also apply the active config's
        ``UIVisibility`` (copy-argv, env button, config-bar mode,
        etc.) so the captured form matches the in-cell runtime
        view.  When False (default), the only sections the
        screenshooter hides are the three it controls explicitly
        (extras / command-line / output) and the rest stays at the
        IDE/docked defaults.
      * ``show_output`` / ``show_extras`` / ``show_command_line`` —
        opt back in to a hidden section.
    """
    _ensure_app()
    from scriptree.core.configs import UIVisibility
    from scriptree.core.io import load_tool
    from scriptree.ui.tool_runner import ToolRunnerView

    tool = load_tool(catalog_path)
    view = ToolRunnerView(tool, file_path=str(catalog_path))

    # ``_apply_visibility`` only honours the field-level toggles for
    # ``extras_box`` / ``command_line`` etc. when the runner is in
    # standalone mode.  We always want those hides to land in
    # screenshooter output, so flip standalone on unconditionally.
    view._standalone_mode = True

    if config:
        try:
            view.apply_named_configuration(config)
        except Exception as exc:  # noqa: BLE001
            _log(
                f"apply_named_configuration({config!r}) failed: {exc!r}; "
                f"falling back to default"
            )
            # Fall back to the sidecar's default if the name was bad.
            try:
                cfg = view._cfg_set.default_config()
                view._apply_configuration(cfg)
            except Exception:  # noqa: BLE001
                pass
    elif standalone:
        # Mirror what StandaloneWindow.from_tool does when no
        # explicit config name is given — pick the sidecar's
        # default and apply.
        try:
            cfg = view._cfg_set.default_config()
            if view._cfg_set.active != cfg.name:
                view._cfg_set.active = cfg.name
            view._apply_configuration(cfg)
        except Exception:  # noqa: BLE001
            pass

    # Apply the screenshooter's section-visibility policy.  We build
    # a UIVisibility from the current config (so per-config hides
    # for tools_sidebar / copy_argv / etc. still apply when
    # ``standalone=True``) and override only the three sections this
    # CLI controls.  When ``standalone=False`` there's no active
    # config-driven visibility, so we start from a fresh default.
    if standalone:
        try:
            base_vis = view._cfg_set.active_config().ui_visibility
        except Exception:  # noqa: BLE001
            base_vis = UIVisibility()
    else:
        base_vis = UIVisibility()

    # Shallow copy with the three CLI-controlled fields overridden.
    vis = UIVisibility(
        output_pane=show_output,
        extras_box=show_extras if not standalone else base_vis.extras_box and show_extras,
        tools_sidebar=base_vis.tools_sidebar,
        command_line=show_command_line if not standalone else base_vis.command_line and show_command_line,
        copy_argv=base_vis.copy_argv,
        clear_output=base_vis.clear_output,
        config_bar=base_vis.config_bar,
        env_button=base_vis.env_button,
        popup_on_error=base_vis.popup_on_error,
        popup_on_success=base_vis.popup_on_success,
    )
    view._apply_visibility(vis)

    # The output pane is parent-coordinated via the ``visibilityChanged``
    # signal — the runner doesn't hide it directly because in a docked
    # MainWindow the parent owns the output dock.  Standalone capture
    # has no such parent, so we hide the inner output container
    # ourselves to match the flag.
    try:
        view._output_container.setVisible(show_output)
    except Exception:  # noqa: BLE001
        pass

    # Capture either the full ToolRunnerView (when at least one of
    # the lower sections is visible) or just the form panel (when
    # the user wanted the minimal "params only" composition).
    # Capturing the form_panel directly produces a tighter image
    # with no leftover splitter gutter where the output pane used
    # to sit, but the form_panel is parented inside the view's
    # internal QSplitter so its parent layout would otherwise
    # override any ``.resize()`` call -- detach it first.
    capture_target: QWidget
    if not (show_output or show_extras or show_command_line):
        capture_target = view.form_panel
        capture_target.setParent(None)
    else:
        capture_target = view

    # Sizing: width is the user's requested width (or the default
    # 520 px).  Height is treated as a minimum — if the form's
    # natural sizeHint is taller (more parameters than fit in the
    # default), the capture grows downward to fit every row.
    if width <= 0:
        width = 520
    if height <= 0:
        height = 1

    # The form panel houses the parameters inside a ``_FormScrollArea``
    # whose ``sizeHint`` is deliberately tiny (so the docked-in-
    # MainWindow case can collapse it) -- which means the form's
    # natural ``sizeHint`` does NOT include the parameters' full
    # height; the scroll area would just show its own scrollbar.
    # For screenshots we want every parameter row visible without
    # scrolling, so we walk to the inner widget and forcibly grow
    # the scroll area to that widget's natural height.  This is
    # the screenshot-mode equivalent of "make the dock tall enough
    # to fit all params with no internal scrollbar."
    try:
        from PySide6.QtWidgets import QScrollArea
        for sa in view.form_panel.findChildren(QScrollArea):
            inner = sa.widget()
            if inner is None:
                continue
            inner.adjustSize()
            target_h = inner.sizeHint().height()
            if target_h > 0:
                sa.setMinimumHeight(target_h)
    except Exception as exc:  # noqa: BLE001
        _log(f"form: param-area grow failed: {exc!r}")

    # Settle layout so sizeHint is meaningful (deferred Qt layout
    # passes haven't run yet on a freshly-constructed widget).
    capture_target.adjustSize()
    app = QApplication.instance()
    for _ in range(3):
        app.processEvents()
    hint = capture_target.sizeHint()
    final_h = max(height, hint.height())
    capture_target.resize(width, final_h)
    # One more settle pass after the explicit resize: forcing a
    # specific size triggers another layout cycle that may shift
    # widgets around (e.g. word-wrapping description labels recomputing
    # at the new width).
    for _ in range(3):
        app.processEvents()
    _capture(capture_target, out)


# ---------------------------------------------------------------------------
# Kind: tree — the popup menu view of a .scriptreetree
# ---------------------------------------------------------------------------

def _render_tree(catalog_path: Path, out: Path, width: int, height: int) -> None:
    """Render the tree-popup view of a ``.scriptreetree``."""
    _ensure_app()
    from scriptree.ui.tree_view import TreeLauncherView

    view = TreeLauncherView()
    # TreeLauncherView populates itself from a path via ``load()``,
    # not from a TreeDef passed to ``__init__`` — match that API.
    view.load(str(catalog_path.resolve()))
    if width > 0 and height > 0:
        view.resize(width, height)
    _capture(view, out)


# ---------------------------------------------------------------------------
# Kind: editor — the full MainWindow with tree / form / output / cmd-line
# ---------------------------------------------------------------------------

def _render_editor(
    catalog_path: Path, out: Path, width: int, height: int,
    *,
    show_output: bool = False,
    show_extras: bool = False,
    show_command_line: bool = False,
) -> None:
    """Render the full editor (``MainWindow``) with the catalog loaded.

    Matches what the user sees when they double-click a ``.scriptree``
    / ``.scriptreetree`` and ScripTree opens the editor — tree dock on
    the left, form panel in the centre, output pane below the form,
    command-line group at the bottom.

    **Default visibility (post v0.8.0a23 doc-screenshot policy):**
    the Output dock and the Run-controls dock (extras + command line)
    are **hidden** so the captured image is the clean "tree + form"
    composition documentation usually wants.  Pass any of the
    ``show_*`` flags to bring a section back.

    ``show_extras`` and ``show_command_line`` both control the
    Run-controls dock (extras and command-line live in the same
    dock), so passing either one shows it.  ``show_output``
    controls the Output dock independently.

    When ``catalog_path`` is a ``.scriptreetree``, the first leaf tool
    is auto-selected so the form / output / command-line docks all
    populate (otherwise the right-hand panel shows just the welcome
    text).  When the input is a single ``.scriptree`` tool, the
    runner is loaded directly via ``_show_runner``.
    """
    _ensure_app()
    from scriptree.ui.main_window import MainWindow
    from scriptree.core.io import load_tool, load_tree

    win = MainWindow()
    try:
        win.open_file(str(catalog_path.resolve()))
    except Exception as exc:  # noqa: BLE001
        _log(f"editor: open_file({catalog_path}) raised {exc!r}")

    # If a tree was opened, walk to the first leaf and ``_show_runner``
    # so the right-hand docks populate with a real tool's form, output
    # pane, and command-line group.  Without this the editor screenshot
    # captures only the tree on the left + welcome banner on the right.
    suffix = catalog_path.suffix.lower()
    if suffix == ".scriptreetree":
        try:
            tree = load_tree(str(catalog_path.resolve()))

            def _first_leaf(nodes):  # noqa: ANN001
                for n in nodes:
                    if getattr(n, "type", "") == "leaf":
                        return n
                    kids = getattr(n, "children", None) or []
                    found = _first_leaf(kids)
                    if found is not None:
                        return found
                return None

            leaf = _first_leaf(tree.nodes)
            if leaf is not None:
                leaf_path = getattr(leaf, "path", None)
                if leaf_path:
                    # Resolve the leaf's path relative to the tree
                    # file's directory (the canonical ScripTree
                    # convention).
                    leaf_full = (catalog_path.parent / leaf_path).resolve()
                    tool = load_tool(str(leaf_full))
                    win._show_runner(tool, str(leaf_full))
        except Exception as exc:  # noqa: BLE001
            _log(
                f"editor: tree-leaf auto-select failed: {exc!r} "
                f"— captured tree-only view"
            )
    elif suffix == ".scriptree":
        try:
            tool = load_tool(str(catalog_path.resolve()))
            win._show_runner(tool, str(catalog_path.resolve()))
        except Exception as exc:  # noqa: BLE001
            _log(f"editor: tool-load auto-show failed: {exc!r}")

    # Apply the screenshooter's section-visibility policy.  By default
    # we want a clean "tree + form" capture; the Output dock and the
    # Run-controls dock (extras + cmd-line) hide unless the caller
    # asked for them.  Use ``toggleView(False)`` which is the same
    # primitive MainWindow uses internally — matches its menu actions.
    try:
        if not show_output:
            win._output_dock.toggleView(False)
        else:
            win._output_dock.toggleView(True)
        if not (show_extras or show_command_line):
            win._run_controls_dock.toggleView(False)
        else:
            win._run_controls_dock.toggleView(True)
    except Exception as exc:  # noqa: BLE001
        _log(f"editor visibility toggle failed: {exc!r}")

    # Settle ads docking layout after the toggles before sizing.
    app = QApplication.instance()
    for _ in range(3):
        app.processEvents()

    if width > 0 and height > 0:
        win.resize(width, height)
    _capture(win, out)


# ---------------------------------------------------------------------------
# Kind: tabs — StandaloneWindow.from_tree (tabbed leaf-per-tool layout)
# ---------------------------------------------------------------------------

def _render_tabs(
    tree_path: Path, out: Path, width: int, height: int,
) -> None:
    """Render a ``StandaloneWindow`` built from a ``.scriptreetree`` —
    one tab per leaf tool, no command-line, no extra-args (the
    in-window view a user sees when launching a tree from a cell)."""
    _ensure_app()
    from scriptree.ui.standalone_window import StandaloneWindow

    if tree_path.suffix.lower() != ".scriptreetree":
        raise ValueError(
            f"tabs mode needs a .scriptreetree, got {tree_path.suffix!r}"
        )
    win = StandaloneWindow.from_tree(str(tree_path.resolve()))
    if width > 0 and height > 0:
        win.resize(width, height)
    _capture(win, out)


# ---------------------------------------------------------------------------
# Composite helper — grab two-or-more widgets onto a single pixmap.
# ---------------------------------------------------------------------------

def _capture_composite(
    placements: "list[tuple[QWidget, QPoint]]",
    out_path: Path,
    *,
    bg: QColor = QColor(245, 245, 248),
    pad: int = 24,
) -> None:
    """Render every widget in ``placements`` (a list of
    ``(widget, top_left_offset)`` tuples) onto a single PNG.

    The composite canvas is sized to fit every widget plus ``pad`` px
    of margin on every side.  Background is filled with ``bg`` so the
    image is not transparent (Word / GitHub READMEs handle solid
    backgrounds better).  No widget is ever shown — every grab is
    against an off-screen widget (Qt's grab() drives paintEvent
    synchronously).
    """
    app = _ensure_app()
    if not placements:
        raise ValueError("_capture_composite: empty placements list")

    # Settle every widget's layout before sizing the canvas.
    for w, _pt in placements:
        if w.size().width() == 0 or w.size().height() == 0:
            w.adjustSize()
    for _ in range(3):
        app.processEvents()

    # Compute canvas bounds.
    min_x = min(pt.x() for _w, pt in placements)
    min_y = min(pt.y() for _w, pt in placements)
    max_x = max(pt.x() + w.width() for w, pt in placements)
    max_y = max(pt.y() + w.height() for w, pt in placements)
    cw = (max_x - min_x) + 2 * pad
    ch = (max_y - min_y) + 2 * pad

    canvas = QPixmap(cw, ch)
    canvas.fill(bg)
    painter = QPainter(canvas)
    try:
        for w, pt in placements:
            pm = w.grab()
            if pm.isNull():
                _log(
                    f"_capture_composite: skipping null grab for "
                    f"{w.__class__.__name__}"
                )
                continue
            painter.drawPixmap(
                pt.x() - min_x + pad,
                pt.y() - min_y + pad,
                pm,
            )
    finally:
        painter.end()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ok = canvas.save(str(out_path), "PNG")
    if not ok:
        raise RuntimeError(f"_capture_composite: failed to write {out_path}")
    _log(f"wrote {out_path} ({canvas.width()}x{canvas.height()} px)")


# ---------------------------------------------------------------------------
# Kind: forest — cell docked to a forest cluster (composite)
# ---------------------------------------------------------------------------

def _build_forest_hub(branding, size_px: int):  # noqa: ANN001
    """Construct a forest master cell with the bundled forest glyph.

    Factored out of ``_render_forest`` / ``_render_menu`` so both
    composite renderers share one configuration path — and so a
    future ``editor`` render of a ``.scriptreeforest`` file (which
    needs the same hub) can reuse it without copy-paste.
    """
    from scriptree.shell.cell_window import CellWindow

    forest = CellWindow(branding, role="master")
    forest._is_forest_master = True
    if size_px > 0:
        try:
            forest.apply_size_change(int(size_px))
        except Exception:  # noqa: BLE001
            forest.resize(size_px, size_px)
    try:
        from scriptree.shell.icon_assets import (
            BUNDLED_FORMAT, bundled_icon_b64,
        )
        b64 = bundled_icon_b64("forest")
        if b64:
            forest._icon_data_b64 = b64
            forest._icon_data_format = BUNDLED_FORMAT
    except Exception as exc:  # noqa: BLE001
        _log(f"forest hub: bundled-icon load failed: {exc!r}")
    return forest


def _forest_member_catalog_paths(forest_path: Path) -> "list[Path]":
    """Read a ``.scriptreeforest`` and return the absolute catalog
    paths of every item — same set the live forest auto-loader
    would expand into cells when ScripTreeForest opens this file."""
    from scriptree.shell.forest_io import load_forest

    forest_def = load_forest(forest_path)
    paths: list[Path] = []
    for item in forest_def.items:
        # Prefer ``catalog_path`` (when set for tree / tool items
        # to disambiguate from the wrapping ``path``); fall back
        # to ``path`` which IS the catalog for ring items.
        cat = item.catalog_path or item.path
        if not cat:
            continue
        p = Path(cat)
        if not p.exists():
            _log(f"forest item missing on disk: {p}")
            continue
        paths.append(p)
    return paths


def _render_forest(
    catalog_path: Path, out: Path, size_px: int,
) -> None:
    """Render a forest hub cell with one or more catalog cells docked
    around it — composed onto a single PNG.

    Two input modes:

    * ``.scriptree`` / ``.scriptreetree``: synthesise a forest hub and
      dock the catalog's cell next to it.  Shows "this is what this
      tool looks like when added to the workspace".

    * ``.scriptreeforest`` (v0.8.0a5+): load the actual forest file
      and place a cell for EVERY item around the hub at honeycomb
      neighbour slots.  Shows the user's real workspace layout as
      a single image — same composition the live forest launcher
      produces at startup, just rendered off-screen as a PNG.
    """
    _ensure_app()
    from scriptree.shell.branding_loader import load_branding
    from scriptree.shell.cell_window import CellWindow

    branding = load_branding()
    forest = _build_forest_hub(branding, size_px)

    # Decide what catalog paths become cells around the hub.
    if catalog_path.suffix.lower() == ".scriptreeforest":
        member_paths = _forest_member_catalog_paths(catalog_path)
        if not member_paths:
            _log(
                f"forest: {catalog_path} has no items on disk — "
                f"capturing the bare hub"
            )
    else:
        member_paths = [catalog_path.resolve()]

    # Place the hub at (0, 0).  Members land at the 6 honeycomb
    # neighbour slots around it; if there are >6, additional cells
    # spiral out onto the second ring.
    placements: list = [(forest, QPoint(0, 0))]

    # Slot offsets in widget-local coordinates relative to the
    # hub's top-left — flat-top hex with neighbour cells centred
    # on (cx + dx, cy + dy) where dy uses sqrt(3)/2 vertical stride.
    import math
    SQRT3_HALF = math.sqrt(3.0) / 2.0
    inner_offsets = [
        (0, -size_px * SQRT3_HALF),            # N
        (size_px * 0.75, -size_px * SQRT3_HALF / 2),   # NE
        (size_px * 0.75,  size_px * SQRT3_HALF / 2),   # SE
        (0,  size_px * SQRT3_HALF),            # S
        (-size_px * 0.75, size_px * SQRT3_HALF / 2),   # SW
        (-size_px * 0.75, -size_px * SQRT3_HALF / 2),  # NW
    ]
    outer_offsets = [
        (2 * dx, 2 * dy) for dx, dy in inner_offsets
    ]
    slot_offsets = inner_offsets + outer_offsets

    for i, p in enumerate(member_paths):
        cell = CellWindow(branding, catalog_path=str(p.resolve()))
        if size_px > 0:
            try:
                cell.apply_size_change(int(size_px))
            except Exception:  # noqa: BLE001
                cell.resize(size_px, size_px)
        slot_idx = i % len(slot_offsets)
        dx, dy = slot_offsets[slot_idx]
        cell_pos = QPoint(int(round(dx)), int(round(dy)))
        # Wire link membership so the cell paints with its
        # forest-linked outline tint (not green free-cell).
        forest._members[cell._id] = QPoint(cell_pos)
        forest._positioned.add(cell._id)
        cell._group_master_id = forest._id
        cell._link_parent_id = forest._id
        placements.append((cell, cell_pos))

    _capture_composite(placements, out)


# ---------------------------------------------------------------------------
# Kind: menu — forest hub + its merged tree-popup menu (composite)
# ---------------------------------------------------------------------------

def _render_menu(
    catalog_path: Path, out: Path, size_px: int,
) -> None:
    """Render a forest hub cell with its merged tree-popup menu
    rendered below it — composed onto a single PNG.

    Two input modes:

    * ``.scriptree`` / ``.scriptreetree``: synthesise a forest hub
      with one catalog cell as its member, so the merged menu
      shows that catalog's tools as a single sub-menu.

    * ``.scriptreeforest`` (v0.8.0a5+): load every item from the
      forest file and add a cell per item to the hub's members.
      The captured menu is then the user's REAL workspace menu —
      the same one ScripTreeForest pops up when the user double-
      clicks the desktop forest hub.

    Uses the same ``build_tree_popup_menu`` code path the live
    shell uses, so menu contents (header label, search bar,
    sub-menus per member, nested ring sub-menus) match runtime.
    """
    _ensure_app()
    from scriptree.shell.branding_loader import load_branding
    from scriptree.shell.cell_window import CellWindow
    from scriptree.shell.tree_popup import build_tree_popup_menu

    branding = load_branding()
    forest = _build_forest_hub(branding, size_px)

    # Resolve member catalogs.
    if catalog_path.suffix.lower() == ".scriptreeforest":
        member_paths = _forest_member_catalog_paths(catalog_path)
        if not member_paths:
            _log(
                f"menu: {catalog_path} has no items on disk — "
                f"capturing an empty forest menu"
            )
    else:
        member_paths = [catalog_path.resolve()]

    # Add every catalog as a forest member so the merged menu
    # populates from each.  Cells aren't drawn — only the menu
    # appears in the composite below the hub.
    for p in member_paths:
        member = CellWindow(branding, catalog_path=str(p.resolve()))
        forest._members[member._id] = QPoint(0, 0)
        forest._positioned.add(member._id)
        member._group_master_id = forest._id
        member._link_parent_id = forest._id

    menu = build_tree_popup_menu(forest)
    menu.adjustSize()
    # Force a settle so the QMenu computes its geometry.
    app = QApplication.instance()
    for _ in range(3):
        app.processEvents()

    # Place the menu just below the forest hub, centred on it.
    forest_pos = QPoint(0, 0)
    menu_pos = QPoint(
        size_px // 2 - menu.width() // 2,
        size_px + 8,
    )

    _capture_composite(
        [(forest, forest_pos), (menu, menu_pos)],
        out,
    )


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------

_SUFFIX_TO_KIND = {
    ".scriptree":     "form",
    ".scriptreetree": "tree",
}


def _batch(
    root: Path,
    out_dir: Path,
    *,
    kind: str | None,
    size_px: int,
    width: int,
    height: int,
    config: str | None = None,
    standalone: bool = False,
    show_output: bool = False,
    show_extras: bool = False,
    show_command_line: bool = False,
) -> int:
    """Walk ``root`` and render one PNG per catalog file found."""
    written = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        suffix = p.suffix.lower()
        if suffix not in _SUFFIX_TO_KIND:
            continue
        effective_kind = kind or _SUFFIX_TO_KIND[suffix]
        # Tag the output filename with the mode so a single batch
        # run can produce docked+standalone variants side by side.
        suffix_tag = ""
        if standalone:
            suffix_tag = "_standalone"
        if config:
            suffix_tag += f"_{config}"
        out = out_dir / f"{p.stem}_{effective_kind}{suffix_tag}.png"
        try:
            if effective_kind == "cell":
                _render_cell(p, out, size_px)
            elif effective_kind == "form":
                _render_form(
                    p, out, width, height,
                    config=config, standalone=standalone,
                    show_output=show_output,
                    show_extras=show_extras,
                    show_command_line=show_command_line,
                )
            elif effective_kind == "tree":
                if suffix != ".scriptreetree":
                    _log(f"  skipping {p} — 'tree' needs .scriptreetree")
                    continue
                _render_tree(p, out, width, height)
            elif effective_kind == "editor":
                _render_editor(
                    p, out, width, height,
                    show_output=show_output,
                    show_extras=show_extras,
                    show_command_line=show_command_line,
                )
            elif effective_kind == "tabs":
                if suffix != ".scriptreetree":
                    _log(f"  skipping {p} — 'tabs' needs .scriptreetree")
                    continue
                _render_tabs(p, out, width, height)
            elif effective_kind == "forest":
                _render_forest(p, out, size_px)
            elif effective_kind == "menu":
                _render_menu(p, out, size_px)
            else:
                _log(f"  unknown kind {effective_kind!r}; skipping {p}")
                continue
            written += 1
        except Exception as exc:  # noqa: BLE001
            _log(f"  FAIL on {p}: {exc!r}")
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="screenshooter",
        description=(
            "Render ScripTree widgets to PNG files without showing "
            "them.  Uses widget.grab() against unshown widgets."
        ),
    )
    parser.add_argument(
        "kind",
        nargs="?",
        choices=["cell", "form", "tree", "editor", "tabs", "forest", "menu"],
        help=(
            "What to capture.  Omit with --batch to auto-pick per file "
            "(.scriptree -> form, .scriptreetree -> tree)."
        ),
    )
    parser.add_argument(
        "input",
        type=Path,
        help=(
            "Path to a catalog file (default mode) OR to a folder "
            "(with --batch)."
        ),
    )
    parser.add_argument(
        "--out", "-o",
        type=Path,
        default=None,
        help=(
            "Output PNG path.  In --batch mode, this is the output "
            "directory.  Defaults to ./<input>.png (single mode) or "
            "./screenshots/ (batch mode)."
        ),
    )
    parser.add_argument(
        "--batch", action="store_true",
        help=(
            "Walk the input folder and render every .scriptree / "
            ".scriptreetree found, one PNG per file."
        ),
    )
    parser.add_argument(
        "--cell-size", type=int, default=128,
        help="Cell-mode size in px (default: 128).",
    )
    parser.add_argument(
        "--width", type=int, default=520,
        help="Form / tree-mode width in px (default: 520).",
    )
    parser.add_argument(
        "--height", type=int, default=640,
        help="Form / tree-mode height in px (default: 640).",
    )
    parser.add_argument(
        "--config", "-c", default=None,
        help=(
            "Name of a sidecar configuration to apply before "
            "capture (form kind only).  Looks up "
            "``<input>.configs.json`` and activates the named "
            "config.  When omitted, uses the sidecar's "
            "default-marked configuration (matching what "
            "standalone mode picks at boot).  Unknown names fall "
            "back to default with a warning."
        ),
    )
    parser.add_argument(
        "--standalone", action="store_true",
        help=(
            "Render in standalone mode — apply the active "
            "configuration's UIVisibility flags so the captured "
            "form matches what the user sees when launching the "
            "tool from ScripTreeRing (hidden command line, no "
            "Copy argv button, etc., per the config's settings)."
        ),
    )
    # ---- Section-visibility opt-ins (form + editor kinds) -----------------
    # Default policy (v0.8.0a23+): the screenshot is the clean
    # "what the user fills in to run this" image — extras, command
    # line, and output area are hidden unless explicitly requested.
    # These flags put each section back individually; ``--full``
    # puts ALL three back at once for a kitchen-sink capture.
    parser.add_argument(
        "--show-output", action="store_true",
        help=(
            "Include the Output area in the screenshot (form + editor "
            "kinds).  Default: hidden."
        ),
    )
    parser.add_argument(
        "--show-extras", action="store_true",
        help=(
            "Include the Extra arguments box in the screenshot "
            "(form + editor kinds).  Default: hidden."
        ),
    )
    parser.add_argument(
        "--show-command-line", action="store_true",
        help=(
            "Include the command-line preview box in the screenshot "
            "(form + editor kinds).  Default: hidden."
        ),
    )
    parser.add_argument(
        "--full", action="store_true",
        help=(
            "Shorthand for --show-output --show-extras "
            "--show-command-line.  Captures every section the editor "
            "/ standalone runner can display."
        ),
    )
    args = parser.parse_args(argv)

    # ``--full`` expands into the three individual flags.
    if args.full:
        args.show_output = True
        args.show_extras = True
        args.show_command_line = True

    inp: Path = args.input.resolve()
    if not inp.exists():
        print(f"screenshooter: input not found: {inp}", file=sys.stderr)
        return 2

    if args.batch:
        if not inp.is_dir():
            print(
                f"screenshooter: --batch requires a folder, got {inp}",
                file=sys.stderr,
            )
            return 2
        out_dir = (args.out or Path("screenshots")).resolve()
        written = _batch(
            inp, out_dir,
            kind=args.kind,
            size_px=args.cell_size,
            width=args.width,
            height=args.height,
            config=args.config,
            standalone=args.standalone,
            show_output=args.show_output,
            show_extras=args.show_extras,
            show_command_line=args.show_command_line,
        )
        print(f"screenshooter: wrote {written} PNG(s) to {out_dir}")
        return 0 if written > 0 else 1

    # Single-file mode.
    if args.kind is None:
        kind = _SUFFIX_TO_KIND.get(inp.suffix.lower())
        if kind is None:
            print(
                f"screenshooter: cannot auto-pick kind for "
                f"{inp.suffix!r}; pass a kind explicitly.",
                file=sys.stderr,
            )
            return 2
        args.kind = kind

    out = args.out
    if out is None:
        out = Path(f"{inp.stem}_{args.kind}.png")
    out = out.resolve()

    try:
        if args.kind == "cell":
            _render_cell(inp, out, args.cell_size)
        elif args.kind == "form":
            _render_form(
                inp, out, args.width, args.height,
                config=args.config, standalone=args.standalone,
                show_output=args.show_output,
                show_extras=args.show_extras,
                show_command_line=args.show_command_line,
            )
        elif args.kind == "tree":
            if inp.suffix.lower() != ".scriptreetree":
                print(
                    f"screenshooter: kind='tree' requires a "
                    f".scriptreetree input.",
                    file=sys.stderr,
                )
                return 2
            _render_tree(inp, out, args.width, args.height)
        elif args.kind == "editor":
            _render_editor(
                inp, out, args.width, args.height,
                show_output=args.show_output,
                show_extras=args.show_extras,
                show_command_line=args.show_command_line,
            )
        elif args.kind == "tabs":
            if inp.suffix.lower() != ".scriptreetree":
                print(
                    f"screenshooter: kind='tabs' requires a "
                    f".scriptreetree input.",
                    file=sys.stderr,
                )
                return 2
            _render_tabs(inp, out, args.width, args.height)
        elif args.kind == "forest":
            _render_forest(inp, out, args.cell_size)
        elif args.kind == "menu":
            _render_menu(inp, out, args.cell_size)
    except Exception as exc:  # noqa: BLE001
        print(f"screenshooter: FAIL: {exc!r}", file=sys.stderr)
        import traceback as _tb
        _tb.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
