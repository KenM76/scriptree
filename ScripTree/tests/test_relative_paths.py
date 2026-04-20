"""Tests for relative-path resolution in ToolDef fields.

A ``.scriptree`` file can store ``executable``, ``working_directory``,
and ``path_prepend`` entries as paths relative to the .scriptree file's
own directory. At run time they're resolved against
``tool.loaded_from`` (set by ``load_tool``/``save_tool``) so moving the
folder doesn't require updating the paths.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scriptree.core.io import load_tool, save_tool
from scriptree.core.model import ParamDef, ToolDef
from scriptree.core.runner import build_env, resolve, resolve_tool_path


class TestResolveToolPath:
    def test_empty_string_is_returned_as_is(self, tmp_path: Path):
        assert resolve_tool_path("", str(tmp_path / "t.scriptree")) == ""

    def test_absolute_path_is_returned_as_is(self, tmp_path: Path):
        abs_p = str(tmp_path / "external.exe")
        assert resolve_tool_path(abs_p, str(tmp_path / "t.scriptree")) == abs_p

    def test_relative_without_anchor_returns_original(self):
        assert resolve_tool_path("./sub/t.exe", None) == "./sub/t.exe"

    def test_relative_resolves_against_tool_file_when_exists(
        self, tmp_path: Path
    ):
        sub = tmp_path / "sub"
        sub.mkdir()
        exe = sub / "t.exe"
        exe.touch()
        tool_file = tmp_path / "tool.scriptree"
        tool_file.touch()
        result = resolve_tool_path("./sub/t.exe", str(tool_file))
        assert Path(result) == exe.resolve()

    def test_bare_name_returns_original_when_not_existing(
        self, tmp_path: Path
    ):
        tool_file = tmp_path / "tool.scriptree"
        tool_file.touch()
        # "python" isn't a sibling file so we fall back to the
        # bare name for PATH resolution.
        assert resolve_tool_path("python", str(tool_file)) == "python"

    def test_relative_resolves_parent_up(self, tmp_path: Path):
        parent_exe = tmp_path / "bin" / "tool.exe"
        parent_exe.parent.mkdir()
        parent_exe.touch()
        tool_file = tmp_path / "configs" / "tool.scriptree"
        tool_file.parent.mkdir()
        tool_file.touch()
        result = resolve_tool_path("../bin/tool.exe", str(tool_file))
        assert Path(result) == parent_exe.resolve()


class TestLoadToolSetsLoadedFrom:
    def test_load_tool_populates_loaded_from(self, tmp_path: Path):
        tool = ToolDef(name="t", executable="./my.exe")
        path = tmp_path / "t.scriptree"
        save_tool(tool, path)
        loaded = load_tool(path)
        assert loaded.loaded_from == str(path.resolve())

    def test_save_tool_also_updates_loaded_from(self, tmp_path: Path):
        """After Save As, the in-memory tool knows its new location."""
        tool = ToolDef(name="t", executable="./my.exe")
        p1 = tmp_path / "a" / "t.scriptree"
        p1.parent.mkdir()
        save_tool(tool, p1)
        assert tool.loaded_from == str(p1.resolve())
        p2 = tmp_path / "b" / "t.scriptree"
        p2.parent.mkdir()
        save_tool(tool, p2)
        assert tool.loaded_from == str(p2.resolve())

    def test_loaded_from_not_serialized(self, tmp_path: Path):
        """The loaded_from attribute must never appear in the JSON."""
        tool = ToolDef(name="t", executable="./my.exe")
        path = tmp_path / "t.scriptree"
        save_tool(tool, path)
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "loaded_from" not in data


class TestResolveUsesLoadedFrom:
    def test_relative_executable_resolved(self, tmp_path: Path):
        exe = tmp_path / "real.exe"
        exe.touch()
        tool_file = tmp_path / "tool.scriptree"
        tool = ToolDef(name="t", executable="./real.exe")
        save_tool(tool, tool_file)
        loaded = load_tool(tool_file)
        cmd = resolve(loaded, {})
        assert Path(cmd.argv[0]) == exe.resolve()

    def test_relative_working_directory_resolved(self, tmp_path: Path):
        exe = tmp_path / "real.exe"
        exe.touch()
        subdir = tmp_path / "work"
        subdir.mkdir()
        tool_file = tmp_path / "tool.scriptree"
        tool = ToolDef(
            name="t",
            executable="./real.exe",
            working_directory="./work",
        )
        save_tool(tool, tool_file)
        loaded = load_tool(tool_file)
        cmd = resolve(loaded, {})
        assert Path(cmd.cwd) == subdir.resolve()

    def test_portable_across_folder_move(self, tmp_path: Path):
        """Moving the folder shouldn't break the tool."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "real.exe").touch()
        tool = ToolDef(name="t", executable="./real.exe")
        save_tool(tool, src / "tool.scriptree")

        # Copy the folder to a new location and load from there.
        dst = tmp_path / "dst"
        shutil.copytree(src, dst)

        loaded = load_tool(dst / "tool.scriptree")
        cmd = resolve(loaded, {})
        # The resolved executable should live in dst, not src.
        assert str(dst.resolve()) in cmd.argv[0]
        assert str(src.resolve()) not in cmd.argv[0]


class TestBuildEnvWithRelativeToolPath:
    def test_path_prepend_anchored_on_loaded_from(self, tmp_path: Path):
        """path_prepend with relative working_directory should anchor
        on the .scriptree file's directory, not process CWD."""
        bindir = tmp_path / "bin"
        bindir.mkdir()
        (tmp_path / "real.exe").touch()
        tool = ToolDef(
            name="t",
            executable="./real.exe",
            working_directory="./",
            path_prepend=["./bin"],
        )
        tool_file = tmp_path / "tool.scriptree"
        save_tool(tool, tool_file)
        loaded = load_tool(tool_file)

        import os as _os
        env = build_env(loaded, base_env={"PATH": ""})
        assert env is not None
        first = env["PATH"].split(_os.pathsep)[0]
        assert Path(first) == bindir.resolve()


class TestMaybeRelativizeInEditor:
    """The editor's _maybe_relativize_paths helper rewrites absolute
    paths that live under the save directory into relative form."""

    def test_relativize_inside_save_dir(self, tmp_path: Path):
        pytest.importorskip("PySide6")
        from PySide6.QtWidgets import QApplication
        _ = QApplication.instance() or QApplication([])

        from scriptree.ui.tool_editor import ToolEditorView
        (tmp_path / "sub").mkdir()
        exe = tmp_path / "sub" / "tool.exe"
        exe.touch()
        tool = ToolDef(name="t", executable=str(exe))
        view = ToolEditorView(tool)  # deepcopies into view._tool
        view._maybe_relativize_paths(str(tmp_path / "tool.scriptree"))
        assert view._tool.executable == "./sub/tool.exe"

    def test_keep_absolute_for_paths_outside(self, tmp_path: Path):
        pytest.importorskip("PySide6")
        from PySide6.QtWidgets import QApplication
        _ = QApplication.instance() or QApplication([])

        from scriptree.ui.tool_editor import ToolEditorView
        outside = tmp_path / "elsewhere" / "tool.exe"
        outside.parent.mkdir()
        outside.touch()
        save_dir = tmp_path / "project"
        save_dir.mkdir()
        tool = ToolDef(name="t", executable=str(outside))
        view = ToolEditorView(tool)
        view._maybe_relativize_paths(str(save_dir / "tool.scriptree"))
        assert Path(view._tool.executable).is_absolute()

    def test_already_relative_unchanged(self, tmp_path: Path):
        pytest.importorskip("PySide6")
        from PySide6.QtWidgets import QApplication
        _ = QApplication.instance() or QApplication([])

        from scriptree.ui.tool_editor import ToolEditorView
        tool = ToolDef(name="t", executable="./existing_relative.exe")
        view = ToolEditorView(tool)
        view._maybe_relativize_paths(str(tmp_path / "tool.scriptree"))
        assert view._tool.executable == "./existing_relative.exe"

    def test_bare_name_unchanged(self, tmp_path: Path):
        pytest.importorskip("PySide6")
        from PySide6.QtWidgets import QApplication
        _ = QApplication.instance() or QApplication([])

        from scriptree.ui.tool_editor import ToolEditorView
        # "python" (bare name via PATH) shouldn't become "./python".
        tool = ToolDef(name="t", executable="python")
        view = ToolEditorView(tool)
        view._maybe_relativize_paths(str(tmp_path / "tool.scriptree"))
        assert view._tool.executable == "python"
