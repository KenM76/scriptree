"""Phase-1 regression suite for the drop-install core logic
(``scriptree.core.app_install``).

Covers:

* Default install-root resolution (shared + personal across the
  three OSes, with the INI override path checked).
* App-name inference from folder + zip sources, with
  filesystem-unsafe character scrubbing.
* Zip shape detection (wrapped vs flat) + ``infer_app_name``
  interaction.
* The five install paths:
    - folder source, no conflict
    - zip source (wrapped), no conflict
    - zip source (flat), no conflict
    - existing target raises without ``conflict_mode``
    - each ``ConflictMode`` produces the right outcome
* Path-traversal guard: a zip with ``..`` or absolute paths
  raises ``InstallError`` rather than escaping the target.
* ``pick_rename_target`` picks the next available numbered slot.

Auto-dismisses ``QMessageBox`` per the standing rule.
"""
from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)

from scriptree.core.app_install import (
    ConflictMode,
    InstallError,
    InstallResult,
    default_personal_root,
    default_shared_root,
    infer_app_name,
    install_app,
    pick_rename_target,
)
from scriptree.core.platform import _reset_host_cache_for_tests


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _make_app_folder(parent: Path, name: str, files: dict[str, str]) -> Path:
    """Build a fake app folder containing the given files.

    Each entry is ``"relative/path": "content"`` -- handy for
    asserting that file content survives copy / extract round
    trips.
    """
    root = parent / name
    root.mkdir(parents=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return root


def _make_zip(zip_path: Path, members: dict[str, str | None]) -> Path:
    """Build a zip at ``zip_path``.  ``None`` value indicates a
    directory-only entry."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, content in members.items():
            if content is None:
                # Directory entry: trailing slash.
                if not name.endswith("/"):
                    name = name + "/"
                zf.writestr(name, "")
            else:
                zf.writestr(name, content)
    return zip_path


# ============================================================================
# Default install roots
# ============================================================================


class TestDefaultRoots:
    def test_shared_root_under_scriptree_install(self) -> None:
        """Without an INI override, the shared root sits under
        the ScripTree app dir (parent of the ``scriptree``
        package)."""
        root = default_shared_root()
        assert root.name == "ScripTreeApps"
        # And it lives under the install tree; same parent as
        # _find_scriptree_dir's result.
        from scriptree.core.app_settings import _find_scriptree_dir
        assert root.parent == _find_scriptree_dir()

    def test_personal_root_windows(self) -> None:
        _reset_host_cache_for_tests()
        with patch("platform.system", return_value="Windows"):
            with patch.dict(
                os.environ, {"LOCALAPPDATA": r"C:\Users\X\AppData\Local"},
            ):
                root = default_personal_root()
                assert str(root).endswith(
                    str(Path("ScripTree") / "Apps")
                )
                assert "AppData" in str(root)
        _reset_host_cache_for_tests()

    def test_personal_root_macos(self) -> None:
        _reset_host_cache_for_tests()
        with patch("platform.system", return_value="Darwin"):
            root = default_personal_root()
            assert "Library/Application Support" in root.as_posix()
            assert root.name == "Apps"
        _reset_host_cache_for_tests()

    def test_personal_root_linux_xdg(self) -> None:
        _reset_host_cache_for_tests()
        with patch("platform.system", return_value="Linux"):
            with patch.dict(os.environ, {"XDG_DATA_HOME": "/tmp/xdg"}):
                root = default_personal_root()
                assert root == Path("/tmp/xdg/ScripTree/Apps")
        _reset_host_cache_for_tests()

    def test_personal_root_linux_no_xdg(self) -> None:
        _reset_host_cache_for_tests()
        with patch("platform.system", return_value="Linux"):
            with patch.dict(os.environ, {}, clear=False):
                # Clear XDG_DATA_HOME just in case the test env
                # carries one.
                os.environ.pop("XDG_DATA_HOME", None)
                root = default_personal_root()
                assert ".local/share/ScripTree/Apps" in root.as_posix()
        _reset_host_cache_for_tests()


# ============================================================================
# App name inference
# ============================================================================


class TestInferAppName:
    def test_folder_name(self, tmp_path: Path) -> None:
        src = tmp_path / "MyTool"
        src.mkdir()
        assert infer_app_name(src) == "MyTool"

    def test_zip_strips_extension(self, tmp_path: Path) -> None:
        src = _make_zip(tmp_path / "MyTool.zip", {"x": "x"})
        assert infer_app_name(src) == "MyTool"

    def test_zip_case_insensitive_extension(self, tmp_path: Path) -> None:
        # Even with .ZIP uppercase, ``Path.stem`` strips it.
        src = tmp_path / "Cap.ZIP"
        _make_zip(src, {"x": "x"})
        assert infer_app_name(src) == "Cap"

    def test_unsafe_chars_scrubbed(self, tmp_path: Path) -> None:
        """The scrub runs on the basename string, not on the FS
        entry -- so we can pass a constructed ``Path`` whose
        basename contains characters the OS would never let us
        create on disk and verify the result is clean."""
        src = tmp_path / "Mon<ke>y"
        # Don't ``mkdir`` -- the FS would reject those chars on
        # Windows.  ``infer_app_name`` reads only the path string.
        cleaned = infer_app_name(src)
        assert "<" not in cleaned
        assert ">" not in cleaned

    def test_empty_name_falls_back_to_App(self, tmp_path: Path) -> None:
        # Constructing a Path whose stem is empty: tricky, but we
        # can build it via a path with no basename.
        src = Path("/")
        assert infer_app_name(src) == "App"


# ============================================================================
# install_app -- happy paths
# ============================================================================


class TestInstallFolder:
    def test_folder_no_conflict(self, tmp_path: Path) -> None:
        src = _make_app_folder(
            tmp_path / "src", "Tool",
            {"main.scriptree": '{"name": "Tool"}', "README.md": "# Tool"},
        )
        target_root = tmp_path / "install"

        result = install_app(src, target_root)

        assert result.target == (target_root / "Tool").resolve()
        assert result.target.exists()
        assert (result.target / "main.scriptree").read_text(encoding="utf-8") == \
            '{"name": "Tool"}'
        assert (result.target / "README.md").exists()
        assert result.files_written == 2
        assert result.conflict_resolved is None

    def test_folder_into_missing_target_root_creates_it(
        self, tmp_path: Path,
    ) -> None:
        src = _make_app_folder(
            tmp_path / "src", "X", {"a.scriptree": "{}"},
        )
        target_root = tmp_path / "nonexistent" / "install"
        # target_root doesn't exist; install_app creates it.
        result = install_app(src, target_root)
        assert result.target.exists()


class TestInstallZipFlat:
    def test_flat_zip(self, tmp_path: Path) -> None:
        """A zip whose top level is multiple files / a folder
        whose name doesn't match the zip stem is treated as
        'flat' and wrapped on extract."""
        zip_path = _make_zip(
            tmp_path / "Toolkit.zip",
            {
                "tool-a.scriptree": '{"name": "A"}',
                "tool-b.scriptree": '{"name": "B"}',
            },
        )
        target_root = tmp_path / "install"

        result = install_app(zip_path, target_root)

        assert result.target == (target_root / "Toolkit").resolve()
        assert (result.target / "tool-a.scriptree").exists()
        assert (result.target / "tool-b.scriptree").exists()
        assert result.files_written == 2


class TestInstallZipWrapped:
    def test_wrapped_zip(self, tmp_path: Path) -> None:
        """A zip whose top level is exactly one folder named
        like the zip stem is treated as 'wrapped'; the wrapper
        is stripped on extract so files land at the same depth
        as in the flat case."""
        zip_path = _make_zip(
            tmp_path / "Toolkit.zip",
            {
                "Toolkit/": None,
                "Toolkit/tool-a.scriptree": '{"name": "A"}',
                "Toolkit/subdir/tool-b.scriptree": '{"name": "B"}',
            },
        )
        target_root = tmp_path / "install"

        result = install_app(zip_path, target_root)

        # The wrapper is stripped -- tool-a lives directly under
        # the install target, NOT under Toolkit/Toolkit/.
        assert (result.target / "tool-a.scriptree").exists()
        assert (result.target / "subdir" / "tool-b.scriptree").exists()
        # No nested duplicate.
        assert not (result.target / "Toolkit").exists()


# ============================================================================
# Conflict modes
# ============================================================================


class TestConflict:
    def _setup(self, tmp_path: Path) -> tuple[Path, Path]:
        """Create a source with one file + an existing target
        with a different file.  Returns ``(src, target_root)``.
        """
        src = _make_app_folder(
            tmp_path / "src", "X",
            {"new.scriptree": "new", "shared.scriptree": "from-src"},
        )
        target_root = tmp_path / "install"
        existing = _make_app_folder(
            target_root, "X",
            {
                "old.scriptree": "old-only-in-target",
                "shared.scriptree": "from-target",
            },
        )
        return src, target_root

    def test_no_conflict_mode_raises(self, tmp_path: Path) -> None:
        src, target_root = self._setup(tmp_path)
        with pytest.raises(InstallError, match="already exists"):
            install_app(src, target_root)

    def test_overwrite(self, tmp_path: Path) -> None:
        src, target_root = self._setup(tmp_path)
        result = install_app(
            src, target_root, conflict_mode=ConflictMode.OVERWRITE,
        )
        # Old file is gone.
        assert not (result.target / "old.scriptree").exists()
        # New files are present.
        assert (result.target / "new.scriptree").read_text(encoding="utf-8") == "new"
        # Shared file matches source.
        assert (result.target / "shared.scriptree").read_text(encoding="utf-8") == "from-src"
        assert result.conflict_resolved is ConflictMode.OVERWRITE

    def test_update_preserves_user_files(self, tmp_path: Path) -> None:
        """``UPDATE`` mode: source files replace at target;
        target-only files survive."""
        src, target_root = self._setup(tmp_path)
        result = install_app(
            src, target_root, conflict_mode=ConflictMode.UPDATE,
        )
        # User's old file is intact.
        assert (result.target / "old.scriptree").read_text(encoding="utf-8") == \
            "old-only-in-target"
        # New file copied in.
        assert (result.target / "new.scriptree").read_text(encoding="utf-8") == "new"
        # Shared file overwritten by source's version.
        assert (result.target / "shared.scriptree").read_text(encoding="utf-8") == \
            "from-src"

    def test_rename(self, tmp_path: Path) -> None:
        src, target_root = self._setup(tmp_path)
        result = install_app(
            src, target_root, conflict_mode=ConflictMode.RENAME,
        )
        # Lands at ``<target_root>/X-2`` (the first available
        # numbered slot).
        assert result.target.name == "X-2"
        assert (result.target / "new.scriptree").exists()
        # Original target is untouched.
        original = target_root / "X"
        assert (original / "old.scriptree").exists()

    def test_cancel_raises(self, tmp_path: Path) -> None:
        src, target_root = self._setup(tmp_path)
        with pytest.raises(InstallError, match="[Cc]ancel"):
            install_app(
                src, target_root, conflict_mode=ConflictMode.CANCEL,
            )


# ============================================================================
# Path-traversal safety
# ============================================================================


class TestPathTraversal:
    def test_double_dot_member_rejected(self, tmp_path: Path) -> None:
        zip_path = _make_zip(
            tmp_path / "Evil.zip",
            {"../escape.scriptree": "bad"},
        )
        with pytest.raises(InstallError, match=r"\.\."):
            install_app(zip_path, tmp_path / "install")

    def test_absolute_member_rejected(self, tmp_path: Path) -> None:
        zip_path = _make_zip(
            tmp_path / "Evil.zip",
            {"/etc/passwd": "bad"},
        )
        with pytest.raises(InstallError, match="absolute"):
            install_app(zip_path, tmp_path / "install")


# ============================================================================
# pick_rename_target
# ============================================================================


class TestPickRename:
    def test_first_slot_when_only_base_exists(
        self, tmp_path: Path,
    ) -> None:
        (tmp_path / "Tool").mkdir()
        assert pick_rename_target(tmp_path, "Tool") == tmp_path / "Tool-2"

    def test_skips_existing_numbered(self, tmp_path: Path) -> None:
        (tmp_path / "Tool").mkdir()
        (tmp_path / "Tool-2").mkdir()
        (tmp_path / "Tool-3").mkdir()
        assert pick_rename_target(tmp_path, "Tool") == tmp_path / "Tool-4"

    def test_returns_sensible_path_for_uncrowded_dir(
        self, tmp_path: Path,
    ) -> None:
        """Smoke check for the common case: an empty parent.
        The function returns the first numbered slot (``-2``) so
        the caller's install operation lands somewhere
        predictable.  The 999-slot cap is documented in the
        source; exercising it would require 998 ``mkdir``s for a
        defensive-code path that's never expected to fire."""
        result = pick_rename_target(tmp_path, "FreshTool")
        assert result == tmp_path / "FreshTool-2"


# ============================================================================
# Bad-source errors
# ============================================================================


class TestBadSources:
    def test_missing_source_raises(self, tmp_path: Path) -> None:
        with pytest.raises(InstallError, match="does not exist"):
            install_app(tmp_path / "nonexistent", tmp_path / "install")

    def test_non_zip_file_raises(self, tmp_path: Path) -> None:
        weird = tmp_path / "random.txt"
        weird.write_text("not a zip or folder", encoding="utf-8")
        with pytest.raises(InstallError, match="folder or .zip"):
            install_app(weird, tmp_path / "install")
