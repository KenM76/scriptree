"""Tests pinning the v0.5.0 / schema_version-3 canonical-names rename.

Per ``scriptree_feature_requests_2026_05_13_canonical_names.md``:

  ``ParamType``:  ``bool``       → ``boolean``,
                  ``float``      → ``number``

  ``Widget``:     ``file_open``  → ``file``,
                  ``file_save``  → ``save_file``,
                  ``enum_radio`` → ``radio``

And ``SCHEMA_VERSION`` bumps 2 → 3.  v3 ScripTree refuses to load
v1/v2 files; the migrate CLI handles the upgrade.

These tests also cover:
  * The difflib-powered error message on a typo'd type / widget.
  * The migration script's rename map + idempotency.
  * The CLI subcommand dispatch (``scriptree validate`` /
    ``scriptree migrate``).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scriptree.core.model import (
    ParamType, SCHEMA_VERSION, VALID_WIDGETS, Widget,
)


# ===========================================================================
# Enum values match the JSON-Schema-aligned vocabulary
# ===========================================================================

class TestCanonicalEnumValues:

    def test_schema_version_is_3(self) -> None:
        assert SCHEMA_VERSION == 3

    def test_paramtype_values_are_json_schema_aligned(self) -> None:
        values = sorted(t.value for t in ParamType)
        assert values == sorted([
            "string", "integer", "number", "boolean",
            "path", "enum", "multiselect",
        ])

    def test_widget_values_are_html5_aligned(self) -> None:
        values = sorted(w.value for w in Widget)
        assert values == sorted([
            "text", "textarea", "number", "checkbox",
            "dropdown", "file", "save_file", "folder", "radio",
        ])

    def test_no_v2_aliases_present(self) -> None:
        """v2 names must NOT round-trip — the rename is a hard break,
        not a backward-compat alias."""
        v2_param_names = {"bool", "float"}
        v2_widget_names = {"file_open", "file_save", "enum_radio"}
        for name in v2_param_names:
            with pytest.raises(ValueError):
                ParamType(name)
        for name in v2_widget_names:
            with pytest.raises(ValueError):
                Widget(name)

    def test_valid_widgets_mapping(self) -> None:
        """Spot-check the type → widget mapping uses the new names."""
        assert Widget.CHECKBOX in VALID_WIDGETS[ParamType.BOOLEAN]
        assert Widget.NUMBER in VALID_WIDGETS[ParamType.NUMBER]
        assert Widget.FILE in VALID_WIDGETS[ParamType.PATH]
        assert Widget.SAVE_FILE in VALID_WIDGETS[ParamType.PATH]
        assert Widget.RADIO in VALID_WIDGETS[ParamType.ENUM]


# ===========================================================================
# v2 files are hard-rejected; loader points at migrate
# ===========================================================================

class TestV2HardReject:

    def test_v2_tool_raises_with_migrate_hint(self, tmp_path: Path) -> None:
        from scriptree.core.io import load_tool
        p = tmp_path / "old.scriptree"
        p.write_text(json.dumps({
            "schema_version": 2,
            "name": "X",
            "executable": "echo",
            "params": [],
        }), encoding="utf-8")
        with pytest.raises(ValueError) as exc:
            load_tool(p)
        msg = str(exc.value)
        assert "schema_version 2" in msg
        assert "scriptree migrate" in msg

    def test_v3_tool_loads_cleanly(self, tmp_path: Path) -> None:
        from scriptree.core.io import load_tool
        p = tmp_path / "new.scriptree"
        p.write_text(json.dumps({
            "schema_version": 3,
            "name": "X",
            "executable": "echo",
            "params": [],
        }), encoding="utf-8")
        tool = load_tool(p)
        assert tool.name == "X"


# ===========================================================================
# difflib hints on bad values
# ===========================================================================

class TestErrorHints:

    def _load(self, tmp_path: Path, bad_type: str = None,
              bad_widget: str = None) -> str:
        from scriptree.core.io import load_tool
        p = tmp_path / "x.scriptree"
        param = {"id": "q", "label": "Q"}
        if bad_type is not None:
            param["type"] = bad_type
        if bad_widget is not None:
            param["widget"] = bad_widget
        p.write_text(json.dumps({
            "schema_version": 3,
            "name": "X",
            "executable": "echo",
            "params": [param],
        }), encoding="utf-8")
        try:
            load_tool(p)
        except ValueError as e:
            return str(e)
        return ""

    def test_int_suggests_integer(self, tmp_path: Path) -> None:
        msg = self._load(tmp_path, bad_type="int")
        assert "'int'" in msg
        assert "'integer'" in msg
        assert "Did you mean" in msg

    def test_bool_suggests_boolean(self, tmp_path: Path) -> None:
        msg = self._load(tmp_path, bad_type="bool")
        assert "'boolean'" in msg

    def test_spinbox_suggests_number(self, tmp_path: Path) -> None:
        msg = self._load(tmp_path, bad_widget="spinbox")
        # Closest standard widget to "spinbox" is "number".
        assert "spinbox" in msg
        assert "'number'" in msg or "number" in msg

    def test_error_mentions_param_id(self, tmp_path: Path) -> None:
        msg = self._load(tmp_path, bad_type="xyz")
        assert "'q'" in msg


# ===========================================================================
# Migration script
# ===========================================================================

class TestMigrate:

    def _write_v2(self, path: Path) -> None:
        path.write_text(json.dumps({
            "schema_version": 2,
            "name": "X",
            "executable": "echo",
            "params": [
                {"id": "a", "label": "A", "type": "bool",
                 "widget": "checkbox"},
                {"id": "b", "label": "B", "type": "float",
                 "widget": "number"},
                {"id": "c", "label": "C", "type": "path",
                 "widget": "file_open"},
                {"id": "d", "label": "D", "type": "path",
                 "widget": "file_save"},
                {"id": "e", "label": "E", "type": "enum",
                 "widget": "enum_radio", "choices": ["x", "y"]},
            ],
        }), encoding="utf-8")

    def test_migrate_one_renames_all_five(self, tmp_path: Path) -> None:
        from scriptree.cli.migrate import migrate_one
        p = tmp_path / "x.scriptree"
        self._write_v2(p)
        changed = migrate_one(p)
        assert changed is True
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["schema_version"] == 3
        types = [pm["type"] for pm in data["params"]]
        widgets = [pm["widget"] for pm in data["params"]]
        assert types == ["boolean", "number", "path", "path", "enum"]
        assert widgets == [
            "checkbox", "number", "file", "save_file", "radio",
        ]

    def test_migrate_handles_llm_noise(self, tmp_path: Path) -> None:
        """The migrator also folds in past LLM-noise aliases —
        ``int`` / ``str`` / ``spinbox`` / ``radiobutton`` / ``select``."""
        from scriptree.cli.migrate import migrate_one
        p = tmp_path / "x.scriptree"
        p.write_text(json.dumps({
            "schema_version": 2,
            "name": "X", "executable": "echo",
            "params": [
                {"id": "a", "label": "A", "type": "int",
                 "widget": "spinbox"},
                {"id": "b", "label": "B", "type": "str",
                 "widget": "select", "choices": ["x"]},
                {"id": "c", "label": "C", "type": "enum",
                 "widget": "radiobutton", "choices": ["x"]},
            ],
        }), encoding="utf-8")
        migrate_one(p)
        data = json.loads(p.read_text(encoding="utf-8"))
        types = [pm["type"] for pm in data["params"]]
        widgets = [pm["widget"] for pm in data["params"]]
        assert types == ["integer", "string", "enum"]
        assert widgets == ["number", "dropdown", "radio"]

    def test_migrate_is_idempotent(self, tmp_path: Path) -> None:
        from scriptree.cli.migrate import migrate_one
        p = tmp_path / "x.scriptree"
        self._write_v2(p)
        first = migrate_one(p)
        second = migrate_one(p)
        assert first is True
        assert second is False

    def test_migrate_dry_run_does_not_write(self, tmp_path: Path) -> None:
        from scriptree.cli.migrate import migrate_one
        p = tmp_path / "x.scriptree"
        self._write_v2(p)
        original = p.read_text(encoding="utf-8")
        changed = migrate_one(p, dry_run=True)
        assert changed is True
        # File contents unchanged in dry-run.
        assert p.read_text(encoding="utf-8") == original

    def test_migrated_file_loads_through_real_loader(
        self, tmp_path: Path,
    ) -> None:
        """End-to-end: migrate a v2 file, then load it via
        ``io.load_tool`` to confirm v3 vocabulary is now valid."""
        from scriptree.cli.migrate import migrate_one
        from scriptree.core.io import load_tool
        p = tmp_path / "x.scriptree"
        self._write_v2(p)
        migrate_one(p)
        tool = load_tool(p)
        assert tool.params[0].type is ParamType.BOOLEAN
        assert tool.params[1].type is ParamType.NUMBER
        assert tool.params[2].widget is Widget.FILE
        assert tool.params[3].widget is Widget.SAVE_FILE
        assert tool.params[4].widget is Widget.RADIO


# ===========================================================================
# CLI dispatch
# ===========================================================================

class TestCLIDispatch:

    def test_validate_reports_clean_file(self, tmp_path: Path) -> None:
        from scriptree.core.io import save_tool
        from scriptree.core.model import ParamDef, ToolDef
        tool = ToolDef(
            name="X", executable="echo",
            params=[ParamDef(id="a", label="A")],
        )
        p = tmp_path / "x.scriptree"
        save_tool(tool, p)
        from scriptree.cli.validate import validate_one
        ok, msg = validate_one(p)
        assert ok is True
        assert "Valid" in msg

    def test_validate_reports_widget_type_mismatch(
        self, tmp_path: Path,
    ) -> None:
        """A path-typed param with a widget=checkbox is technically
        loadable but semantically invalid — ``validate`` catches it
        via the VALID_WIDGETS cross-check."""
        p = tmp_path / "x.scriptree"
        # Write JSON directly because save_tool would refuse.
        # Use TEXT widget which is valid for STRING but not for
        # BOOLEAN — gives us an invalid pairing.
        p.write_text(json.dumps({
            "schema_version": 3,
            "name": "X", "executable": "echo",
            "params": [
                {"id": "a", "label": "A", "type": "boolean",
                 "widget": "text"},
            ],
        }), encoding="utf-8")
        from scriptree.cli.validate import validate_one
        ok, msg = validate_one(p)
        assert ok is False
        assert "widget" in msg.lower()
