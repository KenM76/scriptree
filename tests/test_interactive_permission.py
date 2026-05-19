"""Permission tests for the v0.3.0 ``interactive_stdin`` capability."""
from __future__ import annotations

from pathlib import Path

from scriptree.core.permissions import (
    CAPABILITIES,
    PermissionSet,
    load_permissions,
)


def test_capability_registered() -> None:
    """The new capability must appear in the dict so admin tools (and
    the missing-file scanner) know about it."""
    assert "interactive_stdin" in CAPABILITIES
    desc = CAPABILITIES["interactive_stdin"]
    assert "stdin" in desc.lower()


def test_capability_default_denied_when_perm_dir_present_but_file_missing(
    tmp_path: Path, monkeypatch,
) -> None:
    """Per ScripTree's secure-default rule: a deployed permissions
    directory that is *missing* the ``interactive_stdin`` file means
    the capability is denied at the app level."""
    perms_dir = tmp_path / "permissions"
    perms_dir.mkdir()
    # Other capabilities exist but interactive_stdin does not.
    (perms_dir / "run_tools").write_text("", encoding="utf-8")

    ps = load_permissions(custom_permissions_path=str(perms_dir))
    assert ps.can("run_tools") is True
    assert ps.can("interactive_stdin") is False


def test_capability_granted_when_file_exists_and_writable(
    tmp_path: Path,
) -> None:
    perms_dir = tmp_path / "permissions"
    perms_dir.mkdir()
    (perms_dir / "interactive_stdin").write_text("", encoding="utf-8")

    ps = load_permissions(custom_permissions_path=str(perms_dir))
    assert ps.can("interactive_stdin") is True


def test_capability_denied_when_file_readonly(tmp_path: Path) -> None:
    """An admin can lock down the feature by making the capability
    file read-only — the resolver flips back to denied."""
    import os
    import stat

    perms_dir = tmp_path / "permissions"
    perms_dir.mkdir()
    cap_file = perms_dir / "interactive_stdin"
    cap_file.write_text("", encoding="utf-8")
    os.chmod(cap_file, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    ps = load_permissions(custom_permissions_path=str(perms_dir))
    assert ps.can("interactive_stdin") is False

    # Restore so cleanup can delete the file.
    os.chmod(cap_file, stat.S_IRUSR | stat.S_IWUSR)


def test_no_permission_dir_means_developer_mode_allows_capability(
    tmp_path: Path, monkeypatch,
) -> None:
    """When no permissions directory is deployed at all (developer
    install), every capability — including interactive_stdin —
    defaults to allowed.  Matches the documented developer-mode rule.

    We force "no perm dir" by pointing the env variable at a
    non-existent path AND scrubbing the auto-walk fallback by
    monkeypatching the discovery helper."""
    monkeypatch.setenv("SCRIPTREE_PERMISSIONS_DIR", "")
    monkeypatch.setattr(
        "scriptree.core.permissions._find_app_permissions_dir",
        lambda custom_path=None: None,
    )
    ps = load_permissions()
    assert ps.can("interactive_stdin") is True
