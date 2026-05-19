"""Regression tests for the v0.6.3 bug-audit fixes.

One test per behaviourally-checkable finding so a future change
that reintroduces the bug fails loudly. (Purely cosmetic / Windows-
only-syscall fixes — L1/H1 cmdline+handle, L6 dead-log — are covered
by code review + the full suite, not unit tests here.)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


# --- M1: migrate must never force-DOWNGRADE a newer file -------------------

def test_migrate_does_not_downgrade_future_version(tmp_path: Path) -> None:
    from scriptree.cli.migrate import migrate_one
    p = tmp_path / "future.scriptree"
    p.write_text(json.dumps({
        "schema_version": 4, "name": "X", "executable": "echo",
        "params": [],
    }), encoding="utf-8")
    changed = migrate_one(p)
    assert changed is False
    assert json.loads(p.read_text())["schema_version"] == 4


def test_migrate_still_upgrades_old(tmp_path: Path) -> None:
    from scriptree.cli.migrate import migrate_one
    p = tmp_path / "old.scriptree"
    p.write_text(json.dumps({
        "schema_version": 2, "name": "X", "executable": "echo",
        "params": [{"id": "a", "label": "A", "type": "bool",
                    "widget": "checkbox"}],
    }), encoding="utf-8")
    assert migrate_one(p) is True
    d = json.loads(p.read_text())
    assert d["schema_version"] == 3
    assert d["params"][0]["type"] == "boolean"


# --- M2: atomic write — no temp residue, content intact -------------------

def test_migrate_atomic_write_leaves_no_temp(tmp_path: Path) -> None:
    from scriptree.cli.migrate import migrate_one
    p = tmp_path / "t.scriptree"
    p.write_text(json.dumps({
        "schema_version": 2, "name": "X", "executable": "echo",
        "params": [],
    }), encoding="utf-8")
    migrate_one(p)
    leftovers = [f for f in tmp_path.iterdir()
                 if f.name != "t.scriptree"]
    assert leftovers == [], f"temp residue: {leftovers}"
    assert json.loads(p.read_text())["schema_version"] == 3


# --- L11: single_instance extension parse (dot-in-directory) --------------

def test_messages_from_argv_dot_in_dir(tmp_path: Path) -> None:
    from scriptree.shell.single_instance import messages_from_argv
    # A real .scriptreering whose parent dir name contains a dot.
    d = tmp_path / "my.dir"
    d.mkdir()
    ring = d / "layout.scriptreering"
    ring.write_text("{}", encoding="utf-8")
    msgs = messages_from_argv(["prog", str(ring)])
    assert any(m.get("command") == "load_ring" for m in msgs), msgs


def test_messages_from_argv_extensionless_not_misread(
    tmp_path: Path,
) -> None:
    from scriptree.shell.single_instance import messages_from_argv
    # Path with a dot in a directory but NO file extension must NOT
    # be parsed as a ring/catalog.
    d = tmp_path / "v1.2"
    d.mkdir()
    f = d / "ring"          # no extension
    f.write_text("{}", encoding="utf-8")
    msgs = messages_from_argv(["prog", str(f)])
    assert not any(
        m.get("command") in ("load_ring", "load_catalog")
        for m in msgs
    ), msgs


# --- L18: empty provider result → visible (no items) + signal -------------

def test_dropdown_set_choices_empty_disables_and_signals() -> None:
    from scriptree.ui.widgets.param_widgets import DropdownWidget
    from scriptree.core.model import ParamDef, ParamType, Widget
    p = ParamDef(id="x", type=ParamType.ENUM, widget=Widget.DROPDOWN,
                 choices=["a", "b"])
    w = DropdownWidget(p)
    w.set_value("a")
    fired: list = []
    w.valueChanged.connect(lambda v: fired.append(v))
    w.set_choices([], [], None)
    assert w._combo.isEnabled() is False
    assert w._combo.itemText(0) == "(no items)"
    assert w.get_value() == ""
    assert fired, "valueChanged must fire when choices empty out"


# --- M7: tree-config editor OK must not write when read-only --------------

def test_tree_config_editor_readonly_ok_no_write(tmp_path: Path) -> None:
    from scriptree.core.io import save_tree
    from scriptree.core.model import TreeDef, TreeNode
    from scriptree.ui.tree_config_editor import TreeConfigEditorDialog

    tool = tmp_path / "a.scriptree"
    tool.write_text(json.dumps({
        "schema_version": 3, "name": "a", "executable": "echo",
        "params": [],
    }), encoding="utf-8")
    treep = tmp_path / "t.scriptreetree"
    tree = TreeDef(name="T", nodes=[
        TreeNode(type="leaf", path="./a.scriptree")])
    save_tree(tree, str(treep))

    sidecar = tmp_path / "t.scriptreetree.configs.json"
    before = sidecar.exists()
    dlg = TreeConfigEditorDialog(str(treep), tree, read_only=True)
    dlg._on_accept()
    # Read-only ⇒ OK must not have created/modified the sidecar.
    assert sidecar.exists() == before


# --- H2: closeEvent honours the editor dirty-guard ------------------------

def test_close_event_prompts_on_dirty_editor(
    tmp_path: Path, monkeypatch,
) -> None:
    from scriptree.ui.main_window import MainWindow
    from scriptree.core.io import load_tool

    p = tmp_path / "x.scriptree"
    p.write_text(json.dumps({
        "schema_version": 3, "name": "X", "executable": "echo",
        "params": [],
    }), encoding="utf-8")

    w = MainWindow()
    w._show_editor(load_tool(str(p)), str(p))
    assert w._active_editor is not None
    w._active_editor._tool.description = "dirty now"
    assert w._active_editor.is_dirty() is True

    called: list = []

    def fake_question(*a, **k):
        called.append(a)
        from PySide6.QtWidgets import QMessageBox
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(
        "scriptree.ui.main_window.QMessageBox.question", fake_question
    )

    class _Ev:
        def __init__(self):
            self.ignored = False
        def ignore(self):
            self.ignored = True
        def accept(self):
            pass

    ev = _Ev()
    w.closeEvent(ev)
    # Dirty editor + Cancel ⇒ the guard ran and close was vetoed.
    assert called, "closeEvent did not consult the editor dirty guard"
    assert ev.ignored is True
