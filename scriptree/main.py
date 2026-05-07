"""Application entry point.

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
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QStyleFactory


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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    app = QApplication(sys.argv)

    # Brand the app: custom icon for title bar / taskbar / Dock, and
    # on Windows pin our own AppUserModelID so the taskbar doesn't
    # group us under generic "Python". Call this before any windows
    # are created. No-op if the icon resources aren't present.
    from .core.branding import apply_branding
    apply_branding(app)

    # Use the native Windows style where available. On Linux/macOS this
    # falls through to the platform default.
    for style in ("windowsvista", "windows11", "fusion"):
        if style in QStyleFactory.keys():
            app.setStyle(style)
            break

    # -configuration implies -standalone.
    standalone = args.standalone or args.configuration is not None

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
