"""Phase-1 regression suite for the ``.scriptreetree`` auto-discover
feature — model + I/O round-trip only.

The feature (introduced in v0.8.0a21) adds two optional fields to
``TreeDef``:

* ``auto_discover: TreeAutoDiscoverConfig | None`` — user-tunable
  discovery settings (which folders to scan, what update mode to
  apply, whether sibling sub-trees should be surfaced as
  candidates).  ``None`` carries the runtime meaning "user has
  never been asked" and triggers the one-shot
  ``ChooseUpdateModeDialog`` on first open.
* ``excluded: list[str]`` — paths the user has explicitly removed
  via the diff dialog; discovery still emits them so the dialog
  can route them to the "previously excluded" section.

These tests pin the on-disk contract for Phase 1.  Walker, diff,
add-to-tree logic, and dialog wiring all live in subsequent
phases and are tested separately.

The bar these tests set:

* A legacy ``.scriptreetree`` (no ``auto_discover``, no
  ``excluded``) loads as ``TreeDef(..., auto_discover=None,
  excluded=[])`` and re-saves byte-identically — pre-feature
  files are untouched.
* A configured tree round-trips losslessly: every field that
  differs from the default survives a save / load.
* A tree with the block present but every field defaulted
  round-trips with the block omitted from the JSON (we treat
  "default" as the same as "absent" on save to keep round-trip
  diffs minimal) — but the in-memory ``auto_discover`` is still
  a non-None instance for the loader that wrote it, so the
  "first open" path doesn't fire repeatedly.
* Malformed values (bogus ``update_mode``, non-list ``roots``,
  non-bool ``enabled``) coerce to safe defaults rather than
  raise, so a hand-edited file doesn't break tree loading.

Auto-dismisses ``QMessageBox`` per the standing rule.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)

from scriptree.core.discovery import TreeAutoDiscoverConfig
from scriptree.core.io import load_tree, save_tree, tree_from_dict, tree_to_dict
from scriptree.core.model import TreeDef, TreeNode


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _minimal_tree(name: str = "Test") -> TreeDef:
    """A ``TreeDef`` that exercises the leaf-and-folder shape so
    the round-trip tests also catch any accidental damage to the
    existing ``nodes`` serialisation while we touch the file."""
    return TreeDef(
        name=name,
        nodes=[
            TreeNode(type="folder", name="export", children=[
                TreeNode(type="leaf", path="./export/a.scriptree"),
                TreeNode(type="leaf", path="./export/b.scriptree"),
            ]),
            TreeNode(type="leaf", path="./top.scriptree"),
        ],
    )


# ----------------------------------------------------------------------------
# Defaults: a fresh TreeDef has no discovery config and no exclusions.
# ----------------------------------------------------------------------------


class TestDefaults:
    """The new fields default to None / [] so any code that
    constructs a TreeDef the old way keeps working."""

    def test_auto_discover_default_is_none(self) -> None:
        t = TreeDef(name="x")
        assert t.auto_discover is None, (
            "Fresh TreeDef.auto_discover must default to None; "
            "the runtime distinguishes None (\"never asked\") "
            "from a default-valued config (\"asked and chose "
            "defaults\")."
        )

    def test_excluded_default_is_empty_list(self) -> None:
        t = TreeDef(name="x")
        assert t.excluded == [], (
            "Fresh TreeDef.excluded must be an empty list, not "
            "None — downstream code iterates it without a guard."
        )

    def test_each_treedef_gets_its_own_excluded_list(self) -> None:
        """Catch a mutable-default-argument regression: two
        independent TreeDef instances must NOT share the same
        ``excluded`` list (would let exclusions on one tree leak
        into another)."""
        t1 = TreeDef(name="a")
        t2 = TreeDef(name="b")
        t1.excluded.append("./tool.scriptree")
        assert t2.excluded == [], (
            "TreeDef.excluded is shared between instances -- "
            "the ``field(default_factory=list)`` declaration was "
            "regressed to a bare ``[]`` default."
        )


# ----------------------------------------------------------------------------
# Legacy round-trip: a tree from before this feature must stay
# byte-identical after a load + save.
# ----------------------------------------------------------------------------


class TestLegacyRoundTrip:
    """A ``.scriptreetree`` file written before this feature must
    re-serialise byte-identical so deployed catalogs don't fill
    Git with no-op diffs on the next save."""

    def test_legacy_load_yields_none_auto_discover(
        self, tmp_path: Path,
    ) -> None:
        legacy_json = {
            "schema_version": 3,
            "name": "Legacy",
            "nodes": [
                {"type": "leaf", "path": "./a.scriptree"},
            ],
        }
        p = tmp_path / "legacy.scriptreetree"
        p.write_text(json.dumps(legacy_json, indent=2), encoding="utf-8")

        t = load_tree(p)
        assert t.auto_discover is None
        assert t.excluded == []

    def test_legacy_round_trip_byte_identical(
        self, tmp_path: Path,
    ) -> None:
        """Save → load → save must produce identical bytes when
        the original file had no discovery state.

        This is enforced because hundreds of catalogs in the
        wild predate this feature; tooling that bulk-loads and
        re-saves them (CI lint, future migration scripts)
        must not flip every file dirty."""
        legacy_json = {
            "schema_version": 3,
            "name": "Legacy",
            "nodes": [
                {"type": "folder", "name": "export", "children": [
                    {"type": "leaf", "path": "./export/a.scriptree"},
                ]},
                {"type": "leaf", "path": "./top.scriptree"},
            ],
        }
        original = json.dumps(legacy_json, indent=2)
        p = tmp_path / "legacy.scriptreetree"
        p.write_text(original, encoding="utf-8")

        t = load_tree(p)
        out = tmp_path / "round.scriptreetree"
        save_tree(t, out)
        assert out.read_text(encoding="utf-8") == original

    def test_default_valued_block_round_trips_as_present(
        self, tmp_path: Path,
    ) -> None:
        """A non-None ``auto_discover`` MUST emit a JSON key,
        even when every field equals the dataclass default.

        Rationale (v0.8.0a21+): the PRESENCE of the
        ``auto_discover`` key (even as the empty dict ``{}``)
        is the signal to the loader "the user has already been
        asked which mode to use; do NOT fire the first-load
        chooser again."

        An earlier design omitted the block when all-default
        for byte-identical round-trip elegance, but that meant a
        user who picked the default mode (``"prompt"``) on the
        chooser would be re-asked every load — the worst kind
        of "I already told you" UX.  See ``tree_to_dict``'s
        block comment for the trade-off discussion.
        """
        t = TreeDef(name="x", auto_discover=TreeAutoDiscoverConfig())
        d = tree_to_dict(t)
        assert "auto_discover" in d, (
            "Default-valued TreeAutoDiscoverConfig must emit "
            "an `auto_discover` JSON key (as `{}`) -- the key's "
            "presence is what tells the loader 'user has been "
            "asked, don't re-prompt'."
        )
        # The dict is empty because every field matched its default.
        assert d["auto_discover"] == {}


# ----------------------------------------------------------------------------
# Lossless round-trip for non-default configs.
# ----------------------------------------------------------------------------


class TestNonDefaultRoundTrip:
    """Any field of ``TreeAutoDiscoverConfig`` set to a
    non-default value must survive save → load → save."""

    @pytest.mark.parametrize(
        "field_name,non_default_value",
        [
            ("enabled", False),
            ("roots", ["./solidworks", "./outlook"]),
            ("include_sibling_trees", False),
            ("update_mode", "off"),
        ],
    )
    def test_each_field_survives_round_trip(
        self, tmp_path: Path, field_name: str, non_default_value: object,
    ) -> None:
        kwargs = {field_name: non_default_value}
        t = _minimal_tree()
        t.auto_discover = TreeAutoDiscoverConfig(**kwargs)  # type: ignore[arg-type]
        p = tmp_path / "t.scriptreetree"
        save_tree(t, p)

        loaded = load_tree(p)
        assert loaded.auto_discover is not None, (
            f"Round-trip dropped the auto_discover block when only "
            f"`{field_name}` differed from default."
        )
        assert getattr(loaded.auto_discover, field_name) == non_default_value

    def test_excluded_list_round_trips(self, tmp_path: Path) -> None:
        t = _minimal_tree()
        t.excluded = [
            "./export/old.scriptree",
            "./deprecated/never_again.scriptree",
        ]
        p = tmp_path / "t.scriptreetree"
        save_tree(t, p)

        loaded = load_tree(p)
        assert loaded.excluded == [
            "./export/old.scriptree",
            "./deprecated/never_again.scriptree",
        ]

    def test_empty_excluded_list_omitted_from_json(
        self, tmp_path: Path,
    ) -> None:
        """An empty ``excluded`` list must not emit the JSON key
        — preserves byte-identical round-trip for legacy files."""
        t = _minimal_tree()
        d = tree_to_dict(t)
        assert "excluded" not in d


# ----------------------------------------------------------------------------
# Robustness: malformed values fall back to safe defaults.
# ----------------------------------------------------------------------------


class TestMalformedTolerance:
    """A hand-edited file with bogus values for discovery fields
    must coerce to safe defaults rather than raise.  Tree loading
    is too important to gate on perfect JSON in this corner."""

    def test_bogus_update_mode_falls_back_to_off(self) -> None:
        d = {
            "schema_version": 3,
            "name": "x",
            "nodes": [],
            "auto_discover": {"update_mode": "BANANA"},
        }
        t = tree_from_dict(d)
        assert t.auto_discover is not None
        # We pick "off" (rather than "prompt") for safety: an
        # ambiguous edit shouldn't spring a surprise prompt on
        # the user when they next open the tree.
        assert t.auto_discover.update_mode == "off"

    def test_non_dict_auto_discover_falls_back_to_defaults(self) -> None:
        d = {
            "schema_version": 3,
            "name": "x",
            "nodes": [],
            "auto_discover": "this should be a dict",
        }
        t = tree_from_dict(d)
        assert t.auto_discover is not None
        assert t.auto_discover.enabled is True  # default
        assert t.auto_discover.update_mode == "prompt"  # default

    def test_null_auto_discover_yields_none(self) -> None:
        """Explicit JSON ``null`` is treated the same as the key
        being absent — both mean "first open should ask"."""
        d = {
            "schema_version": 3,
            "name": "x",
            "nodes": [],
            "auto_discover": None,
        }
        t = tree_from_dict(d)
        assert t.auto_discover is None

    def test_missing_roots_falls_back_to_dot(self) -> None:
        d = {
            "schema_version": 3,
            "name": "x",
            "nodes": [],
            "auto_discover": {"enabled": True},  # no roots key
        }
        t = tree_from_dict(d)
        assert t.auto_discover is not None
        assert t.auto_discover.roots == ["."]


# ----------------------------------------------------------------------------
# Cross-feature integrity: the new fields don't interfere with the
# existing serialisation (nodes, cell_*, path_prepend, etc.).
# ----------------------------------------------------------------------------


class TestCoexistence:
    """The new ``auto_discover`` + ``excluded`` fields must not
    perturb the existing serialisation of the rest of TreeDef."""

    def test_round_trip_with_everything_set(
        self, tmp_path: Path,
    ) -> None:
        t = TreeDef(
            name="Everything",
            nodes=[
                TreeNode(type="folder", name="exp", children=[
                    TreeNode(
                        type="leaf",
                        path="./exp/a.scriptree",
                        configuration="release",
                        display_name="A (release)",
                    ),
                ]),
            ],
            folder_layout="tabs",
            path_prepend=["./bin"],
            cell_icon="build",
            cell_text_label="ETool",
            cell_icon_scale=1.5,
            cell_text_over_icon=True,
            auto_discover=TreeAutoDiscoverConfig(
                enabled=True,
                roots=["./tools"],
                include_sibling_trees=False,
                update_mode="auto",
            ),
            excluded=["./skip.scriptree"],
        )
        p = tmp_path / "everything.scriptreetree"
        save_tree(t, p)
        loaded = load_tree(p)

        # Spot-check every group of fields survived.
        assert loaded.name == "Everything"
        assert len(loaded.nodes) == 1
        assert loaded.nodes[0].type == "folder"
        assert loaded.nodes[0].children[0].configuration == "release"
        assert loaded.folder_layout == "tabs"
        assert loaded.path_prepend == ["./bin"]
        assert loaded.cell_icon == "build"
        assert loaded.cell_text_over_icon is True
        assert loaded.cell_icon_scale == pytest.approx(1.5)
        assert loaded.auto_discover is not None
        assert loaded.auto_discover.roots == ["./tools"]
        assert loaded.auto_discover.include_sibling_trees is False
        assert loaded.auto_discover.update_mode == "auto"
        assert loaded.excluded == ["./skip.scriptree"]
