"""Editor dialog for a parameter's dynamic ``choices_provider``
(v0.6.0).

Launched from the tool-editor property panel's **Provider…** button,
mirroring how ``visibility_editor.VisibilityEditorDialog`` is a
self-contained dialog for the ``visible_when`` feature.

Edits, for the currently-selected :class:`ParamDef`:

  * whether it uses a provider at all (unchecking clears it →
    static ``choices`` behaviour returns),
  * the provider ``command`` (one argv token per line — never a
    shell string),
  * ``working_directory`` / ``refresh`` / ``timeout_sec`` / ``cache``,
  * ``depends_on`` (checkboxes of the *other* param ids),
  * ``select_all`` (enabled only when the param's widget is
    ``checkbox_list``).

On **OK** the values are validated by constructing a real
:class:`~scriptree.core.model.ProviderSpec` (its ``__post_init__``
is the single source of truth for legal ``refresh`` / ``cache`` /
``timeout`` / non-empty command); a bad combination shows an inline
error and keeps the dialog open.  The caller reads
:pyattr:`result_provider`, :pyattr:`result_depends_on`,
:pyattr:`result_select_all` after ``exec()`` returns ``Accepted``.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.model import (
    PROVIDER_CACHE_MODES,
    PROVIDER_REFRESH_MODES,
    ParamDef,
    ProviderSpec,
    Widget as WidgetKind,
)


class ProviderEditorDialog(QDialog):
    def __init__(
        self,
        param: ParamDef,
        other_param_ids: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Dynamic provider — {param.id}")
        self.setMinimumWidth(460)
        self._param = param

        # Results read by the caller after Accepted.
        self.result_provider: ProviderSpec | None = None
        self.result_depends_on: list[str] = list(param.depends_on)
        self.result_select_all: bool = bool(param.select_all)

        root = QVBoxLayout(self)

        self._enable = QCheckBox(
            "Use a dynamic provider for this parameter"
        )
        self._enable.setToolTip(
            "When on, this parameter's choices (enum / multiselect / "
            "checkbox_list) or its value (text / path / number / …) "
            "come from running the command below at form-open / "
            "refresh time instead of a static Choices list."
        )
        self._enable.toggled.connect(self._sync_enabled)
        root.addWidget(self._enable)

        form = QFormLayout()
        root.addLayout(form)

        self._command = QPlainTextEdit()
        self._command.setPlaceholderText(
            "../sw_bridge/sw_bridge.exe\nlist-open-drawings\n--json"
        )
        self._command.setToolTip(
            "Argv list — ONE token per line (never a shell string). "
            "Relative path on the first line resolves against the "
            ".scriptree file's directory, like the tool's executable; "
            "a bare name resolves via PATH."
        )
        self._command.setFixedHeight(86)
        form.addRow("Command:", self._command)

        self._workdir = QLineEdit()
        self._workdir.setPlaceholderText(
            "(optional — defaults like the tool's working directory)"
        )
        form.addRow("Working dir:", self._workdir)

        self._refresh = QComboBox()
        for mode in PROVIDER_REFRESH_MODES:
            self._refresh.addItem(mode, mode)
        self._refresh.setToolTip(
            "on_open: run once when the form is built.  "
            "manual: only when the user clicks Refresh.  "
            "on_change: re-run whenever a depends-on value changes "
            "(debounced ~250 ms; a Refresh button is shown too)."
        )
        form.addRow("Refresh:", self._refresh)

        self._timeout = QSpinBox()
        self._timeout.setRange(1, 600)
        self._timeout.setValue(15)
        self._timeout.setSuffix(" s")
        form.addRow("Timeout:", self._timeout)

        self._cache = QComboBox()
        for mode in PROVIDER_CACHE_MODES:
            self._cache.addItem(mode, mode)
        self._cache.setToolTip(
            "form_session: memoize per (command + upstream values) "
            "for the life of one open form.  none: always re-run.  "
            "An explicit Refresh always bypasses the cache."
        )
        form.addRow("Cache:", self._cache)

        # depends_on — checkboxes of the OTHER param ids.
        dep_box = QWidget()
        dep_layout = QVBoxLayout(dep_box)
        dep_layout.setContentsMargins(0, 0, 0, 0)
        dep_layout.setSpacing(1)
        self._dep_boxes: dict[str, QCheckBox] = {}
        if other_param_ids:
            for pid in other_param_ids:
                cb = QCheckBox(pid)
                cb.setChecked(pid in param.depends_on)
                self._dep_boxes[pid] = cb
                dep_layout.addWidget(cb)
        else:
            lbl = QLabel("(no other parameters to depend on)")
            lbl.setEnabled(False)
            dep_layout.addWidget(lbl)
        dep_scroll = QScrollArea()
        dep_scroll.setWidgetResizable(True)
        dep_scroll.setMaximumHeight(110)
        dep_scroll.setWidget(dep_box)
        dep_scroll.setToolTip(
            "Upstream params whose current values are sent to this "
            "provider on stdin, and whose change re-runs it when "
            "Refresh = on_change.  A cycle is rejected when the tool "
            "is saved / loaded."
        )
        form.addRow("Depends on:", dep_scroll)

        self._select_all = QCheckBox(
            "Show a select-all / none master checkbox"
        )
        # select_all is only legal with the checkbox_list widget.
        sa_ok = param.widget is WidgetKind.CHECKBOX_LIST
        self._select_all.setChecked(bool(param.select_all) and sa_ok)
        self._select_all.setEnabled(sa_ok)
        if not sa_ok:
            self._select_all.setToolTip(
                "Only available when this parameter's widget is "
                "'checkbox_list'."
            )
        form.addRow("Select all:", self._select_all)

        self._error = QLabel("")
        self._error.setStyleSheet("QLabel { color: #c0392b; }")
        self._error.setWordWrap(True)
        root.addWidget(self._error)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # Seed from the existing provider (if any).
        ps = param.choices_provider
        if ps is not None:
            self._enable.setChecked(True)
            self._command.setPlainText("\n".join(ps.command))
            self._workdir.setText(ps.working_directory or "")
            ri = self._refresh.findData(ps.refresh)
            self._refresh.setCurrentIndex(max(ri, 0))
            self._timeout.setValue(int(ps.timeout_sec))
            ci = self._cache.findData(ps.cache)
            self._cache.setCurrentIndex(max(ci, 0))
        else:
            self._enable.setChecked(False)
        self._sync_enabled(self._enable.isChecked())

    # -- helpers -----------------------------------------------------

    def _sync_enabled(self, on: bool) -> None:
        for w in (
            self._command, self._workdir, self._refresh,
            self._timeout, self._cache,
        ):
            w.setEnabled(on)
        for cb in self._dep_boxes.values():
            cb.setEnabled(on)
        # select_all keeps its own widget-type gate.
        if self._param.widget is WidgetKind.CHECKBOX_LIST:
            self._select_all.setEnabled(on)

    def _on_accept(self) -> None:
        if not self._enable.isChecked():
            # Provider cleared → static behaviour.
            self.result_provider = None
            self.result_depends_on = []
            self.result_select_all = (
                self._select_all.isChecked()
                and self._param.widget is WidgetKind.CHECKBOX_LIST
            )
            self.accept()
            return

        command = [
            ln.strip()
            for ln in self._command.toPlainText().splitlines()
            if ln.strip()
        ]
        try:
            spec = ProviderSpec(
                command=command,
                working_directory=(self._workdir.text().strip()
                                   or None),
                refresh=self._refresh.currentData(),
                timeout_sec=self._timeout.value(),
                cache=self._cache.currentData(),
            )
        except ValueError as exc:
            self._error.setText(str(exc))
            return

        deps = [
            pid for pid, cb in self._dep_boxes.items()
            if cb.isChecked()
        ]
        if self._param.id in deps:
            self._error.setText(
                "A parameter cannot depend on itself."
            )
            return

        self.result_provider = spec
        self.result_depends_on = deps
        self.result_select_all = (
            self._select_all.isChecked()
            and self._param.widget is WidgetKind.CHECKBOX_LIST
        )
        self.accept()


def apply_to_param(dialog: ProviderEditorDialog, param: ParamDef) -> None:
    """Write a finished dialog's results back onto ``param``.

    Centralised so the tool-editor callsite stays a one-liner and
    the not-both-static-choices-and-provider rule is enforced in one
    place (clearing static ``choices`` when a provider is set —
    they're mutually exclusive per the loader invariant)."""
    param.choices_provider = dialog.result_provider
    param.depends_on = list(dialog.result_depends_on)
    param.select_all = bool(dialog.result_select_all)
    if param.choices_provider is not None:
        # Mutually exclusive with a static list (ParamDef /
        # io.loader would otherwise reject the file).
        param.choices = []
        param.choice_labels = []
