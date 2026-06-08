"""
regex_widget.py — the ``Widget.REGEX`` param widget.

## For humans

A regex-specific param widget that gives users:

* A ``QLineEdit`` with **live validation** -- as the user types, the
  pattern is compiled via Qt's ``QRegularExpression``; the border
  turns green with a ✓ badge when valid, red with a ✗ badge + tooltip
  showing the parse error when not.  Debounced 150 ms so the colour
  doesn't flicker on every keystroke.
* A 🔧 **helper button** opens the modal :class:`RegexHelperDialog`
  with the current pattern + flags pre-loaded.  When the user
  accepts there, the new pattern + flags flow back into the line
  edit -- flags are encoded inline as a ``(?i)``-style prefix on
  the saved value so downstream regex engines see them.

The widget emits a plain string on ``valueChanged`` (the pattern +
any inline-flag prefix) -- nothing special on the wire, so tools
that take a regex CLI argument see no difference.

## For maintainers / LLMs

* Live validation goes through a 150 ms ``QTimer`` debounce.  Don't
  tighten that -- compiling a Python regex on every keystroke is
  cheap but the GUI stylesheet recompute is what causes the visible
  flicker on slow machines, and 150 ms is the empirical sweet spot.
* The helper button's icon is the same ``SP_FileDialogContentsView``
  glyph used by the "Open in developer editor" button in
  ``tree_popup.py`` -- intentional, for visual consistency across
  helper-style affordances.  If you change one, change the other.
* When the user accepts the helper, we set the line-edit text via
  ``setText`` (NOT ``setPlainText`` or signal-block trickery) so
  the normal ``textChanged`` chain runs and the validity badge
  updates without a manual repaint.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRegularExpression, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit, QStyle, QToolButton,
)

from scriptree.core.model import ParamDef
from scriptree.ui.widgets.param_widgets import ParamWidget


class RegexWidget(ParamWidget):
    """A regex-pattern input with live validation + helper dialog."""

    def __init__(self, param: ParamDef) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._edit = QLineEdit(str(param.default or ""))
        self._edit.setPlaceholderText(
            param.description[:80] or
            r"e.g.  \b[A-Z][a-z]+\b   or   ^\d{3}-\d{4}$"
        )
        # Monospace -- regex characters look ugly in proportional
        # fonts and the validation badge is meaningless if the user
        # can't read the glyphs.
        f = self._edit.font()
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setFamilies(["Consolas", "Cascadia Mono", "Menlo", "monospace"])
        self._edit.setFont(f)
        layout.addWidget(self._edit, 1)

        # Validity badge -- tiny label next to the field.
        self._badge = QLabel("")
        self._badge.setMinimumWidth(16)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._badge)

        # Helper button.
        self._helper_btn = QToolButton()
        style = QApplication.style()
        self._helper_btn.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView),
        )
        self._helper_btn.setText("")
        self._helper_btn.setToolTip(
            "Open the regex helper -- test, browse the library, "
            "and pick a flag set"
        )
        self._helper_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._helper_btn.clicked.connect(self._on_open_helper)
        layout.addWidget(self._helper_btn)

        # Debounced validation timer.
        self._validate_timer = QTimer(self)
        self._validate_timer.setSingleShot(True)
        self._validate_timer.setInterval(150)
        self._validate_timer.timeout.connect(self._validate)

        self._edit.textChanged.connect(self._on_text_changed)
        self._validate()

    # --- ParamWidget API --------------------------------------------------

    def get_value(self) -> str:
        return self._edit.text()

    def set_value(self, value: Any) -> None:
        self._edit.setText("" if value is None else str(value))

    # --- internal ---------------------------------------------------------

    def _on_text_changed(self, text: str) -> None:
        # Emit immediately (downstream code may want the partial
        # pattern), but defer the heavy validation paint.
        self.valueChanged.emit(text)
        self._validate_timer.start()

    def _validate(self) -> None:
        text = self._edit.text()
        if not text:
            self._badge.setText("")
            self._badge.setToolTip("")
            self._edit.setStyleSheet("")
            self._edit.setToolTip("")
            return
        qre = QRegularExpression(text)
        if qre.isValid():
            self._badge.setText("✓")
            self._badge.setStyleSheet(
                "color: #2c7a2c; font-weight: bold;",
            )
            self._badge.setToolTip("Pattern parses cleanly.")
            self._edit.setStyleSheet(
                "QLineEdit { border: 1px solid #4caf50; }",
            )
            self._edit.setToolTip("")
        else:
            err = qre.errorString() or "invalid regex"
            self._badge.setText("✗")
            self._badge.setStyleSheet(
                "color: #c62828; font-weight: bold;",
            )
            self._badge.setToolTip(f"Parse error: {err}")
            self._edit.setStyleSheet(
                "QLineEdit { border: 1px solid #e53935; "
                "background-color: #fff5f5; }",
            )
            self._edit.setToolTip(f"Parse error: {err}")

    def _on_open_helper(self) -> None:
        # Pull current pattern; strip any leading inline-flag block so
        # the helper presents the "naked" pattern to the user with the
        # checkboxes set independently.
        text = self._edit.text()
        pattern, flags = _split_inline_flags(text)

        # Lazy import to keep widget construction cheap on cold start
        # (the helper drags in QTextBrowser + QSyntaxHighlighter).
        from scriptree.ui.widgets.regex_helper import RegexHelperDialog
        new_pattern, new_flags = RegexHelperDialog.open_for(
            initial_pattern=pattern,
            initial_flags=flags,
            parent=self,
        )
        if new_pattern is None:
            return  # user cancelled
        # Round-trip the chosen flags into an inline-flag block so the
        # downstream regex engine receives them.  Empty flags => no
        # prefix.
        if new_flags:
            self._edit.setText(f"(?{new_flags}){new_pattern}")
        else:
            self._edit.setText(new_pattern)


def _split_inline_flags(text: str) -> tuple[str, str]:
    """Strip a leading ``(?xxx)`` inline-flag block off ``text``.

    Returns ``(pattern_without_flags, flags_string)``.  When the
    text doesn't start with an inline-flag block, returns the
    original text plus ``""``.  Only the canonical-shape block
    ``(?[imsx]+)`` is stripped -- a fancier construct like
    ``(?i-m)`` (turning flags off) is left in-place so it round-
    trips through the helper untouched.
    """
    if not text.startswith("(?"):
        return text, ""
    end = text.find(")")
    if end < 2:
        return text, ""
    body = text[2:end]
    # Only strip if body is purely flag letters from the simple set.
    if body and all(c in "imsx" for c in body):
        return text[end + 1:], body
    return text, ""
