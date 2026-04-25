"""Tests for the file-permission checking module (core/permissions.py).

Covers:
- Writable files report fully_writable
- Read-only main file → main_file_writable = False
- Read-only sidecar → sidecar_writable = False
- Non-existent sidecar in writable dir → sidecar_writable = True
- Non-existent file in writable dir → main_file_writable = True
- .scriptreetree uses tree sidecar suffix
- WriteAccess property logic
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from scriptree.core.configs import SIDECAR_SUFFIX, TREE_SIDECAR_SUFFIX
from scriptree.core.permissions import WriteAccess, check_write_access


# --- WriteAccess dataclass ---

class TestWriteAccess:
    def test_fully_writable(self) -> None:
        wa = WriteAccess(main_file_writable=True, sidecar_writable=True)
        assert wa.fully_writable is True
        assert wa.any_writable is True

    def test_main_only(self) -> None:
        wa = WriteAccess(main_file_writable=True, sidecar_writable=False)
        assert wa.fully_writable is False
        assert wa.any_writable is True

    def test_sidecar_only(self) -> None:
        wa = WriteAccess(main_file_writable=False, sidecar_writable=True)
        assert wa.fully_writable is False
        assert wa.any_writable is True

    def test_neither(self) -> None:
        wa = WriteAccess(main_file_writable=False, sidecar_writable=False)
        assert wa.fully_writable is False
        assert wa.any_writable is False

    def test_frozen(self) -> None:
        wa = WriteAccess(main_file_writable=True, sidecar_writable=True)
        with pytest.raises(AttributeError):
            wa.main_file_writable = False  # type: ignore[misc]


# --- check_write_access with real files ---

class TestCheckWriteAccess:
    def test_writable_file(self, tmp_path: Path) -> None:
        tool = tmp_path / "test.scriptree"
        tool.write_text("{}", encoding="utf-8")
        access = check_write_access(tool)
        assert access.main_file_writable is True
        # Sidecar doesn't exist yet, but dir is writable.
        assert access.sidecar_writable is True
        assert access.fully_writable is True

    def test_read_only_main_file(self, tmp_path: Path) -> None:
        tool = tmp_path / "test.scriptree"
        tool.write_text("{}", encoding="utf-8")
        # Make it read-only.
        tool.chmod(stat.S_IREAD)
        try:
            access = check_write_access(tool)
            assert access.main_file_writable is False
            # Sidecar doesn't exist, dir is still writable.
            assert access.sidecar_writable is True
            assert access.fully_writable is False
        finally:
            tool.chmod(stat.S_IWRITE | stat.S_IREAD)

    def test_read_only_sidecar(self, tmp_path: Path) -> None:
        tool = tmp_path / "test.scriptree"
        tool.write_text("{}", encoding="utf-8")
        sidecar = tmp_path / ("test.scriptree" + SIDECAR_SUFFIX)
        sidecar.write_text("{}", encoding="utf-8")
        sidecar.chmod(stat.S_IREAD)
        try:
            access = check_write_access(tool)
            assert access.main_file_writable is True
            assert access.sidecar_writable is False
            assert access.fully_writable is False
        finally:
            sidecar.chmod(stat.S_IWRITE | stat.S_IREAD)

    def test_both_read_only(self, tmp_path: Path) -> None:
        tool = tmp_path / "test.scriptree"
        tool.write_text("{}", encoding="utf-8")
        sidecar = tmp_path / ("test.scriptree" + SIDECAR_SUFFIX)
        sidecar.write_text("{}", encoding="utf-8")
        tool.chmod(stat.S_IREAD)
        sidecar.chmod(stat.S_IREAD)
        try:
            access = check_write_access(tool)
            assert access.main_file_writable is False
            assert access.sidecar_writable is False
            assert access.fully_writable is False
            assert access.any_writable is False
        finally:
            tool.chmod(stat.S_IWRITE | stat.S_IREAD)
            sidecar.chmod(stat.S_IWRITE | stat.S_IREAD)

    def test_nonexistent_file_writable_dir(self, tmp_path: Path) -> None:
        tool = tmp_path / "new_tool.scriptree"
        # File doesn't exist — check dir writability.
        access = check_write_access(tool)
        assert access.main_file_writable is True
        assert access.sidecar_writable is True

    def test_nonexistent_sidecar_writable_dir(self, tmp_path: Path) -> None:
        tool = tmp_path / "test.scriptree"
        tool.write_text("{}", encoding="utf-8")
        # No sidecar exists — dir is writable.
        access = check_write_access(tool)
        assert access.sidecar_writable is True


class TestTreeSidecarDetection:
    def test_scriptreetree_uses_tree_suffix(self, tmp_path: Path) -> None:
        tree = tmp_path / "test.scriptreetree"
        tree.write_text("{}", encoding="utf-8")
        # Create the tree sidecar as read-only.
        tree_sidecar = tmp_path / ("test.scriptreetree" + TREE_SIDECAR_SUFFIX)
        tree_sidecar.write_text("{}", encoding="utf-8")
        tree_sidecar.chmod(stat.S_IREAD)
        try:
            access = check_write_access(tree)
            assert access.main_file_writable is True
            # Tree sidecar should be detected as not writable.
            assert access.sidecar_writable is False
        finally:
            tree_sidecar.chmod(stat.S_IWRITE | stat.S_IREAD)

    def test_scriptree_uses_regular_suffix(self, tmp_path: Path) -> None:
        tool = tmp_path / "test.scriptree"
        tool.write_text("{}", encoding="utf-8")
        # Create the regular sidecar as read-only.
        sidecar = tmp_path / ("test.scriptree" + SIDECAR_SUFFIX)
        sidecar.write_text("{}", encoding="utf-8")
        sidecar.chmod(stat.S_IREAD)
        try:
            access = check_write_access(tool)
            assert access.sidecar_writable is False
        finally:
            sidecar.chmod(stat.S_IWRITE | stat.S_IREAD)


class TestStringPath:
    """Verify that check_write_access accepts str as well as Path."""

    def test_accepts_string(self, tmp_path: Path) -> None:
        tool = tmp_path / "test.scriptree"
        tool.write_text("{}", encoding="utf-8")
        access = check_write_access(str(tool))
        assert access.fully_writable is True
