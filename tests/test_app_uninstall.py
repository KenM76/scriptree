"""Regression suite for the uninstall flow added in v0.8.0a26.

Covers:

* ``find_personal_configs_for_app`` -- matches sidecars whose
  source_filename + source_locations point at tools inside the
  given app folder; ignores sidecars for unrelated tools and
  sidecars pointing at a different folder of the same-named tool.
* ``ForestController.uninstall_app`` flags:
    - ``remove_local_configs=True`` deletes personal sidecars
      tied to the app folder.
    - ``remove_local_configs=False`` leaves them on disk.
    - ``remove_shared_configs=False`` snapshots shared sidecars
      into ``<app>_uninstalled_configs/`` BEFORE the app folder
      is removed, and the message names the backup folder.
    - ``remove_shared_configs=True`` (default) removes the app
      folder wholesale -- no backup directory is created.

Heavy use of ``tmp_path`` to avoid touching the real personal
configs dir.  Test passes ``personal_dir`` explicitly into
``find_personal_configs_for_app`` so we never hit
``get_personal_configs_dir()`` at all.

For ``uninstall_app`` the personal_dir resolution does go via
the real ``get_personal_configs_dir`` -- we monkeypatch the
LOCALAPPDATA env var so the resolved dir points into ``tmp_path``.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)


# ---------------------------------------------------------------------------
# Helpers to fabricate a tiny app folder + personal sidecar.
# ---------------------------------------------------------------------------

def _write_scriptree(path: Path) -> None:
    """Drop a minimal but valid-enough .scriptree file at ``path``.

    The uninstall scan only reads the FILENAME from this file, so
    the body doesn't have to parse -- but a well-formed JSON
    structure keeps the test honest if future code starts
    inspecting it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"name": path.stem, "executable": "echo"}),
        encoding="utf-8",
    )


def _write_personal_sidecar(
    personal_dir: Path,
    *,
    stem: str,
    suffix_num: int,
    source_filename: str,
    source_locations: list[str],
) -> Path:
    """Drop a personal sidecar whose dict round-trips through
    ``configs_from_dict`` -- this is what
    ``find_personal_configs_for_app`` reads.

    Returns the path written.
    """
    personal_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{stem}.{int(suffix_num):03d}-scriptree.configs.json"
    path = personal_dir / fname
    payload = {
        "schema_version": 1,
        "active": "Default",
        "configurations": [
            {"name": "Default", "values": {}, "extras": []}
        ],
        "source_filename": source_filename,
        "source_locations": source_locations,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_shared_sidecar(tool_path: Path) -> Path:
    """Drop a SHARED sidecar next to ``tool_path``.

    The filename convention is ``<tool>.configs.json`` -- ie
    ``robocopy.scriptree.configs.json`` for ``robocopy.scriptree``.
    """
    sidecar = tool_path.with_name(tool_path.name + ".configs.json")
    sidecar.write_text(
        json.dumps({
            "schema_version": 1,
            "active": "Default",
            "configurations": [
                {"name": "Default", "values": {}, "extras": []}
            ],
        }),
        encoding="utf-8",
    )
    return sidecar


# ===========================================================================
# find_personal_configs_for_app
# ===========================================================================

class TestFindPersonalConfigsForApp:
    """Per-app personal-sidecar enumerator.

    The function's contract: a sidecar matches when BOTH the
    source_filename AND at least one source_location point at a
    tool inside the given app folder.  Mismatch on either prong
    means the sidecar is left out.
    """

    def test_matches_by_filename_and_location(self, tmp_path):
        from scriptree.core.configs import (
            find_personal_configs_for_app,
        )
        app_dir = tmp_path / "apps" / "MyApp"
        personal_dir = tmp_path / "personal"
        _write_scriptree(app_dir / "robocopy.scriptree")
        sidecar = _write_personal_sidecar(
            personal_dir,
            stem="robocopy",
            suffix_num=0,
            source_filename="robocopy.scriptree",
            source_locations=[str(app_dir)],
        )
        result = find_personal_configs_for_app(
            app_dir, personal_dir=personal_dir,
        )
        assert sidecar.resolve() in result

    def test_skips_sidecar_for_different_app(self, tmp_path):
        from scriptree.core.configs import (
            find_personal_configs_for_app,
        )
        app_a = tmp_path / "apps" / "AppA"
        app_b = tmp_path / "apps" / "AppB"
        personal_dir = tmp_path / "personal"
        _write_scriptree(app_a / "common_tool.scriptree")
        _write_scriptree(app_b / "common_tool.scriptree")
        # Sidecar points at AppB.
        _write_personal_sidecar(
            personal_dir,
            stem="common_tool",
            suffix_num=0,
            source_filename="common_tool.scriptree",
            source_locations=[str(app_b)],
        )
        result = find_personal_configs_for_app(
            app_a, personal_dir=personal_dir,
        )
        # AppA's call must NOT pick up AppB's sidecar.
        assert result == []

    def test_skips_sidecar_whose_filename_no_match(self, tmp_path):
        from scriptree.core.configs import (
            find_personal_configs_for_app,
        )
        app_dir = tmp_path / "apps" / "MyApp"
        personal_dir = tmp_path / "personal"
        _write_scriptree(app_dir / "real_tool.scriptree")
        # Personal sidecar whose source_filename matches no
        # tool in the app folder.
        _write_personal_sidecar(
            personal_dir,
            stem="orphan",
            suffix_num=0,
            source_filename="orphan.scriptree",
            source_locations=[str(app_dir)],
        )
        result = find_personal_configs_for_app(
            app_dir, personal_dir=personal_dir,
        )
        assert result == []

    def test_returns_empty_when_app_dir_missing(self, tmp_path):
        from scriptree.core.configs import (
            find_personal_configs_for_app,
        )
        personal_dir = tmp_path / "personal"
        personal_dir.mkdir()
        result = find_personal_configs_for_app(
            tmp_path / "does_not_exist", personal_dir=personal_dir,
        )
        assert result == []


# ===========================================================================
# ForestController.uninstall_app -- new flags
# ===========================================================================

def _build_controller_with_app(
    tmp_path: Path, monkeypatch,
) -> tuple[object, Path, Path]:
    """Construct a barely-instantiated ForestController + an app
    folder under a fake personal install root.

    Returns ``(controller, app_dir, catalog_path)``.
    """
    # Point default_personal_root at tmp_path / "Apps" by
    # overriding LOCALAPPDATA -- the helper resolves to
    # %LOCALAPPDATA%/ScripTree/Apps on Windows, so we point
    # LOCALAPPDATA at our tmp dir.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    from scriptree.core.app_install import default_personal_root
    apps_root = default_personal_root()
    apps_root.mkdir(parents=True, exist_ok=True)

    app_dir = apps_root / "DemoApp"
    catalog = app_dir / "demo.scriptree"
    _write_scriptree(catalog)

    # Create a barebones ForestController via __new__ to skip
    # the heavy real __init__; only set the few attrs uninstall
    # touches.
    from scriptree.shell.forest_controller import ForestController
    ctrl = ForestController.__new__(ForestController)
    # Forest object with items + excluded lists.
    forest = MagicMock()
    forest.items = []
    forest.excluded = []
    ctrl.forest = forest  # type: ignore[attr-defined]
    ctrl._spawned = {}    # type: ignore[attr-defined]
    ctrl.forestChanged = MagicMock()  # type: ignore[attr-defined]
    return ctrl, app_dir, catalog


class TestUninstallAppFlags:
    """v0.8.0a26 flag behaviour."""

    def test_remove_local_true_deletes_personal_sidecar(
        self, tmp_path, monkeypatch,
    ):
        ctrl, app_dir, catalog = _build_controller_with_app(
            tmp_path, monkeypatch,
        )
        # Personal sidecar that should be swept.
        from scriptree.core.app_settings import (
            get_personal_configs_dir,
        )
        personal_dir = get_personal_configs_dir()
        sidecar = _write_personal_sidecar(
            personal_dir,
            stem="demo",
            suffix_num=0,
            source_filename="demo.scriptree",
            source_locations=[str(app_dir)],
        )
        assert sidecar.exists()
        ok, msg = ctrl.uninstall_app(
            str(catalog),
            remove_local_configs=True,
            remove_shared_configs=True,
        )
        assert ok, msg
        assert not app_dir.exists()
        assert not sidecar.exists(), (
            "personal sidecar should have been deleted when "
            "remove_local_configs=True"
        )

    def test_remove_local_false_keeps_personal_sidecar(
        self, tmp_path, monkeypatch,
    ):
        ctrl, app_dir, catalog = _build_controller_with_app(
            tmp_path, monkeypatch,
        )
        from scriptree.core.app_settings import (
            get_personal_configs_dir,
        )
        personal_dir = get_personal_configs_dir()
        sidecar = _write_personal_sidecar(
            personal_dir,
            stem="demo",
            suffix_num=0,
            source_filename="demo.scriptree",
            source_locations=[str(app_dir)],
        )
        ok, msg = ctrl.uninstall_app(
            str(catalog),
            remove_local_configs=False,
            remove_shared_configs=True,
        )
        assert ok, msg
        assert not app_dir.exists()
        assert sidecar.exists(), (
            "personal sidecar should survive when "
            "remove_local_configs=False"
        )

    def test_remove_shared_false_backs_up_sidecars(
        self, tmp_path, monkeypatch,
    ):
        ctrl, app_dir, catalog = _build_controller_with_app(
            tmp_path, monkeypatch,
        )
        # Drop a shared sidecar next to the catalog.
        shared_sidecar = _write_shared_sidecar(catalog)
        assert shared_sidecar.exists()
        ok, msg = ctrl.uninstall_app(
            str(catalog),
            remove_local_configs=True,
            remove_shared_configs=False,
        )
        assert ok, msg
        assert not app_dir.exists()
        backup = app_dir.parent / (
            app_dir.name + "_uninstalled_configs"
        )
        assert backup.is_dir(), (
            f"backup dir {backup} should exist when "
            f"remove_shared_configs=False"
        )
        # The sidecar file should be inside the backup, at the
        # same relative path.
        copied = backup / shared_sidecar.relative_to(app_dir)
        assert copied.exists(), (
            f"shared sidecar should have been copied to "
            f"{copied}"
        )
        assert str(backup) in msg

    def test_remove_shared_true_no_backup(
        self, tmp_path, monkeypatch,
    ):
        ctrl, app_dir, catalog = _build_controller_with_app(
            tmp_path, monkeypatch,
        )
        _write_shared_sidecar(catalog)
        ok, msg = ctrl.uninstall_app(
            str(catalog),
            remove_local_configs=True,
            remove_shared_configs=True,
        )
        assert ok, msg
        assert not app_dir.exists()
        backup = app_dir.parent / (
            app_dir.name + "_uninstalled_configs"
        )
        assert not backup.exists(), (
            "no backup folder should be created when "
            "remove_shared_configs=True"
        )
