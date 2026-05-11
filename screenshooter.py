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

    cell  — render a single standalone cell bound to ``input``
            (a ``.scriptree`` / ``.scriptreetree`` catalog file).
    form  — render the parameter form view of a ``.scriptree``
            tool (the widget the standalone runner shows).
    tree  — render the popup menu view of a ``.scriptreetree``.

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

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QWidget


HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


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

def _render_form(catalog_path: Path, out: Path, width: int, height: int) -> None:
    """Render the parameter form view of a single tool."""
    _ensure_app()
    from scriptree.core.io import load_tool
    from scriptree.ui.tool_runner import ToolRunnerView

    tool = load_tool(catalog_path)
    view = ToolRunnerView(tool)
    if width > 0 and height > 0:
        view.resize(width, height)
    _capture(view, out)


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
        out = out_dir / f"{p.stem}_{effective_kind}.png"
        try:
            if effective_kind == "cell":
                _render_cell(p, out, size_px)
            elif effective_kind == "form":
                _render_form(p, out, width, height)
            elif effective_kind == "tree":
                if suffix != ".scriptreetree":
                    _log(f"  skipping {p} — 'tree' needs .scriptreetree")
                    continue
                _render_tree(p, out, width, height)
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
        choices=["cell", "form", "tree"],
        help=(
            "What to capture.  Omit with --batch to auto-pick per file "
            "(.scriptree → form, .scriptreetree → tree)."
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
    args = parser.parse_args(argv)

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
            _render_form(inp, out, args.width, args.height)
        elif args.kind == "tree":
            if inp.suffix.lower() != ".scriptreetree":
                print(
                    f"screenshooter: kind='tree' requires a "
                    f".scriptreetree input.",
                    file=sys.stderr,
                )
                return 2
            _render_tree(inp, out, args.width, args.height)
    except Exception as exc:  # noqa: BLE001
        print(f"screenshooter: FAIL: {exc!r}", file=sys.stderr)
        import traceback as _tb
        _tb.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
