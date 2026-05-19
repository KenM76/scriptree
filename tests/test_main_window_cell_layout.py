"""Tests for V1 ``MainWindow``'s new File menu items: Save Cell
Layout, Save Cell Layout As, Open Cell Layout."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.io import save_tree  # noqa: E402
from scriptree.core.model import TreeDef, TreeNode  # noqa: E402
from scriptree.ui.main_window import MainWindow  # noqa: E402


# ---------------------------------------------------------------------------
# Menu items present
# ---------------------------------------------------------------------------

def test_file_menu_has_cell_layout_actions() -> None:
    """File menu should include Save / Save As / Open Cell Layout."""
    w = MainWindow()
    file_menu = w._m_file
    labels = [a.text() for a in file_menu.actions()]
    assert "Save Cell &Layout" in labels
    assert "Save Cell Layout &As..." in labels
    assert "Open Cell Layout..." in labels


def test_save_cell_layout_methods_exist() -> None:
    w = MainWindow()
    assert callable(w._save_cell_layout)
    assert callable(w._save_cell_layout_as)
    assert callable(w._write_single_hex_ring)
    assert callable(w._open_cell_layout)


# ---------------------------------------------------------------------------
# _write_single_hex_ring
# ---------------------------------------------------------------------------

def _seed_tree(tmp_path: Path) -> Path:
    """Create a real .scriptreetree on disk and load it into the
    main window's launcher so ``tree_file()`` returns it."""
    tree = TreeDef(name="DemoTree", nodes=[
        TreeNode(type="folder", name="Group", children=[]),
    ])
    p = tmp_path / "demo.scriptreetree"
    save_tree(tree, p)
    return p


def test_write_single_hex_ring_with_loaded_tree(tmp_path: Path) -> None:
    """When a tree is loaded, the ring should reference its absolute
    path in master.catalog_path."""
    w = MainWindow()
    tree_path = _seed_tree(tmp_path)
    w._launcher.load(str(tree_path))

    ring_path = tmp_path / "out.scriptreering"
    w._write_single_hex_ring(ring_path)

    assert ring_path.is_file()
    doc = json.loads(ring_path.read_text(encoding="utf-8"))
    assert doc["format"] == "scriptreering"
    assert doc["version"] == 1
    assert doc["master"]["role"] == "standalone"
    assert doc["master"]["catalog_path"] == str(tree_path.resolve())
    assert doc["members"] == []


def test_write_single_hex_ring_without_loaded_tree(tmp_path: Path) -> None:
    """No tree loaded → catalog_path is None (a blank starter cell)."""
    w = MainWindow()
    ring_path = tmp_path / "blank.scriptreering"
    w._write_single_hex_ring(ring_path)

    doc = json.loads(ring_path.read_text(encoding="utf-8"))
    assert doc["master"]["catalog_path"] is None


def test_write_single_hex_ring_creates_parent_dir(tmp_path: Path) -> None:
    """Writing to a nested path that doesn't exist yet should
    auto-create the parent directory."""
    w = MainWindow()
    nested = tmp_path / "subdir" / "deeper" / "ring.scriptreering"
    w._write_single_hex_ring(nested)
    assert nested.is_file()


# ---------------------------------------------------------------------------
# _save_cell_layout / _save_cell_layout_as
# ---------------------------------------------------------------------------

def test_save_cell_layout_calls_save_as_on_first_call(tmp_path: Path) -> None:
    """When ``_cell_layout_path`` isn't set, _save_cell_layout should
    delegate to _save_cell_layout_as (which prompts)."""
    w = MainWindow()
    with patch.object(w, "_save_cell_layout_as") as m:
        w._save_cell_layout()
    m.assert_called_once()


def test_save_cell_layout_writes_to_remembered_path(tmp_path: Path) -> None:
    """Once ``_cell_layout_path`` is remembered, _save_cell_layout
    should write directly without prompting."""
    w = MainWindow()
    target = tmp_path / "remembered.scriptreering"
    w._cell_layout_path = target
    with patch.object(w, "_save_cell_layout_as") as m_as:
        w._save_cell_layout()
    m_as.assert_not_called()
    assert target.is_file()


def test_save_cell_layout_as_appends_extension(tmp_path: Path) -> None:
    """If the user types a name without .scriptreering, the suffix
    should be added."""
    w = MainWindow()
    chosen = tmp_path / "noext"
    with patch(
        "PySide6.QtWidgets.QFileDialog.getSaveFileName",
        return_value=(str(chosen), ""),
    ):
        w._save_cell_layout_as()
    assert (tmp_path / "noext.scriptreering").is_file()
    assert w._cell_layout_path == tmp_path / "noext.scriptreering"


def test_save_cell_layout_as_cancelled_no_write(tmp_path: Path) -> None:
    """User cancels the file dialog → no file written, no path
    remembered."""
    w = MainWindow()
    with patch(
        "PySide6.QtWidgets.QFileDialog.getSaveFileName",
        return_value=("", ""),
    ):
        w._save_cell_layout_as()
    # No file in tmp_path.
    assert not list(tmp_path.glob("*.scriptreering"))
    assert getattr(w, "_cell_layout_path", None) is None


# ---------------------------------------------------------------------------
# _open_cell_layout
# ---------------------------------------------------------------------------

def test_open_cell_layout_spawns_subprocess(tmp_path: Path) -> None:
    """Opening a layout should fire-and-forget a subprocess pointing at
    run_scriptreering.bat (or .py / .sh)."""
    w = MainWindow()
    fake_layout = tmp_path / "layout.scriptreering"
    fake_layout.write_text(
        '{"format":"scriptreering","version":1,"master":{},"members":[]}',
        encoding="utf-8",
    )
    with patch(
        "PySide6.QtWidgets.QFileDialog.getOpenFileName",
        return_value=(str(fake_layout), ""),
    ), patch("subprocess.Popen") as m_popen:
        w._open_cell_layout()
    m_popen.assert_called_once()
    cmd = m_popen.call_args[0][0]
    # Last argv must be the picked layout file.
    assert cmd[-1] == str(fake_layout)
    # Launcher reference must be a run_scriptreering.{bat,sh,py}.
    launcher = cmd[0] if len(cmd) == 2 else cmd[1]
    assert "run_scriptreering" in launcher


def test_open_cell_layout_cancelled_no_spawn(tmp_path: Path) -> None:
    w = MainWindow()
    with patch(
        "PySide6.QtWidgets.QFileDialog.getOpenFileName",
        return_value=("", ""),
    ), patch("subprocess.Popen") as m_popen:
        w._open_cell_layout()
    m_popen.assert_not_called()
