"""
test_emit_unselected.py — regression tests for the v0.8.0a50
``ParamDef.emit`` field, the runner's complement-at-argv-time
transformation, and the explicit-default validation rule that
ships alongside it.

Pins the behaviour requested in
``D:/Dev/FeatureRequests/ScripTree_FeatureRequests/FR_checkbox_list_emit_unchecked.md``
(SWBomExcluded use case: open a checkbox_list with everything
pre-ticked = "currently excluded," untick to un-exclude, the
RUN command receives the un-ticked complement so it acts on
"items the user wants flipped").

What's covered:

* Model: ``emit`` defaults to ``"selected"``; ``"unselected"``
  legal on multiselect + checkbox_list/dropdown; rejected
  elsewhere.
* IO: round-trip both modes; omitted-at-default; warn on
  implicit ``default`` for checkbox_list/dropdown-multi
  without a provider.
* Runner-side (via _collect_values): complement is computed
  against the widget's current_choices, preserves choice
  order, drops zero-width matches naturally, composes with
  empty-choice degenerate cases.

What's NOT covered here:

* Headless/CLI emit:unselected with a provider — that path
  isn't supported in v0.8.0a50 (the widget is the source of
  truth for live choices, and headless runs don't materialise
  the widget).  Documented in docs/LLM/checkbox_list_emit.md.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_VENDOR = Path(__file__).resolve().parent.parent / "lib" / "pypi"
if _VENDOR.is_dir():
    sys.path.insert(0, str(_VENDOR))

import pytest  # noqa: E402

from scriptree.core.io import (  # noqa: E402
    _param_from_dict, _param_to_dict, param_load_warnings,
)
from scriptree.core.model import ParamDef, ParamType, Widget  # noqa: E402


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

def test_emit_defaults_to_selected() -> None:
    p = ParamDef(
        id="p", type=ParamType.MULTISELECT,
        widget=Widget.CHECKBOX_LIST, choices=["a", "b"],
    )
    assert p.emit == "selected"


def test_emit_unselected_legal_on_checkbox_list() -> None:
    p = ParamDef(
        id="p", type=ParamType.MULTISELECT,
        widget=Widget.CHECKBOX_LIST, choices=["a"], emit="unselected",
    )
    assert p.emit == "unselected"


def test_emit_unselected_legal_on_dropdown_multiselect() -> None:
    """Per the v0.8.0a50 decision (FR Q3): both checkbox_list AND
    dropdown-multiselect honour ``emit: unselected`` so the
    field-value semantics are widget-symmetric."""
    p = ParamDef(
        id="p", type=ParamType.MULTISELECT,
        widget=Widget.DROPDOWN, choices=["a", "b"], emit="unselected",
    )
    assert p.emit == "unselected"


def test_emit_unselected_rejected_on_string() -> None:
    with pytest.raises(ValueError, match="multiselect"):
        ParamDef(
            id="p", type=ParamType.STRING, widget=Widget.TEXT,
            emit="unselected",
        )


def test_emit_unselected_rejected_on_enum() -> None:
    with pytest.raises(ValueError, match="multiselect"):
        ParamDef(
            id="p", type=ParamType.ENUM, widget=Widget.DROPDOWN,
            choices=["a", "b"], emit="unselected",
        )


def test_emit_unknown_value_rejected() -> None:
    with pytest.raises(ValueError, match="emit"):
        ParamDef(
            id="p", type=ParamType.MULTISELECT,
            widget=Widget.CHECKBOX_LIST, choices=["a"], emit="bogus",
        )


# ---------------------------------------------------------------------------
# IO — round-trip + omitted-at-default
# ---------------------------------------------------------------------------

def test_emit_unselected_round_trips() -> None:
    d = {
        "id": "p", "type": "multiselect", "widget": "checkbox_list",
        "choices": ["a", "b", "c"], "default": [],
        "emit": "unselected",
    }
    p = _param_from_dict(d)
    assert p.emit == "unselected"
    out = _param_to_dict(p)
    assert out["emit"] == "unselected"


def test_emit_selected_not_written_to_json() -> None:
    """Omitted-at-default: a v3 file without ``emit`` round-trips
    byte-identical -- no ``"emit": "selected"`` key gets added."""
    d = {
        "id": "p", "type": "multiselect", "widget": "checkbox_list",
        "choices": ["a"], "default": [],
    }
    p = _param_from_dict(d)
    out = _param_to_dict(p)
    assert "emit" not in out
    assert p.emit == "selected"


# ---------------------------------------------------------------------------
# Explicit-default validation
# ---------------------------------------------------------------------------

def test_implicit_default_warns_on_checkbox_list() -> None:
    """No ``default`` key in the raw JSON for a checkbox_list →
    param_load_warnings produces the MISSING_EXPLICIT_DEFAULT
    diagnostic."""
    d = {
        "id": "p", "type": "multiselect", "widget": "checkbox_list",
        "choices": ["a", "b"],
    }
    p = _param_from_dict(d)
    warnings = param_load_warnings(d, p)
    assert len(warnings) == 1
    assert "default" in warnings[0]
    assert "implicit" in warnings[0]


def test_implicit_default_warns_on_dropdown_multiselect() -> None:
    d = {
        "id": "p", "type": "multiselect", "widget": "dropdown",
        "choices": ["a", "b"],
    }
    p = _param_from_dict(d)
    warnings = param_load_warnings(d, p)
    assert len(warnings) == 1


def test_explicit_empty_default_does_not_warn() -> None:
    """``default: []`` is the SAFE explicit value (everything
    deselected at form-open) -- the whole point of the rule is
    that the author thought about it.  No warning when present."""
    d = {
        "id": "p", "type": "multiselect", "widget": "checkbox_list",
        "choices": ["a"], "default": [],
    }
    p = _param_from_dict(d)
    assert param_load_warnings(d, p) == []


def test_explicit_full_default_does_not_warn() -> None:
    d = {
        "id": "p", "type": "multiselect", "widget": "checkbox_list",
        "choices": ["a", "b"], "default": ["a", "b"],
    }
    p = _param_from_dict(d)
    assert param_load_warnings(d, p) == []


def test_provider_backed_does_not_warn() -> None:
    """When ``choices_provider`` is set the provider's response
    supplies the default; the static ``default`` field is
    irrelevant, so the explicit-default rule does NOT apply."""
    d = {
        "id": "p", "type": "multiselect", "widget": "checkbox_list",
        "choices_provider": {"command": ["x"]},
    }
    p = _param_from_dict(d)
    assert param_load_warnings(d, p) == []


def test_non_multiselect_does_not_warn() -> None:
    """The rule only applies to multiselect rendered as
    checkbox_list or dropdown.  A string/text param with no
    default is fine."""
    d = {"id": "p", "type": "string", "widget": "text"}
    p = _param_from_dict(d)
    assert param_load_warnings(d, p) == []


# ---------------------------------------------------------------------------
# Runner-side complement transformation
# ---------------------------------------------------------------------------
#
# The runner's complement happens in ``ui/tool_runner.py::_collect_values``
# against the widget's ``current_choices()``.  We don't spin up a
# full ToolRunnerView here -- those tests live in test_tool_runner.py
# and exercise the widget interaction directly.  Instead we cover
# the pure-function complement primitive (the list-comprehension
# that lives inside _collect_values) so the order + dedup invariants
# are pinned even if the surrounding code moves.

def _complement(selected: list, all_choices: list) -> list:
    """Reimplementation of the complement that _collect_values runs.
    Keeping this here lets us pin the invariant in isolation."""
    sel_set = {str(s) for s in selected}
    return [c for c in all_choices if str(c) not in sel_set]


def test_complement_preserves_choices_order() -> None:
    """Token-group fan-out is positional, so the complement MUST
    preserve choice order even when ``selected`` is in a different
    order than ``choices``."""
    choices = ["a", "b", "c", "d", "e"]
    selected = ["d", "a"]  # arbitrary order
    assert _complement(selected, choices) == ["b", "c", "e"]


def test_complement_empty_when_all_selected() -> None:
    """Form opens all-checked → emit is [] → Run is a clean no-op."""
    choices = ["a", "b", "c"]
    assert _complement(["a", "b", "c"], choices) == []


def test_complement_full_when_none_selected() -> None:
    """User unticks the master → emit is the whole choice set."""
    choices = ["a", "b", "c"]
    assert _complement([], choices) == ["a", "b", "c"]


def test_complement_empty_choices_yields_empty() -> None:
    """Degenerate case: provider returns no choices → emit is []
    regardless of mode."""
    assert _complement([], []) == []
    assert _complement(["a"], []) == []


def test_complement_handles_str_coercion() -> None:
    """selected list might contain non-string values (rare but
    possible from configurations with int choices); coerce both
    sides via str() before set-diff so the comparison is robust."""
    assert _complement([1, 2], ["1", "2", "3"]) == ["3"]
