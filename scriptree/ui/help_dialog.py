"""Help viewer dialog.

## For humans

Renders the markdown files under ``help/`` with a tree navigator on the
left and a ``QTextBrowser`` rendering the selected page on the right.
Internal links between markdown files are resolved and navigable —
clicking a link in one page loads the target page in the same view.

The help content lives at the repository root in ``help/`` (alongside
the ``scriptree`` package). :func:`help_root` resolves this path
regardless of whether ScripTree is running from a source checkout or a
frozen executable. This module also hosts :func:`show_about`, the
"About ScripTree" dialog.

## For maintainers / LLMs

- The navigation tree is HAND-CURATED in ``build_help_tree`` — files
  are not auto-discovered, so new help pages must be added to that
  function explicitly (this is deliberate: keeps reading order and
  hides WIP/orphan files).
- ``help_root`` does NOT verify the directory exists; it returns
  ``<pkg parent>/help`` if that ``is_dir()`` else ``<cwd>/help``.
  Callers that care must check ``Path.is_dir()`` themselves;
  ``load_markdown`` degrades gracefully (shows the OSError text).
- Path-keyed reverse lookup (``_item_by_path``) stores
  ``node.path.resolve()`` keys; ``_navigate_to`` also resolves before
  lookup. Both sides must resolve or tree-selection sync silently
  fails — keep them symmetric.
- Anchor handling: ``MarkdownBrowser`` sets
  ``setOpenLinks(False)``/``setOpenExternalLinks(False)`` and routes
  clicks through ``_on_anchor``. Only relative / ``file`` / empty-
  scheme links to existing files are followed (``.md`` re-enters the
  viewer); external schemes are intentionally ignored — do NOT add a
  system-browser launch here (deliberate no-open policy).
- ``_navigate_to`` wraps ``setCurrentItem`` in
  ``blockSignals(True/False)`` to avoid re-entrant
  ``_on_tree_selection`` → ``_navigate_to`` recursion. Keep the guard
  if you change selection plumbing.
- ``show_about`` reads ``scriptree.__version__`` (kept in lockstep
  with ``pyproject.toml``) inside a broad ``except`` that falls back
  to ``"(unknown)"`` so the dialog always opens; the import is lazy
  to avoid forcing Qt on importers of this symbol.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


def help_root() -> Path:
    """Return the directory containing the help markdown files.

    Resolution order (v0.8.0a20+):

    1. ``<package parent>/docs`` — the standard source-checkout layout.
       (Was ``help/`` prior to v0.8.0a20; renamed to match the
       universal open-source ``docs/`` convention.)
    2. ``<cwd>/docs`` — a fallback for unusual install layouts.
    3. ``<package parent>/help`` — legacy fallback so end-user
       installs that haven't been refreshed since the rename still
       find their docs.
    4. ``<cwd>/help`` — legacy CWD fallback for the same reason.

    The function does not validate that the directory exists; callers
    that care should check :meth:`Path.is_dir`.
    """
    pkg_parent = Path(__file__).resolve().parent.parent.parent
    for candidate in (
        pkg_parent / "docs",
        Path.cwd() / "docs",
        pkg_parent / "help",
        Path.cwd() / "help",
    ):
        if candidate.is_dir():
            return candidate
    # Nothing exists -- return the *preferred* path so error messages
    # point at the right modern location.
    return pkg_parent / "docs"


# --- tree structure ----------------------------------------------------


@dataclass
class HelpNode:
    """One entry in the help navigation tree."""

    title: str
    path: Path | None = None  # None → a grouping folder, not a leaf page
    children: list["HelpNode"] = field(default_factory=list)


def build_help_tree(root: Path) -> list[HelpNode]:
    """Return the ordered navigation tree for the help viewer.

    We hand-curate the structure instead of auto-discovering files so
    the sidebar order matches reading order rather than directory sort
    order, and so orphan or work-in-progress files don't accidentally
    show up in the UI.
    """
    def leaf(title: str, rel: str) -> HelpNode:
        return HelpNode(title=title, path=root / rel)

    return [
        HelpNode(title="For humans", children=[
            leaf("Overview", "README.md"),
            leaf("Getting started", "getting_started.md"),
            leaf("The tool runner", "tool_runner.md"),
            leaf("The tool editor", "tool_editor.md"),
            leaf("Sections", "sections.md"),
            leaf("Configurations", "configurations.md"),
            leaf("Environment variables", "environment.md"),
            leaf("File formats", "file_formats.md"),
        ]),
        HelpNode(title="For LLMs", children=[
            leaf("Overview", "LLM/README.md"),
            leaf("Architecture", "LLM/architecture.md"),
            leaf(".scriptree format", "LLM/scriptree_format.md"),
            leaf(".scriptreetree format", "LLM/scriptreetree_format.md"),
            leaf("Configurations sidecar", "LLM/configurations_sidecar.md"),
            leaf("Argument template", "LLM/argument_template.md"),
            leaf("Param types and widgets", "LLM/param_types_widgets.md"),
            HelpNode(title="Parser rules", children=[
                leaf("Python scripts", "LLM/parsers/python_scripts.md"),
                leaf("Windows executables", "LLM/parsers/windows_exe.md"),
                leaf("GNU-style tools", "LLM/parsers/gnu_tools.md"),
            ]),
        ]),
        HelpNode(title="Writing parseable --help", children=[
            leaf("Overview", "parsers/README.md"),
            leaf("Python scripts", "parsers/python_scripts.md"),
            leaf("Windows executables", "parsers/windows_exe.md"),
            leaf("GNU-style tools", "parsers/gnu_tools.md"),
        ]),
    ]


# --- widgets -----------------------------------------------------------


class MarkdownBrowser(QTextBrowser):
    """A ``QTextBrowser`` that renders markdown files via ``setMarkdown``.

    ``QTextBrowser`` natively understands HTML but not markdown. The
    :meth:`load_markdown` helper reads a file from disk and feeds it to
    ``setMarkdown`` (Qt's built-in markdown-to-rich-text converter).
    Anchor clicks are intercepted so that relative links between help
    pages re-enter ``load_markdown`` instead of being swallowed or
    handed to the system browser.
    """

    pageRequested = Signal(Path)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setOpenLinks(False)  # we handle navigation ourselves
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self._on_anchor)
        self._current: Path | None = None

    def load_markdown(self, path: Path) -> None:
        """Render a markdown file in the browser."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            self.setPlainText(f"Error reading {path}:\n{e}")
            self._current = None
            return
        self._current = path
        self.setSearchPaths([str(path.parent)])
        self.setMarkdown(text)

    def current_path(self) -> Path | None:
        return self._current

    # --- internal link navigation ---------------------------------------

    def _on_anchor(self, url: QUrl) -> None:
        if url.isRelative() or url.scheme() in ("", "file"):
            # Resolve against the currently-loaded file's directory.
            if self._current is None:
                return
            target = (self._current.parent / url.path()).resolve()
            if target.is_file() and target.suffix.lower() == ".md":
                self.pageRequested.emit(target)
                return
            if target.is_file():
                self.pageRequested.emit(target)
                return
            # Fall through to external handling.
        # External — ignore; we intentionally don't open browsers here.


class HelpDialog(QDialog):
    """Top-level help window.

    A splitter with a ``QTreeWidget`` of help topics on the left and a
    :class:`MarkdownBrowser` on the right. Selecting a tree entry loads
    the corresponding markdown file; clicking a relative link inside a
    page also navigates the browser and updates the tree selection when
    possible.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        root: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ScripTree Help")
        self.resize(1000, 700)
        self.setModal(False)

        self._root = root or help_root()
        self._tree_data = build_help_tree(self._root)
        self._item_by_path: dict[Path, QTreeWidgetItem] = {}

        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        layout.addWidget(splitter, 1)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.itemSelectionChanged.connect(self._on_tree_selection)
        splitter.addWidget(self._tree)

        self._browser = MarkdownBrowser()
        self._browser.pageRequested.connect(self._navigate_to)
        splitter.addWidget(self._browser)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([260, 740])

        self._populate_tree()

        # Bottom button row.
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        # Show the first available page by default.
        first = self._first_leaf_path()
        if first is not None:
            self._navigate_to(first)

    # --- tree population ------------------------------------------------

    def _populate_tree(self) -> None:
        self._tree.clear()
        self._item_by_path.clear()
        for node in self._tree_data:
            self._add_node(node, parent=None)
        self._tree.expandAll()

    def _add_node(
        self,
        node: HelpNode,
        *,
        parent: QTreeWidgetItem | None,
    ) -> QTreeWidgetItem:
        if parent is None:
            item = QTreeWidgetItem(self._tree, [node.title])
        else:
            item = QTreeWidgetItem(parent, [node.title])
        if node.path is not None:
            # Store the resolved path as item data for reverse lookup.
            item.setData(0, Qt.ItemDataRole.UserRole, str(node.path))
            self._item_by_path[node.path.resolve()] = item
        for child in node.children:
            self._add_node(child, parent=item)
        return item

    def _first_leaf_path(self) -> Path | None:
        for node in self._tree_data:
            leaf = _first_leaf(node)
            if leaf is not None:
                return leaf
        return None

    # --- navigation -----------------------------------------------------

    def _on_tree_selection(self) -> None:
        items = self._tree.selectedItems()
        if not items:
            return
        raw = items[0].data(0, Qt.ItemDataRole.UserRole)
        if not raw:
            return
        self._browser.load_markdown(Path(raw))

    def _navigate_to(self, path: Path) -> None:
        """Show ``path`` in the browser and sync the tree selection."""
        path = path.resolve()
        self._browser.load_markdown(path)
        item = self._item_by_path.get(path)
        if item is not None:
            self._tree.blockSignals(True)
            self._tree.setCurrentItem(item)
            self._tree.blockSignals(False)


def _first_leaf(node: HelpNode) -> Path | None:
    if node.path is not None:
        return node.path
    for child in node.children:
        leaf = _first_leaf(child)
        if leaf is not None:
            return leaf
    return None


# --- about dialog ------------------------------------------------------


def show_about(parent: QWidget | None = None) -> None:
    """Show the 'About ScripTree' dialog.

    The version line is sourced from ``scriptree.__version__`` so it
    stays in sync with ``pyproject.toml``.  Falls back to "(unknown)"
    if the package somehow can't be introspected — the dialog still
    opens with a useful blurb either way.

    v0.6.29+ — also shows ``scriptree.__build_date__`` so the user
    can tell which build they're running when revisions happen
    quickly.  Silently omits the line for older ScripTree imports
    that lack the symbol.
    """
    from PySide6.QtWidgets import QMessageBox

    try:
        from scriptree import __version__ as _ver
    except Exception:  # noqa: BLE001
        _ver = "(unknown)"
    try:
        from scriptree import __build_date__ as _bd  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        _bd = ""

    build_line = f"<p><b>Built:</b> {_bd}</p>" if _bd else ""
    QMessageBox.about(
        parent,
        "About ScripTree",
        f"<h3>ScripTree</h3>"
        f"<p><b>Version:</b> {_ver}</p>"
        f"{build_line}"
        f"<p>A universal GUI generator for command-line tools.</p>"
        f"<p>Built with Python and PySide6.  See the Help menu for "
        f"documentation on building tools, configurations, and "
        f"environment overrides.</p>",
    )
