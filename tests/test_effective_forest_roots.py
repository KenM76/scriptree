"""Tests for ``effective_forest_roots`` -- the helper that splices
the personal-apps directory into the forest's discovery roots at
runtime without mutating the serialised config.

See ``scriptree.core.app_install.effective_forest_roots`` docstring
for the contract these tests pin in place.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from scriptree.core import app_install
from scriptree.core.app_install import (
    default_personal_root,
    effective_forest_roots,
)


# ---------------------------------------------------------------------------
# Contract: user roots stay intact, personal root is appended.
# ---------------------------------------------------------------------------


class TestAppending:
    def test_empty_user_roots_returns_personal_only(
        self, tmp_path: Path,
    ) -> None:
        personal = tmp_path / "personal_apps"
        with patch.object(app_install, "default_personal_root",
                          return_value=personal):
            out = effective_forest_roots([])
        # Single entry: the personal root.
        assert len(out) == 1
        assert Path(out[0]).resolve() == personal.resolve()

    def test_user_roots_preserved_first(self, tmp_path: Path) -> None:
        personal = tmp_path / "personal_apps"
        with patch.object(app_install, "default_personal_root",
                          return_value=personal):
            out = effective_forest_roots(["ScripTreeApps", "../ScripTreeApps"])
        # User entries come first (priority-rule walker reads in order).
        assert out[0] == "ScripTreeApps"
        assert out[1] == "../ScripTreeApps"
        # Personal appended at end.
        assert Path(out[-1]).resolve() == personal.resolve()
        assert len(out) == 3

    def test_returns_new_list_does_not_mutate_input(
        self, tmp_path: Path,
    ) -> None:
        original = ["ScripTreeApps"]
        with patch.object(app_install, "default_personal_root",
                          return_value=tmp_path):
            out = effective_forest_roots(original)
        assert original == ["ScripTreeApps"], (
            "User's roots list was mutated; callers depend on it staying "
            "untouched so the .scriptreeforest config stays portable."
        )
        assert out is not original


# ---------------------------------------------------------------------------
# Dedup: don't add personal root twice if user already configured it.
# ---------------------------------------------------------------------------


class TestDedup:
    def test_absolute_match_skips_append(self, tmp_path: Path) -> None:
        personal = tmp_path / "personal_apps"
        personal.mkdir()
        with patch.object(app_install, "default_personal_root",
                          return_value=personal):
            out = effective_forest_roots([str(personal)])
        # User already had it -- no duplicate.
        assert len(out) == 1
        assert out[0] == str(personal)

    def test_case_insensitive_match(self, tmp_path: Path) -> None:
        """Windows path matching is case-insensitive; this test passes
        on every platform because the helper uses ``casefold`` which
        is case-folding on all platforms."""
        personal = tmp_path / "personal_apps"
        personal.mkdir()
        upper = str(personal).upper()
        with patch.object(app_install, "default_personal_root",
                          return_value=personal):
            out = effective_forest_roots([upper])
        assert len(out) == 1

    def test_unresolved_user_entry_does_not_break(
        self, tmp_path: Path,
    ) -> None:
        """Entries that can't be resolved (e.g. a syntactically odd
        path) are skipped rather than aborting the whole helper."""
        personal = tmp_path / "personal_apps"
        with patch.object(app_install, "default_personal_root",
                          return_value=personal):
            # NUL bytes are not valid in filesystem paths on either
            # platform -- guaranteed to fail Path.resolve().
            out = effective_forest_roots(["some\x00bogus"])
        # Despite the broken entry, the personal root still appended.
        assert Path(out[-1]).resolve() == personal.resolve()


# ---------------------------------------------------------------------------
# Resilience: failures in default_personal_root don't crash discovery.
# ---------------------------------------------------------------------------


class TestResilience:
    def test_personal_root_lookup_failure_returns_user_roots(self) -> None:
        with patch.object(app_install, "default_personal_root",
                          side_effect=RuntimeError("env is broken")):
            out = effective_forest_roots(["ScripTreeApps"])
        # No crash, no append -- the user's roots are returned as-is.
        assert out == ["ScripTreeApps"]


# ---------------------------------------------------------------------------
# Integration: ``discover()`` actually sees apps in the personal dir.
# ---------------------------------------------------------------------------


class TestDiscoveryIntegration:
    def test_discover_picks_up_app_in_personal_root(
        self, tmp_path: Path,
    ) -> None:
        """End-to-end: drop a fake ``.scriptreetree`` into the personal
        apps directory, run the same code path the forest controller
        uses, assert the app shows up in discovery results."""
        personal = tmp_path / "personal_apps"
        personal.mkdir()
        app = personal / "MyDroppedApp"
        app.mkdir()
        tree_file = app / "MyDroppedApp.scriptreetree"
        # Minimal valid .scriptreetree JSON the walker will accept.
        tree_file.write_text(
            '{"name": "MyDroppedApp", "nodes": []}',
            encoding="utf-8",
        )

        with patch.object(app_install, "default_personal_root",
                          return_value=personal):
            from scriptree.shell.forest_discover import discover
            roots = effective_forest_roots([])  # empty user roots
            discovered = discover(roots, ["ring", "tree", "tool"], [])

        # Walker should have found the tree.
        paths = [str(Path(d.path).resolve()) for d in discovered]
        assert str(tree_file.resolve()) in paths, (
            f"Expected the dropped app at {tree_file} to appear in "
            f"discovery results, got {paths!r}"
        )
