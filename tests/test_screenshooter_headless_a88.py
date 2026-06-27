"""Tests for the v0.8.0a88 headless-capture mode (``ToolRunnerView``).

## Why this exists

The headless screenshooter (``screenshooter.py``) renders ToolRunnerViews
WITHOUT a running event loop and with no user present — it builds the widget
and calls ``QWidget.grab()``; it never calls ``.show()`` or ``exec()``.  Two
runner behaviours block *forever* in that context and previously forced the
operator to hand-stub them before a SolidWorks-tool screenshot would render:

  1. **The modal personal-config collision prompt.**
     ``_load_personal_configs_with_collision_prompt`` opens a
     ``PersonalConfigCollisionDialog`` and calls ``.exec()`` when a tool has
     personal-config candidates but none match the tool's on-disk location.
     ``exec()`` spins a nested modal loop that never returns headless.
  2. **On-open choice providers.**  ``_run_provider`` shells out to a
     subprocess (e.g. a SolidWorks / combridge query) to populate a dropdown.
     With nothing there to answer, that subprocess hangs.

The fix is a single module flag, ``tool_runner.HEADLESS_CAPTURE``.  The
screenshooter sets it ``True`` in ``_ensure_app`` (the chokepoint every render
passes through) before constructing any widget.  When ``True`` the runner:

  * returns early from ``_load_personal_configs_with_collision_prompt`` at the
    prompt point — treated as "no personal configs loaded", exactly like the
    no-candidates path (the shared/sidecar default config is used), and
  * returns immediately from ``_run_provider`` — the combo simply stays
    unpopulated, which is fine for a snapshot.

The normal app leaves the flag ``False``, so interactive behaviour is
unchanged.

## What these tests pin

For each of the two guarded behaviours, a *pair* of tests:

  * **flag ON  → guarded** : the blocking call (dialog / provider subprocess)
    is NOT reached (a sentinel that raises if reached never fires).
  * **flag OFF → unchanged**: the blocking call IS reached (the sentinel
    raises), proving the guard is scoped to headless capture only and does not
    silently disable the feature for the real app.

All views are *constructed* with the flag ON so construction-time provider /
collision calls don't fire during setup; the flag is then toggled around the
direct method call under test via ``_run_with_flag``.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.io import save_tool  # noqa: E402
from scriptree.core.model import (  # noqa: E402
    ParamDef,
    ProviderSpec,
    ToolDef,
)
from scriptree.ui import tool_runner as tr  # noqa: E402
from scriptree.ui.tool_runner import ToolRunnerView  # noqa: E402


def _provider_tool() -> ToolDef:
    """A tool whose single param is populated by an on-open provider."""
    return ToolDef(
        name="prov_demo",
        executable="/bin/echo",
        argument_template=["{pick}"],
        params=[
            ParamDef(
                id="pick",
                label="Pick",
                choices_provider=ProviderSpec(
                    command=["provider-exe"], refresh="on_open",
                ),
            ),
        ],
    )


def _run_with_flag(flag: bool, fn):
    """Run ``fn`` with ``HEADLESS_CAPTURE`` forced to ``flag``, then restore."""
    prev = tr.HEADLESS_CAPTURE
    tr.HEADLESS_CAPTURE = flag
    try:
        return fn()
    finally:
        tr.HEADLESS_CAPTURE = prev


def _make_view(tmp_path: Path) -> ToolRunnerView:
    """Build a runner under headless capture so setup doesn't fire providers."""
    tool = _provider_tool()
    p = tmp_path / "prov_demo.scriptree"
    save_tool(tool, p)
    return _run_with_flag(
        True, lambda: ToolRunnerView(tool, file_path=str(p)),
    )


class _Reached(Exception):
    """Raised by a sentinel to prove a guarded code path WAS entered."""


# --- provider guard -------------------------------------------------------

def test_run_provider_skipped_when_headless(tmp_path, monkeypatch) -> None:
    """``_run_provider`` returns before shelling out under headless capture."""
    import scriptree.core.providers as providers

    def _must_not_run(*_a, **_kw):
        raise AssertionError(
            "resolve_provider must NOT run under headless capture"
        )

    monkeypatch.setattr(providers, "resolve_provider", _must_not_run)

    view = _make_view(tmp_path)
    try:
        param = view._tool.params[0]
        # Must return cleanly without ever calling resolve_provider.
        _run_with_flag(True, lambda: view._run_provider(param))
    finally:
        view.deleteLater()
        _app.processEvents()


def test_run_provider_runs_when_not_headless(tmp_path, monkeypatch) -> None:
    """Sanity: with the flag off, ``_run_provider`` DOES reach the provider."""
    import scriptree.core.providers as providers

    def _sentinel(*_a, **_kw):
        raise _Reached

    monkeypatch.setattr(providers, "resolve_provider", _sentinel)

    view = _make_view(tmp_path)
    try:
        param = view._tool.params[0]
        with pytest.raises(_Reached):
            _run_with_flag(False, lambda: view._run_provider(param))
    finally:
        view.deleteLater()
        _app.processEvents()


# --- personal-config collision-prompt guard -------------------------------

def _force_collision(monkeypatch, tmp_path: Path) -> None:
    """Make the runner take the 'candidates exist, none by location' branch."""
    monkeypatch.setattr(
        tr, "load_personal_configs_for",
        lambda *_a, **_kw: (None, [tmp_path / "fake.configs.json"]),
    )
    import scriptree.core.permissions as perms
    monkeypatch.setattr(perms, "can_read_personal", lambda *_a, **_kw: True)


def test_collision_prompt_skipped_when_headless(tmp_path, monkeypatch) -> None:
    """The modal collision dialog never opens under headless capture."""
    _force_collision(monkeypatch, tmp_path)

    def _must_not_open(*_a, **_kw):
        raise AssertionError(
            "PersonalConfigCollisionDialog must NOT open under headless capture"
        )

    monkeypatch.setattr(tr, "PersonalConfigCollisionDialog", _must_not_open)

    view = _make_view(tmp_path)
    try:
        _run_with_flag(
            True, view._load_personal_configs_with_collision_prompt,
        )
    finally:
        view.deleteLater()
        _app.processEvents()


def test_collision_prompt_reached_when_not_headless(
    tmp_path, monkeypatch,
) -> None:
    """Sanity: with the flag off, the collision dialog IS constructed."""
    _force_collision(monkeypatch, tmp_path)

    def _sentinel(*_a, **_kw):
        raise _Reached

    monkeypatch.setattr(tr, "PersonalConfigCollisionDialog", _sentinel)

    view = _make_view(tmp_path)
    try:
        with pytest.raises(_Reached):
            _run_with_flag(
                False, view._load_personal_configs_with_collision_prompt,
            )
    finally:
        view.deleteLater()
        _app.processEvents()


# --- screenshooter wiring -------------------------------------------------

def test_screenshooter_ensure_app_sets_flag() -> None:
    """``screenshooter._ensure_app`` flips the runner into headless capture."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_shot_under_test",
        str(Path(__file__).resolve().parent.parent / "screenshooter.py"),
    )
    assert spec and spec.loader
    shot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shot)

    prev = tr.HEADLESS_CAPTURE
    tr.HEADLESS_CAPTURE = False  # ensure _ensure_app is what turns it on
    try:
        shot._ensure_app()
        assert tr.HEADLESS_CAPTURE is True, (
            "_ensure_app must put the tool runner into headless-capture mode"
        )
    finally:
        tr.HEADLESS_CAPTURE = prev
