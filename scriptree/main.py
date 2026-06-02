"""Application entry point.

## For humans

Usage::

    # Normal IDE window
    python -m scriptree

    # Open a tool (IDE window, auto-load)
    python -m scriptree path/to/tool.scriptree

    # Open a tree (IDE window, auto-load)
    python -m scriptree path/to/tree.scriptreetree

    # Standalone window (uses tool's active configuration)
    python -m scriptree path/to/tool.scriptree -standalone

    # Standalone window with a specific configuration
    python -m scriptree path/to/tool.scriptree -standalone -configuration myconfig

    # Tree in standalone (tools as tabs)
    python -m scriptree path/to/tree.scriptreetree -standalone

    # Tree standalone with a specific tree-level configuration
    python -m scriptree path/to/tree.scriptreetree -standalone -configuration production

``-configuration`` and ``-run`` both imply ``-standalone``. ``-run``
(V3 v0.3.5+) auto-clicks Run on the active tool once the standalone
window is up; the V3 cell shell uses it for click-to-run cells.

## For maintainers / LLMs

- HEADLESS PATH (L17 fixed): ``main()`` inspects ``raw_argv[0]`` for
  ``validate`` / ``migrate`` and dispatches to ``.cli.validate`` /
  ``.cli.migrate`` BEFORE any Qt is touched. Those CLI subcommands
  are pure stdlib and must run with no display. PySide6 is imported
  **inside the GUI branch of** ``main()`` only — never at module
  scope — so the headless dispatch is genuinely Qt-free (verified by
  ``tests/test_core_purity.py``'s subprocess check). Do NOT hoist
  the ``from PySide6...`` import back up to module level or above the
  CLI-dispatch branch.
- ``main(argv=None)`` reads ``sys.argv[1:]`` for subcommand detection
  but passes ``argv`` (possibly ``None``) to ``_parse_args``; keep
  both in sync when changing argument plumbing. Returns an int exit
  code (CLI subcommand return or ``app.exec()``).
- Argparse uses single-dash long options (``-standalone``,
  ``-configuration``, ``-run``) intentionally — not GNU ``--`` — to
  match the documented CLI surface; ``args.standalone`` is the
  attribute name argparse derives from ``-standalone``.
- ``standalone`` is derived as ``args.standalone or
  args.configuration is not None or args.run`` — preserve that OR so
  ``-configuration`` / ``-run`` keep implying ``-standalone``.
- ``_autorun_active_tool`` is deferred via ``QTimer.singleShot(0,…)``
  so construction-time signals settle before the synthetic click; it
  introspects ``win._runner`` (from-tool) or ``win._tabs`` (from-tree)
  by duck-typing and only clicks ``_btn_run`` when it ``isEnabled()``,
  so capability gates / sanitisation prompts still apply. Its broad
  ``except Exception`` is intentional (a failed convenience click must
  not crash startup) but it swallows the error to stderr only.
- GUI-only imports (branding, io, windows, QTimer) are lazy by design
  to keep the headless path Qt-light; do not hoist them.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# L17 fix: PySide6 is NOT imported at module scope.  ``main()``
# dispatches the headless ``validate`` / ``migrate`` subcommands
# BEFORE any QApplication is built; a top-level Qt import made even
# ``python -m scriptree validate …`` force-load Qt (and fail on a
# headless box with no Qt platform plugin).  The Qt import now lives
# inside the GUI branch of ``main()``.


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="scriptree",
        description="ScripTree \u2014 a GUI tool launcher for CLI commands.",
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Path to a .scriptree or .scriptreetree file to open.",
    )
    parser.add_argument(
        "-standalone",
        action="store_true",
        default=False,
        help=(
            "Open the file in a standalone window instead of the "
            "IDE. For .scriptreetree files, each tool gets its own tab."
        ),
    )
    parser.add_argument(
        "-configuration",
        metavar="NAME",
        default=None,
        help=(
            "Configuration name to apply. For a .scriptree file, "
            "activates that tool configuration. For a .scriptreetree "
            "file, selects the tree-level configuration that maps "
            "each sub-tool to its own config. Implies -standalone."
        ),
    )
    parser.add_argument(
        "-run",
        action="store_true",
        default=False,
        help=(
            "After the standalone window opens, immediately click "
            "Run on the active tool.  Implies -standalone.  Used by "
            "the V3 cell shell when a cell is configured for "
            "click-to-run (cell.click_action = \"run\" in the "
            "catalog JSON)."
        ),
    )
    return parser.parse_args(argv)


def _autorun_active_tool(win) -> None:  # noqa: ANN001
    """Click the Run button on the standalone window's active tool.

    V3 v0.3.5+ — invoked via ``QTimer.singleShot(0, ...)`` so the
    window's construction-time signals (config loaded, form populated,
    visibility hooks) finish before we synthesise the click.

    The standalone window can host either a single ``ToolRunnerView``
    (for a ``.scriptree`` file) or a tabbed window of runners (for
    a ``.scriptreetree`` file launched in flat mode).  We trigger
    ``_btn_run.click()`` on whichever runner is currently visible —
    that respects the same code path as a real human click,
    including sanitisation warnings, run-tools capability gates,
    and credential prompts.
    """
    try:
        # Lazy attribute lookup — avoids a hard import dep on
        # standalone_window from main's top-of-file.
        runner = None
        # StandaloneWindow.from_tool stashes the runner directly.
        if hasattr(win, "_runner") and getattr(win, "_runner", None):
            runner = win._runner
        # StandaloneWindow.from_tree uses a tab widget — pick the
        # currently-visible tab's runner.
        elif hasattr(win, "_tabs"):
            current = win._tabs.currentWidget()
            if current is not None and hasattr(current, "_btn_run"):
                runner = current
        if runner is not None and hasattr(runner, "_btn_run"):
            if runner._btn_run.isEnabled():
                runner._btn_run.click()
    except Exception as exc:  # noqa: BLE001
        import sys
        print(
            f"[scriptree -run] auto-click failed: {exc!r}",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    # v0.5.0 — CLI subcommand dispatch.  When invoked as
    # ``scriptree validate <path>`` or ``scriptree migrate <path>``
    # we hand off to the relevant module BEFORE constructing a
    # QApplication (the CLI subcommands are pure stdlib + Python
    # core — no Qt, no display required).
    raw_argv = list(sys.argv[1:]) if argv is None else list(argv)
    if raw_argv and raw_argv[0] in ("validate", "migrate"):
        sub = raw_argv[0]
        rest = raw_argv[1:]
        if sub == "validate":
            from .cli.validate import main as _validate_main
            return _validate_main(rest)
        from .cli.migrate import main as _migrate_main
        return _migrate_main(rest)

    # GUI path only — import Qt here (NOT at module scope) so the
    # headless CLI dispatch above never forces a Qt load (L17 fix).
    from PySide6.QtWidgets import QApplication, QStyleFactory

    args = _parse_args(argv)

    app = QApplication(sys.argv)

    # Brand the app: custom icon for title bar / taskbar / Dock, and
    # on Windows pin our own AppUserModelID so the taskbar doesn't
    # group us under generic "Python". Call this before any windows
    # are created. No-op if the icon resources aren't present.
    from .core.branding import apply_branding, apply_tool_branding
    apply_branding(app)

    # v0.8.0a25 -- if we're launching with a specific catalog file
    # (the standalone / -run flow used by the cell shell when the
    # user clicks a tool), give the subprocess its OWN taskbar
    # identity + icon based on the catalog's ``cell_icon_data``.
    # Without this every launched tool appears on the taskbar under
    # the generic ScripTree forest icon.  Must run BEFORE any
    # window is created so the per-process AppUserModelID applies
    # to every HWND this subprocess opens.  No-op when args.file
    # is None or the catalog has no embedded icon.
    if args.file:
        try:
            apply_tool_branding(app, args.file)
        except Exception as exc:  # noqa: BLE001
            # Branding is cosmetic -- never block startup over it.
            print(
                f"main: apply_tool_branding raised {exc!r}; "
                f"continuing with generic ScripTree icon",
                file=sys.stderr,
            )

    # Use the native Windows style where available. On Linux/macOS this
    # falls through to the platform default.
    for style in ("windowsvista", "windows11", "fusion"):
        if style in QStyleFactory.keys():
            app.setStyle(style)
            break

    # -configuration AND -run both imply -standalone.
    standalone = (
        args.standalone or args.configuration is not None or args.run
    )

    if args.file and standalone:
        # Standalone mode — lightweight window with optional config.
        from .core.io import load_tool, load_tree
        from .ui.standalone_window import StandaloneWindow

        file_path = str(Path(args.file).resolve())
        if file_path.endswith(".scriptreetree"):
            win = StandaloneWindow.from_tree(
                file_path,
                config_overrides=None,
            )
        else:
            tool = load_tool(file_path)
            win = StandaloneWindow.from_tool(
                tool, file_path, config_name=args.configuration
            )
        win.show()
        # ``-run`` (V3 v0.3.5+) — auto-click the Run button on the
        # active runner once the window is up.  We defer via a 0-ms
        # ``QTimer.singleShot`` so the window finishes its
        # construction-time signals (config loaded, form populated)
        # before we synthesise the click.
        if args.run:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: _autorun_active_tool(win))
    else:
        # Normal IDE window.
        from .ui.main_window import MainWindow

        window = MainWindow()
        window.show()
        if args.file:
            file_path = str(Path(args.file).resolve())
            window.open_file(file_path)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
