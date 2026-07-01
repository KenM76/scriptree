"""Tests for the canonical category catalog + the soft near-duplicate matcher
+ its integration into ``python -m scriptree validate`` (v0.8.0a112)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scriptree.core import category_catalog as cc


REPO = Path(__file__).resolve().parent.parent


class TestCatalogData:
    def test_catalog_loads_and_is_extensive(self) -> None:
        cc._load_raw.cache_clear()
        assert not cc.is_empty()
        # "very extensive" -- the workflow produced hundreds of categories.
        assert len(cc.canonical_paths()) >= 300
        assert len(cc.canonical_top_levels()) >= 50

    def test_defacto_categories_are_canonical(self) -> None:
        # Every shipped/de-facto category must be in the catalog so existing
        # tools validate clean.
        cc._load_raw.cache_clear()
        paths = set(cc.canonical_paths())
        for c in (
            "Media/ffmpeg", "ScripTree", "Demos",
            "MSOffice/Word", "MSOffice/Excel", "MSOffice/Outlook",
            "MSOffice/PowerPoint",
            "SolidWorks/Drawings", "SolidWorks/Export", "SolidWorks/BOM",
            "SolidWorks/Performance/Assembly",
        ):
            assert c in paths, f"de-facto category {c!r} missing from catalog"

    def test_demo_reconciled_to_demos(self) -> None:
        # The drift was reconciled: 'Demos' is canonical, bare 'Demo' is not.
        cc._load_raw.cache_clear()
        paths = set(cc.canonical_paths())
        assert "Demos" in paths
        assert "Demo" not in paths

    def test_json_and_doc_are_consistent(self) -> None:
        # Documentation-first guard: every machine-readable category must appear
        # in the human-facing catalog doc (so the two can't silently drift).
        data = json.loads(
            (REPO / "scriptree" / "resources" / "category_catalog.json")
            .read_text(encoding="utf-8")
        )
        doc = (REPO / "docs" / "LLM" / "category_catalog.md").read_text(encoding="utf-8")
        missing = [c for c in data["categories"] if f"`{c}`" not in doc]
        assert not missing, f"{len(missing)} catalog categories absent from the doc, e.g. {missing[:5]}"


class TestNearestMatcher:
    POOL = ["Demos", "DevTools/Git", "SolidWorks/Drawings", "MSOffice/Word"]

    def test_case_difference(self) -> None:
        assert cc.nearest("devtools/git", self.POOL) == ("DevTools/Git", "case")

    def test_plural_difference(self) -> None:
        assert cc.nearest("Demo", self.POOL) == ("Demos", "plural")

    def test_typo(self) -> None:
        hit, reason = cc.nearest("SoldWorks/Drawings", self.POOL)
        assert hit == "SolidWorks/Drawings" and reason == "typo"

    def test_exact_match_is_not_a_suggestion(self) -> None:
        # An exact (byte-equal) hit is fine -> nothing to suggest.
        assert cc.nearest("Demos", self.POOL) == (None, None)

    def test_genuinely_new_category_no_match(self) -> None:
        assert cc.nearest("Robotics/ROS", self.POOL) == (None, None)


class TestLintCategory:
    def test_canonical_is_clean(self) -> None:
        cc._load_raw.cache_clear()
        assert cc.lint_category("MSOffice/Word") == []
        assert cc.lint_category("") == []  # uncategorised is fine

    def test_plural_drift_suggests_canonical(self) -> None:
        cc._load_raw.cache_clear()
        w = cc.lint_category("Demo")
        assert any("Demos" in line for line in w)

    def test_casing_drift_suggests_canonical(self) -> None:
        cc._load_raw.cache_clear()
        w = cc.lint_category("msoffice/word")
        assert any("MSOffice/Word" in line for line in w)

    def test_unknown_top_level_soft_warns(self) -> None:
        cc._load_raw.cache_clear()
        w = cc.lint_category("Frobnicator/Wizard")
        assert any("isn't in the canonical catalog" in line for line in w)

    def test_sibling_near_duplicate_warns(self) -> None:
        cc._load_raw.cache_clear()
        w = cc.lint_category("Demo", siblings=["Demos", "DevTools/Git"])
        assert any("sibling 'Demos'" in line for line in w)

    def test_no_double_warning_when_sibling_equals_canonical(self) -> None:
        # Demo, sibling Demos, canonical Demos -> ONE warning (sibling), not two.
        cc._load_raw.cache_clear()
        w = cc.lint_category("Demo", siblings=["Demos"])
        assert len(w) == 1
        assert "sibling 'Demos'" in w[0]


class TestValidateIntegration:
    def _write(self, d: Path, name: str, category: str) -> None:
        (d / name).write_text(
            json.dumps({
                "schema_version": 3, "name": name.split(".")[0],
                "executable": "echo", "category": category, "params": [],
            }),
            encoding="utf-8",
        )

    def test_validate_tree_flags_sibling_drift(self, tmp_path: Path, capsys) -> None:
        from scriptree.cli.validate import validate_tree
        self._write(tmp_path, "a.scriptree", "Demo")
        self._write(tmp_path, "b.scriptree", "Demos")
        self._write(tmp_path, "c.scriptree", "MSOffice/Word")  # clean canonical
        scanned, failed, warned = validate_tree(tmp_path)
        out = capsys.readouterr().out
        assert scanned == 3 and failed == 0
        assert "[WARN]" in out
        assert "consolidate to ONE spelling" in out
        # the clean canonical file must NOT trip a category warning
        assert "c.scriptree: category" not in out
