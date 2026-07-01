"""v0.8.0a97 — single File→Open with all ScripTree types incl. forests.

Covers the consolidated open filter (tool/tree/forest in one dropdown), the
extension routing in ``_load_file_into_ui``, and ``_open_forest`` building a
viewable merged tree from a forest's saved members.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.io import save_tool, save_tree  # noqa: E402
from scriptree.core.model import ToolDef, TreeDef, TreeNode  # noqa: E402
from scriptree.ui.main_window import MainWindow  # noqa: E402


def _seed_tool(tmp_path: Path, name: str = "demo") -> Path:
    p = tmp_path / f"{name}.scriptree"
    save_tool(ToolDef(name=name, executable="python"), p)
    return p


def _seed_forest(tmp_path: Path) -> Path:
    """A .scriptreeforest referencing one loose tool + one tree member."""
    tool = _seed_tool(tmp_path, "loose")
    leaf = _seed_tool(tmp_path, "inner")
    tree = tmp_path / "suite.scriptreetree"
    save_tree(
        TreeDef(name="Suite",
                nodes=[TreeNode(type="leaf", name="inner", path=str(leaf))]),
        tree,
    )
    forest = {
        "format": "scriptreeforest", "version": 1, "name": "F",
        "items": [
            {"path": str(tool), "kind": "tool"},
            {"path": str(tree), "kind": "tree"},
        ],
        "excluded": [], "auto_discover": {"enabled": True},
    }
    fp = tmp_path / "ws.scriptreeforest"
    fp.write_text(json.dumps(forest), encoding="utf-8")
    return fp


def test_open_filters_include_all_types() -> None:
    f = MainWindow._OPEN_FILTERS
    assert "*.scriptree" in f
    assert "*.scriptreetree" in f
    assert "*.scriptreeforest" in f  # forests are openable now


def test_load_file_into_ui_routes_forest_to_open_forest(tmp_path: Path) -> None:
    w = MainWindow()
    fp = _seed_forest(tmp_path)
    with patch.object(w, "_open_forest") as m:
        w._load_file_into_ui(str(fp))
    m.assert_called_once_with(str(fp))


def test_open_forest_builds_merged_and_loads(tmp_path: Path) -> None:
    w = MainWindow()
    w._confirm_discard_tree = lambda: True  # no modal in the test
    fp = _seed_forest(tmp_path)
    w._open_forest(str(fp))
    # The launcher now has a (merged temp) tree loaded with the members under
    # the a96 root row.
    assert w._launcher.tree_file() is not None
    root = w._launcher._tree_widget.topLevelItem(0)
    assert root is not None
    assert root.childCount() >= 1


def test_open_forest_with_no_members_warns_and_loads_nothing(
    tmp_path: Path, monkeypatch,
) -> None:
    from scriptree.ui import main_window as mw
    monkeypatch.setattr(mw.QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))
    w = MainWindow()
    w._confirm_discard_tree = lambda: True
    forest = {"format": "scriptreeforest", "version": 1, "name": "E",
              "items": [], "excluded": [], "auto_discover": {}}
    fp = tmp_path / "empty.scriptreeforest"
    fp.write_text(json.dumps(forest), encoding="utf-8")
    before = w._launcher.tree_file()
    w._open_forest(str(fp))
    assert w._launcher.tree_file() == before  # nothing loaded
