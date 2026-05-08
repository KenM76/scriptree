"""ToolDef ``interactive`` flag — load / save round-trip tests."""
from __future__ import annotations

import json
from pathlib import Path

from scriptree.core.io import load_tool, save_tool, tool_from_dict, tool_to_dict
from scriptree.core.model import ToolDef


def test_default_interactive_false() -> None:
    t = ToolDef(name="x", executable="python")
    assert t.interactive is False


def test_to_dict_omits_field_when_default() -> None:
    """Legacy tools must round-trip byte-identical: the field is
    only emitted when True."""
    t = ToolDef(name="x", executable="python")
    d = tool_to_dict(t)
    assert "interactive" not in d


def test_to_dict_emits_when_true() -> None:
    t = ToolDef(name="x", executable="python", interactive=True)
    d = tool_to_dict(t)
    assert d.get("interactive") is True


def test_from_dict_defaults_false_when_absent() -> None:
    t = tool_from_dict({"name": "x", "executable": "python"})
    assert t.interactive is False


def test_from_dict_reads_true() -> None:
    t = tool_from_dict({
        "name": "x", "executable": "python", "interactive": True,
    })
    assert t.interactive is True


def test_save_load_roundtrip_preserves_true(tmp_path: Path) -> None:
    p = tmp_path / "demo.scriptree"
    save_tool(ToolDef(name="x", executable="python", interactive=True), p)
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["interactive"] is True
    loaded = load_tool(p)
    assert loaded.interactive is True


def test_save_load_roundtrip_preserves_false_byte_identical(
    tmp_path: Path,
) -> None:
    """A False round-trip must NOT add the field to disk — that
    would break byte-equivalence with v0.2.x .scriptree files."""
    p = tmp_path / "demo.scriptree"
    save_tool(ToolDef(name="x", executable="python", interactive=False), p)
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert "interactive" not in on_disk


def test_legacy_truthy_values_coerced_to_bool(tmp_path: Path) -> None:
    """Defensive: hand-edited files might write ``"true"`` (string),
    ``1``, etc.  Loader must coerce to bool."""
    for raw_value, expected in [
        (True, True), (False, False),
        (1, True), (0, False),
        ("yes", True), ("", False),
    ]:
        t = tool_from_dict({
            "name": "x", "executable": "python",
            "interactive": raw_value,
        })
        assert isinstance(t.interactive, bool)
        assert t.interactive is expected, (raw_value, t.interactive)
