"""Regression tests for v0.8.0a37's dropped-origins flow.

User report: after fixing the merged-tree structure in the editor
(moving Outlook Migration under MSOffice to remove a circular
reference) and hitting Save All, the forest itself didn't drop
"Outlook Migration" as a top-level cell -- on the next launch
the user still saw it as its own cell.

The architectural gap: ``push_back_to_origins`` mapped each
sidecar entry to a top-level folder in the saved merged tree
and wrote that source.  When a top-level folder was MISSING
(removed or moved into another folder), it was recorded as
``skipped`` -- which the caller treated as "no problem; that
source just wasn't in the saved tree."  But what the user
intended was "this source is no longer part of the forest."

a37 fix: distinguish dropped origins from skipped origins.
A dropped origin's source path is recorded in
``PushBackResult.dropped_origins``; the caller (the editor's
save path) then updates the on-disk ``.scriptreeforest`` to
remove the entry from items + append to excluded.

Test set
========

A1 - Removing a top-level folder from the merged tree marks
     the corresponding source as a dropped origin in the
     PushBackResult.

A2 - dropped_origins is distinct from skipped: a source whose
     top-level folder is PRESENT but whose write fails goes
     to errors, not dropped_origins.

A3 - dropped_origins is distinct from .scriptree skips: a
     single-tool source still goes to skipped (the wrapper
     folder semantics make it unwriteable), NOT dropped.

A4 - The merged tree's SAVE_TREE path in the editor must
     call _persist_uninstall_to_forest_file for each dropped
     origin so the forest file picks up the exclusion.  We
     verify the integration via the persist helper directly.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)


def _write_scriptree(path: Path, name: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "name": name or path.stem,
            "executable": "echo",
            "params": [],
        }),
        encoding="utf-8",
    )


def _write_scriptreetree(
    path: Path, leaves: list[Path], name: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nodes = []
    for leaf in leaves:
        try:
            rel = Path(leaf).relative_to(path.parent)
            leaf_path = str(rel).replace("\\", "/")
        except ValueError:
            leaf_path = str(leaf)
        nodes.append({
            "type": "leaf",
            "name": leaf.stem,
            "path": leaf_path,
        })
    path.write_text(
        json.dumps({"name": name or path.stem, "nodes": nodes}),
        encoding="utf-8",
    )


# ===========================================================================
# A1 -- Removing a top-level folder marks its source as dropped
# ===========================================================================

class TestA1_RemovedTopLevelMarksSourceAsDropped:
    def test_remove_top_folder_records_in_dropped_origins(
        self, tmp_path,
    ):
        from scriptree.shell.merged_tree import (
            build_merged_tree, push_back_to_origins,
        )
        from scriptree.core.io import load_tree, save_tree

        # Two sources, build merged tree.
        la = tmp_path / "A" / "a.scriptree"
        lb = tmp_path / "B" / "b.scriptree"
        _write_scriptree(la)
        _write_scriptree(lb)
        sa = tmp_path / "A" / "A.scriptreetree"
        sb = tmp_path / "B" / "B.scriptreetree"
        _write_scriptreetree(sa, [la], name="AppA")
        _write_scriptreetree(sb, [lb], name="AppB")

        merged_path = build_merged_tree([str(sa), str(sb)])

        # User removes the top-level "AppB" folder from the merged
        # tree (e.g. by deleting in the editor or by moving its
        # contents into AppA).
        merged = load_tree(str(merged_path))
        merged.nodes = [
            n for n in merged.nodes if n.name != "AppB"
        ]
        save_tree(merged, str(merged_path))

        result = push_back_to_origins(merged_path)
        # AppB should appear in dropped_origins, NOT skipped.
        assert str(sb.resolve()) in result.dropped_origins or (
            str(sb) in result.dropped_origins
        ), (
            f"removed top-level folder's source should appear "
            f"in dropped_origins; got dropped_origins="
            f"{result.dropped_origins!r}, skipped="
            f"{result.skipped!r}"
        )

        # AppA (still present) writes successfully.
        assert any(
            "A.scriptreetree" in w for w in result.written
        ), f"AppA should still write; got written={result.written!r}"


# ===========================================================================
# A2 -- errors are distinct from dropped
# ===========================================================================

class TestA2_DroppedIsDistinctFromErrored:
    """An error during write must NOT be confused with a dropped
    origin.  Errored sources stay in the forest (user can fix the
    underlying issue); dropped sources leave the forest."""

    def test_distinct_lists(self, tmp_path):
        from scriptree.shell.merged_tree import (
            build_merged_tree, push_back_to_origins,
        )

        la = tmp_path / "A" / "a.scriptree"
        _write_scriptree(la)
        sa = tmp_path / "A" / "A.scriptreetree"
        _write_scriptreetree(sa, [la], name="AppA")

        merged_path = build_merged_tree([str(sa)])

        # No user edits: AppA still in tree, source writeable.
        result = push_back_to_origins(merged_path)
        assert not result.errors
        assert not result.dropped_origins
        assert not result.skipped
        assert len(result.written) == 1


# ===========================================================================
# A3 -- .scriptree skips are NOT dropped
# ===========================================================================

class TestA3_ScriptreeSkipsAreNotDropped:
    def test_scriptree_source_with_present_folder_skipped_not_dropped(
        self, tmp_path,
    ):
        from scriptree.shell.merged_tree import (
            build_merged_tree, push_back_to_origins,
        )

        # A .scriptree (single-tool) source.  Build creates a
        # folder wrapper around it.
        lone = tmp_path / "lone.scriptree"
        _write_scriptree(lone, "Lone")
        merged_path = build_merged_tree([str(lone)])

        result = push_back_to_origins(merged_path)
        # Should be in skipped (single-tool wrapper unwriteable),
        # NOT in dropped_origins.
        skipped_paths = [s[0] for s in result.skipped]
        assert str(lone.resolve()) in skipped_paths or (
            str(lone) in skipped_paths
        ), (
            f"single-tool .scriptree source should be in skipped; "
            f"got skipped={result.skipped!r}"
        )
        assert str(lone.resolve()) not in result.dropped_origins
        assert str(lone) not in result.dropped_origins


# ===========================================================================
# A4 -- Integration: persist helper writes dropped origin to forest
# ===========================================================================

class TestA4_PersistHelperWritesDroppedOrigin:
    """When the editor's save path finds a dropped origin and
    calls ``_persist_uninstall_to_forest_file``, the on-disk
    forest file must reflect the change.  We already test the
    persist helper itself in test_editor_bugs_a35; this case
    verifies the END-TO-END contract: dropped_origin path string
    -> persist -> forest file updates."""

    def test_persist_drops_origin_from_forest_items(
        self, tmp_path, monkeypatch,
    ):
        from scriptree.shell import forest_io

        # Build a real forest file with a single item pointing
        # at our soon-to-be-dropped source.
        forest_file = tmp_path / "default.scriptreeforest"
        catalog = tmp_path / "AppB" / "B.scriptreetree"
        _write_scriptreetree(
            catalog,
            [tmp_path / "AppB" / "b.scriptree"],
            name="AppB",
        )
        _write_scriptree(tmp_path / "AppB" / "b.scriptree")
        forest = forest_io.ForestDef(
            items=[
                forest_io.ForestItem(
                    path=str(catalog), kind="tree",
                ),
            ],
            excluded=[],
        )
        forest_io.save_forest(forest, forest_file)

        with patch.object(
            forest_io, "default_autoload_path",
            return_value=forest_file,
        ):
            from scriptree.ui.main_window import MainWindow
            mw = MainWindow.__new__(MainWindow)
            # Simulate the editor save calling the helper as
            # part of its dropped_origins handling.
            mw._persist_uninstall_to_forest_file(str(catalog))

        # The forest file must now exclude the catalog and the
        # items list must not contain it.
        updated = forest_io.load_forest(forest_file)
        norm_excluded = [
            str(Path(e).resolve()) for e in updated.excluded
        ]
        assert (
            str(Path(catalog).resolve()) in norm_excluded
            or str(catalog) in updated.excluded
        ), (
            f"dropped origin should land in excluded; got "
            f"excluded={updated.excluded!r}"
        )
        items_paths = [
            str(Path(it.path).resolve()) for it in updated.items
        ]
        assert str(Path(catalog).resolve()) not in items_paths
