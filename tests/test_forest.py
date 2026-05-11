"""Tests for the v0.3.14 forest layer.

Coverage matches the four files added under ``scriptree/shell/``:

  * ``forest_io.py``           — schema + JSON round-trip + autoload path.
  * ``forest_discover.py``     — priority-rule walker + diff.
  * ``forest_window.py``       — visible cell construction + label/size.
  * ``forest_controller.py``   — singleton orchestration: add / remove
                                 with excluded-list semantics, save /
                                 open round-trip, discover_now,
                                 apply_diff with checkbox-style
                                 selective acceptance.
  * ``forest_dialogs.py``      — dialog construction + apply paths.

Dialog tests are headless: they construct the dialog, manipulate
its widgets directly, and call the apply method as the user would
have via Qt signals.  No actual user interaction or modal exec.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.shell.branding_loader import load_branding
from scriptree.shell.cell_registry import CellRegistry
from scriptree.shell.forest_io import (
    AutoDiscoverConfig,
    ForestDef,
    ForestItem,
    kind_for_suffix,
    load_forest,
    save_forest,
)
from scriptree.shell.forest_discover import (
    DiscoveredItem,
    DiscoveryDiff,
    diff_against,
    discover,
)


def _fresh_registry() -> CellRegistry:
    reg = CellRegistry.instance()
    for h in list(reg.standalones()) + list(reg.masters()):
        try:
            h.close()
        except Exception:  # noqa: BLE001
            pass
    return reg


# ===========================================================================
# forest_io
# ===========================================================================

class TestKindForSuffix:

    def test_ring(self) -> None:
        assert kind_for_suffix("foo.scriptreering") == "ring"

    def test_tree(self) -> None:
        assert kind_for_suffix("foo.scriptreetree") == "tree"

    def test_tool(self) -> None:
        assert kind_for_suffix("foo.scriptree") == "tool"

    def test_case_insensitive(self) -> None:
        assert kind_for_suffix("FOO.SCRIPTREERING") == "ring"

    def test_overlap_disambiguation(self) -> None:
        """``.scriptreetree`` ends in ``.scriptree`` too — the longer
        suffix must win."""
        assert kind_for_suffix("foo.scriptreetree") == "tree"

    def test_unrecognised_suffix(self) -> None:
        assert kind_for_suffix("foo.txt") is None
        assert kind_for_suffix("foo") is None


class TestForestIoRoundTrip:

    def test_default_forest_round_trips(self, tmp_path: Path) -> None:
        f = ForestDef()
        p = tmp_path / "default.scriptreeforest"
        save_forest(f, p)
        loaded = load_forest(p)
        assert loaded.name == "Forest"
        assert loaded.items == []
        assert loaded.excluded == []
        assert loaded.auto_discover.enabled is True
        # v0.3.22: default roots are both "ScripTreeApps" (in-source)
        # and "../ScripTreeApps" (sibling-of-install layout).
        assert loaded.auto_discover.roots == [
            "ScripTreeApps", "../ScripTreeApps",
        ]
        assert loaded.auto_discover.update_mode == "prompt"

    def test_items_with_position_round_trip(self, tmp_path: Path) -> None:
        f = ForestDef(items=[
            ForestItem(
                path="ScripTreeApps/Demo/x.scriptree",
                kind="tool",
                position=(123, 456),
            ),
        ])
        p = tmp_path / "f.scriptreeforest"
        save_forest(f, p)
        loaded = load_forest(p)
        assert len(loaded.items) == 1
        # path becomes absolute on load (the resolver finds the
        # project-root-relative form and resolves it).
        assert loaded.items[0].kind == "tool"
        assert loaded.items[0].position == (123, 456)

    def test_excluded_round_trip(self, tmp_path: Path) -> None:
        f = ForestDef(excluded=["ScripTreeApps/old/dropped.scriptree"])
        p = tmp_path / "f.scriptreeforest"
        save_forest(f, p)
        loaded = load_forest(p)
        assert len(loaded.excluded) == 1

    def test_auto_discover_round_trip(self, tmp_path: Path) -> None:
        f = ForestDef(auto_discover=AutoDiscoverConfig(
            enabled=False,
            roots=["X", "Y/Z"],
            include=["ring", "tree"],
            update_mode="auto",
        ))
        p = tmp_path / "f.scriptreeforest"
        save_forest(f, p)
        loaded = load_forest(p)
        assert loaded.auto_discover.enabled is False
        assert loaded.auto_discover.roots == ["X", "Y/Z"]
        assert loaded.auto_discover.include == ["ring", "tree"]
        assert loaded.auto_discover.update_mode == "auto"

    def test_invalid_update_mode_falls_back_to_prompt(
        self, tmp_path: Path,
    ) -> None:
        """Hand-edited file with an unknown update mode shouldn't crash;
        we coerce to the safe default."""
        p = tmp_path / "f.scriptreeforest"
        p.write_text(
            json.dumps({
                "format": "scriptreeforest",
                "version": 1,
                "auto_discover": {"update_mode": "MAYHEM"},
            }),
            encoding="utf-8",
        )
        loaded = load_forest(p)
        assert loaded.auto_discover.update_mode == "prompt"

    def test_format_mismatch_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "wrong.json"
        p.write_text(json.dumps({"format": "wrong"}), encoding="utf-8")
        with pytest.raises(ValueError):
            load_forest(p)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_forest(tmp_path / "nope.scriptreeforest")


# ===========================================================================
# forest_discover — priority rule + filter + excluded
# ===========================================================================

class TestDiscover:

    def _build_layout(self, tmp_path: Path) -> Path:
        """Layout used by several tests::

            tmp_path/
              A/
                a.scriptreering   (ring wins; a.scriptree ignored)
                a.scriptree
              B/
                b.scriptree       (only tool; emitted)
              C/
                inner/
                  c.scriptreetree (recurse-then-emit)
              D/
                .hidden/          (skipped)
                  d.scriptree
        """
        root = tmp_path
        (root / "A").mkdir()
        (root / "A" / "a.scriptreering").write_text("{}", encoding="utf-8")
        (root / "A" / "a.scriptree").write_text("{}", encoding="utf-8")
        (root / "B").mkdir()
        (root / "B" / "b.scriptree").write_text("{}", encoding="utf-8")
        (root / "C" / "inner").mkdir(parents=True)
        (root / "C" / "inner" / "c.scriptreetree").write_text("{}", encoding="utf-8")
        (root / "D" / ".hidden").mkdir(parents=True)
        (root / "D" / ".hidden" / "d.scriptree").write_text("{}", encoding="utf-8")
        return root

    def test_priority_rule_picks_highest_layer_per_folder(
        self, tmp_path: Path,
    ) -> None:
        root = self._build_layout(tmp_path)
        items = discover([root])
        kinds_by_name = {Path(i.path).name: i.kind for i in items}
        # Folder A: ring wins; tool ignored.
        assert kinds_by_name.get("a.scriptreering") == "ring"
        assert "a.scriptree" not in kinds_by_name
        # Folder B: only a tool exists, emit it.
        assert kinds_by_name.get("b.scriptree") == "tool"
        # Folder C/inner: tree found via recursion.
        assert kinds_by_name.get("c.scriptreetree") == "tree"
        # Folder D/.hidden: hidden dir skipped.
        assert "d.scriptree" not in kinds_by_name

    def test_include_filter_no_silent_demotion(
        self, tmp_path: Path,
    ) -> None:
        """When the include filter excludes the folder's highest tier,
        we must NOT fall through to a lower tier in the same folder
        — that would be a silent demotion the user didn't ask for."""
        root = self._build_layout(tmp_path)
        # Filter to rings only.
        items = discover([root], include=["ring"])
        names = [Path(i.path).name for i in items]
        assert "a.scriptreering" in names
        # B has no ring; the tool is NOT promoted as a fallback.
        assert "b.scriptree" not in names
        # C has no ring; the tree is NOT promoted as a fallback.
        assert "c.scriptreetree" not in names

    def test_excluded_ring_blocks_tool_demotion(
        self, tmp_path: Path,
    ) -> None:
        """If the user excluded a ring, the folder's tool sibling
        does NOT take its place — the ring still 'occupies' the
        folder's priority slot.

        Note: ``discover()`` DOES still emit the excluded ring
        itself (so ``diff_against`` can route it into the
        ``previously_excluded`` bucket and the prompt dialog can
        offer re-inclusion).  What stays excluded is the
        DEMOTION to the lower-tier file."""
        root = self._build_layout(tmp_path)
        excluded = [str(root / "A" / "a.scriptreering")]
        items = discover([root], excluded=excluded)
        names = [Path(i.path).name for i in items]
        # The ring flows through (router handles excluded routing).
        assert "a.scriptreering" in names
        # But the tool sibling does NOT — that's the priority
        # rule's "stop descending" behaviour.
        assert "a.scriptree" not in names

    def test_default_roots_include_sibling_layout(self) -> None:
        """v0.3.22: the factory-default ``roots`` lists both
        ``ScripTreeApps`` and ``../ScripTreeApps`` so a deployment
        with ScripTreeApps outside the ScripTree folder is
        discovered automatically."""
        from scriptree.shell.forest_io import AutoDiscoverConfig
        cfg = AutoDiscoverConfig()
        assert "ScripTreeApps" in cfg.roots
        assert "../ScripTreeApps" in cfg.roots

    def test_relative_root_resolves_against_project_root(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """Relative roots like ``../ScripTreeApps`` resolve at
        discovery time against the project root.  Files only there
        (not under ``ScripTreeApps``) still get walked."""
        # Pretend the project root is tmp_path/proj/ScripTree.
        # Place a tool at tmp_path/proj/ScripTreeApps/Demo/x.scriptree
        # — the sibling layout the v0.3.22 default targets.
        install = tmp_path / "proj" / "ScripTree"
        install.mkdir(parents=True)
        sibling = tmp_path / "proj" / "ScripTreeApps" / "Demo"
        sibling.mkdir(parents=True)
        (sibling / "x.scriptree").write_text("{}", encoding="utf-8")

        from scriptree.shell import forest_io as io_mod
        monkeypatch.setattr(
            io_mod, "_project_root",
            lambda: install,
        )

        items = discover(["../ScripTreeApps"])
        names = [Path(i.path).name for i in items]
        assert "x.scriptree" in names

    def test_missing_default_root_is_silently_skipped(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """Both default roots being listed doesn't error when only
        one (or neither) exists on disk — discover just skips the
        missing ones."""
        install = tmp_path / "proj" / "ScripTree"
        install.mkdir(parents=True)
        # No ScripTreeApps anywhere — but defaults list two.
        from scriptree.shell import forest_io as io_mod
        monkeypatch.setattr(
            io_mod, "_project_root",
            lambda: install,
        )
        # Should not raise; should return zero items.
        items = discover(["ScripTreeApps", "../ScripTreeApps"])
        assert items == []

    def test_excluded_individual_tool_still_emitted(
        self, tmp_path: Path,
    ) -> None:
        """``discover()`` emits all priority-tier matches in a folder
        — including excluded ones — so the diff layer can route them.
        ``diff_against`` is the right place for excluded vs added
        bookkeeping."""
        root = tmp_path / "Multi"
        root.mkdir()
        (root / "a.scriptree").write_text("{}", encoding="utf-8")
        (root / "b.scriptree").write_text("{}", encoding="utf-8")
        (root / "c.scriptree").write_text("{}", encoding="utf-8")
        items = discover([root.parent], excluded=[str(root / "b.scriptree")])
        names = sorted(Path(i.path).name for i in items)
        assert names == ["a.scriptree", "b.scriptree", "c.scriptree"]


class TestDiff:

    def test_added_when_in_discovery_not_in_current(self) -> None:
        cur = []
        disc = [DiscoveredItem(path="/x/foo.scriptree", kind="tool")]
        d = diff_against(cur, disc, [])
        assert len(d.added) == 1
        assert d.added[0].path.endswith("foo.scriptree")

    def test_added_paths_in_excluded_become_previously_excluded(
        self, tmp_path: Path,
    ) -> None:
        """When discovery finds a path that's in the user's excluded
        list, surface it as previously_excluded — NOT added — so
        the prompt dialog shows a separate section."""
        path = str(tmp_path / "x.scriptree")
        Path(path).write_text("{}", encoding="utf-8")
        cur: list[ForestItem] = []
        disc = [DiscoveredItem(path=path, kind="tool")]
        d = diff_against(cur, disc, [path])
        assert len(d.added) == 0
        assert len(d.previously_excluded) == 1

    def test_removed_only_when_path_no_longer_exists(
        self, tmp_path: Path,
    ) -> None:
        """An item the user added MANUALLY (outside the auto-discover
        roots) won't appear in ``discovered``, but it shouldn't be
        treated as 'removed' just for that — only files that have
        actually disappeared from disk count as removals."""
        existing = tmp_path / "still_here.scriptree"
        existing.write_text("{}", encoding="utf-8")
        gone = tmp_path / "deleted.scriptree"  # never written

        cur = [
            ForestItem(path=str(existing), kind="tool"),
            ForestItem(path=str(gone), kind="tool"),
        ]
        disc: list[DiscoveredItem] = []  # discovery found neither

        d = diff_against(cur, disc, [])
        # `existing` stays — file still on disk (user-added or moved
        # outside the discovery roots).
        # `gone` is removed.
        removed_paths = [it.path for it in d.removed]
        assert str(gone) in removed_paths
        assert str(existing) not in removed_paths


# ===========================================================================
# Forest cell — same shape/size as a regular CellWindow, role="master",
# with the ``_is_forest_master`` flag set.
# ===========================================================================

class TestForestCell:

    def test_forest_cell_is_master_with_flag(self) -> None:
        from scriptree.shell.forest_controller import ForestController
        from scriptree.shell.cell_window import CellWindow

        _fresh_registry()
        ctrl = ForestController(load_branding(), CellRegistry.instance(), None)
        ctrl.start(forest=ForestDef(), suppress_first_run=True)
        assert isinstance(ctrl.forest_window, CellWindow)
        assert ctrl.forest_window.role == "master"
        assert ctrl.forest_window._is_forest_master is True
        ctrl.forest_window.close()

    def test_forest_cell_uses_branding_default_size(self) -> None:
        from scriptree.shell.forest_controller import ForestController
        _fresh_registry()
        ctrl = ForestController(load_branding(), CellRegistry.instance(), None)
        ctrl.start(forest=ForestDef(), suppress_first_run=True)
        # Same default size as any other CellWindow.
        expected = load_branding().get(
            "hexagon", {}
        ).get("defaultSizePx", 56)
        assert ctrl.forest_window.size().width() == expected
        ctrl.forest_window.close()

    def test_forest_cell_quorum_exempt(self) -> None:
        """A normal master with < 2 members tears itself down via
        ``_check_master_validity``.  The forest must persist even
        with 0 members."""
        from scriptree.shell.forest_controller import ForestController
        from scriptree.shell.cell_window import _check_master_validity

        _fresh_registry()
        ctrl = ForestController(load_branding(), CellRegistry.instance(), None)
        ctrl.start(forest=ForestDef(), suppress_first_run=True)
        forest = ctrl.forest_window
        assert len(forest._members) == 0
        # Should NOT close.
        _check_master_validity(forest, CellRegistry.instance())
        assert forest.isVisible()
        assert forest._id in {c._id for c in CellRegistry.instance().all()}
        ctrl.forest_window.close()

    def test_forest_cell_has_menu_extension_hook(self) -> None:
        from scriptree.shell.forest_controller import ForestController
        _fresh_registry()
        ctrl = ForestController(load_branding(), CellRegistry.instance(), None)
        ctrl.start(forest=ForestDef(), suppress_first_run=True)
        assert ctrl.forest_window._forest_menu_extension is not None
        # The hook should be callable with a QMenu.
        from PySide6.QtWidgets import QMenu
        m = QMenu()
        ctrl.forest_window._forest_menu_extension(m)
        # At least the Forest submenu was inserted.
        labels = [a.text() for a in m.actions() if a.text()]
        assert any("Forest" in label for label in labels)
        ctrl.forest_window.close()


# ===========================================================================
# forest_controller — orchestration
# ===========================================================================

class TestForestController:

    def _make(self):
        """Fresh, started controller with an empty forest.

        v0.3.20+ — autosave is disabled here so tests don't write
        to the developer's real ``last_forest.scriptreeforest``
        when the controller's ``forestChanged`` signal fires
        during normal test setup.
        """
        from scriptree.shell.forest_controller import ForestController
        _fresh_registry()
        ctrl = ForestController(load_branding(), CellRegistry.instance(), None)
        ctrl.set_autosave_enabled(False)
        ctrl.start(forest=ForestDef(), suppress_first_run=True)
        return ctrl

    def test_construct_no_window_until_start(self) -> None:
        """Bare construction (no ``start()``) does NOT create a
        forest cell — that happens lazily so an embedding caller
        can configure the controller before the window appears."""
        from scriptree.shell.forest_controller import ForestController
        _fresh_registry()
        ctrl = ForestController(load_branding(), CellRegistry.instance(), None)
        assert ctrl.forest_window is None
        assert isinstance(ctrl.forest, ForestDef)

    def test_add_item_de_duplicates(self, tmp_path: Path) -> None:
        ctrl = self._make()
        ctrl.start(forest=ForestDef(), suppress_first_run=True)
        path = str(tmp_path / "x.scriptree")
        Path(path).write_text("{}", encoding="utf-8")
        ctrl.add_item(path, "tool")
        ctrl.add_item(path, "tool")
        assert len(ctrl.forest.items) == 1

    def test_leave_forest_keeps_ring_master_intact(
        self, tmp_path: Path,
    ) -> None:
        """A ring-master attached to the forest must be able to
        leave the forest WITHOUT disbanding its own ring.  This is
        the v0.3.15 ``_leave_forest_keep_ring`` contract — the
        whole point of the menu split between "Leave forest" and
        "Disband group".
        """
        from scriptree.shell.cell_window import CellWindow, _try_spawn_master
        ctrl = self._make()
        forest = ctrl.forest_window
        # Build a real 2-member ring outside the forest.
        a = CellWindow(load_branding())
        a.move(800, 400)
        a.show()
        b = CellWindow(load_branding())
        b.move(856, 400)
        b.show()
        _try_spawn_master(a, b)
        ring_master_id = CellRegistry.instance().master_of(a._id)
        ring_master = CellRegistry.instance().get(ring_master_id)
        assert ring_master is not None
        # Attach the ring-master as a forest member (this is what
        # the controller's _attach_existing_master_as_member does).
        ctrl._attach_existing_master_as_member(ring_master)
        assert ring_master._group_master_id == forest._id
        ring_member_count_before = len(ring_master._members)
        assert ring_member_count_before == 2

        # Now leave the forest — keep the ring intact.
        ring_master._leave_forest_keep_ring()
        # Forest no longer holds the ring-master.
        assert ring_master._id not in forest._members
        # Ring-master no longer points at the forest.
        assert ring_master._group_master_id is None
        # The ring's own members are STILL grouped under it.
        assert len(ring_master._members) == ring_member_count_before
        for member_id in ring_master._members:
            member = CellRegistry.instance().get(member_id)
            assert member is not None
            assert member._group_master_id == ring_master._id

    def test_add_tool_docks_as_forest_member(
        self, tmp_path: Path,
    ) -> None:
        """Adding a tool to the forest must wire it as a member of
        the forest's group — same semantics as a ring drop."""
        ctrl = self._make()
        ctrl.start(forest=ForestDef(), suppress_first_run=True)
        forest = ctrl.forest_window
        path = str(tmp_path / "tool.scriptree")
        Path(path).write_text("{}", encoding="utf-8")
        ctrl.add_item(path, "tool")
        # Forest now has 1 member.
        assert len(forest._members) == 1
        member_id = next(iter(forest._members.keys()))
        member = CellRegistry.instance().get(member_id)
        assert member is not None
        # The member is grouped under the forest.
        assert member._group_master_id == forest._id

    def test_remove_item_with_exclude(self, tmp_path: Path) -> None:
        ctrl = self._make()
        path = str(tmp_path / "x.scriptree")
        Path(path).write_text("{}", encoding="utf-8")
        ctrl.add_item(path, "tool")
        ctrl.remove_item(path, exclude=True)
        assert ctrl.forest.items == []
        assert len(ctrl.forest.excluded) == 1

    def test_remove_item_without_exclude(self, tmp_path: Path) -> None:
        """When the file's gone from disk we don't add it to
        excluded — the user didn't choose to exclude, the file
        just disappeared."""
        ctrl = self._make()
        path = str(tmp_path / "x.scriptree")
        Path(path).write_text("{}", encoding="utf-8")
        ctrl.add_item(path, "tool")
        ctrl.remove_item(path, exclude=False)
        assert ctrl.forest.items == []
        assert ctrl.forest.excluded == []

    def test_add_item_clears_excluded(self, tmp_path: Path) -> None:
        """Re-including a previously-excluded path clears it from
        the excluded list (the user changed their mind)."""
        ctrl = self._make()
        path = str(tmp_path / "x.scriptree")
        Path(path).write_text("{}", encoding="utf-8")
        ctrl.add_item(path, "tool")
        ctrl.remove_item(path, exclude=True)
        assert len(ctrl.forest.excluded) == 1
        ctrl.add_item(path, "tool")
        assert len(ctrl.forest.excluded) == 0
        assert len(ctrl.forest.items) == 1

    def test_save_open_round_trip(self, tmp_path: Path) -> None:
        ctrl = self._make()
        path = str(tmp_path / "x.scriptree")
        Path(path).write_text("{}", encoding="utf-8")
        ctrl.forest.name = "RoundTrip"
        ctrl.add_item(path, "tool")
        ctrl.remove_item(
            str(tmp_path / "ghost.scriptree"), exclude=True,
        )  # adds excluded entry directly via add+remove? No —
           # remove_item early-returns if the path isn't in items.
        # So just exercise save/open with the live state.
        target = tmp_path / "f.scriptreeforest"
        ctrl.save_as(target)

        # Make a fresh controller, open the file.  ``_make()``
        # already calls ``start(suppress_first_run=True)`` so a
        # second start would create a duplicate forest cell + queue
        # a first-run dialog — the test would hang on the modal.
        ctrl2 = self._make()
        ctrl2.open(str(target))
        assert ctrl2.forest.name == "RoundTrip"
        assert len(ctrl2.forest.items) == 1

    def test_discover_now_uses_excluded_list(
        self, tmp_path: Path,
    ) -> None:
        """The walker honours the controller's excluded list — the
        wiring between the two layers actually plumbs."""
        ctrl = self._make()
        # Build a layout in a fresh root we can point the controller at.
        root = tmp_path / "root"
        (root / "Tool").mkdir(parents=True)
        tool_path = root / "Tool" / "x.scriptree"
        tool_path.write_text("{}", encoding="utf-8")
        ctrl.forest.auto_discover.roots = [str(root)]
        ctrl.forest.excluded = [str(tool_path)]

        diff = ctrl.discover_now()
        # Excluded path doesn't show up in `added` — it goes to
        # `previously_excluded` so the prompt dialog can offer
        # re-inclusion.
        assert all(
            d.path != str(tool_path) for d in diff.added
        )
        assert any(
            d.path == str(tool_path) for d in diff.previously_excluded
        )

    def test_apply_diff_with_selective_acceptance(
        self, tmp_path: Path,
    ) -> None:
        """Prompt-mode flow: user ticks some items, leaves others
        unticked.  Ticked apply; unticked stay as-is."""
        ctrl = self._make()
        ctrl.forest.auto_discover.roots = [str(tmp_path)]
        a = tmp_path / "A" / "a.scriptree"
        b = tmp_path / "B" / "b.scriptree"
        a.parent.mkdir()
        b.parent.mkdir()
        a.write_text("{}", encoding="utf-8")
        b.write_text("{}", encoding="utf-8")

        diff = ctrl.discover_now()
        assert len(diff.added) == 2

        # User accepts only A.
        ctrl.apply_diff(diff, accepted_added={str(a.resolve())})
        names = [Path(it.path).name for it in ctrl.forest.items]
        assert "a.scriptree" in names
        assert "b.scriptree" not in names


# ===========================================================================
# forest_dialogs — construct headless and apply
# ===========================================================================

class TestForestPreferences:
    """v0.3.21: ``forest_preferences.json`` controls launch
    behaviour when no explicit forest is passed.

      * ``fallback_to_default=True`` (factory default): the launcher
        loads the configured default file, creating it empty if
        missing — matches v0.3.20 behaviour.
      * ``fallback_to_default=False``: launcher starts with a
        transient in-memory forest; autosave is implicitly off
        because there's nowhere safe to write.
      * ``default_forest_path``: where the fallback points.  Empty
        string = canonical autoload path.

    These tests redirect the preferences + autoload paths to
    ``tmp_path`` via ``monkeypatch`` so they don't touch the dev's
    real ``%APPDATA%``.
    """

    def _make_branding(self) -> dict:
        # Use a unique app name so preferences land in a fresh
        # APPDATA subdirectory; combined with monkeypatch this
        # keeps tests fully isolated.
        return load_branding()

    def test_factory_defaults(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """First-run user (no prefs file): fallback ON, path empty.
        Matches the v0.3.20 experience verbatim."""
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.forest_io import load_preferences

        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda branding: tmp_path / "forest_preferences.json",
        )
        prefs = load_preferences(self._make_branding())
        assert prefs.fallback_to_default is True
        assert prefs.default_forest_path == ""

    def test_round_trip(self, tmp_path: Path, monkeypatch: Any) -> None:
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.forest_io import (
            ForestPreferences, load_preferences, save_preferences,
        )

        prefs_file = tmp_path / "forest_preferences.json"
        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda branding: prefs_file,
        )

        br = self._make_branding()
        save_preferences(
            ForestPreferences(
                fallback_to_default=False,
                default_forest_path=str(tmp_path / "x.scriptreeforest"),
            ),
            br,
        )
        loaded = load_preferences(br)
        assert loaded.fallback_to_default is False
        assert loaded.default_forest_path == str(
            tmp_path / "x.scriptreeforest",
        )

    def test_start_with_fallback_off_no_file_created(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """``fallback_to_default=False`` → controller starts with
        an empty in-memory forest, and the autoload path is NOT
        written even when autosave is on."""
        from scriptree.shell import forest_controller as fc_mod
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.forest_controller import ForestController
        from scriptree.shell.forest_io import (
            ForestPreferences, save_preferences,
        )

        autoload_target = tmp_path / "last_forest.scriptreeforest"
        prefs_file = tmp_path / "forest_preferences.json"
        monkeypatch.setattr(
            fc_mod, "default_autoload_path",
            lambda branding: autoload_target,
        )
        monkeypatch.setattr(
            io_mod, "default_autoload_path",
            lambda branding: autoload_target,
        )
        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda branding: prefs_file,
        )

        save_preferences(
            ForestPreferences(fallback_to_default=False),
            self._make_branding(),
        )

        _fresh_registry()
        ctrl = ForestController(
            self._make_branding(), CellRegistry.instance(), None,
        )
        ctrl.start(suppress_first_run=True)
        # Forest exists in memory but no file backs it.
        assert ctrl.forest.loaded_from is None
        # Autoload file should NOT have been written.
        assert not autoload_target.is_file()

    def test_start_with_fallback_on_custom_path(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """``fallback_to_default=True`` + custom ``default_forest_path``
        → controller loads/creates that file, not the canonical one."""
        from scriptree.shell import forest_controller as fc_mod
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.forest_controller import ForestController
        from scriptree.shell.forest_io import (
            ForestPreferences, save_preferences,
        )

        canonical = tmp_path / "canonical.scriptreeforest"
        custom = tmp_path / "custom.scriptreeforest"
        prefs_file = tmp_path / "forest_preferences.json"
        monkeypatch.setattr(
            fc_mod, "default_autoload_path",
            lambda branding: canonical,
        )
        monkeypatch.setattr(
            io_mod, "default_autoload_path",
            lambda branding: canonical,
        )
        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda branding: prefs_file,
        )

        save_preferences(
            ForestPreferences(
                fallback_to_default=True,
                default_forest_path=str(custom),
            ),
            self._make_branding(),
        )

        _fresh_registry()
        ctrl = ForestController(
            self._make_branding(), CellRegistry.instance(), None,
        )
        ctrl.set_autosave_enabled(False)
        ctrl.start(suppress_first_run=True)
        # Custom file got created; canonical did NOT.
        assert custom.is_file()
        assert not canonical.is_file()
        assert ctrl.forest.loaded_from == str(custom.resolve())

    def test_save_is_noop_when_fallback_off_and_unsaved(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """When the user runs transient (fallback off, no explicit
        save_as), calling ``save()`` is a silent no-op rather than
        secretly writing to APPDATA."""
        from scriptree.shell import forest_controller as fc_mod
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.forest_controller import ForestController
        from scriptree.shell.forest_io import (
            ForestPreferences, save_preferences,
        )

        canonical = tmp_path / "canonical.scriptreeforest"
        prefs_file = tmp_path / "forest_preferences.json"
        monkeypatch.setattr(
            fc_mod, "default_autoload_path",
            lambda branding: canonical,
        )
        monkeypatch.setattr(
            io_mod, "default_autoload_path",
            lambda branding: canonical,
        )
        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda branding: prefs_file,
        )
        save_preferences(
            ForestPreferences(fallback_to_default=False),
            self._make_branding(),
        )

        _fresh_registry()
        ctrl = ForestController(
            self._make_branding(), CellRegistry.instance(), None,
        )
        ctrl.start(suppress_first_run=True)
        # Trigger a change so dirty flag is set.
        ctrl.forest.name = "Transient"
        ctrl._dirty = True
        # Save should NOT write anything.
        ctrl.save()
        assert not canonical.is_file()


class TestAutosaveAndDefaultFile:
    """v0.3.20: starting the forest with no autoload file present
    creates a default ``.scriptreeforest`` at the canonical autoload
    path, and ``forestChanged`` signals auto-save through a 250ms
    debounce timer so changes hit disk without the user clicking
    Save."""

    def test_start_creates_default_file_when_no_autoload(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """Factory-default preferences (fallback ON, path empty)
        and no autoload file → controller saves a fresh one at the
        canonical autoload path on start.

        v0.3.21 changes: the start() flow now resolves the default
        path via ``ForestPreferences.resolved_default_path``, which
        calls ``default_autoload_path`` from inside ``forest_io``.
        We patch both the controller's bound reference AND the
        forest_io module's reference so the helper class also sees
        the redirected path.
        """
        from scriptree.shell import forest_controller as fc_mod
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.forest_controller import ForestController

        target = tmp_path / "last_forest.scriptreeforest"
        prefs_file = tmp_path / "forest_preferences.json"
        monkeypatch.setattr(
            fc_mod, "default_autoload_path",
            lambda branding: target,
        )
        monkeypatch.setattr(
            io_mod, "default_autoload_path",
            lambda branding: target,
        )
        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda branding: prefs_file,
        )

        _fresh_registry()
        ctrl = ForestController(load_branding(), CellRegistry.instance(), None)
        ctrl.set_autosave_enabled(False)
        ctrl.start(suppress_first_run=True)

        assert target.is_file(), (
            "expected default forest file to be created on start"
        )
        assert ctrl.forest.loaded_from == str(target.resolve())

    def test_autosave_fires_on_change(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """A ``forestChanged`` signal triggers the autosave
        debounce timer, which writes to disk after ~250 ms."""
        from PySide6.QtCore import QEventLoop, QTimer
        from scriptree.shell import forest_controller as fc_mod
        from scriptree.shell.forest_controller import ForestController

        target = tmp_path / "f.scriptreeforest"
        monkeypatch.setattr(
            fc_mod, "default_autoload_path",
            lambda branding: target,
        )

        _fresh_registry()
        ctrl = ForestController(load_branding(), CellRegistry.instance(), None)
        # Set loaded_from explicitly so save() targets our tmp file
        # rather than the dev's APPDATA.
        forest = ForestDef()
        forest.loaded_from = str(target)
        ctrl.start(forest=forest, suppress_first_run=True)

        assert ctrl._autosave_enabled is True

        # Trigger a change.
        ctrl.forest.name = "AutoSaved"
        ctrl.forestChanged.emit()
        assert ctrl._dirty is True

        # Pump the event loop for >250 ms so the debounce timer fires.
        loop = QEventLoop()
        QTimer.singleShot(400, loop.quit)
        loop.exec()

        # Save should have happened.
        assert target.is_file()
        from scriptree.shell.forest_io import load_forest
        loaded = load_forest(target)
        assert loaded.name == "AutoSaved"

    def test_autosave_disabled_does_not_write(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """``set_autosave_enabled(False)`` stops the debounce timer
        from writing — the dirty flag is still set, but disk stays
        untouched until the user explicitly saves."""
        from PySide6.QtCore import QEventLoop, QTimer
        from scriptree.shell import forest_controller as fc_mod
        from scriptree.shell.forest_controller import ForestController

        target = tmp_path / "f.scriptreeforest"
        monkeypatch.setattr(
            fc_mod, "default_autoload_path",
            lambda branding: target,
        )

        _fresh_registry()
        ctrl = ForestController(load_branding(), CellRegistry.instance(), None)
        ctrl.set_autosave_enabled(False)
        forest = ForestDef()
        forest.loaded_from = str(target)
        ctrl.start(forest=forest, suppress_first_run=True)

        ctrl.forest.name = "Manual"
        ctrl.forestChanged.emit()
        loop = QEventLoop()
        QTimer.singleShot(400, loop.quit)
        loop.exec()

        # Disk file does NOT exist (autosave was off).
        assert not target.is_file()
        # But the dirty flag was still set, so a manual save works.
        assert ctrl._dirty is True


class TestDialogs:

    def _make_ctrl(self):
        """Fresh controller bound to a fresh empty forest.

        We pass a brand-new ``ForestDef`` to ``start()`` so the
        controller does NOT load the user's real per-machine
        ``last_forest.scriptreeforest`` — that would let test state
        leak between runs (and between developers running the suite).
        Autosave is disabled (v0.3.20+) so ``forestChanged`` signals
        in dialog tests don't write to the dev's APPDATA either.
        """
        from scriptree.shell.forest_controller import ForestController
        _fresh_registry()
        ctrl = ForestController(load_branding(), CellRegistry.instance(), None)
        ctrl.set_autosave_enabled(False)
        ctrl.start(forest=ForestDef(), suppress_first_run=True)
        return ctrl

    def test_first_run_dialog_constructs(self) -> None:
        ctrl = self._make_ctrl()
        from scriptree.shell.forest_dialogs import FirstRunDialog
        dlg = FirstRunDialog(ctrl)
        # Apply with no actual changes — we just confirm the
        # widget tree is wired.
        assert dlg._roots.values() == ctrl.forest.auto_discover.roots
        assert dlg._mode.value() == "prompt"
        dlg.close()

    def test_settings_dialog_save_updates_controller(
        self, tmp_path: Path,
    ) -> None:
        ctrl = self._make_ctrl()
        from scriptree.shell.forest_dialogs import ForestSettingsDialog
        dlg = ForestSettingsDialog(ctrl)
        dlg._name_edit.setText("Renamed")
        dlg._enabled_cb.setChecked(False)
        dlg._mode._rb_auto.setChecked(True)
        # Mimic the save path.
        dlg._save()
        assert ctrl.forest.name == "Renamed"
        assert ctrl.forest.auto_discover.enabled is False
        assert ctrl.forest.auto_discover.update_mode == "auto"

    def test_excluded_dialog_reinclude(self, tmp_path: Path) -> None:
        ctrl = self._make_ctrl()
        path = str(tmp_path / "x.scriptree")
        Path(path).write_text("{}", encoding="utf-8")
        ctrl.add_item(path, "tool")
        ctrl.remove_item(path, exclude=True)
        assert len(ctrl.forest.excluded) == 1

        from scriptree.shell.forest_dialogs import ExcludedItemsDialog
        dlg = ExcludedItemsDialog(ctrl)
        dlg._reinclude(path)
        assert len(ctrl.forest.excluded) == 0
        assert len(ctrl.forest.items) == 1

    def test_settings_dialog_has_run_button(self) -> None:
        """v0.3.16: ForestSettingsDialog gains a "Save && Run
        discovery" button so the user can configure scan folders
        and immediately run a pass without right-clicking → Refresh."""
        ctrl = self._make_ctrl()
        from scriptree.shell.forest_dialogs import ForestSettingsDialog
        dlg = ForestSettingsDialog(ctrl)
        assert hasattr(dlg, "_btn_run")
        from PySide6.QtWidgets import QPushButton
        assert isinstance(dlg._btn_run, QPushButton)
        assert "Run" in dlg._btn_run.text()
        dlg.close()

    def test_diff_dialog_uses_tree_view(self, tmp_path: Path) -> None:
        """v0.3.16: UpdateDiffDialog renders the added / removed /
        previously-excluded sections as ``QTreeWidget`` rows so the
        user can see ring → tree → tool hierarchy."""
        from scriptree.shell.forest_dialogs import UpdateDiffDialog
        from scriptree.shell.forest_discover import (
            DiscoveredItem, DiscoveryDiff,
        )
        from PySide6.QtWidgets import QTreeWidget

        # Build a DiscoveryDiff with one added tool so the tree gets
        # populated.
        tool = tmp_path / "x.scriptree"
        tool.write_text("{}", encoding="utf-8")
        diff = DiscoveryDiff(added=[
            DiscoveredItem(path=str(tool), kind="tool"),
        ])
        ctrl = self._make_ctrl()
        dlg = UpdateDiffDialog(ctrl, diff)
        assert isinstance(dlg._added_tree, QTreeWidget)
        assert dlg._added_tree.topLevelItemCount() == 1
        # Top-level row is checkable and checked by default.
        from PySide6.QtCore import Qt
        top = dlg._added_tree.topLevelItem(0)
        assert top.checkState(0) == Qt.CheckState.Checked
        dlg.close()

    def test_excluded_dialog_forget(self, tmp_path: Path) -> None:
        ctrl = self._make_ctrl()
        path = str(tmp_path / "x.scriptree")
        Path(path).write_text("{}", encoding="utf-8")
        ctrl.add_item(path, "tool")
        ctrl.remove_item(path, exclude=True)
        from scriptree.shell.forest_dialogs import ExcludedItemsDialog
        dlg = ExcludedItemsDialog(ctrl)
        dlg._forget(path)
        # Forget → path leaves excluded list, but is NOT re-added.
        assert len(ctrl.forest.excluded) == 0
        assert len(ctrl.forest.items) == 0
