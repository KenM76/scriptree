"""v0.8.0a98 — discovery must never re-ingest its own synthesised `_groups`
output.  This is the lasting fix for the reorganize duplicate/circular bug:
``_groups/`` sits under the personal-apps scan root, so without an explicit
skip the walker re-discovers ``MSOffice.scriptreetree`` and the next synth pass
emits a duplicate ``MSOffice__auto.scriptreetree``.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.shell import forest_discover as fd  # noqa: E402
from scriptree.shell.forest_discover import discover  # noqa: E402


def test_is_skipped_dir() -> None:
    assert fd._is_skipped_dir("_groups")
    assert fd._is_skipped_dir(".git")
    assert not fd._is_skipped_dir("MSOffice")
    assert not fd._is_skipped_dir("ffmpeg")


def test_discover_skips_synthesised_groups_dir(tmp_path: Path) -> None:
    root = tmp_path / "Apps"
    # A real tool under a category folder — MUST be discovered.
    (root / "MSOffice" / "Word").mkdir(parents=True)
    (root / "MSOffice" / "Word" / "tool.scriptree").write_text("{}", encoding="utf-8")
    # Synthesised group trees under _groups — must NOT be discovered (else the
    # next synth pass dups them).
    (root / "_groups").mkdir(parents=True)
    (root / "_groups" / "MSOffice.scriptreetree").write_text("{}", encoding="utf-8")
    (root / "_groups" / "MSOffice__auto.scriptreetree").write_text("{}", encoding="utf-8")

    items = discover([str(root)])
    names = [Path(i.path).name for i in items]

    assert "tool.scriptree" in names                      # real tool surfaces
    assert "MSOffice.scriptreetree" not in names          # synth output skipped
    assert "MSOffice__auto.scriptreetree" not in names
    assert not any(
        "_groups" in str(i.path).replace("\\", "/").lower() for i in items
    )


def test_existing_tree_names_excludes_groups(tmp_path: Path) -> None:
    """_existing_tree_names must not count synthesised _groups trees, or the
    synth pass renames its own fresh output to <name>__auto.

    The method only reads ``self.forest.auto_discover.roots``, so we call it on
    a tiny stub rather than constructing a full (Qt-heavy) ForestController.
    """
    from scriptree.shell.forest_controller import ForestController
    from scriptree.shell.forest_io import AutoDiscoverConfig, ForestDef

    root = tmp_path / "Apps"
    (root / "MSOffice").mkdir(parents=True)
    # a user-authored tree (counts) + a synthesised one under _groups (excluded)
    (root / "MSOffice" / "Suite.scriptreetree").write_text("{}", encoding="utf-8")
    (root / "_groups").mkdir(parents=True)
    (root / "_groups" / "MSOffice.scriptreetree").write_text("{}", encoding="utf-8")

    class _Stub:
        pass
    stub = _Stub()
    stub.forest = ForestDef(
        name="t", items=[],
        auto_discover=AutoDiscoverConfig(roots=[str(root)]),
    )
    names = ForestController._existing_tree_names(stub)
    assert "Suite" in names           # user-authored counts
    assert "MSOffice" not in names     # synthesised _groups tree excluded
