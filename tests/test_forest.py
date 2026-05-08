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
from scriptree.shell.forest_window import ForestWindow


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
        assert loaded.auto_discover.roots == ["ScripTreeApps"]
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
# forest_window — visible cell construction
# ===========================================================================

class TestForestWindow:

    def test_constructs_with_branding(self) -> None:
        fw = ForestWindow(load_branding())
        assert fw.size().width() == 96
        assert fw._label_text == "F"
        fw.close()

    def test_set_label_truncates_to_three(self) -> None:
        fw = ForestWindow(load_branding())
        fw.set_label("Engineering")
        assert fw._label_text == "Eng"
        fw.close()

    def test_set_size_recomputes_geometry(self) -> None:
        fw = ForestWindow(load_branding())
        fw.set_size(120)
        assert fw.size().width() == 120
        assert len(fw._vertices) == 12
        fw.close()


# ===========================================================================
# forest_controller — orchestration
# ===========================================================================

class TestForestController:

    def _make(self):
        from scriptree.shell.forest_controller import ForestController
        _fresh_registry()
        ctrl = ForestController(load_branding(), CellRegistry.instance(), None)
        return ctrl

    def test_construct_no_window_until_start(self) -> None:
        ctrl = self._make()
        assert ctrl.forest_window is None
        assert isinstance(ctrl.forest, ForestDef)

    def test_add_item_de_duplicates(self, tmp_path: Path) -> None:
        ctrl = self._make()
        path = str(tmp_path / "x.scriptree")
        Path(path).write_text("{}", encoding="utf-8")
        ctrl.add_item(path, "tool")
        ctrl.add_item(path, "tool")
        assert len(ctrl.forest.items) == 1

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

        # Make a fresh controller, open the file.
        ctrl2 = self._make()
        ctrl2.start()  # spawns the forest_window
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

class TestDialogs:

    def _make_ctrl(self):
        """Fresh controller bound to a fresh empty forest.

        We pass a brand-new ``ForestDef`` to ``start()`` so the
        controller does NOT load the user's real per-machine
        ``last_forest.scriptreeforest`` — that would let test state
        leak between runs (and between developers running the suite).
        """
        from scriptree.shell.forest_controller import ForestController
        _fresh_registry()
        ctrl = ForestController(load_branding(), CellRegistry.instance(), None)
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
