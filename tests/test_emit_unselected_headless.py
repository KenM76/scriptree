"""
test_emit_unselected_headless.py — v0.8.0a51 regression tests for
the headless / CLI ``emit: "unselected"`` path AND the editor's
"Default master state" radio picker.

What these pin (in addition to the v0.8.0a50 tests in
test_emit_unselected.py):

* ``apply_emit_complement`` (the new core helper) computes the
  complement at argv-assembly time, regardless of UI presence.
* The three-tier choice-set resolution:
    1. ``live_choices`` arg from the caller (the UI path).
    2. ``resolve_provider`` re-run when a provider is set and no
       live_choices was passed (the headless path that v0.8.0a50
       couldn't do).
    3. Static ``param.choices`` for non-provider catalogs.
* ``build_full_argv`` runs the complement exactly once (no
  double-application).
* The editor's three-radio default-state picker mutates
  ``param.default`` correctly and stays in sync with subsequent
  ``choices`` edits.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_VENDOR = Path(__file__).resolve().parent.parent / "lib" / "pypi"
if _VENDOR.is_dir():
    sys.path.insert(0, str(_VENDOR))

import pytest  # noqa: E402

from scriptree.core.model import (  # noqa: E402
    ParamDef, ParamType, ProviderSpec, ToolDef, Widget,
)
from scriptree.core.runner import (  # noqa: E402
    apply_emit_complement, build_full_argv,
)


# ---------------------------------------------------------------------------
# Tier 1: live_choices wins (UI path)
# ---------------------------------------------------------------------------

def test_complement_uses_live_choices_when_supplied() -> None:
    """When the caller passes ``live_choices``, those are the source
    of truth -- static ``param.choices`` is ignored even when it
    differs.  This is the UI path: the widget knows the current
    set (post-provider) and tells the runner."""
    p = ParamDef(
        id="opts", type=ParamType.MULTISELECT,
        widget=Widget.CHECKBOX_LIST,
        choices=["static_a", "static_b"],   # stale; should be ignored
        emit="unselected",
    )
    tool = ToolDef(name="t", executable="x", params=[p])
    values = {"opts": ["LIVE2"]}
    apply_emit_complement(
        tool, values,
        live_choices={"opts": ["LIVE1", "LIVE2", "LIVE3"]},
    )
    assert values["opts"] == ["LIVE1", "LIVE3"]


# ---------------------------------------------------------------------------
# Tier 3: static fallback (headless static-choices path)
# ---------------------------------------------------------------------------

def test_complement_falls_back_to_static_choices_headless() -> None:
    """No live_choices, no provider -> use ``param.choices``.
    Order is preserved in the result."""
    p = ParamDef(
        id="opts", type=ParamType.MULTISELECT,
        widget=Widget.CHECKBOX_LIST,
        choices=["a", "b", "c", "d", "e"],
        emit="unselected",
    )
    tool = ToolDef(name="t", executable="x", params=[p])
    values = {"opts": ["d", "a"]}  # arbitrary user-selection order
    apply_emit_complement(tool, values)
    # Complement preserves CHOICES order, not selected order.
    assert values["opts"] == ["b", "c", "e"]


def test_emit_selected_is_passthrough() -> None:
    """``emit: "selected"`` (the default) is a no-op even in
    apply_emit_complement.  The values dict round-trips unchanged."""
    p = ParamDef(
        id="opts", type=ParamType.MULTISELECT,
        widget=Widget.CHECKBOX_LIST, choices=["a", "b", "c"],
    )
    tool = ToolDef(name="t", executable="x", params=[p])
    values = {"opts": ["a", "b"]}
    apply_emit_complement(tool, values)
    assert values["opts"] == ["a", "b"]


def test_empty_choices_emit_empty() -> None:
    """Degenerate case: zero choices on either side -> empty
    complement, regardless of mode."""
    p = ParamDef(
        id="opts", type=ParamType.MULTISELECT,
        widget=Widget.CHECKBOX_LIST,
        choices=[], emit="unselected",
    )
    tool = ToolDef(name="t", executable="x", params=[p])
    values = {"opts": []}
    apply_emit_complement(tool, values)
    assert values["opts"] == []


# ---------------------------------------------------------------------------
# Tier 2: provider re-run headlessly
# ---------------------------------------------------------------------------

@pytest.fixture
def provider_stub_script(tmp_path: Path) -> Path:
    """A tiny Python script that prints a fake provider response.

    Used as a ``ProviderSpec.command`` target so we can exercise
    the headless ``resolve_provider`` re-run path without leaning
    on combridge or any external binary.
    """
    script = tmp_path / "fake_provider.py"
    script.write_text(
        "import json, sys\n"
        "print(json.dumps({"
        "'choices': ['p1', 'p2', 'p3'], "
        "'default': ['p1', 'p2', 'p3']"
        "}))\n",
        encoding="utf-8",
    )
    return script


def test_complement_reruns_provider_when_no_live_choices(
    provider_stub_script: Path,
) -> None:
    """Headless path: emit:unselected param has a provider, no
    live_choices was passed -> apply_emit_complement re-invokes
    the provider via resolve_provider, uses its choices, computes
    the complement.  This is what v0.8.0a50 couldn't do."""
    spec = ProviderSpec(
        command=[sys.executable, str(provider_stub_script)],
    )
    p = ParamDef(
        id="opts", type=ParamType.MULTISELECT,
        widget=Widget.CHECKBOX_LIST,
        choices_provider=spec, emit="unselected",
    )
    tool = ToolDef(name="t", executable="x", params=[p])
    values = {"opts": ["p2"]}
    apply_emit_complement(tool, values)
    # Provider returned ['p1', 'p2', 'p3'].  Selected = ['p2'].
    # Complement = ['p1', 'p3'] in choices order.
    assert values["opts"] == ["p1", "p3"]


def test_complement_provider_failure_emits_empty_list(
    tmp_path: Path,
) -> None:
    """If the provider invocation fails (script not found / crashes /
    returns garbage), the complement falls back to empty.

    A provider-backed param has no static ``choices`` (the
    structural invariant forbids both), so the only available
    fallback when the provider fails is an empty list.  The
    complement of any selection against an empty choice set is
    ``[]``.  Token-group drop-on-empty then makes Run a no-op
    for that flag, which is the safe behaviour -- the run isn't
    blocked, the param simply contributes nothing.
    """
    spec = ProviderSpec(
        command=[sys.executable, str(tmp_path / "does_not_exist.py")],
    )
    p = ParamDef(
        id="opts", type=ParamType.MULTISELECT,
        widget=Widget.CHECKBOX_LIST,
        choices_provider=spec, emit="unselected",
    )
    tool = ToolDef(name="t", executable="x", params=[p])
    values = {"opts": ["whatever"]}
    # Should NOT raise; falls through to the static (empty) list.
    apply_emit_complement(tool, values)
    assert values["opts"] == []


# ---------------------------------------------------------------------------
# build_full_argv integration (the end-to-end argv path)
# ---------------------------------------------------------------------------

def test_build_full_argv_applies_complement_once(tmp_path: Path) -> None:
    """The whole argv-assembly chain: build_full_argv invokes
    apply_emit_complement exactly once.  The resulting argv carries
    the complement values, not the selected ones."""
    # ``executable`` must be a real-ish path; use sys.executable.
    p = ParamDef(
        id="opts", type=ParamType.MULTISELECT,
        widget=Widget.CHECKBOX_LIST,
        choices=["x", "y", "z"],
        emit="unselected",
    )
    tool = ToolDef(
        name="t", executable=sys.executable,
        argument_template=[["--flag", "{opts}"]],
        params=[p],
    )
    cmd = build_full_argv(
        tool, {"opts": ["y"]}, extras=[],
        ignore_required=True,
    )
    # Fan-out group: one --flag <val> per emitted value, in choices
    # order.  Complement of [y] against [x, y, z] is [x, z].
    # argv = [exe, "--flag", "x", "--flag", "z"]
    assert cmd.argv[1:] == ["--flag", "x", "--flag", "z"]


def test_build_full_argv_does_not_mutate_caller_values() -> None:
    """``build_full_argv`` must operate on a SHALLOW COPY of the
    values dict -- callers (the UI's live preview in particular)
    re-use the same dict across calls and a hidden mutation would
    feed the next call a pre-complemented list, which would then
    get complemented back to the selected list."""
    p = ParamDef(
        id="opts", type=ParamType.MULTISELECT,
        widget=Widget.CHECKBOX_LIST,
        choices=["x", "y", "z"], emit="unselected",
    )
    tool = ToolDef(
        name="t", executable=sys.executable,
        argument_template=[["--flag", "{opts}"]],
        params=[p],
    )
    values_in = {"opts": ["y"]}
    build_full_argv(tool, values_in, extras=[], ignore_required=True)
    # Caller's dict still has the SELECTED list, not the complement.
    assert values_in["opts"] == ["y"]


def test_build_full_argv_idempotent_when_called_twice() -> None:
    """Calling build_full_argv twice on the same values dict must
    yield identical argvs -- the double-complement guard ensures
    we don't oscillate between selected and complement."""
    p = ParamDef(
        id="opts", type=ParamType.MULTISELECT,
        widget=Widget.CHECKBOX_LIST,
        choices=["a", "b", "c"], emit="unselected",
    )
    tool = ToolDef(
        name="t", executable=sys.executable,
        argument_template=[["--flag", "{opts}"]],
        params=[p],
    )
    values = {"opts": ["b"]}
    cmd1 = build_full_argv(tool, values, extras=[], ignore_required=True)
    cmd2 = build_full_argv(tool, values, extras=[], ignore_required=True)
    assert cmd1.argv == cmd2.argv


# ---------------------------------------------------------------------------
# Editor radio picker
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_editor_radio_picker_all_selected_sets_full_default(qapp) -> None:
    """Clicking the 'All selected' radio fills ``param.default``
    with the full ``param.choices`` list (UI semantic: 'open the
    form all-ticked')."""
    from scriptree.ui.tool_editor import ToolEditorView

    p = ParamDef(
        id="opts", type=ParamType.MULTISELECT,
        widget=Widget.CHECKBOX_LIST,
        choices=["alpha", "beta", "gamma"], default=[],
    )
    tool = ToolDef(name="t", executable="python", params=[p])
    ed = ToolEditorView(tool, file_path=None)
    ed._on_param_selected(0)
    ep = ed._current_param()
    assert ep.default == []
    ed._on_prop_default_state_picked(ed._prop_default_state_all)
    assert ep.default == ["alpha", "beta", "gamma"]


def test_editor_radio_picker_all_deselected_clears_default(qapp) -> None:
    """Clicking the 'All deselected' radio empties ``param.default``."""
    from scriptree.ui.tool_editor import ToolEditorView

    p = ParamDef(
        id="opts", type=ParamType.MULTISELECT,
        widget=Widget.CHECKBOX_LIST,
        choices=["a", "b", "c"], default=["a", "b", "c"],
    )
    tool = ToolDef(name="t", executable="python", params=[p])
    ed = ToolEditorView(tool, file_path=None)
    ed._on_param_selected(0)
    ep = ed._current_param()
    assert ep.default == ["a", "b", "c"]
    ed._on_prop_default_state_picked(ed._prop_default_state_none)
    assert ep.default == []


def test_editor_radio_picker_custom_leaves_default(qapp) -> None:
    """'Custom' is a no-op on default -- the radio just acknowledges
    the author wants a partial selection edited via the Default
    text field above.  We test that clicking Custom doesn't fire
    the All-selected / All-deselected mutation."""
    from scriptree.ui.tool_editor import ToolEditorView

    p = ParamDef(
        id="opts", type=ParamType.MULTISELECT,
        widget=Widget.CHECKBOX_LIST,
        choices=["a", "b", "c"], default=["a"],  # partial
    )
    tool = ToolDef(name="t", executable="python", params=[p])
    ed = ToolEditorView(tool, file_path=None)
    ed._on_param_selected(0)
    ep = ed._current_param()
    assert ep.default == ["a"]
    ed._on_prop_default_state_picked(ed._prop_default_state_custom)
    # Custom must NOT mutate; the partial default stays.
    assert ep.default == ["a"]


def test_editor_radio_sync_reflects_current_default(qapp) -> None:
    """When the editor loads a param, the picker's selected radio
    must reflect whether the existing ``default`` matches choices
    (All selected), is empty (All deselected), or is partial
    (Custom).  Pins the load-time sync logic."""
    from scriptree.ui.tool_editor import ToolEditorView

    # All-selected default
    p = ParamDef(
        id="opts", type=ParamType.MULTISELECT,
        widget=Widget.CHECKBOX_LIST,
        choices=["a", "b"], default=["a", "b"],
    )
    tool = ToolDef(name="t", executable="python", params=[p])
    ed = ToolEditorView(tool, file_path=None)
    ed._on_param_selected(0)
    assert ed._prop_default_state_all.isChecked()
    assert not ed._prop_default_state_none.isChecked()
    assert not ed._prop_default_state_custom.isChecked()

    # Now switch to a param whose default is empty
    p.default = []
    ed._load_param_into_panel(p)
    assert ed._prop_default_state_none.isChecked()

    # Now partial
    p.default = ["a"]
    ed._load_param_into_panel(p)
    assert ed._prop_default_state_custom.isChecked()
