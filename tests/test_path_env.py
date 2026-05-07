"""Tests for ``scriptree.core.path_env``.

Covers the three "safe" scopes that don't touch the OS environment
beyond the current process. The system / user PATH scopes write to
the Windows registry — those are smoke-tested by hand, since
modifying real registry keys in a unit test would be both slow and
side-effecting.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from scriptree.core.io import load_tool, load_tree, save_tool, save_tree
from scriptree.core.model import ToolDef, TreeDef
from scriptree.core.path_env import (
    ScopeResult,
    add_to_scriptree_path_prepend,
    add_to_scriptreetree_path_prepend,
    add_to_session_path,
)


class TestSessionPath:
    def test_prepends_to_path(self, monkeypatch) -> None:
        monkeypatch.setenv("PATH", "C:/existing")
        r = add_to_session_path("C:/new")
        assert r.ok
        first = os.environ["PATH"].split(os.pathsep)[0]
        assert os.path.normcase(first) == os.path.normcase(
            os.path.abspath("C:/new")
        )

    def test_idempotent_when_already_first(self, monkeypatch) -> None:
        monkeypatch.setenv("PATH", "")
        add_to_session_path("C:/foo")
        r = add_to_session_path("C:/foo")
        assert r.ok
        assert "first" in r.message.lower()

    def test_moves_to_front_when_already_present(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("PATH", os.pathsep.join([
            "C:/a", "C:/b", "C:/foo", "C:/c",
        ]))
        r = add_to_session_path("C:/foo")
        assert r.ok
        parts = os.environ["PATH"].split(os.pathsep)
        # foo is now first; old entry removed (no duplicates).
        assert os.path.normcase(parts[0]) == os.path.normcase(
            os.path.abspath("C:/foo")
        )
        assert sum(
            1 for p in parts
            if os.path.normcase(os.path.abspath(p))
            == os.path.normcase(os.path.abspath("C:/foo"))
        ) == 1

    def test_empty_directory_rejected(self) -> None:
        r = add_to_session_path("")
        assert not r.ok


class TestScripTreePathPrepend:
    def test_appends_and_persists(self, tmp_path: Path) -> None:
        p = tmp_path / "tool.scriptree"
        save_tool(ToolDef(name="t", executable="gh.exe"), p)

        r = add_to_scriptree_path_prepend(str(p), "C:/Tools/gh")
        assert r.ok
        assert r.file_modified == str(p)

        restored = load_tool(p)
        assert restored.path_prepend == ["C:/Tools/gh"]

    def test_appends_to_existing(self, tmp_path: Path) -> None:
        p = tmp_path / "tool.scriptree"
        tool = ToolDef(
            name="t", executable="gh.exe",
            path_prepend=["C:/Existing"],
        )
        save_tool(tool, p)

        r = add_to_scriptree_path_prepend(str(p), "C:/Tools/gh")
        assert r.ok
        restored = load_tool(p)
        assert restored.path_prepend == ["C:/Existing", "C:/Tools/gh"]

    def test_idempotent_when_already_present(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "tool.scriptree"
        save_tool(
            ToolDef(
                name="t", executable="gh.exe",
                path_prepend=["C:/Tools/gh"],
            ),
            p,
        )

        r = add_to_scriptree_path_prepend(str(p), "C:/Tools/gh")
        assert r.ok
        assert "already" in r.message.lower()
        restored = load_tool(p)
        # Still just one entry.
        assert restored.path_prepend == ["C:/Tools/gh"]

    def test_missing_file_returns_error(self, tmp_path: Path) -> None:
        r = add_to_scriptree_path_prepend(
            str(tmp_path / "nope.scriptree"), "C:/Tools/gh",
        )
        assert not r.ok
        assert "not found" in r.message.lower()


class TestScripTreeTreePathPrepend:
    def test_appends_and_persists(self, tmp_path: Path) -> None:
        p = tmp_path / "tree.scriptreetree"
        save_tree(TreeDef(name="t"), p)

        r = add_to_scriptreetree_path_prepend(str(p), "C:/Tools")
        assert r.ok
        restored = load_tree(p)
        assert restored.path_prepend == ["C:/Tools"]

    def test_idempotent(self, tmp_path: Path) -> None:
        p = tmp_path / "tree.scriptreetree"
        save_tree(
            TreeDef(name="t", path_prepend=["C:/Tools"]),
            p,
        )

        r = add_to_scriptreetree_path_prepend(str(p), "C:/Tools")
        assert r.ok
        assert "already" in r.message.lower()
