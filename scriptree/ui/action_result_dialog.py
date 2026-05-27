"""Copy-friendly result popup for action buttons (V3 v0.8.0a11+).

## For humans

When a producer authors an ``ActionDef`` with ``popup="always"``
(or ``popup="auto"`` and the output is short), this dialog opens
after the action finishes so the user can copy the result text
into the clipboard with one click.  Two key invariants:

* The text is **selectable** -- standard click-and-drag / Ctrl-A /
  right-click → Copy / keyboard navigation all work.
* A **Copy** button at the bottom-left copies the entire visible
  output to the clipboard in one shot.

The dialog is non-modal so the user can leave it open while they
fire other actions; the runner doesn't depend on the dialog being
closed.  Closing it does not affect the output pane (the output
that streamed into the pane is preserved there regardless).

## For maintainers / LLMs

* ``maybe_show_action_result`` is the only public entry point.
  It's called from ``ToolRunnerView._on_finished`` *after* the
  worker has been torn down and the buttons re-enabled, so a
  click on Copy never races a still-running spawn.
* The "auto" decision uses :data:`AUTO_POPUP_MAX_LINES` -- short
  enough to be a "drop the result on screen so I can copy it"
  affordance, long enough to cover most diagnostic commands
  (``git status -s``, ``git log --oneline -10``, ``docker ps``,
  ``pip list --outdated``).  Tune via that constant; don't make
  the threshold per-action -- the user wants predictable behaviour
  across the catalog.
* Huge outputs are capped at :data:`MAX_VISIBLE_LINES` so the
  dialog can't lag on a 10-MB ``find /`` blast.  A truncation
  notice appears at the bottom directing the user back to the
  output pane (which has no cap).
* Error styling: when ``exit_code != 0`` the title gets a "⚠"
  prefix and the text widget paints the body in a red-tinted
  monospace so the user can tell at a glance that the action
  failed without scanning the content.
* The dialog has NO modal blocking -- the runner can spawn the
  next action while this dialog is still open.  This is
  intentional ("show me the results, let me get on with my work")
  and matches the spec's "non-modal" rule.
* Position memory uses QSettings keyed by ``<tool_name>::<action_id>``
  so the same action's dialog returns to the same screen position
  next time, but different actions get their own slots.  Reuses
  the project's existing QSettings ("ScripTree" / "ScripTree")
  namespace.
"""
from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


# Tunables -- see module docstring for the rationale.
AUTO_POPUP_MAX_LINES = 200
"""Output line count under which ``popup="auto"`` triggers the dialog."""

MAX_VISIBLE_LINES = 10_000
"""Hard cap on lines shown in the dialog before truncation kicks in.

Truncation is visible to the user (a note appended at the bottom);
the output pane is never truncated.
"""


class ActionResultDialog(QDialog):
    """Non-modal copy-friendly result viewer for one action run.

    Constructed with the captured output and an exit code; opens
    immediately and disposes itself when the user closes it.  The
    parent reference is used only for centring and clipboard owner
    -- the dialog does NOT inherit the parent's modality.
    """

    def __init__(
        self,
        parent: QWidget | None,
        *,
        tool_name: str,
        action_label: str,
        action_id: str,
        output_text: str,
        exit_code: int,
    ) -> None:
        super().__init__(parent)
        prefix = "⚠ " if exit_code != 0 else ""
        self.setWindowTitle(f"{prefix}{tool_name} — {action_label}")
        # Non-modal: user can leave it open while running more
        # actions.  ``Qt.NonModal`` is the default for QDialog but
        # we set it explicitly so the intent is documented.
        self.setModal(False)

        self._tool_name = tool_name
        self._action_id = action_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Header: brief stats so a glance answers "what happened?".
        line_count = output_text.count("\n") + (
            1 if output_text and not output_text.endswith("\n") else 0
        )
        status = (
            f"exit {exit_code}"
            if exit_code != 0 else "exit 0"
        )
        header_text = (
            f"<b>{action_label}</b> &nbsp;"
            f"<span style='color:#666;'>"
            f"({line_count} line{'s' if line_count != 1 else ''}, "
            f"{status})</span>"
        )
        self._header = QLabel(header_text)
        self._header.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self._header)

        # Body: read-only, selectable, monospace.  Truncate to
        # MAX_VISIBLE_LINES so a runaway action doesn't freeze the
        # dialog on materialisation.
        self._edit = QPlainTextEdit(self)
        self._edit.setReadOnly(True)
        self._edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = self._edit.font()
        font.setFamily("Consolas, Menlo, monospace")
        self._edit.setFont(font)
        if exit_code != 0:
            self._edit.setStyleSheet(
                "QPlainTextEdit { background: #fff5f5; "
                "color: #6a1a1a; }"
            )
        display_text, truncated = _truncate_for_display(output_text)
        self._edit.setPlainText(display_text)
        if truncated:
            self._edit.appendPlainText(
                f"\n--- output truncated at {MAX_VISIBLE_LINES} lines; "
                f"full output is in the main pane ---"
            )
        layout.addWidget(self._edit, 1)

        # Footer: Copy-all + Close.
        footer = QHBoxLayout()
        self._copy_btn = QPushButton("Copy")
        self._copy_btn.setToolTip(
            "Copy the entire visible output to the clipboard."
        )
        self._copy_btn.clicked.connect(self._copy_all)
        footer.addWidget(self._copy_btn)

        footer.addStretch(1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        footer.addWidget(close_btn)
        layout.addLayout(footer)

        # Default size sensible for diagnostic outputs.
        self.resize(720, 480)

        # Escape closes -- standard dialog ergonomics.
        QShortcut(QKeySequence("Esc"), self, self.close)
        # Ctrl-C copies the current selection (PlainTextEdit handles
        # this natively); also bind Ctrl-Shift-C to copy-all so a
        # power user can grab everything without reaching for the
        # mouse.
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, self._copy_all)

        # Position memory -- restore the last-known position for
        # this exact tool+action pair, so re-running the same action
        # leaves the dialog where the user last put it.
        self._restore_geometry()
        # Save on close.  ``finished`` fires for both Accept and
        # Reject paths.
        self.finished.connect(self._save_geometry)

    # ------------------------------------------------------------------
    # Copy / clipboard
    # ------------------------------------------------------------------

    def _copy_all(self) -> None:
        """Copy the entire visible body to the system clipboard.

        Uses ``QGuiApplication.clipboard()`` rather than going
        through ``self._edit.selectAll() + copy()`` so the user's
        current selection isn't disturbed.
        """
        QGuiApplication.clipboard().setText(self._edit.toPlainText())
        # One-shot visual feedback so the user knows the copy
        # happened -- temporarily relabel the button.
        original = self._copy_btn.text()
        self._copy_btn.setText("Copied")
        # Restore the label after a short tick.  ``QTimer`` would
        # need an import; reusing the dialog's own event loop via
        # ``QTimer.singleShot`` is cleaner -- inline import to keep
        # the module-level imports thin.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(900, lambda: self._copy_btn.setText(original))

    # ------------------------------------------------------------------
    # Geometry memory
    # ------------------------------------------------------------------

    def _geometry_key(self) -> str:
        return (
            f"action_result_dialog/"
            f"{self._tool_name}::{self._action_id}/geometry"
        )

    def _restore_geometry(self) -> None:
        s = QSettings("ScripTree", "ScripTree")
        geom = s.value(self._geometry_key())
        if geom is not None:
            self.restoreGeometry(geom)

    def _save_geometry(self, *_args: object) -> None:
        s = QSettings("ScripTree", "ScripTree")
        s.setValue(self._geometry_key(), self.saveGeometry())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate_for_display(text: str) -> tuple[str, bool]:
    """Cap ``text`` to :data:`MAX_VISIBLE_LINES`, returning the
    capped text and a flag.

    Returns ``(text, False)`` if no truncation was needed; otherwise
    ``(first_N_lines_joined, True)``.  Keeps the original line
    endings so monospace alignment is preserved.
    """
    if not text:
        return text, False
    lines = text.splitlines(keepends=True)
    if len(lines) <= MAX_VISIBLE_LINES:
        return text, False
    return "".join(lines[:MAX_VISIBLE_LINES]), True


def maybe_show_action_result(
    *,
    parent: QWidget,
    tool_name: str,
    action: object,  # ActionDef
    output_lines: Iterable[str],
    exit_code: int,
) -> ActionResultDialog | None:
    """Conditionally show the result dialog for a finished action.

    Decision matrix (matches the ``ActionDef.popup`` field's
    documented contract):

    * ``"never"`` (default) -> no dialog.
    * ``"always"`` -> always show.
    * ``"auto"`` -> show when output is <= ``AUTO_POPUP_MAX_LINES``
      lines; otherwise skip (the output pane is the better surface
      for long outputs).

    Returns the opened dialog (or ``None`` if the policy declined
    to show one).  Caller does not need to keep the reference --
    the dialog's parent ownership keeps it alive until close.

    ``action`` is typed as ``object`` rather than ``ActionDef`` to
    keep this module free of cross-imports; we duck-type the only
    three fields we need: ``popup``, ``label``, ``id``.
    """
    popup = getattr(action, "popup", "never")
    if popup not in ("always", "auto"):
        return None

    # Materialise the buffer once; ``count`` may be called twice
    # (once for the auto threshold, once for the dialog body) and a
    # bare iterable can only be consumed once.
    output_text = "".join(output_lines)
    if popup == "auto":
        line_count = output_text.count("\n") + (
            1 if output_text and not output_text.endswith("\n") else 0
        )
        if line_count > AUTO_POPUP_MAX_LINES:
            return None

    dlg = ActionResultDialog(
        parent,
        tool_name=tool_name,
        action_label=getattr(action, "label", getattr(action, "id", "Action")),
        action_id=getattr(action, "id", "action"),
        output_text=output_text,
        exit_code=exit_code,
    )
    dlg.show()
    return dlg
