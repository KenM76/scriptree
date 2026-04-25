"""Tests for the new shared/personal configuration capabilities
(read_shared_configurations, write_shared_configurations,
read_personal_configurations, write_personal_configurations) and
the legacy fallback logic.
"""
from __future__ import annotations

import stat
from pathlib import Path

from scriptree.core.permissions import (
    PermissionSet,
    can_read_personal,
    can_read_shared,
    can_write_personal,
    can_write_shared,
    load_permissions,
)


class TestLegacyFallback:
    def test_falls_back_to_read_configurations(self, tmp_path: Path):
        """When new granular file isn't deployed, falls back to legacy."""
        app_dir = tmp_path / "permissions"
        app_dir.mkdir()
        # Only legacy file exists.
        (app_dir / "read_configurations").touch()
        # No read_shared_configurations file.

        ps = load_permissions(custom_permissions_path=str(app_dir))
        # Legacy file is writable → read_shared falls back to True.
        assert can_read_shared(ps) is True

    def test_legacy_denied_fallback(self, tmp_path: Path):
        app_dir = tmp_path / "permissions"
        app_dir.mkdir()
        f = app_dir / "read_configurations"
        f.touch()
        f.chmod(stat.S_IREAD)
        try:
            ps = load_permissions(custom_permissions_path=str(app_dir))
            assert can_read_shared(ps) is False
            assert can_read_personal(ps) is False
        finally:
            f.chmod(stat.S_IWRITE | stat.S_IREAD)

    def test_new_capability_overrides_legacy(self, tmp_path: Path):
        """When both exist, the granular one wins."""
        app_dir = tmp_path / "permissions"
        app_dir.mkdir()
        # Legacy: allowed.
        (app_dir / "read_configurations").touch()
        # Granular: denied.
        f = app_dir / "read_shared_configurations"
        f.touch()
        f.chmod(stat.S_IREAD)
        try:
            ps = load_permissions(custom_permissions_path=str(app_dir))
            # Granular denies, legacy allows → denied (granular wins).
            assert can_read_shared(ps) is False
            # But read_personal still falls back to legacy (no granular file).
            assert can_read_personal(ps) is True
        finally:
            f.chmod(stat.S_IWRITE | stat.S_IREAD)


class TestGranularPermissions:
    def test_all_four_allowed(self, tmp_path: Path):
        app_dir = tmp_path / "permissions"
        app_dir.mkdir()
        for name in (
            "read_shared_configurations",
            "write_shared_configurations",
            "read_personal_configurations",
            "write_personal_configurations",
        ):
            (app_dir / name).touch()
        ps = load_permissions(custom_permissions_path=str(app_dir))
        assert can_read_shared(ps)
        assert can_write_shared(ps)
        assert can_read_personal(ps)
        assert can_write_personal(ps)

    def test_personal_allowed_shared_denied(self, tmp_path: Path):
        app_dir = tmp_path / "permissions"
        app_dir.mkdir()
        (app_dir / "read_personal_configurations").touch()
        (app_dir / "write_personal_configurations").touch()
        # Deny shared via read-only files.
        for name in (
            "read_shared_configurations", "write_shared_configurations",
        ):
            f = app_dir / name
            f.touch()
            f.chmod(stat.S_IREAD)
        try:
            ps = load_permissions(custom_permissions_path=str(app_dir))
            assert can_read_personal(ps)
            assert can_write_personal(ps)
            assert not can_read_shared(ps)
            assert not can_write_shared(ps)
        finally:
            for name in (
                "read_shared_configurations", "write_shared_configurations",
            ):
                (app_dir / name).chmod(stat.S_IWRITE | stat.S_IREAD)
