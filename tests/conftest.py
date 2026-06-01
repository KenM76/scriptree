"""Shared pytest fixtures for the ScripTree test suite.

Two responsibilities:

1. **Personal-config isolation** -- redirect ``user_configs/`` to a
   per-session temp dir so test runs don't pollute the real folder
   and individual cases stay deterministic.
2. **Non-interactive Qt** -- monkey-patch every blocking ``QMessageBox``,
   ``QFileDialog``, and ``QInputDialog`` static method to return a safe
   default *immediately*.  This is the session-wide safety net: any
   production code path that pops a modal dialog under test will get
   a synthetic "Cancel" / "Ok" answer instead of stalling the
   suite while waiting for a human to click.

   Individual tests may still re-patch these methods locally (e.g.
   to assert a specific message text, or to force a different button
   answer); their local ``staticmethod(...)`` override stays in effect
   for the duration of that test only.  The session fixture restores
   the no-op defaults on teardown via ``monkeypatch``.

   Patched methods and their return values:

   ============================================ ===================================
   Method                                        Returns
   ============================================ ===================================
   ``QMessageBox.warning / information /         ``QMessageBox.StandardButton.Ok``
   critical / about / aboutQt``
   ``QMessageBox.question``                      ``QMessageBox.StandardButton.No``
                                                 (the safer default for "are you sure?")
   ``QFileDialog.getOpenFileName /               ``("", "")`` -- user cancelled
   getSaveFileName``
   ``QFileDialog.getOpenFileNames``              ``([], "")``
   ``QFileDialog.getExistingDirectory``          ``""`` -- user cancelled
   ``QInputDialog.getText / getMultiLineText``   ``("", False)``
   ``QInputDialog.getInt / getDouble``           ``(0, False)`` / ``(0.0, False)``
   ``QInputDialog.getItem``                      ``("", False)``
   ============================================ ===================================

   We also patch ``QDialog.exec`` to return ``Rejected`` (0)
   immediately -- this catches every custom modal that escapes the
   static-helper net (e.g. ``InstallLocationDialog``,
   ``InstallConflictDialog``, ``SettingsDialog``, ``ToolEditor``).
   Production code that follows the standard
   ``if dlg.exec() == Accepted`` pattern reads "Rejected" as
   "user cancelled" and bails gracefully.

   This is safe because no test in the suite needs a real
   blocking ``QDialog.exec`` -- the three test files that DO call
   ``.exec()`` all use ``QEventLoop.exec`` (event-loop pumping,
   not modal), which is a different class entirely and not
   patched here.  ``QMenu.exec`` is also unpatched (inherits from
   ``QWidget``, not ``QDialog``).
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True, scope="session")
def _silence_qt_modals() -> None:  # noqa: PT004
    """Autouse, session-scoped: replace every blocking dialog static
    method with an immediate no-op so the test suite never stalls
    waiting for a human button-press.

    Session scope (vs function scope) so the patches stick across
    test boundaries -- a per-test ``monkeypatch`` would restore the
    real blocking method between tests, defeating the safety net
    for tests that forget to mock.
    """
    try:
        from PySide6.QtWidgets import (
            QDialog, QFileDialog, QInputDialog, QMessageBox,
        )
    except Exception:  # noqa: BLE001
        # No Qt available (e.g. pure-stdlib test environment).
        # Nothing to patch.
        yield
        return

    # ---- QMessageBox ----------------------------------------------------
    ok = QMessageBox.StandardButton.Ok
    no = QMessageBox.StandardButton.No

    QMessageBox.warning = staticmethod(lambda *a, **kw: ok)         # type: ignore[assignment]
    QMessageBox.information = staticmethod(lambda *a, **kw: ok)     # type: ignore[assignment]
    QMessageBox.critical = staticmethod(lambda *a, **kw: ok)        # type: ignore[assignment]
    QMessageBox.about = staticmethod(lambda *a, **kw: None)         # type: ignore[assignment]
    QMessageBox.aboutQt = staticmethod(lambda *a, **kw: None)       # type: ignore[assignment]
    # ``question`` defaults to "No" -- safest answer for any
    # "are you sure you want to delete X?" prompt that a wandering
    # test path might trigger.
    QMessageBox.question = staticmethod(lambda *a, **kw: no)        # type: ignore[assignment]

    # ---- QFileDialog ----------------------------------------------------
    QFileDialog.getOpenFileName = staticmethod(                     # type: ignore[assignment]
        lambda *a, **kw: ("", "")
    )
    QFileDialog.getSaveFileName = staticmethod(                     # type: ignore[assignment]
        lambda *a, **kw: ("", "")
    )
    QFileDialog.getOpenFileNames = staticmethod(                    # type: ignore[assignment]
        lambda *a, **kw: ([], "")
    )
    QFileDialog.getExistingDirectory = staticmethod(                # type: ignore[assignment]
        lambda *a, **kw: ""
    )

    # ---- QInputDialog ---------------------------------------------------
    QInputDialog.getText = staticmethod(                            # type: ignore[assignment]
        lambda *a, **kw: ("", False)
    )
    QInputDialog.getMultiLineText = staticmethod(                   # type: ignore[assignment]
        lambda *a, **kw: ("", False)
    )
    QInputDialog.getInt = staticmethod(                             # type: ignore[assignment]
        lambda *a, **kw: (0, False)
    )
    QInputDialog.getDouble = staticmethod(                          # type: ignore[assignment]
        lambda *a, **kw: (0.0, False)
    )
    QInputDialog.getItem = staticmethod(                            # type: ignore[assignment]
        lambda *a, **kw: ("", False)
    )

    # ---- QDialog.exec ---------------------------------------------------
    # Every custom modal (InstallLocationDialog, InstallConflictDialog,
    # SettingsDialog, ToolEditor, etc.) inherits from QDialog and uses
    # the standard ``if dlg.exec() == Accepted`` idiom.  Forcing a
    # ``Rejected`` return means production code reads it as
    # "user cancelled" and bails gracefully -- the test process never
    # stalls waiting for a click.
    rejected = QDialog.DialogCode.Rejected
    QDialog.exec = lambda self, *a, **kw: rejected                  # type: ignore[assignment]
    QDialog.exec_ = lambda self, *a, **kw: rejected                 # type: ignore[assignment]

    yield


@pytest.fixture(autouse=True)
def isolate_user_configs_dir(tmp_path_factory, monkeypatch):
    """Redirect personal configs to a per-session temp dir.

    Prevents test runs from polluting the real ``ScripTree/user_configs/``
    and keeps tests deterministic.
    """
    user_dir = tmp_path_factory.mktemp("user_configs")
    monkeypatch.setenv("SCRIPTREE_USER_CONFIGS_DIR", str(user_dir))
    yield user_dir
