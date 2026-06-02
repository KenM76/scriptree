"""Round-trip tests for ``ToolDef.category`` and ``TreeDef.category``.

Phase 1 of the v0.8.0a25 auto-organise feature.  Pins:

* Empty category is omitted from JSON (legacy round-trip stays
  byte-identical).
* Set category round-trips verbatim.
* Loader sanitises malformed inputs (leading/trailing slashes,
  empty segments, non-string types).
* Loader is case-preserving but the bucket-level comparison done
  by ``group_by_category`` is case-insensitive (tested in the
  Phase 2 test file).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scriptree.core.io import (
    _normalise_category,
    tool_from_dict,
    tool_to_dict,
    tree_from_dict,
    tree_to_dict,
)
from scriptree.core.model import ToolDef, TreeDef, TreeNode


def _minimal_tool(**overrides) -> ToolDef:
    base = dict(name="X", executable="x.exe", argument_template=[])
    base.update(overrides)
    return ToolDef(**base)


def _minimal_tree(**overrides) -> TreeDef:
    base = dict(name="X", nodes=[])
    base.update(overrides)
    return TreeDef(**base)


# ---------------------------------------------------------------------------
# _normalise_category
# ---------------------------------------------------------------------------


class TestNormaliseCategory:
    def test_empty_string(self) -> None:
        assert _normalise_category("") == ""

    def test_none_returns_empty(self) -> None:
        assert _normalise_category(None) == ""

    def test_non_string_returns_empty(self) -> None:
        # A list (e.g. someone wrote ``"category": ["MSOffice", "Word"]``)
        # is treated as malformed, not crashed on.
        assert _normalise_category(["MSOffice", "Word"]) == ""

    def test_single_segment(self) -> None:
        assert _normalise_category("MSOffice") == "MSOffice"

    def test_multi_segment(self) -> None:
        assert _normalise_category("MSOffice/Word") == "MSOffice/Word"

    def test_leading_slash_stripped(self) -> None:
        assert _normalise_category("/MSOffice/Word") == "MSOffice/Word"

    def test_trailing_slash_stripped(self) -> None:
        assert _normalise_category("MSOffice/Word/") == "MSOffice/Word"

    def test_leading_and_trailing_slash_stripped(self) -> None:
        assert _normalise_category("/MSOffice/Word/") == "MSOffice/Word"

    def test_inner_whitespace_segments_trimmed(self) -> None:
        assert _normalise_category("MSOffice/ Word ") == "MSOffice/Word"

    def test_empty_segment_truncates(self) -> None:
        # "a//b" -> stop at the empty middle segment; everything past
        # is unreachable taxonomy.
        assert _normalise_category("MSOffice//Word") == "MSOffice"


# ---------------------------------------------------------------------------
# ToolDef round-trip
# ---------------------------------------------------------------------------


class TestToolDefRoundTrip:
    def test_empty_category_omitted(self) -> None:
        tool = _minimal_tool()
        d = tool_to_dict(tool)
        assert "category" not in d, (
            "Tools with no category must omit the field from JSON so "
            "legacy .scriptree files round-trip byte-identical."
        )

    def test_round_trip_preserves_category(self) -> None:
        tool = _minimal_tool(category="MSOffice/Word")
        d = tool_to_dict(tool)
        assert d["category"] == "MSOffice/Word"
        loaded = tool_from_dict(d)
        assert loaded.category == "MSOffice/Word"

    def test_loader_sanitises_malformed_category(self) -> None:
        # JSON with leading slash + trailing slash.
        d = {
            "name": "X",
            "executable": "x.exe",
            "argument_template": [],
            "category": "/MSOffice/Word/",
        }
        loaded = tool_from_dict(d)
        assert loaded.category == "MSOffice/Word"

    def test_loader_silently_drops_non_string_category(self) -> None:
        d = {
            "name": "X",
            "executable": "x.exe",
            "argument_template": [],
            "category": ["MSOffice", "Word"],  # malformed
        }
        loaded = tool_from_dict(d)
        assert loaded.category == ""


# ---------------------------------------------------------------------------
# TreeDef round-trip
# ---------------------------------------------------------------------------


class TestTreeDefRoundTrip:
    def test_empty_category_omitted(self) -> None:
        tree = _minimal_tree()
        d = tree_to_dict(tree)
        assert "category" not in d

    def test_round_trip_preserves_category(self) -> None:
        tree = _minimal_tree(category="MSOffice")
        d = tree_to_dict(tree)
        assert d["category"] == "MSOffice"
        loaded = tree_from_dict(d)
        assert loaded.category == "MSOffice"


# ---------------------------------------------------------------------------
# Legacy diff-clean guarantee.  A category-less tool that already
# exists in the wild must produce identical JSON before and after
# our load/save cycle so users don't see a noisy diff after
# upgrading.
# ---------------------------------------------------------------------------


class TestLegacyDiffClean:
    def test_legacy_tool_no_category_field(self, tmp_path: Path) -> None:
        original_json = {
            "name": "Demo",
            "executable": "demo.exe",
            "argument_template": [],
            "params": [],
        }
        tool = tool_from_dict(original_json)
        re_emitted = tool_to_dict(tool)
        assert "category" not in re_emitted, (
            "Legacy tool without category produced a category field on "
            "save -- this would dirty every legacy .scriptree the user "
            "touches in the editor."
        )

    def test_legacy_tree_no_category_field(self, tmp_path: Path) -> None:
        original_json = {
            "name": "DemoTree",
            "nodes": [],
        }
        tree = tree_from_dict(original_json)
        re_emitted = tree_to_dict(tree)
        assert "category" not in re_emitted
