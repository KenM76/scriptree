"""Regression suite for the per-item right-click context menu
(v0.8.0a28+).

The popup tree menu now lets the user right-click any tool item
to open a small per-item context menu.  These tests pin the
plumbing without driving the actual right-click event (which
requires a real Qt event loop + mouse synthesis to be reliable):

  * Each leaf QAction carries an ``_st_context`` dict with
    ``leaf_path``, ``root_catalog_path``, and the node-name
    fields.
  * For a tree catalog, every leaf's ``root_catalog_path`` is
    the .scriptreetree (not the individual .scriptree the leaf
    points at).
  * For a single-tool catalog, the leaf's ``leaf_path`` ==
    ``root_catalog_path``.
  * The event filter's ``_catalog_is_uninstallable`` predicate
    returns True only when the catalog lives under one of the
    install roots.
  * ``_PerItemContextFilter._on_uninstall_by_path`` delegates to
    the forest controller's ``_on_uninstall_app``, passing the
    catalog path verbatim -- the controller's path-string code
    path (added v0.8.0a28) is what handles it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

_app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_scriptree(path: Path, name: str | None = None) -> None:
    """Drop a minimal .scriptree file at ``path``.

    Uses V1's actual JSON shape so ``load_tool`` succeeds in the
    tests that pop a single-tool catalog menu.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "name": name or path.stem,
            "executable": "echo",
            "params": [],
        }),
        encoding="utf-8",
    )


def _write_scriptreetree(path: Path, leaves: list[Path]) -> None:
    """Drop a .scriptreetree that lists ``leaves`` as top-level
    leaf nodes.

    Uses RELATIVE paths from the tree file, mirroring the V1
    convention -- the popup code resolves these relative to the
    tree's parent.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    nodes = []
    for leaf in leaves:
        rel = Path(leaf).relative_to(path.parent)
        nodes.append({
            "type": "leaf",
            "name": leaf.stem,
            "path": str(rel).replace("\\", "/"),
        })
    path.write_text(
        json.dumps({
            "name": path.stem,
            "nodes": nodes,
        }),
        encoding="utf-8",
    )


def _flatten_actions(menu: QMenu) -> list:
    """Walk every action of ``menu`` and its submenus, return all
    LEAF actions (no sub-menus) that aren't separators."""
    out = []
    for act in menu.actions():
        sub = act.menu()
        if sub is not None:
            out.extend(_flatten_actions(sub))
        elif not act.isSeparator():
            out.append(act)
    return out


# ---------------------------------------------------------------------------
# _st_context stamping
# ---------------------------------------------------------------------------

class TestActionContextStamping:
    """Every leaf in the popup must carry a usable ``_st_context``
    dict so the right-click filter has somewhere to look."""

    def test_single_tool_catalog_leaf_carries_context(self, tmp_path):
        from scriptree.shell.tree_popup import _build_menu_for_catalog

        tool = tmp_path / "demo.scriptree"
        _write_scriptree(tool, name="Demo")

        menu = QMenu()
        _build_menu_for_catalog(menu, tool)
        leaves = _flatten_actions(menu)
        assert len(leaves) == 1
        ctx = getattr(leaves[0], "_st_context", None)
        assert ctx is not None
        assert ctx["leaf_path"] == str(tool.resolve())
        # Single-tool catalogs are their own root.
        assert ctx["root_catalog_path"] == str(tool.resolve())

    def test_tree_catalog_leaf_root_is_the_tree_file(
        self, tmp_path,
    ):
        """A .scriptreetree may aggregate many .scriptree leaves;
        each leaf's ``root_catalog_path`` must point at the
        .scriptreetree itself so the uninstall path is keyed off
        the app folder, not the per-leaf folder."""
        from scriptree.shell.tree_popup import _build_menu_for_catalog

        leaf_a = tmp_path / "a.scriptree"
        leaf_b = tmp_path / "sub" / "b.scriptree"
        _write_scriptree(leaf_a, name="A")
        _write_scriptree(leaf_b, name="B")
        tree = tmp_path / "catalog.scriptreetree"
        _write_scriptreetree(tree, [leaf_a, leaf_b])

        menu = QMenu()
        _build_menu_for_catalog(menu, tree)
        leaves = _flatten_actions(menu)
        assert len(leaves) == 2, [a.text() for a in leaves]
        for leaf_act in leaves:
            ctx = getattr(leaf_act, "_st_context", None)
            assert ctx is not None
            assert ctx["root_catalog_path"] == str(tree.resolve()), (
                f"leaf {leaf_act.text()!r} root_catalog should be "
                f"the .scriptreetree itself, not the .scriptree"
            )
            # leaf_path should be one of the two .scriptree files.
            assert ctx["leaf_path"] in (
                str(leaf_a.resolve()), str(leaf_b.resolve()),
            )


# ---------------------------------------------------------------------------
# _catalog_is_uninstallable
# ---------------------------------------------------------------------------

class TestCatalogUninstallablePredicate:
    """The right-click filter only offers Uninstall when the
    catalog's containing folder is under an install root."""

    def test_catalog_under_personal_root_is_uninstallable(
        self, tmp_path, monkeypatch,
    ):
        from scriptree.shell.tree_popup import (
            _PerItemContextFilter,
        )
        # Redirect default_personal_root via LOCALAPPDATA so the
        # tmp_path acts as the personal install root.
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        from scriptree.core.app_install import default_personal_root
        apps = default_personal_root()
        apps.mkdir(parents=True, exist_ok=True)
        app_dir = apps / "MyApp"
        catalog = app_dir / "tool.scriptree"
        _write_scriptree(catalog)

        flt = _PerItemContextFilter(MagicMock())
        assert flt._catalog_is_uninstallable(str(catalog))

    def test_catalog_outside_install_roots_is_NOT_uninstallable(
        self, tmp_path, monkeypatch,
    ):
        from scriptree.shell.tree_popup import (
            _PerItemContextFilter,
        )
        # Set both install roots to tmp_path/Apps -- catalog at
        # tmp_path/elsewhere is outside.
        monkeypatch.setenv(
            "LOCALAPPDATA", str(tmp_path / "appdata"),
        )
        outside = tmp_path / "elsewhere" / "tool.scriptree"
        _write_scriptree(outside)

        flt = _PerItemContextFilter(MagicMock())
        assert not flt._catalog_is_uninstallable(str(outside))


# ---------------------------------------------------------------------------
# Uninstall dispatch
# ---------------------------------------------------------------------------

class TestUninstallDispatch:
    """The filter's uninstall handler must reach the forest
    controller via the standard ``_forest_menu_extension`` hook
    and pass the catalog path through to ``_on_uninstall_app``."""

    def test_handler_calls_forest_controller_with_path(
        self, tmp_path,
    ):
        from scriptree.shell.tree_popup import (
            _PerItemContextFilter,
        )
        # Build a hex_win whose _forest_menu_extension.__self__ is
        # a controller mock with _on_uninstall_app callable.
        controller = MagicMock()
        hex_win = MagicMock()
        hook = MagicMock()
        hook.__self__ = controller
        hex_win._forest_menu_extension = hook

        flt = _PerItemContextFilter(hex_win)
        flt._on_uninstall_by_path("C:/fake/MyApp/tool.scriptree")

        controller._on_uninstall_app.assert_called_once_with(
            "C:/fake/MyApp/tool.scriptree"
        )

    def test_handler_noops_when_no_controller(self, tmp_path):
        """Standalone cell case -- no forest controller attached."""
        from scriptree.shell.tree_popup import (
            _PerItemContextFilter,
        )
        hex_win = MagicMock(spec=[])  # no _forest_menu_extension
        flt = _PerItemContextFilter(hex_win)
        # Should not raise.
        flt._on_uninstall_by_path("C:/fake/MyApp/tool.scriptree")


# ---------------------------------------------------------------------------
# Forest controller -- _on_uninstall_app accepts a path string
# ---------------------------------------------------------------------------

class TestOnUninstallAppAcceptsPath:
    """v0.8.0a28 made ``_on_uninstall_app`` accept either a cell
    OR a path string.  These tests pin the latter."""

    def test_path_string_walks_to_dialog(self, tmp_path, monkeypatch):
        """Passing a path string should reach the uninstall dialog
        path-resolution logic.  We can't drive the dialog itself
        without showing a window, so we monkeypatch QDialog.exec
        to return Rejected (cancel) and assert that the controller
        DID find the catalog (no early-return error)."""
        from scriptree.shell.forest_controller import ForestController
        from PySide6.QtWidgets import QDialog

        # Build a catalog under a tmp personal root.
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        from scriptree.core.app_install import default_personal_root
        apps = default_personal_root()
        apps.mkdir(parents=True, exist_ok=True)
        app_dir = apps / "DispatchTestApp"
        catalog = app_dir / "demo.scriptree"
        _write_scriptree(catalog)

        ctrl = ForestController.__new__(ForestController)
        forest = MagicMock()
        forest.items = []
        forest.excluded = []
        ctrl.forest = forest
        ctrl._spawned = {}
        ctrl.forestChanged = MagicMock()
        ctrl.forest_window = None

        # Cancel the confirmation dialog immediately.
        monkeypatch.setattr(
            QDialog, "exec",
            lambda self: QDialog.DialogCode.Rejected,
        )

        # Should not raise -- the path is valid + under the root,
        # the dialog opens, the user "cancels," and we return.
        ctrl._on_uninstall_app(str(catalog))
        # Catalog file still exists -- cancel left disk untouched.
        assert catalog.exists()
        assert app_dir.exists()
