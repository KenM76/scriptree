"""Tests for the ParamDef.no_persist field and its effects."""
from __future__ import annotations

from pathlib import Path

import pytest

from scriptree.core.io import (
    _param_from_dict,
    _param_to_dict,
    load_tool,
    save_tool,
)
from scriptree.core.model import ParamDef, ParamType, ToolDef, Widget


class TestParamDefNoPersist:
    def test_default_false(self):
        p = ParamDef(id="x")
        assert p.no_persist is False

    def test_explicit_true(self):
        p = ParamDef(id="x", no_persist=True)
        assert p.no_persist is True


class TestParamSerialization:
    def test_emits_only_when_true(self):
        p = ParamDef(id="x", no_persist=False)
        d = _param_to_dict(p)
        assert "no_persist" not in d

    def test_emits_when_true(self):
        p = ParamDef(id="x", no_persist=True)
        d = _param_to_dict(p)
        assert d["no_persist"] is True

    def test_round_trip_true(self):
        p = ParamDef(id="x", no_persist=True)
        d = _param_to_dict(p)
        p2 = _param_from_dict(d)
        assert p2.no_persist is True

    def test_round_trip_false(self):
        p = ParamDef(id="x", no_persist=False)
        d = _param_to_dict(p)
        p2 = _param_from_dict(d)
        assert p2.no_persist is False

    def test_legacy_file_defaults_false(self):
        """A serialized param without no_persist loads as False."""
        d = {
            "id": "x",
            "label": "X",
            "description": "",
            "type": "string",
            "widget": "text",
            "required": False,
            "default": "",
        }
        p = _param_from_dict(d)
        assert p.no_persist is False


class TestToolFileRoundTrip:
    def test_tool_round_trip_preserves_no_persist(self, tmp_path: Path):
        tool = ToolDef(
            name="t",
            executable="/bin/echo",
            params=[
                ParamDef(
                    id="password", type=ParamType.STRING,
                    widget=Widget.TEXT, no_persist=True,
                ),
                ParamDef(id="name", type=ParamType.STRING, widget=Widget.TEXT),
            ],
            argument_template=["--password", "{password}", "{name}"],
        )
        path = tmp_path / "t.scriptree"
        save_tool(tool, path)

        loaded = load_tool(path)
        pwd = next(p for p in loaded.params if p.id == "password")
        name = next(p for p in loaded.params if p.id == "name")
        assert pwd.no_persist is True
        assert name.no_persist is False
