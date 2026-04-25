"""Tests for scriptree.core.model."""
from __future__ import annotations

import pytest

from scriptree.core.model import (
    ParamDef,
    ParamType,
    ToolDef,
    TreeDef,
    TreeNode,
    Widget,
    default_widget_for,
    _template_refs,
)


class TestParamDef:
    def test_identifier_required(self) -> None:
        with pytest.raises(ValueError, match="identifier"):
            ParamDef(id="not an id")

    def test_label_defaults_to_humanized_id(self) -> None:
        p = ParamDef(id="output_file")
        assert p.label == "Output file"

    def test_explicit_label_wins(self) -> None:
        p = ParamDef(id="x", label="Custom")
        assert p.label == "Custom"

    def test_widget_must_match_type(self) -> None:
        with pytest.raises(ValueError, match="not valid for type"):
            ParamDef(id="x", type=ParamType.BOOL, widget=Widget.DROPDOWN)

    def test_default_widget_for_each_type(self) -> None:
        for t in ParamType:
            w = default_widget_for(t)
            p = ParamDef(id="x", type=t, widget=w)
            assert p.widget is w


class TestToolDefValidate:
    def _tool(self, **overrides) -> ToolDef:
        base = dict(name="t", executable="/bin/echo")
        base.update(overrides)
        return ToolDef(**base)

    def test_empty_name_rejected(self) -> None:
        assert "Tool name is empty." in self._tool(name="").validate()

    def test_empty_executable_rejected(self) -> None:
        assert "Executable path is empty." in self._tool(executable="").validate()

    def test_duplicate_param_ids_rejected(self) -> None:
        tool = self._tool(
            params=[ParamDef(id="a"), ParamDef(id="a")],
        )
        assert any("Duplicate parameter" in e for e in tool.validate())

    def test_template_refs_unknown_param(self) -> None:
        tool = self._tool(
            argument_template=["{missing}"],
            params=[ParamDef(id="present")],
        )
        errors = tool.validate()
        assert any("unknown parameter" in e for e in errors)

    def test_valid_tool_has_no_errors(self) -> None:
        tool = self._tool(
            argument_template=["--name", "{name}"],
            params=[ParamDef(id="name", required=True)],
        )
        assert tool.validate() == []

    def test_param_by_id(self) -> None:
        tool = self._tool(params=[ParamDef(id="a"), ParamDef(id="b")])
        assert tool.param_by_id("b").id == "b"
        assert tool.param_by_id("missing") is None


class TestTreeNode:
    def test_leaf_requires_path(self) -> None:
        with pytest.raises(ValueError, match="leaf"):
            TreeNode(type="leaf")

    def test_folder_rejects_path(self) -> None:
        with pytest.raises(ValueError, match="folder"):
            TreeNode(type="folder", path="x")

    def test_invalid_type(self) -> None:
        with pytest.raises(ValueError):
            TreeNode(type="bogus")

    def test_leaf_with_configuration(self) -> None:
        n = TreeNode(type="leaf", path="./tool.scriptree", configuration="standalone")
        assert n.configuration == "standalone"

    def test_leaf_configuration_defaults_none(self) -> None:
        n = TreeNode(type="leaf", path="./tool.scriptree")
        assert n.configuration is None


class TestTemplateRefs:
    def test_simple(self) -> None:
        assert _template_refs("{name}") == ["name"]

    def test_embedded(self) -> None:
        assert _template_refs("prefix{name}suffix") == ["name"]

    def test_conditional(self) -> None:
        assert _template_refs("{verbose?--verbose}") == ["verbose"]

    def test_multiple(self) -> None:
        assert _template_refs("{a}-{b}") == ["a", "b"]

    def test_no_refs(self) -> None:
        assert _template_refs("literal") == []

    def test_invalid_inner_ignored(self) -> None:
        assert _template_refs("{not an id}") == []
