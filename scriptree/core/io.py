"""JSON serialization for .scriptree and .scriptreetree files.

Kept separate from model.py so tests can build dataclasses without
touching the filesystem, and so a future schema migration layer has a
natural home.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import (
    SCHEMA_VERSION,
    MenuItemDef,
    ParamDef,
    ParamType,
    ParseSource,
    Section,
    ToolDef,
    TreeDef,
    TreeNode,
    Widget,
)


# --- ToolDef (.scriptree) --------------------------------------------------

def tool_to_dict(tool: ToolDef) -> dict[str, Any]:
    d: dict[str, Any] = {
        "schema_version": tool.schema_version,
        "name": tool.name,
        "description": tool.description,
        "executable": tool.executable,
        "working_directory": tool.working_directory,
        "argument_template": [
            list(entry) if isinstance(entry, list) else entry
            for entry in tool.argument_template
        ],
        "params": [_param_to_dict(p) for p in tool.params],
        "source": {
            "mode": tool.source.mode,
            "help_text_cached": tool.source.help_text_cached,
        },
    }
    # Sections are only emitted when non-empty, so a legacy flat tool
    # round-trips into the same compact JSON it was loaded from.
    # Each section carries its own ``layout`` field; the old tool-level
    # ``section_layout`` is no longer written.
    if tool.sections:
        sec_list: list[dict[str, Any]] = []
        for s in tool.sections:
            sd: dict[str, Any] = {"name": s.name, "collapsed": s.collapsed}
            if s.layout != "collapse":
                sd["layout"] = s.layout
            sec_list.append(sd)
        d["sections"] = sec_list
    # Env + path_prepend are only emitted when non-empty — same compact-
    # round-trip rule as sections. Legacy v1/v2 files without these
    # fields load cleanly with empty defaults.
    if tool.env:
        d["env"] = dict(tool.env)
    if tool.path_prepend:
        d["path_prepend"] = list(tool.path_prepend)
    if tool.menus:
        d["menus"] = [_menu_item_to_dict(m) for m in tool.menus]
    return d


def _load_template(raw: Any) -> list:
    if not isinstance(raw, list):
        return []
    out: list = []
    for entry in raw:
        if isinstance(entry, list):
            # Token group — every element must be a string.
            out.append([str(x) for x in entry])
        else:
            out.append(str(entry))
    return out


def _menu_item_to_dict(m: MenuItemDef) -> dict[str, Any]:
    d: dict[str, Any] = {"label": m.label}
    if m.menu:
        d["menu"] = m.menu
    if m.command:
        d["command"] = m.command
    if m.shortcut:
        d["shortcut"] = m.shortcut
    if m.tooltip:
        d["tooltip"] = m.tooltip
    if m.children:
        d["children"] = [_menu_item_to_dict(c) for c in m.children]
    return d


def _menu_item_from_dict(raw: dict[str, Any]) -> MenuItemDef:
    return MenuItemDef(
        label=str(raw.get("label", "")),
        menu=str(raw.get("menu", "")),
        command=str(raw.get("command", "")),
        shortcut=str(raw.get("shortcut", "")),
        tooltip=str(raw.get("tooltip", "")),
        children=[
            _menu_item_from_dict(c)
            for c in (raw.get("children") or [])
        ],
    )


def _load_menus(raw: Any) -> list[MenuItemDef]:
    if not isinstance(raw, list):
        return []
    return [_menu_item_from_dict(m) for m in raw if isinstance(m, dict)]


def tool_from_dict(data: dict[str, Any]) -> ToolDef:
    _check_schema(data)
    src = data.get("source") or {}
    # Legacy files may have a tool-level ``section_layout`` instead of
    # per-section ``layout``.  Apply the tool-level default to any
    # section that doesn't declare its own layout.
    legacy_layout = str(data.get("section_layout", "collapse"))
    # Map legacy "tabs" value to per-section "tab" (singular).
    if legacy_layout == "tabs":
        legacy_layout = "tab"
    raw_sections = data.get("sections") or []
    sections = [
        Section(
            name=str(s.get("name", "")),
            collapsed=bool(s.get("collapsed", False)),
            layout=str(s.get("layout", legacy_layout)),
        )
        for s in raw_sections
    ]
    return ToolDef(
        name=data["name"],
        executable=data["executable"],
        argument_template=_load_template(data.get("argument_template", [])),
        params=[_param_from_dict(p) for p in data.get("params", [])],
        description=data.get("description", ""),
        working_directory=data.get("working_directory"),
        source=ParseSource(
            mode=src.get("mode", "manual"),
            help_text_cached=src.get("help_text_cached"),
        ),
        sections=sections,
        section_layout=legacy_layout,
        env={
            str(k): str(v) for k, v in (data.get("env") or {}).items()
        },
        path_prepend=[str(p) for p in (data.get("path_prepend") or [])],
        menus=_load_menus(data.get("menus")),
        schema_version=data.get("schema_version", SCHEMA_VERSION),
    )


def save_tool(tool: ToolDef, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(tool_to_dict(tool), indent=2), encoding="utf-8"
    )
    # Update the in-memory tool to remember where it now lives — so
    # subsequent relative-path resolution uses the current file
    # location (important for Save As).
    tool.loaded_from = str(Path(path).resolve())


def load_tool(path: str | Path) -> ToolDef:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tool = tool_from_dict(data)
    # Remember where we loaded from so relative paths in the tool
    # definition can be resolved against this file's directory at
    # run time, regardless of where the process was launched from.
    tool.loaded_from = str(Path(path).resolve())
    return tool


def _param_to_dict(p: ParamDef) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": p.id,
        "label": p.label,
        "description": p.description,
        "type": p.type.value,
        "widget": p.widget.value,
        "required": p.required,
        "default": p.default,
    }
    if p.choices:
        d["choices"] = list(p.choices)
    # Only emit choice_labels when at least one entry is non-empty —
    # legacy tools without explicit labels round-trip unchanged.
    if any(p.choice_labels):
        d["choice_labels"] = list(p.choice_labels)
    if p.file_filter:
        d["file_filter"] = p.file_filter
    if p.section:
        d["section"] = p.section
    if p.no_persist:
        d["no_persist"] = True
    if p.no_split:
        d["no_split"] = True
    return d


def _normalize_choices(
    raw_choices: list[Any],
    raw_labels: list[str],
) -> tuple[list[str], list[str]]:
    """Accept both flat strings and ``[value, label]`` pairs.

    Some external tooling writes choices as::

        "choices": [["0", "Millimeters"], ["1", "Centimeters"]]

    Our canonical form uses two parallel lists (``choices`` +
    ``choice_labels``).  This helper normalises both styles into the
    canonical pair so the rest of the codebase can stay simple.
    """
    if not raw_choices:
        return [], list(raw_labels)

    # Detect the [value, label] pair format: every entry is a 2-element
    # list/tuple whose first element is a string.
    if all(
        isinstance(c, (list, tuple)) and len(c) == 2 and isinstance(c[0], str)
        for c in raw_choices
    ):
        values = [str(c[0]) for c in raw_choices]
        labels = [str(c[1]) for c in raw_choices]
        return values, labels

    # Already flat strings (the normal path).
    return [str(c) for c in raw_choices], list(raw_labels)


def _param_from_dict(d: dict[str, Any]) -> ParamDef:
    choices, choice_labels = _normalize_choices(
        d.get("choices", []),
        d.get("choice_labels", []),
    )
    return ParamDef(
        id=d["id"],
        label=d.get("label", ""),
        description=d.get("description", ""),
        type=ParamType(d.get("type", "string")),
        widget=Widget(d.get("widget", "text")),
        required=d.get("required", False),
        default=d.get("default", ""),
        choices=choices,
        choice_labels=choice_labels,
        file_filter=d.get("file_filter", ""),
        section=d.get("section", ""),
        no_persist=bool(d.get("no_persist", False)),
        no_split=bool(d.get("no_split", False)),
    )


# --- TreeDef (.scriptreetree) ----------------------------------------------

def tree_to_dict(tree: TreeDef) -> dict[str, Any]:
    d: dict[str, Any] = {
        "schema_version": tree.schema_version,
        "name": tree.name,
        "nodes": [_node_to_dict(n) for n in tree.nodes],
    }
    if tree.menus:
        d["menus"] = [_menu_item_to_dict(m) for m in tree.menus]
    return d


def tree_from_dict(data: dict[str, Any]) -> TreeDef:
    _check_schema(data)
    return TreeDef(
        name=data["name"],
        nodes=[_node_from_dict(n) for n in data.get("nodes", [])],
        menus=_load_menus(data.get("menus")),
        schema_version=data.get("schema_version", SCHEMA_VERSION),
    )


def save_tree(tree: TreeDef, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(tree_to_dict(tree), indent=2), encoding="utf-8"
    )


def load_tree(path: str | Path) -> TreeDef:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return tree_from_dict(data)


def collect_scriptreetree_refs(
    tree: TreeDef,
    tree_file: str | Path,
) -> list[str]:
    """Return resolved absolute paths of all .scriptreetree files referenced
    by leaf nodes in *tree*.

    Used for circular-reference detection: before adding a subtree
    reference, callers can check whether the new path would create a
    cycle.
    """
    base = Path(tree_file).resolve().parent
    refs: list[str] = []

    def _walk(nodes: list[TreeNode]) -> None:
        for n in nodes:
            if n.type == "leaf" and n.path and n.path.lower().endswith(
                ".scriptreetree"
            ):
                p = Path(n.path)
                resolved = str(
                    (base / p).resolve() if not p.is_absolute() else p.resolve()
                )
                refs.append(resolved)
            if n.children:
                _walk(n.children)

    _walk(tree.nodes)
    return refs


def check_circular_tree_refs(
    root_path: str | Path,
    *,
    _seen: set[str] | None = None,
) -> list[str] | None:
    """Walk .scriptreetree references starting at *root_path*.

    Returns ``None`` if no cycle is detected. If a cycle exists,
    returns the chain of paths forming the cycle (for diagnostics).

    This does **not** raise — the caller decides how to surface the
    error (GUI warning, exception, etc.).
    """
    root = str(Path(root_path).resolve())
    if _seen is None:
        _seen = set()
    if root in _seen:
        return [root]
    _seen.add(root)
    try:
        tree = load_tree(root_path)
    except Exception:  # noqa: BLE001
        return None  # can't load → can't check, but not a cycle
    refs = collect_scriptreetree_refs(tree, root_path)
    for ref in refs:
        cycle = check_circular_tree_refs(ref, _seen=_seen)
        if cycle is not None:
            return [root] + cycle
    _seen.discard(root)
    return None


def _node_to_dict(n: TreeNode) -> dict[str, Any]:
    if n.type == "leaf":
        d: dict[str, Any] = {"type": "leaf", "path": n.path}
        if n.configuration is not None:
            d["configuration"] = n.configuration
        if n.display_name is not None:
            d["display_name"] = n.display_name
        return d
    folder: dict[str, Any] = {
        "type": "folder",
        "name": n.name,
        "children": [_node_to_dict(c) for c in n.children],
    }
    if n.display_name is not None:
        folder["display_name"] = n.display_name
    return folder


def _node_from_dict(d: dict[str, Any]) -> TreeNode:
    if d.get("type") == "leaf":
        return TreeNode(
            type="leaf",
            path=d["path"],
            configuration=d.get("configuration"),
            display_name=d.get("display_name"),
        )
    return TreeNode(
        type="folder",
        name=d.get("name", ""),
        children=[_node_from_dict(c) for c in d.get("children", [])],
        display_name=d.get("display_name"),
    )


# --- internal --------------------------------------------------------------

def _check_schema(data: dict[str, Any]) -> None:
    v = data.get("schema_version", SCHEMA_VERSION)
    if v > SCHEMA_VERSION:
        raise ValueError(
            f"File has schema_version {v}, this build only understands "
            f"up to {SCHEMA_VERSION}. Upgrade ScripTree."
        )
