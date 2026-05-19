"""Tests that pin the About dialog to the package version.

Per direction (v0.4.0): both the editor's Help → About dialog and
the cell shell's right-click → About should surface the current
``scriptree.__version__`` so users can confirm which build they're
running.  These tests pin the wiring (version exposed on the
package, dialog text contains it).
"""
from __future__ import annotations

import re

import pytest

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def test_version_string_is_semver_shape() -> None:
    """``scriptree.__version__`` is a non-empty string in
    ``MAJOR.MINOR.PATCH`` form (extra suffix allowed for
    pre-releases later)."""
    from scriptree import __version__
    assert isinstance(__version__, str)
    assert __version__, "version must not be empty"
    # Three numeric segments at minimum.
    assert re.match(r"^\d+\.\d+\.\d+", __version__), (
        f"version {__version__!r} doesn't look like MAJOR.MINOR.PATCH"
    )


def test_package_and_pyproject_versions_match() -> None:
    """``scriptree.__version__`` matches ``pyproject.toml``'s
    ``project.version``.  Drift between them means the package
    and the build tooling disagree on what to call this release —
    confusing for users and for any reproducible-build chain."""
    from pathlib import Path
    from scriptree import __version__

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    m = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert m, "couldn't find version line in pyproject.toml"
    assert m.group(1) == __version__, (
        f"pyproject.toml version {m.group(1)!r} doesn't match "
        f"scriptree.__version__ {__version__!r}"
    )


def test_editor_about_dialog_includes_version() -> None:
    """The Help → About dialog uses ``QMessageBox.about`` which
    creates and shows the dialog modally.  We exercise the
    function by patching ``QMessageBox.about`` to capture the
    text rather than actually showing a dialog (which would
    block the test runner)."""
    from PySide6.QtWidgets import QMessageBox
    from scriptree import __version__
    import scriptree.ui.help_dialog as help_dialog

    captured: dict[str, str] = {}

    def _fake_about(parent, title, text):
        captured["title"] = title
        captured["text"] = text

    real_about = QMessageBox.about
    QMessageBox.about = _fake_about  # type: ignore[assignment]
    try:
        help_dialog.show_about(None)
    finally:
        QMessageBox.about = real_about  # type: ignore[assignment]

    assert "About ScripTree" in captured["title"]
    assert __version__ in captured["text"], (
        f"About dialog text {captured['text']!r} doesn't contain "
        f"version {__version__!r}"
    )
