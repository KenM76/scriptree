"""Shared dialog for "file not found" recovery.

Shown whenever ScripTree references a file that no longer exists on
disk — a tool file that a tree leaf points to, a tool's executable
path, a recently-opened file that has moved, etc.

The dialog:

- Displays a clear human-readable message explaining what's missing.
- Shows the expected path in a read-only ``QLineEdit`` that's
  selectable and copy-pasteable (supports keyboard Ctrl+C and a
  dedicated Copy button).
- Optionally offers a **Browse for replacement...** button that opens
  a native file picker. If the user picks a file, the dialog accepts
  with the new path available via :meth:`selected_replacement`.
- Offers a **Close** button that dismisses the dialog without action.

Permission enforcement is the caller's responsibility — pass
``allow_replace=False`` to hide the Browse button entirely (e.g. when
the user lacks ``edit_tree_structure`` / ``edit_tool_definition``).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class MissingFileRecoveryDialog(QDialog):
    """Modal dialog for recovering from a missing-file reference."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        title: str,
        message: str,
        missing_path: str,
        allow_replace: bool,
        file_filter: str = "All files (*)",
        browse_caption: str = "Select replacement file",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(580)
        self._replacement_path: str | None = None
        self._file_filter = file_filter
        self._browse_caption = browse_caption

        layout = QVBoxLayout(self)

        msg = QLabel(message)
        msg.setWordWrap(True)
        layout.addWidget(msg)

        layout.addWidget(QLabel("<b>Expected location:</b>"))

        path_row = QHBoxLayout()
        self._path_edit = QLineEdit(missing_path)
        self._path_edit.setReadOnly(True)
        # Start with the cursor at the beginning so the start of the
        # path is visible if the field is long.
        self._path_edit.setCursorPosition(0)
        # Keep read-only but allow selection + copy.
        self._path_edit.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        path_row.addWidget(self._path_edit, stretch=1)

        btn_copy = QPushButton("Copy")
        btn_copy.setToolTip("Copy the path to the clipboard.")
        btn_copy.clicked.connect(self._copy_path)
        path_row.addWidget(btn_copy)
        layout.addLayout(path_row)

        # Status label for "Replacement selected: ..." feedback.
        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        if not allow_replace:
            hint = QLabel(
                "<i>You don't have permission to replace this path. "
                "Copy it above and ask an administrator to fix the "
                "reference, or restore the file to the expected "
                "location.</i>"
            )
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #888;")
            layout.addWidget(hint)

        # Button row.
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        if allow_replace:
            btn_browse = QPushButton("Browse for replacement...")
            btn_browse.setToolTip(
                "Pick a replacement file. Accepting applies the new "
                "path and saves the change."
            )
            btn_browse.clicked.connect(self._browse)
            btn_row.addWidget(btn_browse)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(btn_close)

        layout.addLayout(btn_row)

    # --- slots ---------------------------------------------------------

    def _copy_path(self) -> None:
        QApplication.clipboard().setText(self._path_edit.text())
        self._status_label.setText(
            "<span style='color:#007700;'>Path copied to clipboard.</span>"
        )

    def _browse(self) -> None:
        start_dir = str(Path(self._path_edit.text()).parent)
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._browse_caption,
            start_dir,
            self._file_filter,
        )
        if not path:
            return
        self._replacement_path = path
        # Accept immediately — the user explicitly picked a replacement.
        self.accept()

    # --- result accessor ---------------------------------------------

    def selected_replacement(self) -> str | None:
        """Return the replacement path if one was picked, else None."""
        return self._replacement_path
