"""v0.8.0a101 — per-forest 'fold single-item categories' toggle.

Default OFF keeps the "don't make a one-item folder" rule (a lone Media/ffmpeg
tool stays top-level); ON folds even a single-member category into its own
folder.  The toggle lives on AutoDiscoverConfig (travels with the forest file)
and drives ``group_by_category(min_items_to_synthesise=…)``.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.categorize import GroupCandidate, group_by_category  # noqa: E402
from scriptree.shell.forest_io import (  # noqa: E402
    AutoDiscoverConfig,
    ForestDef,
    load_forest,
    save_forest,
)


def test_fold_flag_default_false_and_round_trips(tmp_path: Path) -> None:
    assert AutoDiscoverConfig().fold_single_item_categories is False

    f = ForestDef(name="t",
                  auto_discover=AutoDiscoverConfig(
                      fold_single_item_categories=True))
    p = tmp_path / "x.scriptreeforest"
    save_forest(f, p)
    assert load_forest(p).auto_discover.fold_single_item_categories is True

    # A legacy forest file without the key loads as False.
    legacy = tmp_path / "legacy.scriptreeforest"
    legacy.write_text(json.dumps({
        "format": "scriptreeforest", "version": 1, "name": "L",
        "items": [], "excluded": [], "auto_discover": {"enabled": True},
    }), encoding="utf-8")
    assert load_forest(legacy).auto_discover.fold_single_item_categories is False


def test_single_item_category_threshold(tmp_path: Path) -> None:
    """The lever the toggle drives: min_items_to_synthesise 2 (default) passes a
    lone category through; 1 folds it."""
    cands = [GroupCandidate(
        path=str(tmp_path / "ffmpeg.scriptreetree"),
        category="Media/ffmpeg", display_name="ffmpeg toolkit")]

    out_default = group_by_category(
        cands, output_dir=tmp_path / "_g2", min_items_to_synthesise=2)
    assert all(o.kind == "passthrough" for o in out_default)  # stays top-level

    out_fold = group_by_category(
        cands, output_dir=tmp_path / "_g1", min_items_to_synthesise=1)
    assert any(o.kind == "synthesised" for o in out_fold)     # folded under Media
    synth = next(o for o in out_fold if o.kind == "synthesised")
    assert Path(synth.path).name.lower().startswith("media")
