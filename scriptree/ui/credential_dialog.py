"""Dialog prompting for alternate credentials before a tool run.

## For humans

Shows a domain field (optional DOMAIN or computer name; blank = local),
a username, a password, and a "Remember for this session" checkbox. If
remembered, the credential store keeps the encrypted password in memory
until the application exits or the user clears it.

## For maintainers / LLMs

- Pure view: this dialog only collects input. It does NOT touch the
  credential store, encrypt anything, or run the tool — the caller
  reads :meth:`username` / :meth:`domain` / :meth:`password` /
  :meth:`remember` only after ``exec() == Accepted`` and is
  responsible for persistence and process launch.
- ``_validate_and_accept`` blocks ``accept()`` when username is blank
  (whitespace-stripped); it deliberately does NOT require a password
  (empty/blank passwords are a legitimate input to pass through).
- Accessors strip whitespace for username/domain but
  :meth:`password` is returned verbatim (leading/trailing spaces can
  be significant in a password) — preserve this asymmetry.
- Initial focus is placed on the first empty field
  (domain→username→password); keep this when adding fields.
- ``tool_name`` is interpolated into a rich-text ``QLabel`` without
  escaping — callers pass internal tool names, not untrusted input;
  do not relax that assumption.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)


class CredentialDialog(QDialog):
    """Prompt for username and password.

    After ``exec() == Accepted``, read :meth:`username`,
    :meth:`domain`, :meth:`password`, and :meth:`remember`.
    """

    def __init__(
        self,
        tool_name: str = "",
        prefill_username: str = "",
        prefill_domain: str = "",
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Run as different user")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)

        if tool_name:
            hint = QLabel(
                f"Enter credentials to run <b>{tool_name}</b> as a "
                "different user."
            )
            hint.setWordWrap(True)
            layout.addWidget(hint)

        form = QFormLayout()

        self._domain_edit = QLineEdit()
        self._domain_edit.setPlaceholderText("DOMAIN or computer name (blank = local)")
        self._domain_edit.setText(prefill_domain)
        form.addRow("Domain:", self._domain_edit)

        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText("Username")
        self._user_edit.setText(prefill_username)
        form.addRow("Username:", self._user_edit)

        self._pass_edit = QLineEdit()
        self._pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._pass_edit.setPlaceholderText("Password")
        form.addRow("Password:", self._pass_edit)

        layout.addLayout(form)

        self._chk_remember = QCheckBox(
            "Remember credentials for this session"
        )
        self._chk_remember.setToolTip(
            "Store these credentials (encrypted in memory) so you "
            "won't be prompted again until ScripTree is restarted."
        )
        layout.addWidget(self._chk_remember)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
        )
        btns.accepted.connect(self._validate_and_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # Focus the first empty field.
        if prefill_username:
            self._pass_edit.setFocus()
        elif prefill_domain:
            self._user_edit.setFocus()
        else:
            self._domain_edit.setFocus()

    def _validate_and_accept(self) -> None:
        if not self._user_edit.text().strip():
            self._user_edit.setFocus()
            return
        self.accept()

    # --- result accessors ---

    def username(self) -> str:
        return self._user_edit.text().strip()

    def domain(self) -> str:
        return self._domain_edit.text().strip()

    def password(self) -> str:
        return self._pass_edit.text()

    def remember(self) -> bool:
        return self._chk_remember.isChecked()
