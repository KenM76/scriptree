"""
regex_helper.py — the modal Regex Helper dialog (Test / Library / Reference).

## For humans

Opens when the user clicks the 🔧 button next to any ``regex`` widget
in a tool form.  Three tabs:

1. **Test** — pattern + flags on top, a sample-text editor below, and
   live match highlighting in the sample as the user types.  Captures
   table breaks down matches by group.  "Use this pattern" returns
   the pattern + flags to the caller via ``accept()`` so the parent
   widget can adopt them.
2. **Library** — pre-built CommonRegex patterns (email, phone, url, …)
   in one section, the user's own saved patterns
   (``%APPDATA%/ScripTree/regex_library.json``) in another.  Selecting
   a row populates the Test tab so the user can verify before
   adopting.  An "Add current pattern" button promotes whatever's in
   the Test tab into the user library.
3. **Reference** — a static markdown cheatsheet rendered into a
   ``QTextBrowser``.  Zero deps.

Persisted UI state between launches (via ``QSettings``):

* ``regex_helper/last_sample`` — the sample text the user typed
  last time, so re-opening the dialog feels continuous.
* ``regex_helper/last_tab`` — index of the tab that was open at
  close time.

## For maintainers / LLMs

* ``RegexHelperDialog.open_for(initial_pattern, initial_flags,
  parent)`` is the public entry point.  Returns ``(pattern, flags)``
  or ``(None, None)`` if the user cancelled / closed without
  accepting.  The function name mirrors ``QFileDialog.getOpenFileName``
  so call-sites read fluently.
* The dialog itself is intentionally NOT exposed as a top-level
  widget for embedding -- it's modal and self-contained on purpose
  (avoids us having to deal with focus loss + popup grab cycles).
* Live highlighting goes through a ``_HighlightWorker`` that
  re-runs the regex 150 ms after the last edit (debounce) -- the
  debounce avoids re-running for every keystroke during a long
  pattern, which becomes noticeable on the bigger sample texts.
* The Library tab's "Add current pattern" reads the Test tab; this
  is deliberate ("save what I'm working on right now") rather than
  reading the caller's parent widget (which might be stale).
* Right-click on a USER library row offers Edit / Delete / Use.
  Right-click on a BUILTIN row offers only Use.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRegularExpression, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction, QColor, QSyntaxHighlighter, QTextCharFormat,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QSplitter, QStyle, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from .regex_library import (
    LibraryEntry, all_entries, builtin_entries, export_to_forest_folder,
    load_user_library, save_user_library,
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

_FLAG_MAP = {
    "i": ("Case insensitive", "Match without regard to letter case"),
    "m": ("Multiline",          "^ and $ match at every line boundary"),
    "s": ("Dot matches newline", ". matches newline characters too"),
    "x": ("Verbose / extended",  "Whitespace + # comments ignored in pattern"),
}


def _compile_pattern(pattern: str, flags: str) -> tuple[
    QRegularExpression, Optional[str],
]:
    """Build a ``QRegularExpression`` from pattern + flag string.

    Flag string is just the inline-flag letters concatenated, e.g.
    ``"im"``.  We prepend ``(?<letters>)`` to the pattern so the
    flags travel with it even when the user copies the result out.
    Returns ``(qre, error_or_None)``; the qre is always valid as a
    Python object but ``.isValid()`` is False when the pattern
    couldn't be parsed.
    """
    if flags:
        full = f"(?{flags}){pattern}"
    else:
        full = pattern
    qre = QRegularExpression(full)
    if not qre.isValid():
        return qre, qre.errorString() or "invalid regex"
    return qre, None


# --------------------------------------------------------------------------
# Live match highlighter for the sample text
# --------------------------------------------------------------------------

class _MatchHighlighter(QSyntaxHighlighter):
    """Paint every regex match in the sample editor with an alternating
    background colour so adjacent matches read clearly.

    ``set_pattern`` is the only mutator the dialog calls -- it
    triggers a full ``rehighlight`` so a freshly-typed pattern shows
    up immediately (Qt's QSyntaxHighlighter only re-runs on document
    edits otherwise, and we want the inverse here: re-run when the
    PATTERN changes, not when the document does).
    """
    _COLORS = (
        QColor(252, 232, 131, 180),   # warm yellow
        QColor(160, 217, 248, 180),   # cool blue
    )

    def __init__(self, document) -> None:  # noqa: ANN001
        super().__init__(document)
        self._qre: Optional[QRegularExpression] = None
        self._formats: list[QTextCharFormat] = []
        for c in self._COLORS:
            fmt = QTextCharFormat()
            fmt.setBackground(c)
            self._formats.append(fmt)

    def set_pattern(self, qre: Optional[QRegularExpression]) -> None:
        self._qre = qre if (qre is not None and qre.isValid()) else None
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802 -- Qt API
        if self._qre is None or not self._qre.isValid() or not text:
            return
        it = self._qre.globalMatch(text)
        n = 0
        while it.hasNext():
            m = it.next()
            start = m.capturedStart(0)
            length = m.capturedLength(0)
            if length <= 0:
                # Zero-width matches would infinite-loop globalMatch
                # on some Qt builds; guard explicitly.
                break
            self.setFormat(start, length, self._formats[n % 2])
            n += 1


# --------------------------------------------------------------------------
# The dialog
# --------------------------------------------------------------------------

class RegexHelperDialog(QDialog):
    """Modal regex helper.  Public entry point is the
    :meth:`open_for` classmethod -- prefer that over direct
    instantiation so call-sites stay one-liners."""

    SETTINGS_KEY_SAMPLE = "regex_helper/last_sample"
    SETTINGS_KEY_TAB = "regex_helper/last_tab"

    accepted_pattern_changed = Signal(str, str)

    def __init__(
        self,
        initial_pattern: str = "",
        initial_flags: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Regex helper")
        self.resize(720, 540)

        self._accepted_pattern: Optional[str] = None
        self._accepted_flags: Optional[str] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        self._tabs = QTabWidget(self)
        outer.addWidget(self._tabs)

        # Build each tab.  Test must come first because Library +
        # Reference reference back into it.
        self._build_test_tab()
        self._build_library_tab()
        self._build_reference_tab()

        # OK / Cancel row.
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel,
        )
        self._accept_btn = QPushButton("Use this pattern")
        self._accept_btn.setDefault(True)
        self._accept_btn.clicked.connect(self._on_accept)
        btns.addButton(self._accept_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        btns.rejected.connect(self.reject)
        outer.addWidget(btns)

        # Seed initial pattern + flags.
        self._pattern_edit.setText(initial_pattern)
        for letter, cb in self._flag_checks.items():
            cb.setChecked(letter in (initial_flags or ""))
        self._restore_sample_text()
        self._recompile_and_repaint()

        # Restore last-open tab.
        try:
            from PySide6.QtCore import QSettings
            s = QSettings()
            last = int(s.value(self.SETTINGS_KEY_TAB, 0) or 0)
            if 0 <= last < self._tabs.count():
                self._tabs.setCurrentIndex(last)
        except Exception:  # noqa: BLE001
            pass

    # --- Test tab ---------------------------------------------------------

    def _build_test_tab(self) -> None:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(6, 6, 6, 6)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Pattern row.
        pat_row = QHBoxLayout()
        self._pattern_edit = QLineEdit()
        self._pattern_edit.setPlaceholderText(
            r"e.g.  \b[A-Z][a-z]+\b   or   ^\d{3}-\d{4}$",
        )
        # Monospace for legibility -- regex characters look ugly in
        # proportional fonts.
        f = self._pattern_edit.font()
        f.setStyleHint(f.StyleHint.Monospace)
        f.setFamilies(["Consolas", "Cascadia Mono", "Menlo", "monospace"])
        self._pattern_edit.setFont(f)
        pat_row.addWidget(self._pattern_edit, 1)
        self._validity_lbl = QLabel("")
        self._validity_lbl.setMinimumWidth(20)
        pat_row.addWidget(self._validity_lbl)
        form.addRow("Pattern:", pat_row)

        # Flags row.
        flag_row = QHBoxLayout()
        self._flag_checks: dict[str, QCheckBox] = {}
        for letter, (label, tip) in _FLAG_MAP.items():
            cb = QCheckBox(f"{letter} ({label})")
            cb.setToolTip(tip)
            self._flag_checks[letter] = cb
            flag_row.addWidget(cb)
        flag_row.addStretch(1)
        form.addRow("Flags:", flag_row)
        v.addLayout(form)

        # Sample / matches splitter.
        split = QSplitter(Qt.Orientation.Vertical)
        self._sample_edit = QPlainTextEdit()
        self._sample_edit.setPlaceholderText(
            "Paste sample text here; matches highlight live as you "
            "type in the pattern above.",
        )
        sf = self._sample_edit.font()
        sf.setStyleHint(sf.StyleHint.Monospace)
        sf.setFamilies(["Consolas", "Cascadia Mono", "Menlo", "monospace"])
        self._sample_edit.setFont(sf)
        self._highlighter = _MatchHighlighter(self._sample_edit.document())
        split.addWidget(self._sample_edit)

        bot = QWidget()
        bv = QVBoxLayout(bot)
        bv.setContentsMargins(0, 0, 0, 0)
        self._match_count_lbl = QLabel("Matches: 0")
        bv.addWidget(self._match_count_lbl)
        self._match_table = QTableWidget(0, 3)
        self._match_table.setHorizontalHeaderLabels(["#", "Match", "Span"])
        self._match_table.horizontalHeader().setStretchLastSection(True)
        self._match_table.verticalHeader().setVisible(False)
        self._match_table.setEditTriggers(self._match_table.EditTrigger.NoEditTriggers)
        bv.addWidget(self._match_table)
        split.addWidget(bot)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        v.addWidget(split, 1)

        self._tabs.addTab(page, "Test")

        # Debounced re-run on pattern / flag / sample changes.
        self._recompile_timer = QTimer(self)
        self._recompile_timer.setSingleShot(True)
        self._recompile_timer.setInterval(150)
        self._recompile_timer.timeout.connect(self._recompile_and_repaint)

        def _schedule() -> None:
            self._recompile_timer.start()
        self._pattern_edit.textChanged.connect(_schedule)
        self._sample_edit.textChanged.connect(_schedule)
        for cb in self._flag_checks.values():
            cb.toggled.connect(_schedule)

    def _restore_sample_text(self) -> None:
        try:
            from PySide6.QtCore import QSettings
            s = QSettings()
            saved = s.value(self.SETTINGS_KEY_SAMPLE, "") or ""
            if saved:
                self._sample_edit.setPlainText(str(saved))
                return
        except Exception:  # noqa: BLE001
            pass
        # First-launch default: a friendly little example so the
        # user can see what live matching looks like before they
        # paste their own input.
        self._sample_edit.setPlainText(
            "Try a sample pattern in the field above, e.g.\n"
            "    \\b\\w+@\\w+\\.\\w+\\b\n\n"
            "Then edit this text -- alice@example.com, "
            "bob@scriptree.dev, c-d@x.io -- to see live matches.\n"
            "Press \"Use this pattern\" to send it back to the form.\n",
        )

    def _current_flags(self) -> str:
        return "".join(
            letter for letter, cb in self._flag_checks.items()
            if cb.isChecked()
        )

    def _recompile_and_repaint(self) -> None:
        pattern = self._pattern_edit.text()
        flags = self._current_flags()
        qre, err = _compile_pattern(pattern, flags)

        # Validity badge + line-edit styling.
        if not pattern:
            self._validity_lbl.setText("")
            self._validity_lbl.setToolTip("")
            self._pattern_edit.setStyleSheet("")
            self._accept_btn.setEnabled(False)
        elif err is None:
            self._validity_lbl.setText("✓")
            self._validity_lbl.setStyleSheet("color: #2c7a2c; font-weight: bold;")
            self._validity_lbl.setToolTip("Pattern parses cleanly.")
            self._pattern_edit.setStyleSheet(
                "QLineEdit { border: 1px solid #4caf50; }",
            )
            self._accept_btn.setEnabled(True)
        else:
            self._validity_lbl.setText("✗")
            self._validity_lbl.setStyleSheet("color: #c62828; font-weight: bold;")
            self._validity_lbl.setToolTip(f"Parse error: {err}")
            self._pattern_edit.setStyleSheet(
                "QLineEdit { border: 1px solid #e53935; "
                "background-color: #fff5f5; }",
            )
            self._pattern_edit.setToolTip(f"Parse error: {err}")
            self._accept_btn.setEnabled(False)

        # Repaint highlights + rebuild matches table.
        self._highlighter.set_pattern(qre if err is None else None)
        self._rebuild_match_table(qre if err is None else None)

    def _rebuild_match_table(
        self, qre: Optional[QRegularExpression],
    ) -> None:
        self._match_table.setRowCount(0)
        if qre is None or not qre.isValid():
            self._match_count_lbl.setText("Matches: 0")
            return
        text = self._sample_edit.toPlainText()
        if not text:
            self._match_count_lbl.setText("Matches: 0")
            return
        # Discover the maximum number of captures so we can size
        # the table columns dynamically.
        sample_match = qre.match(text)
        nfields = max(0, sample_match.lastCapturedIndex())
        cols = ["#", "Match", "Span"]
        for i in range(1, nfields + 1):
            cols.append(f"Group {i}")
        self._match_table.setColumnCount(len(cols))
        self._match_table.setHorizontalHeaderLabels(cols)

        rows: list[list[str]] = []
        it = qre.globalMatch(text)
        idx = 0
        while it.hasNext():
            m = it.next()
            length = m.capturedLength(0)
            if length <= 0:
                break  # zero-width match guard (see highlighter)
            idx += 1
            row = [
                str(idx),
                m.captured(0),
                f"{m.capturedStart(0)}-{m.capturedEnd(0)}",
            ]
            for g in range(1, nfields + 1):
                row.append(m.captured(g))
            rows.append(row)

        self._match_count_lbl.setText(f"Matches: {len(rows)}")
        self._match_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self._match_table.setItem(r, c, QTableWidgetItem(val))
        self._match_table.resizeColumnsToContents()

    # --- Library tab ------------------------------------------------------

    def _build_library_tab(self) -> None:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(6, 6, 6, 6)

        top = QHBoxLayout()
        top.addWidget(QLabel("Filter:"))
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Type to filter...")
        self._filter_edit.textChanged.connect(self._rebuild_library_list)
        top.addWidget(self._filter_edit, 1)
        v.addLayout(top)

        self._lib_list = QListWidget()
        self._lib_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._lib_list.customContextMenuRequested.connect(
            self._on_library_context_menu,
        )
        self._lib_list.itemDoubleClicked.connect(self._on_library_use)
        v.addWidget(self._lib_list, 1)

        button_row = QHBoxLayout()
        self._add_current_btn = QPushButton("Add current pattern...")
        self._add_current_btn.setToolTip(
            "Save the pattern + flags currently in the Test tab into "
            "your personal regex library."
        )
        self._add_current_btn.clicked.connect(self._on_add_current_pattern)
        button_row.addWidget(self._add_current_btn)

        self._use_lib_btn = QPushButton("Use selected")
        self._use_lib_btn.clicked.connect(
            lambda: self._on_library_use(self._lib_list.currentItem()),
        )
        button_row.addWidget(self._use_lib_btn)

        self._export_btn = QPushButton("Export to forest folder...")
        self._export_btn.setToolTip(
            "Copy your library to a folder next to a "
            ".scriptreeforest file (e.g. for Dropbox / OneDrive "
            "sync).  The %APPDATA% copy stays the source of truth; "
            "future edits go back there."
        )
        self._export_btn.clicked.connect(self._on_export_library)
        button_row.addWidget(self._export_btn)

        button_row.addStretch(1)
        v.addLayout(button_row)

        self._tabs.addTab(page, "Library")
        self._rebuild_library_list()

    def _rebuild_library_list(self) -> None:
        self._lib_list.clear()
        needle = self._filter_edit.text().lower().strip() if hasattr(
            self, "_filter_edit",
        ) else ""

        builtins = builtin_entries()
        user = load_user_library()

        def _match(e: LibraryEntry) -> bool:
            if not needle:
                return True
            hay = " ".join((e.name, e.description, e.pattern)).lower()
            return needle in hay

        def _section_header(label: str) -> None:
            item = QListWidgetItem(label)
            f = item.font()
            f.setBold(True)
            item.setFont(f)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._lib_list.addItem(item)

        def _add(e: LibraryEntry) -> None:
            label = (
                f"{e.name}\n"
                f"    {e.pattern}"
                + (f"   ({e.description})" if e.description else "")
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, e)
            self._lib_list.addItem(item)

        bi = [e for e in builtins if _match(e)]
        if bi:
            _section_header("─── Built-in (CommonRegex) ───")
            for e in bi:
                _add(e)

        u = [e for e in user if _match(e)]
        if u:
            _section_header("─── My patterns ───")
            for e in u:
                _add(e)

        if self._lib_list.count() == 0:
            empty = QListWidgetItem("(no patterns match the filter)")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._lib_list.addItem(empty)

    def _selected_entry(self) -> Optional[LibraryEntry]:
        item = self._lib_list.currentItem()
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, LibraryEntry):
            return None
        return data

    def _on_library_use(self, item: Optional[QListWidgetItem]) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        # Switch to the Test tab and populate so the user can verify
        # before adopting; they still have to click "Use this pattern".
        self._pattern_edit.setText(entry.pattern)
        for letter, cb in self._flag_checks.items():
            cb.setChecked(letter in entry.flags)
        self._tabs.setCurrentIndex(0)
        self._recompile_and_repaint()

    def _on_add_current_pattern(self) -> None:
        pattern = self._pattern_edit.text()
        if not pattern:
            QMessageBox.information(
                self, "Nothing to save",
                "Enter a pattern in the Test tab before saving.",
            )
            return
        name, ok = QInputDialog.getText(
            self, "Save pattern",
            "Short name for this pattern:",
        )
        if not ok or not name.strip():
            return
        entries = load_user_library()
        entries.append(LibraryEntry(
            name=name.strip(),
            pattern=pattern,
            description="",
            flags=self._current_flags(),
            source="user",
            notes="",
        ))
        save_user_library(entries)
        self._rebuild_library_list()

    def _on_library_context_menu(self, pos) -> None:  # noqa: ANN001
        entry = self._selected_entry()
        if entry is None:
            return
        menu = QMenu(self)
        menu.addAction("Use this pattern", lambda: self._on_library_use(None))
        if entry.source == "user":
            menu.addSeparator()
            menu.addAction("Edit...", lambda: self._on_edit_entry(entry))
            menu.addAction("Delete", lambda: self._on_delete_entry(entry))
        menu.exec(self._lib_list.mapToGlobal(pos))

    def _on_edit_entry(self, entry: LibraryEntry) -> None:
        new_name, ok = QInputDialog.getText(
            self, "Rename pattern", "Name:", text=entry.name,
        )
        if not ok or not new_name.strip():
            return
        entries = load_user_library()
        for e in entries:
            if (
                e.name == entry.name and e.pattern == entry.pattern
                and e.flags == entry.flags
            ):
                e.name = new_name.strip()
                break
        save_user_library(entries)
        self._rebuild_library_list()

    def _on_delete_entry(self, entry: LibraryEntry) -> None:
        if QMessageBox.question(
            self, "Delete pattern",
            f"Delete '{entry.name}' from your library?",
        ) != QMessageBox.StandardButton.Yes:
            return
        entries = [
            e for e in load_user_library()
            if not (
                e.name == entry.name and e.pattern == entry.pattern
                and e.flags == entry.flags
            )
        ]
        save_user_library(entries)
        self._rebuild_library_list()

    def _on_export_library(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Pick a folder to export the regex library into "
            "(e.g. next to your .scriptreeforest)",
        )
        if not folder:
            return
        target = export_to_forest_folder(Path(folder))
        QMessageBox.information(
            self, "Library exported",
            f"Wrote {target}\n\n"
            "Future edits still go to %APPDATA%/ScripTree/"
            "regex_library.json -- this export is a one-time copy.",
        )

    # --- Reference tab ----------------------------------------------------

    def _build_reference_tab(self) -> None:
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setMarkdown(_REFERENCE_MARKDOWN)
        # Slightly enlarged font for readability of small glyphs
        # like \b vs \B.
        f = browser.font()
        f.setPointSize(max(10, f.pointSize() + 1))
        browser.setFont(f)
        self._tabs.addTab(browser, "Reference")

    # --- Accept / reject --------------------------------------------------

    def _on_accept(self) -> None:
        pattern = self._pattern_edit.text()
        if not pattern:
            QMessageBox.information(
                self, "No pattern",
                "Enter a regex in the pattern field first.",
            )
            return
        _, err = _compile_pattern(pattern, self._current_flags())
        if err is not None:
            QMessageBox.warning(
                self, "Invalid regex",
                f"Cannot adopt -- the pattern doesn't parse:\n\n{err}",
            )
            return
        self._accepted_pattern = pattern
        self._accepted_flags = self._current_flags()
        self.accept()

    def closeEvent(self, ev) -> None:  # noqa: N802 -- Qt API
        try:
            from PySide6.QtCore import QSettings
            s = QSettings()
            s.setValue(
                self.SETTINGS_KEY_SAMPLE,
                self._sample_edit.toPlainText(),
            )
            s.setValue(self.SETTINGS_KEY_TAB, self._tabs.currentIndex())
            s.sync()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(ev)

    # --- Public entry -----------------------------------------------------

    @classmethod
    def open_for(
        cls,
        initial_pattern: str = "",
        initial_flags: str = "",
        parent: Optional[QWidget] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """Open the helper modally and return ``(pattern, flags)``.

        Both values are ``None`` when the user cancelled or closed
        the dialog without picking; otherwise both are non-None
        (flags may be empty string, never None).
        """
        dlg = cls(initial_pattern, initial_flags, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return (
                dlg._accepted_pattern or "",
                dlg._accepted_flags or "",
            )
        return (None, None)


# --------------------------------------------------------------------------
# Static reference cheatsheet
# --------------------------------------------------------------------------

_REFERENCE_MARKDOWN = """
# Regex quick reference

## Anchors
| Pattern | Matches |
|---|---|
| `^` | Start of line / string |
| `$` | End of line / string |
| `\\b` | Word boundary |
| `\\B` | Non-boundary |
| `\\A` | Start of input (multiline-insensitive) |
| `\\Z` | End of input |

## Character classes
| Pattern | Matches |
|---|---|
| `\\d` | Any digit (0-9) |
| `\\D` | Any non-digit |
| `\\w` | Word character (letter / digit / underscore) |
| `\\W` | Non-word character |
| `\\s` | Whitespace |
| `\\S` | Non-whitespace |
| `.` | Any character (except newline unless `(?s)` flag) |
| `[abc]` | Any of `a`, `b`, `c` |
| `[^abc]` | Anything *except* `a`, `b`, `c` |
| `[a-z]` | Range |

## Quantifiers
| Pattern | Matches |
|---|---|
| `?` | 0 or 1 |
| `*` | 0 or more |
| `+` | 1 or more |
| `{n}` | Exactly `n` |
| `{n,}` | At least `n` |
| `{n,m}` | Between `n` and `m` (inclusive) |
| Append `?` | Make any quantifier non-greedy (`*?`, `+?`, `{n,m}?`) |

## Groups
| Pattern | Matches |
|---|---|
| `(...)` | Capture group |
| `(?:...)` | Non-capturing group |
| `(?P<name>...)` | Named capture |
| `\\1`, `\\2`, ... | Back-reference to capture N |
| `\\k<name>` | Back-reference to named capture |

## Look-around
| Pattern | Matches |
|---|---|
| `(?=...)` | Positive lookahead |
| `(?!...)` | Negative lookahead |
| `(?<=...)` | Positive lookbehind |
| `(?<!...)` | Negative lookbehind |

## Inline flags
| Pattern | Effect |
|---|---|
| `(?i)` | Case-insensitive |
| `(?m)` | Multi-line (`^`/`$` match every line) |
| `(?s)` | Dotall (`.` matches newline) |
| `(?x)` | Verbose (whitespace + `#` comments ignored) |

Flags can be combined: `(?imx)`. Toggle them via the checkboxes in
the Test tab — they're prepended to the saved pattern so downstream
tools see them.

## Common pitfalls
- Forgetting to escape: `.` matches any char, write `\\.` for a literal period.
- Greedy vs lazy: `<.+>` matches as much as possible; `<.+?>` matches the smallest.
- Anchors in multi-line strings: enable `(?m)` so `^` / `$` match each line.
- Character classes don't need backslashes for most punctuation: `[.+*?]` is fine.
"""
