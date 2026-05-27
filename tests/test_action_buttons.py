"""Tests for the action-buttons feature (v0.8.0a11+).

Covers:
  * ``ActionDef.__post_init__`` structural validation (id format,
    label, popup enum, argv element types).
  * ``ToolDef.validate`` cross-action checks (duplicate id, section
    reference must resolve).
  * ``io._action_to_dict`` / ``_action_from_dict`` round-trip,
    including the compactness rule that omits defaults so legacy
    ``.scriptree`` files round-trip byte-identical.
  * ``tool_to_dict`` / ``tool_from_dict`` propagate ``actions``
    end-to-end.
  * Backward compatibility: a ``.scriptree`` without an ``actions``
    key loads cleanly with an empty list and ``tool_to_dict`` does
    NOT emit ``actions`` for tools that have none.

The runner / UI / popup tests live in
``test_action_buttons_runner.py`` and ``test_action_buttons_ui.py``
respectively (separate files keep the headless model+io suite
import-light).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scriptree.core.io import (
    _action_from_dict,
    _action_to_dict,
    load_tool,
    save_tool,
    tool_from_dict,
    tool_to_dict,
)
from scriptree.core.model import ActionDef, ToolDef


# ---------------------------------------------------------------------------
# ActionDef.__post_init__ structural validation
# ---------------------------------------------------------------------------

class TestActionDefValidation:
    """Per-action structural checks that fire at construction time."""

    def test_minimal_valid_action(self) -> None:
        a = ActionDef(id="status", label="Status", argv=["status", "--short"])
        assert a.id == "status"
        assert a.label == "Status"
        assert a.argv == ["status", "--short"]
        assert a.popup == "never"
        assert a.confirm == ""
        assert a.icon == ""
        assert a.hidden is False
        assert a.section == ""

    def test_empty_argv_is_legal(self) -> None:
        # "Run executable with no args" is a meaningful preset.
        a = ActionDef(id="version", label="Version", argv=[])
        assert a.argv == []

    def test_id_must_be_non_empty(self) -> None:
        with pytest.raises(ValueError, match="must be non-empty"):
            ActionDef(id="", label="x")

    def test_id_must_match_pattern(self) -> None:
        # Capitals, spaces, dashes, leading digits all rejected --
        # the id is a stable handle for permissions and editor
        # tooling.  Matches the standard "Python identifier" feel:
        # leading [a-z_], then [a-z0-9_]*.
        for bad in ("Status", "git status", "git-status", "status!", "1leading"):
            with pytest.raises(ValueError, match=r"\[a-z"):
                ActionDef(id=bad, label="x")

    def test_id_lowercase_alphanum_underscore_ok(self) -> None:
        for ok in ("status", "log10", "log_short", "a", "x_y_z_1"):
            ActionDef(id=ok, label="x")  # no raise

    def test_label_must_be_non_empty(self) -> None:
        with pytest.raises(ValueError, match="label must be non-empty"):
            ActionDef(id="x", label="")

    def test_popup_enum(self) -> None:
        for ok in ("never", "auto", "always"):
            ActionDef(id="x", label="X", popup=ok)
        for bad in ("yes", "true", "popup", ""):
            with pytest.raises(ValueError, match="popup must be one of"):
                ActionDef(id="x", label="X", popup=bad)

    def test_argv_elements_must_be_strings(self) -> None:
        # Numbers / None in argv = an authoring bug; fail loud.
        with pytest.raises(ValueError, match="must be a string"):
            ActionDef(id="x", label="X", argv=["status", 42])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# ToolDef.validate cross-action checks
# ---------------------------------------------------------------------------

class TestToolDefActionValidation:
    """Cross-action checks the per-ActionDef post_init can't see."""

    def _minimal_tool(self, actions: list[ActionDef]) -> ToolDef:
        return ToolDef(name="t", executable="echo", actions=actions)

    def test_no_actions_validates_clean(self) -> None:
        tool = self._minimal_tool([])
        assert tool.validate() == []

    def test_one_action_validates_clean(self) -> None:
        tool = self._minimal_tool([ActionDef(id="s", label="S")])
        assert tool.validate() == []

    def test_duplicate_action_ids_caught(self) -> None:
        tool = self._minimal_tool([
            ActionDef(id="s", label="A"),
            ActionDef(id="s", label="B"),
        ])
        errors = tool.validate()
        assert any("Duplicate action id" in e and "'s'" in e for e in errors)

    def test_section_must_be_declared(self) -> None:
        from scriptree.core.model import Section
        # Action references "Diagnostics" but the tool has no sections.
        tool = ToolDef(
            name="t", executable="echo",
            actions=[ActionDef(id="s", label="S", section="Diagnostics")],
        )
        errors = tool.validate()
        assert any("Diagnostics" in e and "section" in e.lower()
                   for e in errors)

    def test_section_declared_resolves(self) -> None:
        from scriptree.core.model import Section
        tool = ToolDef(
            name="t", executable="echo",
            sections=[Section(name="Diagnostics")],
            actions=[ActionDef(id="s", label="S", section="Diagnostics")],
        )
        assert tool.validate() == []

    def test_empty_section_string_ok(self) -> None:
        # Default ("") means "render in the dedicated Actions row" --
        # don't trip on it.
        tool = self._minimal_tool([ActionDef(id="s", label="S", section="")])
        assert tool.validate() == []


# ---------------------------------------------------------------------------
# JSON round-trip + compactness rule
# ---------------------------------------------------------------------------

class TestActionRoundTrip:
    """``_action_to_dict`` / ``_action_from_dict`` byte-stable round-trip."""

    def test_minimal_round_trip(self) -> None:
        a = ActionDef(id="status", label="Status", argv=["status", "--short"])
        d = _action_to_dict(a)
        # Only required fields + argv emitted -- compactness rule.
        assert d == {"id": "status", "label": "Status",
                     "argv": ["status", "--short"]}
        # And it re-loads to an equivalent ActionDef.
        a2 = _action_from_dict(d)
        assert a2 == a

    def test_all_fields_round_trip(self) -> None:
        a = ActionDef(
            id="log10", label="Last 10", argv=["log", "--oneline", "-10"],
            tooltip="Show the last 10 commits",
            popup="auto",
            confirm="This rewrites the index. Continue?",
            icon="history",
            hidden=False,
            section="Diagnostics",
        )
        d = _action_to_dict(a)
        a2 = _action_from_dict(d)
        assert a2 == a

    def test_hidden_true_round_trip(self) -> None:
        a = ActionDef(id="x", label="X", hidden=True)
        d = _action_to_dict(a)
        assert d.get("hidden") is True
        a2 = _action_from_dict(d)
        assert a2.hidden is True

    def test_defaults_omitted_from_dict(self) -> None:
        """Every optional field at its default MUST stay out of the
        emitted JSON so a ``.scriptree`` authored before this feature
        is re-saved without churning."""
        a = ActionDef(id="x", label="X", argv=["x"])
        d = _action_to_dict(a)
        assert "tooltip" not in d
        assert "popup"   not in d
        assert "confirm" not in d
        assert "icon"    not in d
        assert "hidden"  not in d
        assert "section" not in d


# ---------------------------------------------------------------------------
# tool_to_dict / tool_from_dict integration
# ---------------------------------------------------------------------------

class TestToolWithActions:
    """End-to-end integration via the public io entry points."""

    def test_legacy_tool_no_actions_emits_no_actions_key(self) -> None:
        """A tool without actions must produce JSON with no
        ``"actions"`` key -- so existing on-disk ``.scriptree`` files
        round-trip byte-identical through a loader that knows about
        actions."""
        tool = ToolDef(name="legacy", executable="echo")
        d = tool_to_dict(tool)
        assert "actions" not in d
        # And re-loading produces the same actions list (empty).
        tool2 = tool_from_dict(d)
        assert tool2.actions == []

    def test_tool_with_actions_round_trips(self) -> None:
        tool = ToolDef(
            name="git_helper", executable="git",
            actions=[
                ActionDef(id="status", label="Status",
                          argv=["status", "--short"]),
                ActionDef(id="log10", label="Last 10",
                          argv=["log", "--oneline", "-10"],
                          popup="auto"),
            ],
        )
        d = tool_to_dict(tool)
        assert "actions" in d
        assert len(d["actions"]) == 2

        tool2 = tool_from_dict(d)
        assert len(tool2.actions) == 2
        assert tool2.actions[0].id == "status"
        assert tool2.actions[1].popup == "auto"

    def test_save_load_round_trip_disk(self, tmp_path: Path) -> None:
        """Write then read a ``.scriptree`` from disk; the actions
        survive the JSON serialisation + parser path."""
        path = tmp_path / "git_helper.scriptree"
        original = ToolDef(
            name="git_helper", executable="git",
            actions=[
                ActionDef(id="status", label="Status",
                          argv=["status", "--short"],
                          tooltip="Show working-tree status."),
                ActionDef(id="branches", label="Branches",
                          argv=["branch", "-a"], popup="always"),
            ],
        )
        save_tool(original, path)
        loaded = load_tool(path)

        assert len(loaded.actions) == 2
        assert loaded.actions[0].id == "status"
        assert loaded.actions[0].tooltip == "Show working-tree status."
        assert loaded.actions[1].popup == "always"

    def test_unknown_fields_in_action_are_dropped(self, tmp_path: Path) -> None:
        """If a future schema version adds a field this loader doesn't
        know about, the unknown field must be silently dropped (not
        crash the load).  Forward-compatibility insurance."""
        path = tmp_path / "future.scriptree"
        path.write_text(json.dumps({
            "schema_version": 3,
            "name": "x", "executable": "echo",
            "actions": [
                {"id": "a", "label": "A", "argv": [],
                 "future_field": "ignored"},
            ],
        }), encoding="utf-8")
        tool = load_tool(path)
        assert len(tool.actions) == 1
        assert tool.actions[0].id == "a"

    def test_malformed_action_raises_at_load(self, tmp_path: Path) -> None:
        """Per the schema's fail-loud-at-load contract: a structurally
        broken action (bad id pattern, wrong popup enum, non-string
        argv element) MUST raise at ``load_tool``, not get silently
        coerced."""
        path = tmp_path / "broken.scriptree"
        path.write_text(json.dumps({
            "schema_version": 3,
            "name": "x", "executable": "echo",
            "actions": [{"id": "Bad Id", "label": "X", "argv": []}],
        }), encoding="utf-8")
        with pytest.raises(ValueError, match=r"\[a-z0-9_\]"):
            load_tool(path)
