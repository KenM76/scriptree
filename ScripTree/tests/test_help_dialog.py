"""Tests for the help viewer (``scriptree.ui.help_dialog``).

Covers:
- The curated navigation tree references real files on disk.
- ``help_root()`` points at a directory containing ``README.md``.
- Opening the dialog populates the tree and renders the first page.
- Programmatic navigation to a leaf path loads the file and updates
  the tree selection.
- Internal relative links fire the ``pageRequested`` signal and
  navigate the browser to the resolved path.
- ``MarkdownBrowser.load_markdown`` gracefully handles missing files.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.ui.help_dialog import (  # noqa: E402
    HelpDialog,
    MarkdownBrowser,
    build_help_tree,
    help_root,
)


def _all_leaf_paths(nodes) -> list[Path]:
    out: list[Path] = []
    for node in nodes:
        if node.path is not None:
            out.append(node.path)
        out.extend(_all_leaf_paths(node.children))
    return out


# --- help_root & tree structure ----------------------------------------


def test_help_root_contains_readme():
    root = help_root()
    assert root.is_dir(), f"help/ dir not found at {root}"
    assert (root / "README.md").is_file()


def test_every_leaf_in_tree_exists_on_disk():
    root = help_root()
    tree = build_help_tree(root)
    leaves = _all_leaf_paths(tree)
    # Sanity: at least the seven human-facing files we've written.
    assert len(leaves) >= 7
    missing = [p for p in leaves if not p.is_file()]
    assert not missing, f"help files missing: {missing}"


# --- MarkdownBrowser ---------------------------------------------------


def test_markdown_browser_loads_file():
    root = help_root()
    browser = MarkdownBrowser()
    browser.load_markdown(root / "README.md")
    assert browser.current_path() == root / "README.md"
    # setMarkdown converts to HTML → toPlainText strips the markup but
    # keeps the text, so we can sanity-check content survived.
    assert "ScripTree" in browser.toPlainText()


def test_markdown_browser_missing_file_shows_error(tmp_path):
    browser = MarkdownBrowser()
    bogus = tmp_path / "nope.md"
    browser.load_markdown(bogus)
    assert browser.current_path() is None
    assert "Error" in browser.toPlainText()


def test_markdown_browser_relative_link_emits_request():
    root = help_root()
    browser = MarkdownBrowser()
    browser.load_markdown(root / "README.md")

    received: list[Path] = []
    browser.pageRequested.connect(received.append)

    # Simulate an anchor click to a relative sibling file.
    browser.anchorClicked.emit(QUrl("getting_started.md"))
    assert len(received) == 1
    assert received[0].resolve() == (root / "getting_started.md").resolve()


# --- HelpDialog --------------------------------------------------------


def test_help_dialog_renders_first_page():
    dlg = HelpDialog()
    try:
        assert dlg._browser.current_path() is not None
        # First page in the curated tree is help/README.md.
        assert dlg._browser.current_path().name == "README.md"
    finally:
        dlg.deleteLater()


def test_help_dialog_navigate_updates_tree_selection():
    dlg = HelpDialog()
    try:
        root = help_root()
        target = root / "environment.md"
        dlg._navigate_to(target)
        assert dlg._browser.current_path() == target.resolve()
        items = dlg._tree.selectedItems()
        assert items and items[0].text(0) == "Environment variables"
    finally:
        dlg.deleteLater()


def test_help_dialog_tree_click_loads_page():
    dlg = HelpDialog()
    try:
        root = help_root()
        target = root / "configurations.md"
        item = dlg._item_by_path[target.resolve()]
        dlg._tree.setCurrentItem(item)
        # Qt processes selection synchronously; the slot should have
        # fired by now.
        assert dlg._browser.current_path() == target.resolve()
    finally:
        dlg.deleteLater()


def test_help_dialog_in_page_link_navigates():
    """A relative link inside a page should load the target AND sync
    the sidebar selection to match.
    """
    dlg = HelpDialog()
    try:
        root = help_root()
        # Start on README, then emit a synthetic anchor click for a
        # sibling help file and confirm both browser and tree update.
        dlg._navigate_to(root / "README.md")
        dlg._browser.anchorClicked.emit(QUrl("tool_runner.md"))
        assert dlg._browser.current_path() == (root / "tool_runner.md").resolve()
        items = dlg._tree.selectedItems()
        assert items and items[0].text(0) == "The tool runner"
    finally:
        dlg.deleteLater()
