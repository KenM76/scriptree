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
        # v0.3.22: default roots include "ScripTreeApps" (in-source)
        # and "../ScripTreeApps" (sibling-of-install layout).
        # v0.8.0a24+: also includes the host's per-user app-data
        # directory (where the drop-install dialog's "Personal"
        # target installs to) so freshly-installed apps are picked
        # up automatically by the next forest scan.
        roots = loaded.auto_discover.roots
        assert "ScripTreeApps" in roots
        assert "../ScripTreeApps" in roots
        # Third root is the host-specific personal-apps directory.
        # We don't pin the exact string (it's OS- and user-
        # specific) but we DO pin that there are three entries.
        assert len(roots) == 3, (
            f"Expected 3 default roots (ScripTreeApps, "
            f"../ScripTreeApps, personal-apps), got {roots!r}"
        )
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

    @pytest.fixture(autouse=True)
    def _isolate_prefs_from_user_appdata(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """v0.8.0a53: redirect ``default_preferences_path`` to an
        empty tmp dir so ``load_preferences`` returns factory
        defaults regardless of what the dev's actual
        ``%APPDATA%/ScripTree/forest_preferences.json`` says.

        Pre-a52, prefs only carried two fields and the failure
        mode of reading dev-machine prefs was harmless.  a52
        introduced visibility flags that gate whether the forest
        hub gets ``forest_window.show()`` called at startup -- so
        a dev whose live prefs have ``show_always_on_top=False``
        (because they tested the new feature) would see this
        whole test class fail.  The fixture is autouse so it
        applies to every test in the class without modifying
        each one.
        """
        from scriptree.shell import forest_io as io_mod
        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda branding: tmp_path / "forest_preferences.json",
        )

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

    def test_forest_cell_has_stable_settings_id(self) -> None:
        """v0.8.0a47 regression: the forest hub's ``_id`` must be the
        ``FOREST_HUB_HEX_ID`` sentinel so per-cell QSettings entries
        (``hexagon/<id>/text_label`` etc.) survive across launches.

        Pre-a47 the forest cell got a fresh ``uuid.uuid4()`` from
        ``CellWindow.__init__`` every run, so user customisations
        on the forest cell silently vanished after restart.  Locking
        this to the sentinel value keeps the saved settings live.

        If a future change wants to relax this (e.g. derive per-
        forest ids from the file path), update the sentinel name
        and the comment in ``forest_controller`` together -- but
        DO NOT change the literal value ``"forest-hub"``; every
        existing user's saved settings live at that key.
        """
        from scriptree.shell.forest_controller import (
            ForestController, FOREST_HUB_HEX_ID,
        )

        _fresh_registry()
        ctrl = ForestController(load_branding(), CellRegistry.instance(), None)
        ctrl.start(forest=ForestDef(), suppress_first_run=True)
        assert ctrl.forest_window._id == FOREST_HUB_HEX_ID
        assert FOREST_HUB_HEX_ID == "forest-hub"  # frozen literal
        # Derived QSettings key must also be deterministic and
        # use the sentinel -- this is what guarantees saved
        # settings round-trip across launches.
        assert ctrl.forest_window._settings_key("text_label") == (
            "hexagon/forest-hub/text_label"
        )
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
        to the developer's real ``default.scriptreeforest``
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

        autoload_target = tmp_path / "default.scriptreeforest"
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


class TestForestVisibilityPreferences:
    """v0.8.0a52: three visibility flags on ForestPreferences
    (``show_always_on_top``, ``show_on_taskbar``,
    ``show_in_system_tray``) control how the forest hub is
    reachable.  At least one MUST stay True or the hub becomes
    unreachable; ``normalised()`` repairs the degenerate state.
    """

    def _make_branding(self) -> dict:
        return load_branding()

    def test_factory_defaults_visibility(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """First-run user (no prefs file): only ``show_always_on_top``
        is True.  Matches the pre-a52 behaviour verbatim."""
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.forest_io import load_preferences

        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda branding: tmp_path / "forest_preferences.json",
        )
        prefs = load_preferences(self._make_branding())
        assert prefs.show_always_on_top is True
        assert prefs.show_on_taskbar is False
        assert prefs.show_in_system_tray is False

    def test_round_trip_all_three_flags(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
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
                show_always_on_top=False,
                show_on_taskbar=True,
                show_in_system_tray=True,
            ),
            br,
        )
        loaded = load_preferences(br)
        assert loaded.show_always_on_top is False
        assert loaded.show_on_taskbar is True
        assert loaded.show_in_system_tray is True

    def test_normalised_repairs_all_false(self) -> None:
        """``normalised()`` must force ``show_always_on_top`` ON
        when the user (or a hand-edited disk file) would leave
        all three flags False -- otherwise the hub is
        unreachable."""
        from scriptree.shell.forest_io import ForestPreferences

        prefs = ForestPreferences(
            show_always_on_top=False,
            show_on_taskbar=False,
            show_in_system_tray=False,
        )
        repaired = prefs.normalised()
        assert repaired.show_always_on_top is True
        # The other two flags are left alone (the user's
        # explicit intent for taskbar/tray, if any, is
        # preserved).
        assert repaired.show_on_taskbar is False
        assert repaired.show_in_system_tray is False

    def test_normalised_passthrough_when_at_least_one_true(
        self,
    ) -> None:
        """Any combination with ≥1 True passes through unchanged."""
        from scriptree.shell.forest_io import ForestPreferences

        for aot, tb, tr in [
            (True, False, False),
            (False, True, False),
            (False, False, True),
            (True, True, True),
            (False, True, True),
        ]:
            prefs = ForestPreferences(
                show_always_on_top=aot,
                show_on_taskbar=tb,
                show_in_system_tray=tr,
            )
            out = prefs.normalised()
            assert out.show_always_on_top is aot
            assert out.show_on_taskbar is tb
            assert out.show_in_system_tray is tr

    def test_load_repairs_disk_file_with_all_false(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """A hand-edited prefs file with all three flags False
        must be repaired by ``load_preferences`` -- the runtime
        should never see the degenerate state."""
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.forest_io import load_preferences

        prefs_file = tmp_path / "forest_preferences.json"
        # Hand-craft a degenerate prefs file.
        prefs_file.write_text(
            '{"format": "scriptreeforest_prefs", "version": 1, '
            '"fallback_to_default": true, '
            '"default_forest_path": "", '
            '"show_always_on_top": false, '
            '"show_on_taskbar": false, '
            '"show_in_system_tray": false}',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda branding: prefs_file,
        )
        loaded = load_preferences(self._make_branding())
        assert loaded.show_always_on_top is True

    def test_save_repairs_all_false_before_write(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """``save_preferences`` must call ``normalised()`` so a
        degenerate in-memory object never reaches disk."""
        import json
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.forest_io import (
            ForestPreferences, save_preferences,
        )

        prefs_file = tmp_path / "forest_preferences.json"
        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda branding: prefs_file,
        )

        save_preferences(
            ForestPreferences(
                show_always_on_top=False,
                show_on_taskbar=False,
                show_in_system_tray=False,
            ),
            self._make_branding(),
        )
        on_disk = json.loads(prefs_file.read_text(encoding="utf-8"))
        assert on_disk["show_always_on_top"] is True

    def test_legacy_prefs_file_gets_defaults(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """Prefs files written BEFORE a52 don't carry the three
        visibility keys.  Loading them must yield the factory
        defaults so the user's existing always-on-top experience
        is preserved verbatim."""
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.forest_io import load_preferences

        prefs_file = tmp_path / "forest_preferences.json"
        # Pre-a52 format -- only the two original keys.
        prefs_file.write_text(
            '{"format": "scriptreeforest_prefs", "version": 1, '
            '"fallback_to_default": true, '
            '"default_forest_path": ""}',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda branding: prefs_file,
        )
        loaded = load_preferences(self._make_branding())
        assert loaded.show_always_on_top is True
        assert loaded.show_on_taskbar is False
        assert loaded.show_in_system_tray is False


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

        target = tmp_path / "default.scriptreeforest"
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
        ``default.scriptreeforest`` — that would let test state
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


# ===========================================================================
# v0.5.2 — default.scriptreeforest rename + legacy migration
# ===========================================================================

class TestDefaultForestFilenameRename:
    """Pin the v0.5.2 rename ``last_forest.scriptreeforest`` →
    ``default.scriptreeforest`` and the one-shot migration that
    rehomes an existing legacy file."""

    def test_default_autoload_path_is_default_scriptreeforest(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Factory default filename is ``default.scriptreeforest``."""
        from scriptree.shell.forest_io import default_autoload_path
        # Redirect HOME so we resolve into the tmp dir.
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        p = default_autoload_path({"appName": "ScripTree"})
        assert p.name == "default.scriptreeforest"

    def test_migrate_legacy_renames_old_file(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Existing ``last_forest.scriptreeforest`` → rename to
        ``default.scriptreeforest``; original removed."""
        from scriptree.shell.forest_io import (
            default_autoload_path, migrate_legacy_autoload_path,
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        new_p = default_autoload_path({"appName": "ScripTree"})
        new_p.parent.mkdir(parents=True, exist_ok=True)
        legacy = new_p.parent / "last_forest.scriptreeforest"
        legacy.write_text(
            '{"format":"scriptreeforest","version":1,"items":[]}',
            encoding="utf-8",
        )
        result = migrate_legacy_autoload_path({"appName": "ScripTree"})
        assert result == legacy
        assert new_p.is_file()
        assert not legacy.exists()

    def test_migrate_legacy_is_noop_when_new_exists(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """If ``default.scriptreeforest`` already exists, the legacy
        file is left untouched."""
        from scriptree.shell.forest_io import (
            default_autoload_path, migrate_legacy_autoload_path,
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        new_p = default_autoload_path({"appName": "ScripTree"})
        new_p.parent.mkdir(parents=True, exist_ok=True)
        new_p.write_text(
            '{"format":"scriptreeforest","version":1,"items":[]}',
            encoding="utf-8",
        )
        legacy = new_p.parent / "last_forest.scriptreeforest"
        legacy.write_text(
            '{"format":"scriptreeforest","version":1,"items":[]}',
            encoding="utf-8",
        )
        result = migrate_legacy_autoload_path({"appName": "ScripTree"})
        assert result is None
        assert legacy.is_file()  # untouched

    def test_migrate_legacy_is_noop_on_fresh_install(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """No legacy + no new = no-op (returns None)."""
        from scriptree.shell.forest_io import migrate_legacy_autoload_path
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = migrate_legacy_autoload_path({"appName": "ScripTree"})
        assert result is None


# ===========================================================================
# v0.6.9 — unsaved-forest default-spot save (personal vs shared, no
# filename/dir prompt; becomes the auto-load default next launch)
# ===========================================================================

class TestUnsavedForestDefaultSpot:
    def test_shared_path_distinct_from_personal(self) -> None:
        from scriptree.shell.forest_io import (
            default_autoload_path, shared_autoload_path,
        )
        br = load_branding()
        personal = default_autoload_path(br)
        shared = shared_autoload_path(br)
        assert personal != shared
        assert personal.name == "default.scriptreeforest"
        assert shared.name == "default.scriptreeforest"

    def test_save_as_default_writes_and_sets_autoload(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """``_save_as_default`` writes the forest to the fixed path
        AND records it as the auto-load default (so next launch
        loads it without asking)."""
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.forest_controller import ForestController
        from scriptree.shell.forest_io import load_preferences

        prefs_file = tmp_path / "forest_preferences.json"
        target = tmp_path / "personal" / "default.scriptreeforest"
        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda branding: prefs_file,
        )

        _fresh_registry()
        ctrl = ForestController(
            load_branding(), CellRegistry.instance(), None,
        )
        ctrl.set_autosave_enabled(False)
        ctrl.start(forest=ForestDef(name="Fresh"), suppress_first_run=True)
        ctrl._save_as_default(target)

        assert target.is_file()
        assert ctrl.forest.loaded_from == str(target.resolve())
        prefs = load_preferences(load_branding())
        assert prefs.fallback_to_default is True
        assert prefs.default_forest_path == str(target)

    def test_try_spawn_master_preserves_forest_link(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """v0.6.14 — two forest-linked cells dragged together form
        a ring that itself stays forest-linked.  The new master is
        promoted to a forest member; the source cells become ring
        members (dropped from the forest's direct membership)."""
        from PySide6.QtCore import QPoint
        from scriptree.shell import forest_controller as fc_mod
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.cell_window import (
            CellWindow, _try_spawn_master,
        )
        from scriptree.shell.forest_controller import ForestController

        prefs_file = tmp_path / "forest_preferences.json"
        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda b: prefs_file,
        )
        monkeypatch.setattr(
            fc_mod, "default_autoload_path",
            lambda b: tmp_path / "default.scriptreeforest",
        )
        monkeypatch.setattr(
            io_mod, "default_autoload_path",
            lambda b: tmp_path / "default.scriptreeforest",
        )

        _fresh_registry()
        ctrl = ForestController(
            load_branding(), CellRegistry.instance(), None,
        )
        ctrl.set_autosave_enabled(False)
        ctrl.start(forest=ForestDef(name="F"), suppress_first_run=True)
        forest = ctrl.forest_window

        # Two cells that are forest members but have been broken
        # free (gripped → dragged out → still linked).
        a = CellWindow(load_branding())
        b = CellWindow(load_branding())
        a.show(); b.show()
        a.move(420, 420); b.move(480, 420)
        forest._members[a._id] = QPoint(420, 420)
        forest._members[b._id] = QPoint(480, 420)
        a._group_master_id = forest._id
        b._group_master_id = forest._id
        # Break-free state: not in _positioned anymore.
        # (forest._positioned doesn't include them.)

        # Drive _try_spawn_master directly — same as snap engine.
        _try_spawn_master(a, b)

        # Find the newly spawned master (only one CellWindow with
        # role=="master" that isn't the forest_window).
        reg = CellRegistry.instance()
        new_master = next(
            m for m in reg.masters()
            if m._id != forest._id
        )

        # The two source cells are members of the new ring.
        assert a._id in new_master._members
        assert b._id in new_master._members
        # The new ring is itself a forest member.
        assert new_master._id in forest._members
        assert new_master._group_master_id == forest._id
        # Source cells are no longer in the forest's *direct*
        # membership (their forest link is transitive via the ring).
        assert a._id not in forest._members
        assert b._id not in forest._members
        new_master.close(); a.close(); b.close()

    def test_forest_submenu_actions_carry_icons(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """v0.6.15 — every action under the Forest submenu has a
        non-null icon (used to be all icon-less, looking unfinished
        next to the cell submenu's icons)."""
        from PySide6.QtWidgets import QMenu
        from scriptree.shell import forest_controller as fc_mod
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.forest_controller import ForestController

        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda b: tmp_path / "forest_preferences.json",
        )
        monkeypatch.setattr(
            fc_mod, "default_autoload_path",
            lambda b: tmp_path / "default.scriptreeforest",
        )

        _fresh_registry()
        ctrl = ForestController(
            load_branding(), CellRegistry.instance(), None,
        )
        ctrl.set_autosave_enabled(False)
        ctrl.start(forest=ForestDef(name="F"), suppress_first_run=True)

        parent = QMenu()
        ctrl._populate_forest_menu(parent)

        # The forest submenu is the first action's menu().
        forest_submenu_action = parent.actions()[0]
        forest_submenu = forest_submenu_action.menu()
        assert forest_submenu is not None
        # The submenu marker itself carries the forest icon.
        assert not forest_submenu.icon().isNull(), (
            "Forest submenu should carry the forest hub icon."
        )
        # And every (non-separator) action inside has an icon.
        for act in forest_submenu.actions():
            if act.isSeparator():
                continue
            assert not act.icon().isNull(), (
                f"Forest submenu action {act.text()!r} has no icon."
            )

    def test_master_absorbs_nearby_forest_linked_free_cell(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """v0.6.14 — a master dragged near a free cell that's
        forest-linked absorbs the cell as a new ring member AND
        inherits the forest link itself."""
        from PySide6.QtCore import QPoint
        from scriptree.shell import forest_controller as fc_mod
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.cell_window import CellWindow
        from scriptree.shell.forest_controller import ForestController

        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda b: tmp_path / "forest_preferences.json",
        )
        monkeypatch.setattr(
            fc_mod, "default_autoload_path",
            lambda b: tmp_path / "default.scriptreeforest",
        )
        monkeypatch.setattr(
            io_mod, "default_autoload_path",
            lambda b: tmp_path / "default.scriptreeforest",
        )

        _fresh_registry()
        ctrl = ForestController(
            load_branding(), CellRegistry.instance(), None,
        )
        ctrl.set_autosave_enabled(False)
        ctrl.start(forest=ForestDef(name="F"), suppress_first_run=True)
        forest = ctrl.forest_window

        # A standalone master (a ring's master) at (500, 500).
        m = CellWindow(load_branding(), role="master")
        m.show()
        m.move(500, 500)

        # A free cell that's forest-linked (break-free state),
        # placed within absorb radius of the master's centre.
        c = CellWindow(load_branding())
        c.show()
        c.move(550, 500)  # ~50 px right of master, well within 1.6*size
        forest._members[c._id] = QPoint(550, 500)
        c._group_master_id = forest._id

        # Drive the absorb routine that drag-end now invokes.
        m._try_absorb_nearby_free_cells()

        # The cell is now a ring member.
        assert c._id in m._members
        assert c._group_master_id == m._id
        # The cell is no longer a direct forest member.
        assert c._id not in forest._members
        # The master itself inherited the forest link.
        assert m._id in forest._members
        assert m._group_master_id == forest._id
        m.close(); c.close()

    def test_loose_linked_outline_dimmer_than_docked(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """v0.6.16 — a cell that has link_master_id but isn't in
        the master's _positioned set (break-free state) renders
        its outline at ~55% alpha so the user can tell it's
        loose-linked rather than fully docked."""
        from PySide6.QtCore import QPoint
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        _fresh_registry()
        master = CellWindow(load_branding(), role="master")
        c = CellWindow(load_branding())
        master.show(); c.show()
        master.move(400, 400); c.move(456, 400)
        master._members[c._id] = QPoint(456, 400)
        master._positioned.add(c._id)
        c._group_master_id = master._id

        # While docked, the stroke is the normal _stroke_color.
        docked_color = c._compute_stroke_color()
        assert not c.is_loose_linked

        # Break-free: remove from _positioned but keep the link.
        master._positioned.discard(c._id)
        assert c.is_loose_linked
        loose_color = c._compute_stroke_color()
        # Same RGB, different alpha (dimmer).
        assert loose_color.alpha() < docked_color.alpha()
        master.close(); c.close()

    def test_collapse_cascades_to_linked_members(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """v0.6.20 — collapsing the forest cascades to every linked
        cell (ring members + standalone children).  The v0.6.17
        opt-in model was reverted per user direction: "single click
        on forest or a ring is supposed to collapse all linked
        cells."

        The dead ``_collapse_with_master`` field still exists for
        backward-compat on disk but no longer gates the cascade —
        every member tucks toward the master regardless.
        """
        from PySide6.QtCore import QPoint
        from scriptree.shell import forest_controller as fc_mod
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.cell_window import CellWindow
        from scriptree.shell.forest_controller import ForestController

        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda b: tmp_path / "forest_preferences.json",
        )
        monkeypatch.setattr(
            fc_mod, "default_autoload_path",
            lambda b: tmp_path / "default.scriptreeforest",
        )

        _fresh_registry()
        ctrl = ForestController(
            load_branding(), CellRegistry.instance(), None,
        )
        ctrl.set_autosave_enabled(False)
        ctrl.start(forest=ForestDef(name="F"), suppress_first_run=True)
        forest = ctrl.forest_window

        # A ring that's a forest member.
        ring = CellWindow(load_branding(), role="master")
        ring.show(); ring.move(500, 500)
        forest._members[ring._id] = QPoint(500, 500)
        forest._positioned.add(ring._id)
        ring._group_master_id = forest._id

        # Collapse the forest.  The forest transitions through
        # ``"collapsing"`` and lands at ``"collapsed"`` once the
        # animation finishes — we tolerate either since the exact
        # moment depends on the Qt event loop's frame timing under
        # headless test runs.
        #
        # The ring itself stays ``"expanded"``: the v0.6.20 cascade
        # recurses into a member only when the member is a master
        # WITH its own ``_members`` (a populated ring inside the
        # forest).  This ring has no members of its own, so the
        # forest tucks it positionally but leaves its state alone.
        # When a populated ring is inside the forest the recursive
        # branch fires — that's the "forest collapse → ring cells
        # shrink into ring AND ring shrinks into forest" path.
        forest._start_collapse()
        assert forest._collapse_state in ("collapsing", "collapsed")
        assert ring._collapse_state == "expanded"
        ring.close()

    def test_ring_drag_end_near_forest_member_joins_forest(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """v0.6.16 — drag a free ring to a cell that's a forest
        member: the ring becomes a forest member (link=Forest,
        dock=Forest).  The cell is NOT pulled into the ring."""
        from PySide6.QtCore import QPoint
        from scriptree.shell import forest_controller as fc_mod
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.cell_window import CellWindow
        from scriptree.shell.forest_controller import ForestController

        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda b: tmp_path / "forest_preferences.json",
        )
        monkeypatch.setattr(
            fc_mod, "default_autoload_path",
            lambda b: tmp_path / "default.scriptreeforest",
        )

        _fresh_registry()
        ctrl = ForestController(
            load_branding(), CellRegistry.instance(), None,
        )
        ctrl.set_autosave_enabled(False)
        ctrl.start(forest=ForestDef(name="F"), suppress_first_run=True)
        forest = ctrl.forest_window

        # A cell that's already a forest member.
        anchor = CellWindow(load_branding())
        anchor.show()
        anchor.move(500, 500)
        forest._members[anchor._id] = QPoint(500, 500)
        forest._positioned.add(anchor._id)
        anchor._group_master_id = forest._id

        # A free ring master near the anchor.  Not linked yet.
        ring = CellWindow(load_branding(), role="master")
        ring.show()
        ring.move(560, 500)
        assert ring._group_master_id is None

        ring._try_join_forest_near_member()

        # Ring is now a forest member.
        assert ring._id in forest._members
        assert ring._id in forest._positioned
        assert ring._group_master_id == forest._id
        # Anchor cell is UNTOUCHED — still a direct forest member.
        assert anchor._id in forest._members
        assert anchor._group_master_id == forest._id
        assert anchor._id not in ring._members
        ring.close(); anchor.close()

    def test_flush_prompt_personal_choice_no_file_dialog(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """Transient forest with items at exit: the prompt offers
        Personal/Shared and writes to the personal default WITHOUT
        ever calling QFileDialog.getSaveFileName."""
        from unittest.mock import patch

        from PySide6.QtWidgets import QFileDialog, QMessageBox

        from scriptree.shell import forest_controller as fc_mod
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.forest_controller import ForestController
        from scriptree.shell.forest_io import (
            ForestItem, ForestPreferences, load_preferences,
            save_preferences,
        )

        personal = tmp_path / "personal" / "default.scriptreeforest"
        shared = tmp_path / "shared" / "default.scriptreeforest"
        prefs_file = tmp_path / "forest_preferences.json"
        monkeypatch.setattr(
            fc_mod, "default_autoload_path", lambda b: personal,
        )
        monkeypatch.setattr(
            fc_mod, "shared_autoload_path", lambda b: shared,
        )
        monkeypatch.setattr(
            io_mod, "default_preferences_path", lambda b: prefs_file,
        )
        monkeypatch.setattr(
            io_mod, "default_autoload_path", lambda b: personal,
        )
        # Run transient (fallback OFF) so save() is a no-op and the
        # exit-time prompt actually fires — this is the user's
        # "started empty, no file loaded" scenario.
        save_preferences(
            ForestPreferences(fallback_to_default=False), load_branding(),
        )

        _fresh_registry()
        ctrl = ForestController(
            load_branding(), CellRegistry.instance(), None,
        )
        ctrl.set_autosave_enabled(False)
        ctrl.start(forest=ForestDef(name="T"), suppress_first_run=True)
        ctrl.forest.loaded_from = None
        ctrl.forest.items.append(
            ForestItem(path="x.scriptree", kind="tool")
        )
        ctrl._dirty = True

        def _pick_personal(self):
            self._fake_clicked = next(
                b for b in self.buttons() if b.text() == "Personal"
            )
            return 0

        file_dialog_calls: list = []
        with patch.object(QMessageBox, "exec", _pick_personal), \
             patch.object(
                 QMessageBox, "clickedButton",
                 lambda self: self._fake_clicked,
             ), \
             patch.object(
                 QFileDialog, "getSaveFileName",
                 lambda *a, **k: file_dialog_calls.append(a) or ("", ""),
             ):
            ctrl.flush_if_dirty()

        assert file_dialog_calls == []
        assert personal.is_file()
        assert not shared.exists()
        assert ctrl.forest.loaded_from == str(personal.resolve())
        prefs = load_preferences(load_branding())
        assert prefs.fallback_to_default is True
        assert prefs.default_forest_path == str(personal)


# ===========================================================================
# v0.6.11 — flakey-movement / overlap / live-edge / window-position fixes
# ===========================================================================

class TestForestWindowPositionPersistence:
    """``ForestDef.window_position`` round-trips through io and the
    controller restores it on start (default = bottom-left)."""

    def test_window_position_round_trips(self, tmp_path: Path) -> None:
        f = ForestDef(name="X")
        f.window_position = (137, 421)
        p = tmp_path / "x.scriptreeforest"
        save_forest(f, p)
        loaded = load_forest(p)
        assert loaded.window_position == (137, 421)

    def test_default_window_position_omitted_from_json(
        self, tmp_path: Path,
    ) -> None:
        """Pre-v0.6.11 files have no ``window_position`` key — a
        forest with the default (None) must round-trip byte-stable."""
        f = ForestDef(name="X")
        p = tmp_path / "x.scriptreeforest"
        save_forest(f, p)
        blob = json.loads(p.read_text(encoding="utf-8"))
        assert "window_position" not in blob

    def test_malformed_window_position_ignored(
        self, tmp_path: Path,
    ) -> None:
        """A hand-edited ``window_position`` that isn't a 2-tuple of
        ints silently falls back to ``None`` so the file can't poison
        the launcher."""
        p = tmp_path / "x.scriptreeforest"
        p.write_text(json.dumps({
            "format": "scriptreeforest", "version": 1,
            "name": "X", "items": [], "excluded": [],
            "auto_discover": {"enabled": True, "roots": [],
                              "include": ["ring", "tree", "tool"],
                              "update_mode": "prompt"},
            "window_position": "not-a-tuple",
        }), encoding="utf-8")
        loaded = load_forest(p)
        assert loaded.window_position is None

    def test_start_uses_bottom_left_when_no_stored_position(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        """First-run forest with no stored window_position → hub
        appears in the bottom-left of the primary screen."""
        from PySide6.QtGui import QGuiApplication
        from scriptree.shell import forest_controller as fc_mod
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.forest_controller import ForestController

        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda b: tmp_path / "forest_preferences.json",
        )
        monkeypatch.setattr(
            fc_mod, "default_autoload_path",
            lambda b: tmp_path / "default.scriptreeforest",
        )
        monkeypatch.setattr(
            io_mod, "default_autoload_path",
            lambda b: tmp_path / "default.scriptreeforest",
        )

        _fresh_registry()
        ctrl = ForestController(
            load_branding(), CellRegistry.instance(), None,
        )
        ctrl.set_autosave_enabled(False)
        ctrl.start(forest=ForestDef(name="F"), suppress_first_run=True)
        pos = ctrl.forest_window.pos()
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            # x is near the left edge…
            assert pos.x() <= geo.left() + 100
            # …y is near the bottom edge.
            assert pos.y() >= geo.bottom() - ctrl.forest_window.height() - 100
        # And the seeded position lands on the in-memory ForestDef
        # so the next save carries it.
        assert ctrl.forest.window_position is not None

    def test_start_restores_stored_window_position(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        from scriptree.shell import forest_controller as fc_mod
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.forest_controller import ForestController

        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda b: tmp_path / "forest_preferences.json",
        )
        monkeypatch.setattr(
            fc_mod, "default_autoload_path",
            lambda b: tmp_path / "default.scriptreeforest",
        )

        f = ForestDef(name="F", window_position=(212, 88))
        _fresh_registry()
        ctrl = ForestController(
            load_branding(), CellRegistry.instance(), None,
        )
        ctrl.set_autosave_enabled(False)
        ctrl.start(forest=f, suppress_first_run=True)
        pos = ctrl.forest_window.pos()
        assert pos.x() == 212 and pos.y() == 88


class TestMemberOverlapResolution:
    """``_resolve_member_overlap`` repacks members that overlap and
    leaves non-overlapping members alone (preserves user layout)."""

    def test_overlapping_pair_is_repacked(
        self, tmp_path: Path, monkeypatch: Any,
    ) -> None:
        from scriptree.shell import forest_controller as fc_mod
        from scriptree.shell import forest_io as io_mod
        from scriptree.shell.forest_controller import ForestController
        from scriptree.shell.cell_window import CellWindow

        monkeypatch.setattr(
            io_mod, "default_preferences_path",
            lambda b: tmp_path / "forest_preferences.json",
        )
        monkeypatch.setattr(
            fc_mod, "default_autoload_path",
            lambda b: tmp_path / "default.scriptreeforest",
        )

        _fresh_registry()
        ctrl = ForestController(
            load_branding(), CellRegistry.instance(), None,
        )
        ctrl.set_autosave_enabled(False)
        ctrl.start(forest=ForestDef(name="F"), suppress_first_run=True)
        forest = ctrl.forest_window

        # Spawn two real members and stack them on the same pixel.
        a = CellWindow(load_branding())
        b = CellWindow(load_branding())
        a.show(); b.show()
        forest._members[a._id] = a.pos()
        forest._members[b._id] = b.pos()
        forest._positioned.add(a._id)
        forest._positioned.add(b._id)
        a.move(400, 400); b.move(400, 400)

        ctrl._resolve_member_overlap()

        # The surgical repack uses ``_smooth_move`` so the slot moves
        # are eased animations — pump the event loop until they
        # settle before asserting positions.
        from PySide6.QtCore import QEventLoop, QRect, QTimer
        loop = QEventLoop()
        QTimer.singleShot(400, loop.quit)
        loop.exec()

        # Hex bounding rects overlap at adjacent honeycomb slots
        # (hexes touch at edges but axis-aligned rects intersect).
        # The real check is centre-stacking: any two cells whose
        # centres lie within half the hex size are visually stacked.
        ca = (a.pos().x() + a._size_px // 2, a.pos().y() + a._size_px // 2)
        cb = (b.pos().x() + b._size_px // 2, b.pos().y() + b._size_px // 2)
        threshold = min(a._size_px, b._size_px) * 0.5
        assert (
            abs(ca[0] - cb[0]) >= threshold
            or abs(ca[1] - cb[1]) >= threshold
        ), (
            f"members still stacked after resolve: a-centre={ca}, "
            f"b-centre={cb}, threshold={threshold}"
        )
        a.close(); b.close()


class TestDragCancelsMemberAnimation:
    """During a master drag, each member's in-flight ``_pos_anim``
    must be cancelled so the rigid translation isn't overridden by
    a stale animation target (the v0.6.10 "left behind" symptom)."""

    def test_drag_kills_member_pos_anim(self) -> None:
        from PySide6.QtCore import QPoint
        from scriptree.shell.branding_loader import load_branding
        from scriptree.shell.cell_window import CellWindow

        _fresh_registry()
        master = CellWindow(load_branding(), role="master")
        member = CellWindow(load_branding())
        master.show(); member.show()
        master.move(500, 500)
        member.move(560, 500)
        master._members[member._id] = QPoint(560, 500)
        master._positioned.add(member._id)

        # Start an eased move on the member — the kind a prior
        # repack would have started.
        member._smooth_move(700, 500, duration_ms=400)
        assert getattr(member, "_pos_anim", None) is not None

        # Simulate the master taking a drag step.  moveEvent reads
        # ``_drag_started`` + ``_last_pos`` and applies the rigid
        # translation to every positioned member.
        master._drag_started = True
        master._last_pos = QPoint(500, 500)
        master.move(510, 500)
        # The moveEvent fires synchronously and should have killed
        # the prior animation so the rigid +10 px translation wins.
        assert getattr(member, "_pos_anim", None) is None
        assert member.pos().x() == 570  # 560 + 10

        master._drag_started = False
        master.close(); member.close()
