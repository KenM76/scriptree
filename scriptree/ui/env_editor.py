"""A shared popup for editing environment variables and PATH prepends.

Used by both the tool editor (editing ``ToolDef.env`` /
``ToolDef.path_prepend``) and the tool runner (editing the active
configuration's env overrides). The dialog is deliberately text-based:
a monospace ``QPlainTextEdit`` for env vars (one ``KEY=value`` per
line) and another for directories (one per line). Parsing happens on
Accept — malformed lines are reported via ``QMessageBox.warning`` and
the dialog stays open so the user can fix them.

Why text boxes and not a KEY/VALUE table:
    - Copy/paste from other sources (``.env`` files, shell exports)
      round-trips cleanly.
    - No per-row widget boilerplate, so the widget is easy to test.
    - Comment lines (``# ...``) are preserved as a "notes" channel.
"""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


class EnvEditorDialog(QDialog):
    """Dialog for editing ``(env, path_prepend)`` pairs.

    Constructor takes the current values. The caller reads the
    updated values via :meth:`result_env` and :meth:`result_paths`
    after ``exec`` returns :attr:`QDialog.DialogCode.Accepted`.

    Comment and blank lines are preserved in the env text box but
    not returned in the parsed result — they're stripped during
    :meth:`_parse_env`. This lets users keep notes inline without
    affecting the child process environment.
    """

    def __init__(
        self,
        env: dict[str, str],
        path_prepend: list[str],
        title: str = "Environment",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 460)

        self._result_env: dict[str, str] = {}
        self._result_paths: list[str] = []

        layout = QVBoxLayout(self)

        # Known-broken warning. The merge order of os.environ ->
        # global -> tool -> config (and the override-checkbox logic
        # that flips the layering) doesn't reliably reach child
        # processes in v0.1.x — see issue tracker. Saved values
        # round-trip through .scriptree / sidecar correctly; the
        # bug is in how those values get applied at spawn time.
        warning = QLabel(
            "<b>\u26a0 Heads up:</b> the env-var / PATH-prepend "
            "feature is <b>not fully working yet</b>. Edits save "
            "and persist, but they may not actually reach the "
            "child process at run time. To be fixed in a later "
            "release; for now use OS-level environment variables "
            "if you need a guaranteed effect."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "QLabel { background-color: #fff3cd; color: #664d03; "
            "border: 1px solid #ffecb5; padding: 6px; "
            "border-radius: 4px; }"
        )
        layout.addWidget(warning)

        layout.addWidget(QLabel("<b>Environment variables</b>"))
        layout.addWidget(
            QLabel(
                "<i>One <code>KEY=value</code> per line. Lines starting "
                "with <code>#</code> are comments and are ignored.</i>"
            )
        )
        self._env_edit = QPlainTextEdit()
        mono = QFont()
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setFamily("Consolas")
        self._env_edit.setFont(mono)
        self._env_edit.setPlaceholderText("MY_VAR=hello\nAPI_KEY=secret")
        self._env_edit.setPlainText(_env_to_text(env))
        layout.addWidget(self._env_edit, stretch=2)

        layout.addWidget(QLabel("<b>PATH prepend (directories)</b>"))
        layout.addWidget(
            QLabel(
                "<i>One directory per line. Prepended to the child "
                "process's <code>PATH</code> (relative paths are "
                "resolved against the tool's working directory).</i>"
            )
        )
        self._path_edit = QPlainTextEdit()
        self._path_edit.setFont(mono)
        self._path_edit.setPlaceholderText("C:/tools/bin\n./vendor")
        self._path_edit.setPlainText("\n".join(path_prepend))
        layout.addWidget(self._path_edit, stretch=1)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # --- parsing --------------------------------------------------------

    def _on_accept(self) -> None:
        try:
            env = _parse_env(self._env_edit.toPlainText())
        except ValueError as e:
            QMessageBox.warning(
                self,
                "Invalid environment variable",
                str(e),
            )
            return
        paths = _parse_paths(self._path_edit.toPlainText())
        self._result_env = env
        self._result_paths = paths
        self.accept()

    # --- results --------------------------------------------------------

    def result_env(self) -> dict[str, str]:
        return dict(self._result_env)

    def result_paths(self) -> list[str]:
        return list(self._result_paths)


# --- helpers (module-level so tests can exercise them directly) ----------

def _env_to_text(env: dict[str, str]) -> str:
    return "\n".join(f"{k}={v}" for k, v in env.items())


def _parse_env(text: str) -> dict[str, str]:
    """Parse ``KEY=value`` lines into a dict.

    - Blank lines and lines starting with ``#`` are ignored.
    - Leading/trailing whitespace around the key is trimmed.
    - The value keeps any internal whitespace but loses its leading
      and trailing whitespace (so ``FOO = bar`` -> ``{'FOO': 'bar'}``).
    - Raises ``ValueError`` for any non-empty, non-comment line that
      doesn't contain an ``=``, or whose key isn't a valid identifier-
      ish token (letters, digits, underscore — Windows env var rules
      are lax but we keep this strict to catch typos).
    """
    out: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(
                f"Line {lineno}: expected KEY=value, got: {raw!r}"
            )
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"Line {lineno}: empty variable name")
        if not _is_valid_env_key(key):
            raise ValueError(
                f"Line {lineno}: invalid variable name {key!r} "
                "(only letters, digits and underscore allowed)"
            )
        out[key] = value
    return out


def _parse_paths(text: str) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def _is_valid_env_key(key: str) -> bool:
    if not key:
        return False
    if not (key[0].isalpha() or key[0] == "_"):
        return False
    return all(c.isalnum() or c == "_" for c in key)
