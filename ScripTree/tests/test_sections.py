"""Tests for the Section feature (Level 2).

Sections are an optional rendering hint: a ``ToolDef`` can declare a
list of ``Section`` objects, and each ``ParamDef`` can be assigned to
one by name via the ``section`` field. When a tool has no sections,
everything behaves exactly as it did in schema v1 — that's the
"flat form" compatibility path and it gets the most test weight,
since Ken's existing .scriptree files will all use it.

What we cover:

- Model: ``grouped_params`` returns the right structure for flat
  tools, sectioned tools, and the tricky "orphaned param" case where
  a param references a section that was deleted.
- IO: round-trip of sections and the per-param ``section`` field, plus
  backward-compat loading of v1-style files with no sections block.
- Runner: rendering a sectioned tool builds one ``QGroupBox`` per
  section, and reorder preserves cross-section order.
- Editor: add/rename/remove section mutate the model and refresh
  the preview.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication, QGroupBox

_app = QApplication.instance() or QApplication([])

from scriptree.core.io import load_tool, save_tool, tool_from_dict, tool_to_dict  # noqa: E402
from scriptree.core.model import (  # noqa: E402
    SCHEMA_VERSION,
    ParamDef,
    ParamType,
    Section,
    ToolDef,
    Widget,
)
from scriptree.ui.tool_editor import ToolEditorView  # noqa: E402
from scriptree.ui.tool_runner import ToolRunnerView  # noqa: E402


def _flat_tool() -> ToolDef:
    return ToolDef(
        name="flat",
        executable="/bin/echo",
        argument_template=["{a}", "{b}", "{c}"],
        params=[
            ParamDef(id="a", label="A"),
            ParamDef(id="b", label="B"),
            ParamDef(id="c", label="C"),
        ],
    )


def _sectioned_tool() -> ToolDef:
    return ToolDef(
        name="sectioned",
        executable="/bin/echo",
        argument_template=["{host}", "{user}", "{verbose?--verbose}"],
        params=[
            ParamDef(id="host", label="Host", section="Connection"),
            ParamDef(id="user", label="User", section="Connection"),
            ParamDef(
                id="verbose",
                label="Verbose",
                type=ParamType.BOOL,
                widget=Widget.CHECKBOX,
                default=False,
                section="Debug",
            ),
        ],
        sections=[
            Section(name="Connection"),
            Section(name="Debug"),
        ],
    )


# --- model ------------------------------------------------------------------


class TestGroupedParams:
    def test_flat_tool_returns_single_none_group(self) -> None:
        tool = _flat_tool()
        groups = tool.grouped_params()
        assert len(groups) == 1
        section, params = groups[0]
        assert section is None
        assert [p.id for p in params] == ["a", "b", "c"]

    def test_sectioned_tool_returns_groups_in_section_order(self) -> None:
        tool = _sectioned_tool()
        groups = tool.grouped_params()
        assert [g[0].name for g in groups] == ["Connection", "Debug"]
        assert [p.id for p in groups[0][1]] == ["host", "user"]
        assert [p.id for p in groups[1][1]] == ["verbose"]

    def test_orphaned_param_falls_into_other_section(self) -> None:
        tool = _sectioned_tool()
        tool.params.append(
            ParamDef(id="oops", label="Oops", section="Deleted")
        )
        groups = tool.grouped_params()
        assert groups[-1][0].name == "Other"
        assert [p.id for p in groups[-1][1]] == ["oops"]

    def test_empty_section_still_rendered(self) -> None:
        tool = ToolDef(
            name="empty_sec",
            executable="/bin/true",
            params=[ParamDef(id="x", section="Main")],
            sections=[Section(name="Main"), Section(name="Extras")],
        )
        groups = tool.grouped_params()
        names = [g[0].name for g in groups]
        assert names == ["Main", "Extras"]
        assert [p.id for p in groups[1][1]] == []


# --- IO round-trip ----------------------------------------------------------


class TestSectionIO:
    def test_flat_tool_emits_no_sections_key(self) -> None:
        tool = _flat_tool()
        d = tool_to_dict(tool)
        assert "sections" not in d

    def test_sectioned_tool_round_trips(self, tmp_path: Path) -> None:
        tool = _sectioned_tool()
        path = tmp_path / "t.scriptree"
        save_tool(tool, path)
        reloaded = load_tool(path)
        assert [s.name for s in reloaded.sections] == ["Connection", "Debug"]
        assert reloaded.param_by_id("host").section == "Connection"
        assert reloaded.param_by_id("verbose").section == "Debug"

    def test_collapsed_flag_round_trips(self, tmp_path: Path) -> None:
        tool = _sectioned_tool()
        tool.sections[1].collapsed = True
        path = tmp_path / "t.scriptree"
        save_tool(tool, path)
        reloaded = load_tool(path)
        assert reloaded.sections[0].collapsed is False
        assert reloaded.sections[1].collapsed is True

    def test_v1_file_loads_without_sections(self) -> None:
        v1_data = {
            "schema_version": 1,
            "name": "legacy",
            "description": "",
            "executable": "/bin/echo",
            "working_directory": None,
            "argument_template": ["{a}"],
            "params": [
                {
                    "id": "a",
                    "label": "A",
                    "description": "",
                    "type": "string",
                    "widget": "text",
                    "required": False,
                    "default": "",
                }
            ],
            "source": {"mode": "manual", "help_text_cached": None},
        }
        tool = tool_from_dict(v1_data)
        assert tool.sections == []
        assert tool.param_by_id("a").section == ""


# --- runner rendering -------------------------------------------------------


class TestRunnerSectionRendering:
    def test_flat_tool_has_no_section_boxes(self) -> None:
        view = ToolRunnerView(_flat_tool())
        assert view._section_boxes == {}
        # The single empty-key form holds all three rows.
        assert "" in view._section_forms
        assert view._section_forms[""].count() == 3

    def test_sectioned_tool_builds_one_form_per_section(self) -> None:
        view = ToolRunnerView(_sectioned_tool())
        assert set(view._section_forms.keys()) == {"Connection", "Debug"}
        assert view._section_forms["Connection"].count() == 2
        assert view._section_forms["Debug"].count() == 1

    def test_sectioned_tool_wraps_each_form_in_a_groupbox(self) -> None:
        view = ToolRunnerView(_sectioned_tool())
        assert set(view._section_boxes.keys()) == {"Connection", "Debug"}
        for box in view._section_boxes.values():
            assert isinstance(box, QGroupBox)
            assert box.isCheckable()

    def test_collapsed_section_starts_hidden(self) -> None:
        tool = _sectioned_tool()
        tool.sections[1].collapsed = True
        view = ToolRunnerView(tool)
        assert view._section_boxes["Debug"].isChecked() is False
        assert view._section_forms["Debug"].isVisible() is False

    def test_toggle_persists_collapsed_flag(self, tmp_path: Path) -> None:
        tool = _sectioned_tool()
        path = tmp_path / "t.scriptree"
        save_tool(tool, path)
        view = ToolRunnerView(tool, file_path=str(path))
        # Simulate user unchecking the Connection groupbox.
        view._on_section_toggled(
            "Connection", False, view._section_forms["Connection"]
        )
        reloaded = load_tool(path)
        conn = next(s for s in reloaded.sections if s.name == "Connection")
        assert conn.collapsed is True


class TestRunnerSectionReorder:
    def test_reorder_within_section_preserves_other_section_order(
        self, tmp_path: Path
    ) -> None:
        tool = _sectioned_tool()
        path = tmp_path / "t.scriptree"
        save_tool(tool, path)
        view = ToolRunnerView(tool, file_path=str(path))
        # Reorder within Connection: user -> host.
        view._on_form_reordered("Connection", ["user", "host"])
        ids = [p.id for p in view._tool.params]
        # The Debug-section param should still be last.
        assert ids[-1] == "verbose"
        # Within Connection, order flipped.
        assert ids.index("user") < ids.index("host")
        # Persisted.
        reloaded = load_tool(path)
        ids2 = [p.id for p in reloaded.params]
        assert ids2.index("user") < ids2.index("host")
        assert ids2[-1] == "verbose"


# --- editor section management ---------------------------------------------


class TestEditorSectionManagement:
    def test_add_section_appends_to_tool(self, monkeypatch) -> None:
        editor = ToolEditorView(_flat_tool())
        # Patch QInputDialog.getText to return a fixed name.
        from PySide6.QtWidgets import QInputDialog
        monkeypatch.setattr(
            QInputDialog, "getText",
            staticmethod(lambda *a, **k: ("Advanced", True)),
        )
        editor._param_list.setCurrentRow(0)
        editor._add_section()
        assert [s.name for s in editor._tool.sections] == ["Advanced"]
        # The currently-selected param should have been auto-assigned
        # into the new section (convenience — one less click).
        assert editor._tool.params[0].section == "Advanced"

    def test_add_section_duplicate_name_rejected(self, monkeypatch) -> None:
        editor = ToolEditorView(_sectioned_tool())
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        monkeypatch.setattr(
            QInputDialog, "getText",
            staticmethod(lambda *a, **k: ("Connection", True)),
        )
        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
        before = len(editor._tool.sections)
        editor._add_section()
        assert len(editor._tool.sections) == before

    def test_rename_section_repoints_params(self, monkeypatch) -> None:
        editor = ToolEditorView(_sectioned_tool())
        from PySide6.QtWidgets import QInputDialog
        # First call returns the section to rename, second returns new name.
        calls = iter([("Connection", True), ("Network", True)])
        monkeypatch.setattr(
            QInputDialog, "getItem",
            staticmethod(lambda *a, **k: next(calls)),
        )
        monkeypatch.setattr(
            QInputDialog, "getText",
            staticmethod(lambda *a, **k: next(calls)),
        )
        editor._rename_section()
        names = [s.name for s in editor._tool.sections]
        assert "Network" in names and "Connection" not in names
        assert editor._tool.param_by_id("host").section == "Network"
        assert editor._tool.param_by_id("user").section == "Network"

    def test_remove_section_orphans_params(self, monkeypatch) -> None:
        editor = ToolEditorView(_sectioned_tool())
        from PySide6.QtWidgets import QInputDialog
        monkeypatch.setattr(
            QInputDialog, "getItem",
            staticmethod(lambda *a, **k: ("Debug", True)),
        )
        editor._remove_section()
        assert [s.name for s in editor._tool.sections] == ["Connection"]
        # Verbose param's section field cleared.
        assert editor._tool.param_by_id("verbose").section == ""


class TestEditorPreviewWithSections:
    def test_sectioned_preview_has_groupbox_rows(self) -> None:
        editor = ToolEditorView(_sectioned_tool())
        layout = editor._form_preview_layout  # QVBoxLayout
        # The layout holds one QGroupBox per section (collapse mode)
        # plus a trailing stretch.
        found_boxes = []
        for i in range(layout.count()):
            item = layout.itemAt(i)
            w = item.widget() if item else None
            if isinstance(w, QGroupBox):
                found_boxes.append(w)
        assert len(found_boxes) == 2
        assert {b.title() for b in found_boxes} == {"Connection", "Debug"}

    def test_prop_section_combo_lists_declared_sections(self) -> None:
        editor = ToolEditorView(_sectioned_tool())
        combo = editor._prop_section
        # Index 0 is "(no section)", then Connection, then Debug.
        labels = [combo.itemText(i) for i in range(combo.count())]
        assert labels == ["(no section)", "Connection", "Debug"]

    def test_changing_prop_section_moves_param(self) -> None:
        editor = ToolEditorView(_sectioned_tool())
        editor._param_list.setCurrentRow(0)  # host
        idx = editor._prop_section.findData("Debug")
        editor._prop_section.setCurrentIndex(idx)
        assert editor._tool.param_by_id("host").section == "Debug"
