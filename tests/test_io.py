"""Round-trip tests for scriptree.core.io."""
from __future__ import annotations

from pathlib import Path

from scriptree.core.io import (
    load_tool,
    load_tree,
    save_tool,
    save_tree,
    tool_from_dict,
    tool_to_dict,
    tree_from_dict,
    tree_to_dict,
)
from scriptree.core.model import (
    ParamDef,
    ParamType,
    ParseSource,
    ToolDef,
    TreeDef,
    TreeNode,
    Widget,
)


def _sample_tool() -> ToolDef:
    return ToolDef(
        name="sw_bridge list-components",
        executable="C:/sw_bridge/bin/sw_bridge.exe",
        description="List all components in a SolidWorks assembly.",
        argument_template=["list-components", "{title}", "{output}"],
        params=[
            ParamDef(
                id="title",
                label="Assembly title fragment",
                type=ParamType.STRING,
                widget=Widget.TEXT,
                required=True,
            ),
            ParamDef(
                id="output",
                label="Output file",
                type=ParamType.PATH,
                widget=Widget.FILE_SAVE,
                required=True,
                file_filter="Text (*.txt);;All (*)",
            ),
        ],
        source=ParseSource(mode="manual"),
    )


class TestToolRoundTrip:
    def test_dict_round_trip(self) -> None:
        original = _sample_tool()
        restored = tool_from_dict(tool_to_dict(original))
        assert restored.name == original.name
        assert restored.executable == original.executable
        assert len(restored.params) == 2
        assert restored.params[1].file_filter == "Text (*.txt);;All (*)"
        assert restored.argument_template == original.argument_template
        assert restored.source.mode == "manual"

    def test_file_round_trip(self, tmp_path: Path) -> None:
        original = _sample_tool()
        path = tmp_path / "sample.scriptree"
        save_tool(original, path)
        restored = load_tool(path)
        assert tool_to_dict(restored) == tool_to_dict(original)

    def test_preserves_help_text_cache(self) -> None:
        tool = _sample_tool()
        tool.source = ParseSource(mode="argparse", help_text_cached="usage: foo")
        restored = tool_from_dict(tool_to_dict(tool))
        assert restored.source.mode == "argparse"
        assert restored.source.help_text_cached == "usage: foo"

    def test_no_split_round_trip(self) -> None:
        """The per-param no_split flag survives serialization."""
        from scriptree.core.model import ParamDef, ParamType, ToolDef

        tool = ToolDef(
            name="t",
            executable="t.exe",
            params=[
                ParamDef(id="a", type=ParamType.STRING, no_split=False),
                ParamDef(id="b", type=ParamType.STRING, no_split=True),
            ],
        )
        d = tool_to_dict(tool)
        # Default-False is omitted from the on-disk form (matches the
        # convention used for other boolean flags like required /
        # no_persist) — only True writes a key.
        assert "no_split" not in d["params"][0]
        assert d["params"][1]["no_split"] is True
        restored = tool_from_dict(d)
        assert restored.params[0].no_split is False
        assert restored.params[1].no_split is True


class TestTreeRoundTrip:
    def _sample_tree(self) -> TreeDef:
        return TreeDef(
            name="SolidWorks toolkit",
            nodes=[
                TreeNode(
                    type="folder",
                    name="sw_bridge",
                    children=[
                        TreeNode(type="leaf", path="./sw_bridge/list-components.scriptree"),
                        TreeNode(type="leaf", path="./sw_bridge/compare-hardware.scriptree"),
                    ],
                ),
                TreeNode(type="leaf", path="./SwApiTrainingGen.scriptree"),
            ],
        )

    def test_dict_round_trip(self) -> None:
        original = self._sample_tree()
        restored = tree_from_dict(tree_to_dict(original))
        assert restored.name == original.name
        assert len(restored.nodes) == 2
        assert restored.nodes[0].type == "folder"
        assert len(restored.nodes[0].children) == 2
        assert restored.nodes[1].type == "leaf"

    def test_file_round_trip(self, tmp_path: Path) -> None:
        original = self._sample_tree()
        path = tmp_path / "toolkit.scriptreetree"
        save_tree(original, path)
        restored = load_tree(path)
        assert tree_to_dict(restored) == tree_to_dict(original)

    def test_leaf_configuration_round_trips(self) -> None:
        tree = TreeDef(
            name="test",
            nodes=[
                TreeNode(
                    type="leaf",
                    path="./tool.scriptree",
                    configuration="standalone",
                ),
                TreeNode(type="leaf", path="./other.scriptree"),
            ],
        )
        d = tree_to_dict(tree)
        # Only the first leaf should have a configuration key.
        assert d["nodes"][0]["configuration"] == "standalone"
        assert "configuration" not in d["nodes"][1]
        # Round-trip.
        restored = tree_from_dict(d)
        assert restored.nodes[0].configuration == "standalone"
        assert restored.nodes[1].configuration is None
