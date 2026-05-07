"""Tests for the capability-based permission system.

Tests the load_permissions function with app-level and per-file
permission directories, conflict detection, merge rules, and the
secure default (missing file = denied at app level).
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from scriptree.core.permissions import (
    CAPABILITIES,
    PermissionSet,
    _read_capability,
    load_permissions,
)


class TestReadCapability:
    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        result = _read_capability(tmp_path, "create_new_scriptree")
        assert result is None

    def test_writable_file_returns_true(self, tmp_path: Path) -> None:
        cap_dir = tmp_path / "files"
        cap_dir.mkdir()
        cap_file = cap_dir / "create_new_scriptree"
        cap_file.touch()
        result = _read_capability(tmp_path, "create_new_scriptree")
        assert result is True

    def test_readonly_file_returns_false(self, tmp_path: Path) -> None:
        cap_dir = tmp_path / "files"
        cap_dir.mkdir()
        cap_file = cap_dir / "create_new_scriptree"
        cap_file.touch()
        cap_file.chmod(stat.S_IREAD)
        try:
            result = _read_capability(tmp_path, "create_new_scriptree")
            assert result is False
        finally:
            cap_file.chmod(stat.S_IWRITE | stat.S_IREAD)


class TestPermissionSet:
    def test_default_allows_everything(self) -> None:
        ps = PermissionSet()
        assert ps.can("create_new_scriptree") is True
        assert ps.can("nonexistent/capability") is True

    def test_explicit_deny(self) -> None:
        ps = PermissionSet(allowed={"create_new_scriptree": False})
        assert ps.can("create_new_scriptree") is False

    def test_no_conflicts(self) -> None:
        ps = PermissionSet()
        assert not ps.has_conflicts()

    def test_conflict_summary(self) -> None:
        from scriptree.core.permissions import PermissionConflict
        ps = PermissionSet(conflicts=[
            PermissionConflict(
                capability="save_scriptree",
                description="Save .scriptree files",
                app_level_allowed=True,
                file_level_allowed=False,
                resolved_to=False,
                app_source="/app/permissions/files/save_scriptree",
                file_source="/tool/permissions/files/save_scriptree",
            )
        ])
        assert ps.has_conflicts()
        summary = ps.conflict_summary()
        assert "Save .scriptree files" in summary
        assert "denied" in summary


class TestLoadPermissionsNoDir:
    def test_no_permissions_dir_allows_all(self, tmp_path: Path) -> None:
        """When no permissions directory exists at all (developer mode),
        everything is allowed."""
        tool = tmp_path / "test.scriptree"
        tool.touch()
        # Point to a nonexistent custom path so the walk-up doesn't
        # find the real project permissions/ dir.
        fake = str(tmp_path / "nonexistent_perms")
        perms = load_permissions(
            file_path=str(tool),
            custom_permissions_path=fake,
        )
        for cap in CAPABILITIES:
            assert perms.can(cap) is True, f"{cap} should be allowed in dev mode"


class TestAppLevelSecureDefault:
    """App-level: missing file = DENIED when the permissions dir exists."""

    def test_missing_file_in_app_dir_denies(self, tmp_path: Path) -> None:
        """If the app permissions dir exists but a file is missing,
        the capability is denied (secure default)."""
        app_dir = tmp_path / "permissions"
        app_dir.mkdir()
        # Don't create any capability files — all should be denied.
        perms = load_permissions(custom_permissions_path=str(app_dir))
        for cap in CAPABILITIES:
            assert perms.can(cap) is False, f"{cap} should be denied"

    def test_writable_file_allows(self, tmp_path: Path) -> None:
        """A writable file in the app permissions dir allows."""
        app_dir = tmp_path / "permissions"
        (app_dir / "files").mkdir(parents=True)
        cap_file = app_dir / "files" / "save_scriptree"
        cap_file.touch()  # writable
        perms = load_permissions(custom_permissions_path=str(app_dir))
        assert perms.can("save_scriptree") is True

    def test_readonly_file_denies(self, tmp_path: Path) -> None:
        """A read-only file in the app permissions dir denies."""
        app_dir = tmp_path / "permissions"
        (app_dir / "files").mkdir(parents=True)
        cap_file = app_dir / "files" / "save_scriptree"
        cap_file.touch()
        cap_file.chmod(stat.S_IREAD)
        try:
            perms = load_permissions(custom_permissions_path=str(app_dir))
            assert perms.can("save_scriptree") is False
        finally:
            cap_file.chmod(stat.S_IWRITE | stat.S_IREAD)


class TestPerFileInheritance:
    """Per-file level: missing file = INHERIT from app level."""

    def _make_app_dir(self, tmp_path: Path) -> Path:
        """Create an app permissions dir with one allowed capability."""
        app_dir = tmp_path / "app_perms"
        (app_dir / "files").mkdir(parents=True)
        (app_dir / "files" / "save_scriptree").touch()  # writable = allowed
        return app_dir

    def test_per_file_missing_inherits_from_app(self, tmp_path: Path) -> None:
        """Per-file missing → inherits allowed from app."""
        app_dir = self._make_app_dir(tmp_path)
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        tool = tool_dir / "test.scriptree"
        tool.touch()
        # tool_dir has no permissions/ subfolder → inherit from app.
        perms = load_permissions(
            file_path=str(tool),
            custom_permissions_path=str(app_dir),
        )
        assert perms.can("save_scriptree") is True

    def test_per_file_readonly_restricts(self, tmp_path: Path) -> None:
        """Per-file read-only overrides app-level allowed (restricts)."""
        app_dir = self._make_app_dir(tmp_path)
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        tool = tool_dir / "test.scriptree"
        tool.touch()
        perm_dir = tool_dir / "permissions" / "files"
        perm_dir.mkdir(parents=True)
        cap_file = perm_dir / "save_scriptree"
        cap_file.touch()
        cap_file.chmod(stat.S_IREAD)
        try:
            perms = load_permissions(
                file_path=str(tool),
                custom_permissions_path=str(app_dir),
            )
            assert perms.can("save_scriptree") is False
        finally:
            cap_file.chmod(stat.S_IWRITE | stat.S_IREAD)

    def test_per_file_cannot_grant_beyond_app(self, tmp_path: Path) -> None:
        """Per-file writable cannot grant when app-level denies."""
        app_dir = tmp_path / "app_perms"
        app_dir.mkdir()
        # App dir exists but save_scriptree file is missing → denied.
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        tool = tool_dir / "test.scriptree"
        tool.touch()
        perm_dir = tool_dir / "permissions" / "files"
        perm_dir.mkdir(parents=True)
        (perm_dir / "save_scriptree").touch()  # writable = tries to allow
        perms = load_permissions(
            file_path=str(tool),
            custom_permissions_path=str(app_dir),
        )
        # App denies (missing file), per-file can't override → denied.
        assert perms.can("save_scriptree") is False

    def test_conflict_detected(self, tmp_path: Path) -> None:
        """When app allows and per-file denies, conflict is recorded."""
        app_dir = self._make_app_dir(tmp_path)
        tool_dir = tmp_path / "tool"
        tool_dir.mkdir()
        tool = tool_dir / "test.scriptree"
        tool.touch()
        perm_dir = tool_dir / "permissions" / "files"
        perm_dir.mkdir(parents=True)
        cap_file = perm_dir / "save_scriptree"
        cap_file.touch()
        cap_file.chmod(stat.S_IREAD)
        try:
            perms = load_permissions(
                file_path=str(tool),
                custom_permissions_path=str(app_dir),
            )
            assert perms.has_conflicts()
            assert any(
                c.capability == "save_scriptree"
                for c in perms.conflicts
            )
        finally:
            cap_file.chmod(stat.S_IWRITE | stat.S_IREAD)


class TestCustomPermissionsPath:
    def test_custom_path_used(self, tmp_path: Path) -> None:
        """load_permissions uses custom_permissions_path when given."""
        custom = tmp_path / "my_perms"
        (custom / "files").mkdir(parents=True)
        (custom / "files" / "save_scriptree").touch()  # writable
        perms = load_permissions(custom_permissions_path=str(custom))
        assert perms.can("save_scriptree") is True
        assert perms.app_permissions_dir == str(custom)


class TestRecursiveSearch:
    """Capability files are found regardless of subfolder structure."""

    def test_file_found_in_subfolder(self, tmp_path: Path) -> None:
        """A capability file in a nested subfolder is found."""
        app_dir = tmp_path / "perms"
        (app_dir / "group_A" / "dept_X").mkdir(parents=True)
        (app_dir / "group_A" / "dept_X" / "save_scriptree").touch()
        perms = load_permissions(custom_permissions_path=str(app_dir))
        assert perms.can("save_scriptree") is True

    def test_file_found_at_root(self, tmp_path: Path) -> None:
        """A capability file at the permissions root is found."""
        app_dir = tmp_path / "perms"
        app_dir.mkdir()
        (app_dir / "save_scriptree").touch()
        perms = load_permissions(custom_permissions_path=str(app_dir))
        assert perms.can("save_scriptree") is True

    def test_most_restrictive_wins_with_duplicates(self, tmp_path: Path) -> None:
        """When the same file exists in multiple subfolders, the most
        restrictive (read-only) wins."""
        app_dir = tmp_path / "perms"
        (app_dir / "group_A").mkdir(parents=True)
        (app_dir / "group_B").mkdir(parents=True)
        # group_A allows (writable)
        (app_dir / "group_A" / "save_scriptree").touch()
        # group_B denies (read-only)
        denied = app_dir / "group_B" / "save_scriptree"
        denied.touch()
        denied.chmod(stat.S_IREAD)
        try:
            perms = load_permissions(custom_permissions_path=str(app_dir))
            # Most restrictive wins → denied.
            assert perms.can("save_scriptree") is False
        finally:
            denied.chmod(stat.S_IWRITE | stat.S_IREAD)

    def test_all_copies_writable_allows(self, tmp_path: Path) -> None:
        """When all copies are writable, the capability is allowed."""
        app_dir = tmp_path / "perms"
        (app_dir / "team_1").mkdir(parents=True)
        (app_dir / "team_2").mkdir(parents=True)
        (app_dir / "team_1" / "save_scriptree").touch()
        (app_dir / "team_2" / "save_scriptree").touch()
        perms = load_permissions(custom_permissions_path=str(app_dir))
        assert perms.can("save_scriptree") is True


class TestNoFilePathAppOnly:
    def test_no_file_path_uses_app_only(self) -> None:
        """When no file_path is given, only app-level permissions apply."""
        perms = load_permissions()
        assert isinstance(perms, PermissionSet)
