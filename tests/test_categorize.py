"""Tests for ``scriptree.core.categorize`` -- the auto-organise
algorithm (v0.8.0a25, Phase 2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scriptree.core.categorize import (
    GroupCandidate,
    group_by_category,
    prune_orphan_synthesised,
)


def _c(path: str, category: str, name: str | None = None) -> GroupCandidate:
    return GroupCandidate(
        path=path, category=category,
        display_name=name or Path(path).stem,
    )


# ---------------------------------------------------------------------------
# Passthrough cases
# ---------------------------------------------------------------------------


class TestPassthrough:
    def test_empty_input(self, tmp_path: Path) -> None:
        out = group_by_category([], output_dir=tmp_path)
        assert out == []

    def test_all_uncategorised(self, tmp_path: Path) -> None:
        items = [
            _c("a.scriptree", ""),
            _c("b.scriptree", ""),
        ]
        out = group_by_category(items, output_dir=tmp_path)
        assert all(o.kind == "passthrough" for o in out)
        assert {o.path for o in out} == {"a.scriptree", "b.scriptree"}

    def test_solo_category_passes_through(self, tmp_path: Path) -> None:
        """Only one tool in ``DevTools`` -> flat ForestItem, no tree."""
        items = [_c("git.scriptree", "DevTools")]
        out = group_by_category(items, output_dir=tmp_path)
        assert len(out) == 1
        assert out[0].kind == "passthrough"
        assert out[0].path == "git.scriptree"

    def test_no_files_written_when_all_passthrough(
        self, tmp_path: Path,
    ) -> None:
        items = [
            _c("a.scriptree", "DevTools"),     # solo
            _c("b.scriptree", ""),             # uncategorised
        ]
        group_by_category(items, output_dir=tmp_path)
        # output_dir may exist (we mkdir it) but should have no
        # .scriptreetree files inside.
        synths = list(tmp_path.glob("*.scriptreetree"))
        assert synths == []


# ---------------------------------------------------------------------------
# Synthesis cases
# ---------------------------------------------------------------------------


class TestSynthesis:
    def test_two_items_same_category(self, tmp_path: Path) -> None:
        items = [
            _c("a.scriptree", "MSOffice/Word", "StyleSanitizer"),
            _c("b.scriptree", "MSOffice/Word", "WordCounter"),
        ]
        out = group_by_category(items, output_dir=tmp_path)
        assert len(out) == 1
        assert out[0].kind == "synthesised"
        synth_path = Path(out[0].path)
        assert synth_path.exists()
        assert synth_path.name == "MSOffice.scriptreetree"

        data = json.loads(synth_path.read_text(encoding="utf-8"))
        assert data["name"] == "MSOffice"
        # nodes: [folder Word -> [leaf a, leaf b]]
        assert len(data["nodes"]) == 1
        word = data["nodes"][0]
        assert word["type"] == "folder"
        assert word["name"] == "Word"
        leaves = word["children"]
        assert len(leaves) == 2
        assert all(l["type"] == "leaf" for l in leaves)
        assert {l["path"] for l in leaves} == {"a.scriptree", "b.scriptree"}

    def test_mixed_sub_categories_one_synth_tree(
        self, tmp_path: Path,
    ) -> None:
        """User's main scenario: Word + Excel under one MSOffice."""
        items = [
            _c("a.scriptree", "MSOffice/Word", "A"),
            _c("b.scriptree", "MSOffice/Word", "B"),
            _c("c.scriptree", "MSOffice/Excel", "C"),
        ]
        out = group_by_category(items, output_dir=tmp_path)
        # One synthesised tree, no passthroughs.
        assert len(out) == 1
        assert out[0].kind == "synthesised"
        data = json.loads(Path(out[0].path).read_text(encoding="utf-8"))
        folder_names = {n["name"] for n in data["nodes"]
                        if n["type"] == "folder"}
        assert folder_names == {"Word", "Excel"}

    def test_multiple_top_categories(self, tmp_path: Path) -> None:
        """Two unrelated categories each with 2+ items: two synth trees."""
        items = [
            _c("a.scriptree", "MSOffice/Word"),
            _c("b.scriptree", "MSOffice/Word"),
            _c("c.scriptree", "SolidWorks/Drawings"),
            _c("d.scriptree", "SolidWorks/Drawings"),
        ]
        out = group_by_category(items, output_dir=tmp_path)
        synth = [o for o in out if o.kind == "synthesised"]
        assert len(synth) == 2
        names = {Path(o.path).name for o in synth}
        assert names == {"MSOffice.scriptreetree",
                         "SolidWorks.scriptreetree"}

    def test_user_main_scenario(self, tmp_path: Path) -> None:
        """Verbatim from the plan: 5 inputs -> 3 outputs."""
        items = [
            _c("a.scriptree", "MSOffice/Word", "StyleSanitizer"),
            _c("b.scriptree", "MSOffice/Word", "WordCounter"),
            _c("c.scriptree", "MSOffice/Excel", "CellAggregator"),
            _c("d.scriptree", "DevTools", "GitStatus"),
            _c("e.scriptree", "", "RandomTool"),
        ]
        out = group_by_category(items, output_dir=tmp_path)
        assert len(out) == 3
        # One synth (MSOffice), two passthroughs (DevTools, RandomTool).
        synth_outs = [o for o in out if o.kind == "synthesised"]
        pass_outs = [o for o in out if o.kind == "passthrough"]
        assert len(synth_outs) == 1
        assert len(pass_outs) == 2
        assert Path(synth_outs[0].path).name == "MSOffice.scriptreetree"
        pass_paths = {o.path for o in pass_outs}
        assert pass_paths == {"d.scriptree", "e.scriptree"}


# ---------------------------------------------------------------------------
# Naming / collision rules
# ---------------------------------------------------------------------------


class TestNamingCollisions:
    def test_existing_authored_tree_forces_auto_suffix(
        self, tmp_path: Path,
    ) -> None:
        """If a user has authored ``MSOffice.scriptreetree`` already,
        the synth uses ``__auto`` suffix to avoid clobbering."""
        items = [
            _c("a.scriptree", "MSOffice/Word"),
            _c("b.scriptree", "MSOffice/Word"),
        ]
        out = group_by_category(
            items, output_dir=tmp_path,
            existing_tree_names={"MSOffice"},
        )
        assert len(out) == 1
        assert Path(out[0].path).name == "MSOffice__auto.scriptreetree"

    def test_collision_check_is_case_insensitive(
        self, tmp_path: Path,
    ) -> None:
        items = [
            _c("a.scriptree", "MSOffice/Word"),
            _c("b.scriptree", "MSOffice/Word"),
        ]
        # User authored "msoffice.scriptreetree" (lowercase).
        out = group_by_category(
            items, output_dir=tmp_path,
            existing_tree_names={"msoffice"},
        )
        assert Path(out[0].path).name == "MSOffice__auto.scriptreetree"

    def test_unsafe_chars_in_segment_scrubbed(
        self, tmp_path: Path,
    ) -> None:
        items = [
            _c("a.scriptree", 'Bad<name>/Word'),
            _c("b.scriptree", 'Bad<name>/Word'),
        ]
        out = group_by_category(items, output_dir=tmp_path)
        # ``<>`` scrubbed.
        assert Path(out[0].path).name == "Badname.scriptreetree"

    def test_case_insensitive_bucketing(self, tmp_path: Path) -> None:
        """Two tools with categories ``MSOffice`` and ``msoffice``
        end up in one bucket, not two."""
        items = [
            _c("a.scriptree", "MSOffice/Word"),
            _c("b.scriptree", "msoffice/Excel"),
        ]
        out = group_by_category(items, output_dir=tmp_path)
        synth = [o for o in out if o.kind == "synthesised"]
        assert len(synth) == 1


# ---------------------------------------------------------------------------
# Marker field + auto_discover settings
# ---------------------------------------------------------------------------


class TestMarker:
    def test_synthesised_tree_carries_marker(self, tmp_path: Path) -> None:
        items = [
            _c("a.scriptree", "X/Y"),
            _c("b.scriptree", "X/Y"),
        ]
        out = group_by_category(
            items, output_dir=tmp_path,
            marker_version="scriptree-auto-organise/v1.0",
        )
        data = json.loads(Path(out[0].path).read_text(encoding="utf-8"))
        assert data["synthesised_by"] == "scriptree-auto-organise/v1.0"

    def test_synthesised_tree_has_auto_update_mode(
        self, tmp_path: Path,
    ) -> None:
        items = [
            _c("a.scriptree", "X/Y"),
            _c("b.scriptree", "X/Y"),
        ]
        out = group_by_category(items, output_dir=tmp_path)
        data = json.loads(Path(out[0].path).read_text(encoding="utf-8"))
        assert data["auto_discover"]["update_mode"] == "auto"


# ---------------------------------------------------------------------------
# Prune orphan synthesised trees
# ---------------------------------------------------------------------------


class TestPrune:
    def test_orphan_deleted(self, tmp_path: Path) -> None:
        # Create an orphan synthesised tree (no longer in keep_paths).
        orphan = tmp_path / "Stale.scriptreetree"
        orphan.write_text(json.dumps({
            "name": "Stale",
            "nodes": [],
            "synthesised_by": "scriptree-auto-organise/v1",
        }), encoding="utf-8")

        # Plus a "current" synth that should survive.
        keeper = tmp_path / "Current.scriptreetree"
        keeper.write_text(json.dumps({
            "name": "Current",
            "nodes": [],
            "synthesised_by": "scriptree-auto-organise/v1",
        }), encoding="utf-8")

        deleted = prune_orphan_synthesised(
            tmp_path, keep_paths={keeper},
        )
        assert deleted == [orphan]
        assert not orphan.exists()
        assert keeper.exists()

    def test_user_authored_tree_never_pruned(self, tmp_path: Path) -> None:
        """A ``.scriptreetree`` in the same directory but WITHOUT
        the synthesised_by marker is left untouched."""
        user = tmp_path / "MyHandTree.scriptreetree"
        user.write_text(json.dumps({
            "name": "MyHandTree",
            "nodes": [],
            # No synthesised_by field.
        }), encoding="utf-8")

        deleted = prune_orphan_synthesised(tmp_path, keep_paths=set())
        assert deleted == []
        assert user.exists()

    def test_marker_with_wrong_prefix_not_pruned(
        self, tmp_path: Path,
    ) -> None:
        """If a tree has a synthesised_by field but it's from a
        different tool entirely, leave it alone."""
        third_party = tmp_path / "ThirdParty.scriptreetree"
        third_party.write_text(json.dumps({
            "name": "ThirdParty",
            "nodes": [],
            "synthesised_by": "some-other-tool/v1",
        }), encoding="utf-8")

        deleted = prune_orphan_synthesised(tmp_path, keep_paths=set())
        assert deleted == []
        assert third_party.exists()


# ---------------------------------------------------------------------------
# Threshold customisation
# ---------------------------------------------------------------------------


class TestThreshold:
    def test_min_items_three_solo_pair_passthrough(
        self, tmp_path: Path,
    ) -> None:
        """When the threshold is raised to 3, a pair becomes
        passthrough."""
        items = [
            _c("a.scriptree", "X"),
            _c("b.scriptree", "X"),
        ]
        out = group_by_category(
            items, output_dir=tmp_path,
            min_items_to_synthesise=3,
        )
        assert all(o.kind == "passthrough" for o in out)

    def test_min_items_one_always_wraps(self, tmp_path: Path) -> None:
        """Threshold of 1 wraps even solo categories."""
        items = [_c("a.scriptree", "X")]
        out = group_by_category(
            items, output_dir=tmp_path,
            min_items_to_synthesise=1,
        )
        assert out[0].kind == "synthesised"
