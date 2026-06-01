"""Tests for ``AutoDiscoverConfig``'s default ``roots`` list.

The drop-install dialog's **Personal** target -- the path returned by
``default_personal_root()`` -- must appear in the default scan-folders
list for every freshly-constructed ``AutoDiscoverConfig``.  This pins
the contract so apps the user drop-installs there are picked up by
forest discovery automatically, and so the user sees the path in the
forest settings dialog (free to edit / remove like any other root).

Missing roots are skipped silently by ``discover``; that's pinned by
the integration test at the bottom of this file.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from scriptree.core import app_install
from scriptree.shell.forest_io import AutoDiscoverConfig, _default_roots


# ---------------------------------------------------------------------------
# Contract: factory produces THREE entries in the documented order.
# ---------------------------------------------------------------------------


class TestDefaultRoots:
    def test_factory_returns_three_entries(self, tmp_path: Path) -> None:
        with patch.object(app_install, "default_personal_root",
                          return_value=tmp_path / "personal"):
            out = _default_roots()
        assert len(out) == 3, (
            f"Expected three entries (ScripTreeApps + ../ScripTreeApps "
            f"+ personal); got {out!r}"
        )

    def test_first_two_entries_are_relative(self, tmp_path: Path) -> None:
        with patch.object(app_install, "default_personal_root",
                          return_value=tmp_path / "personal"):
            out = _default_roots()
        assert out[0] == "ScripTreeApps"
        assert out[1] == "../ScripTreeApps"

    def test_third_entry_is_personal_root(self, tmp_path: Path) -> None:
        personal = tmp_path / "personal"
        with patch.object(app_install, "default_personal_root",
                          return_value=personal):
            out = _default_roots()
        assert Path(out[2]) == personal

    def test_auto_discover_config_picks_up_factory(
        self, tmp_path: Path,
    ) -> None:
        personal = tmp_path / "personal"
        with patch.object(app_install, "default_personal_root",
                          return_value=personal):
            cfg = AutoDiscoverConfig()
        assert len(cfg.roots) == 3
        assert Path(cfg.roots[2]) == personal


# ---------------------------------------------------------------------------
# Resilience: a broken personal-root lookup must not break forest
# construction.  We fall back to just the two static roots.
# ---------------------------------------------------------------------------


class TestResilience:
    def test_personal_root_lookup_failure_falls_back_to_two_roots(
        self,
    ) -> None:
        with patch.object(app_install, "default_personal_root",
                          side_effect=RuntimeError("env is broken")):
            out = _default_roots()
        assert out == ["ScripTreeApps", "../ScripTreeApps"]


# ---------------------------------------------------------------------------
# Integration: ``discover()`` actually picks up an app dropped into the
# personal-root directory, and silently skips missing paths.
# ---------------------------------------------------------------------------


class TestDiscoveryIntegration:
    def test_discover_picks_up_app_in_personal_root(
        self, tmp_path: Path,
    ) -> None:
        """End-to-end: a fake ``.scriptreetree`` in the personal dir is
        found by the same code path the forest controller uses."""
        personal = tmp_path / "personal_apps"
        personal.mkdir()
        app = personal / "MyDroppedApp"
        app.mkdir()
        tree_file = app / "MyDroppedApp.scriptreetree"
        tree_file.write_text(
            '{"name": "MyDroppedApp", "nodes": []}',
            encoding="utf-8",
        )

        with patch.object(app_install, "default_personal_root",
                          return_value=personal):
            cfg = AutoDiscoverConfig()
            from scriptree.shell.forest_discover import discover
            discovered = discover(cfg.roots, ["ring", "tree", "tool"], [])

        paths = [str(Path(d.path).resolve()) for d in discovered]
        assert str(tree_file.resolve()) in paths, (
            f"Expected the dropped app at {tree_file} to appear in "
            f"discovery results, got {paths!r}"
        )

    def test_missing_personal_root_is_silently_skipped(
        self, tmp_path: Path,
    ) -> None:
        """A non-existent personal-root path produces no error and no
        warning -- the walker just moves past it.

        We pass only the personal root (not the full default factory)
        so the real install's ScripTreeApps folder doesn't pollute
        the result.  The contract under test is "a path that doesn't
        exist returns zero items, not an exception."
        """
        nonexistent = tmp_path / "this_does_not_exist"
        # Confirm precondition.
        assert not nonexistent.exists()

        from scriptree.shell.forest_discover import discover
        # Should produce an empty list, not raise.
        discovered = discover(
            [str(nonexistent)], ["ring", "tree", "tool"], [],
        )
        assert discovered == []
