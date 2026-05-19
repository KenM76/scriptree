"""JSON serialization for .scriptree and .scriptreetree files.

## For humans

Turns the dataclasses in ``model.py`` into JSON on disk and back.
``load_tool`` / ``save_tool`` for ``.scriptree`` tools,
``load_tree`` / ``save_tree`` for ``.scriptreetree`` catalogs.
Kept separate from ``model.py`` so models stay IO-free and a schema
migration layer has a home.

## For maintainers / LLMs

Invariants & edit-safety:

* **Loader fails loud on structural errors.** ``_check_schema``
  hard-rejects files whose ``schema_version`` is below
  ``model.SCHEMA_VERSION`` (points the user at ``scriptree
  migrate``).  ``_param_from_dict`` → ``ParamDef(...)`` lets
  ``__post_init__`` raise on a bad widget/type or provider config.
  ``tool_from_dict`` additionally runs ``provider_run_order`` to
  reject ``depends_on`` cycles / unknown ids at load.  This
  "broken file => exception, not silent best-effort" stance is
  what ``scriptree validate`` depends on.
* **Writer compactness is a contract.** ``_param_to_dict`` /
  ``_provider_to_dict`` OMIT any field that's at its default so a
  file authored before a feature existed round-trips byte-
  identical.  When you add a ``ParamDef`` field, add a matching
  "emit only if non-default" guard here or you'll churn every
  existing file on first save.
* ``_enum_from_str`` is the difflib-hint path (``'int'`` → "did
  you mean 'integer'?").  Keep its message format stable —
  ``validate``/tests assert substrings of it.
* ``_normalize_choices`` accepts the legacy ``[[value,label],…]``
  pair form for back-compat but the canonical on-disk form is two
  parallel flat lists; don't "simplify" it away.
* ``save_tool`` sets ``tool.loaded_from`` so later relative-path
  resolution (executable / provider command / working_directory)
  anchors to the file's dir, not the process CWD.  Tools that
  break when "moved" are usually a ``loaded_from`` regression.
* ``.scriptreering`` / ``.scriptreeforest`` are NOT handled here —
  they have their own ``shell/ring_io.py`` / ``shell/forest_io.py``
  with independent ``version`` keys under a ``format`` field.
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
    ProviderSpec,
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
    # Cell-shell visual settings (V3, optional).  Each emitted only
    # when set so legacy tools round-trip byte-identical.  A "cell"
    # sub-object groups them so the top-level ToolDef JSON stays
    # uncluttered for the common case where no cell metadata exists.
    cell_d: dict[str, Any] = {}
    if tool.cell_icon:
        cell_d["icon"] = tool.cell_icon
    if tool.cell_icon_data:
        cell_d["icon_data"] = tool.cell_icon_data
    if tool.cell_icon_format:
        cell_d["icon_format"] = tool.cell_icon_format
    if tool.cell_text_label:
        cell_d["text_label"] = tool.cell_text_label
    if tool.cell_icon_scale != 1.0:
        cell_d["icon_scale"] = float(tool.cell_icon_scale)
    if tool.cell_label_opacity != 1.0:
        cell_d["label_opacity"] = float(tool.cell_label_opacity)
    # Superimpose text over icon (V3 v0.6.9+).  Emitted only when
    # True so pre-v0.6.9 catalogs round-trip byte-identical.
    if tool.cell_text_over_icon:
        cell_d["text_over_icon"] = True
    # Cell click action (V3 v0.3.5+).  Emitted only when off the
    # default ("menu") so legacy tools round-trip byte-identical.
    if tool.cell_click_action and tool.cell_click_action != "menu":
        cell_d["click_action"] = str(tool.cell_click_action)
    if (
        tool.cell_click_run_mode
        and tool.cell_click_run_mode != "sequential"
    ):
        cell_d["click_run_mode"] = str(tool.cell_click_run_mode)
    # Cell fill colour (V3 v0.3.6+).  Empty string is the default
    # (branding fill) and stays out of the JSON for byte-identical
    # round-trip with legacy catalogs.
    if tool.cell_fill_color:
        cell_d["fill_color"] = str(tool.cell_fill_color)
    # Cell text colour (V3 v0.3.8+).  Same default-omit rule.
    if tool.cell_text_color:
        cell_d["text_color"] = str(tool.cell_text_color)
    if cell_d:
        d["cell"] = cell_d
    # Interactive stdin (V3 v0.3.0) — emitted only when True so legacy
    # tools round-trip byte-identical.
    if tool.interactive:
        d["interactive"] = True
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
    # Cell-shell visual settings: live under a "cell" sub-object so
    # the top-level JSON stays uncluttered for tools that don't have
    # any.  Missing object → default field values (all empty / 1.0).
    cell_d = data.get("cell") or {}
    if not isinstance(cell_d, dict):
        cell_d = {}

    def _cell_float(key: str, default: float) -> float:
        try:
            return float(cell_d.get(key, default))
        except (TypeError, ValueError):
            return default

    params = [_param_from_dict(p) for p in data.get("params", [])]
    # v0.6.0 — validate the depends_on dependency graph at load time.
    # An unknown depends_on id or a cycle is a structural authoring
    # bug → fail loud here, the same fail-at-load stance the schema
    # takes for a bad widget/type pairing.  Runtime provider
    # *execution* failures still fail soft (see core/providers.py).
    if any(getattr(p, "choices_provider", None) is not None
           for p in params):
        from .providers import provider_run_order
        provider_run_order(params)  # raises ValueError on cycle / bad id

    return ToolDef(
        name=data["name"],
        executable=data["executable"],
        argument_template=_load_template(data.get("argument_template", [])),
        params=params,
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
        cell_icon=str(cell_d.get("icon", "")),
        cell_icon_data=str(cell_d.get("icon_data", "")),
        cell_icon_format=str(cell_d.get("icon_format", "")),
        cell_text_label=str(cell_d.get("text_label", "")),
        cell_icon_scale=_cell_float("icon_scale", 1.0),
        cell_label_opacity=_cell_float("label_opacity", 1.0),
        cell_text_over_icon=bool(cell_d.get("text_over_icon", False)),
        cell_click_action=str(cell_d.get("click_action", "menu")),
        cell_click_run_mode=str(cell_d.get("click_run_mode", "sequential")),
        cell_fill_color=str(cell_d.get("fill_color", "")),
        cell_text_color=str(cell_d.get("text_color", "")),
        interactive=bool(data.get("interactive", False)),
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
    # V0.4.0 — emit only when non-empty so legacy tools without
    # visible_when / required_when round-trip byte-identical.
    if p.visible_when:
        d["visible_when"] = p.visible_when
    if p.required_when:
        d["required_when"] = p.required_when
    # v0.6.0 — dynamic providers.  Same compactness rule: emit only
    # when set so a v3 file authored before this feature round-trips
    # byte-identical.
    if p.choices_provider is not None:
        d["choices_provider"] = _provider_to_dict(p.choices_provider)
    if p.depends_on:
        d["depends_on"] = list(p.depends_on)
    if p.select_all:
        d["select_all"] = True
    return d


def _provider_to_dict(ps: ProviderSpec) -> dict[str, Any]:
    """Serialise a :class:`ProviderSpec`.  ``command`` is always
    emitted (required); the rest only when not at their defaults so
    the JSON stays minimal."""
    d: dict[str, Any] = {"command": list(ps.command)}
    if ps.working_directory:
        d["working_directory"] = ps.working_directory
    if ps.refresh != "on_open":
        d["refresh"] = ps.refresh
    if ps.timeout_sec != 15:
        d["timeout_sec"] = ps.timeout_sec
    if ps.cache != "form_session":
        d["cache"] = ps.cache
    return d


def _provider_from_dict(
    raw: Any, *, param_id: str,
) -> ProviderSpec | None:
    """Parse a ``choices_provider`` block.  ``None`` / missing →
    ``None`` (static behaviour).  A malformed block raises
    ``ValueError`` (structural authoring bug → fail loud at load,
    same stance as a bad widget/type pairing)."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(
            f"ParamDef {param_id!r}: 'choices_provider' must be an "
            f"object, got {type(raw).__name__}."
        )
    try:
        return ProviderSpec(
            command=list(raw.get("command", [])),
            working_directory=raw.get("working_directory") or None,
            refresh=str(raw.get("refresh", "on_open")),
            timeout_sec=raw.get("timeout_sec", 15),
            cache=str(raw.get("cache", "form_session")),
        )
    except ValueError as exc:
        # Re-raise with the param id so the author can find it.
        raise ValueError(
            f"ParamDef {param_id!r}: invalid 'choices_provider' — "
            f"{exc}"
        ) from None


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


def _enum_from_str(
    enum_cls: type,
    raw: str,
    *,
    field_name: str,
    param_id: str,
) -> Any:
    """Coerce a JSON string to an enum value with a helpful error.

    v0.5.0 — replaces the bare ``ParamType(raw)`` / ``Widget(raw)``
    calls in ``_param_from_dict``.  When ``raw`` isn't a member of
    the enum, raise a ``ValueError`` whose message includes:
      * the offending value,
      * the offending field name (``type`` / ``widget``),
      * the param id (so the user can find the broken entry),
      * a ``Did you mean '<closest>'?`` hint (via difflib), and
      * the full list of valid values.

    Diagnosis goes from "what does that mean?" to "oh, typo" in
    seconds.
    """
    try:
        return enum_cls(raw)
    except ValueError:
        import difflib
        valid = [member.value for member in enum_cls]
        closest = difflib.get_close_matches(raw, valid, n=1)
        hint = f" Did you mean '{closest[0]}'?" if closest else ""
        raise ValueError(
            f"{raw!r} is not a valid {field_name} for param "
            f"{param_id!r}.{hint}\n"
            f"Valid {field_name}s: {', '.join(valid)}."
        ) from None


def _param_from_dict(d: dict[str, Any]) -> ParamDef:
    choices, choice_labels = _normalize_choices(
        d.get("choices", []),
        d.get("choice_labels", []),
    )
    param_id = d.get("id", "<unknown>")
    return ParamDef(
        id=d["id"],
        label=d.get("label", ""),
        description=d.get("description", ""),
        type=_enum_from_str(
            ParamType, d.get("type", "string"),
            field_name="type", param_id=param_id,
        ),
        widget=_enum_from_str(
            Widget, d.get("widget", "text"),
            field_name="widget", param_id=param_id,
        ),
        required=d.get("required", False),
        default=d.get("default", ""),
        choices=choices,
        choice_labels=choice_labels,
        file_filter=d.get("file_filter", ""),
        section=d.get("section", ""),
        no_persist=bool(d.get("no_persist", False)),
        no_split=bool(d.get("no_split", False)),
        visible_when=str(d.get("visible_when", "") or ""),
        required_when=str(d.get("required_when", "") or ""),
        choices_provider=_provider_from_dict(
            d.get("choices_provider"), param_id=param_id,
        ),
        depends_on=[str(x) for x in (d.get("depends_on") or [])],
        select_all=bool(d.get("select_all", False)),
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
    # Only emit folder_layout when it's the non-default ("tabs") so
    # existing flat-mode trees stay byte-identical on save.
    if tree.folder_layout and tree.folder_layout != "flat":
        d["folder_layout"] = tree.folder_layout
    # Only emit path_prepend when non-empty — preserves byte-identical
    # JSON for trees that don't use it.
    if tree.path_prepend:
        d["path_prepend"] = list(tree.path_prepend)
    # Cell-shell visual settings — same shape as ToolDef.cell_*
    # (grouped under a "cell" sub-object, omitted when all-default
    # so legacy trees stay byte-identical).
    cell_d: dict[str, Any] = {}
    if tree.cell_icon:
        cell_d["icon"] = tree.cell_icon
    if tree.cell_icon_data:
        cell_d["icon_data"] = tree.cell_icon_data
    if tree.cell_icon_format:
        cell_d["icon_format"] = tree.cell_icon_format
    if tree.cell_text_label:
        cell_d["text_label"] = tree.cell_text_label
    if tree.cell_icon_scale != 1.0:
        cell_d["icon_scale"] = float(tree.cell_icon_scale)
    if tree.cell_label_opacity != 1.0:
        cell_d["label_opacity"] = float(tree.cell_label_opacity)
    # Superimpose text over icon (V3 v0.6.9+).  Emitted only when
    # True so pre-v0.6.9 trees round-trip byte-identical.
    if tree.cell_text_over_icon:
        cell_d["text_over_icon"] = True
    # Cell click action (V3 v0.3.5+).  Same default-omit rule as
    # ToolDef so legacy trees round-trip byte-identical.
    if tree.cell_click_action and tree.cell_click_action != "menu":
        cell_d["click_action"] = str(tree.cell_click_action)
    if (
        tree.cell_click_run_mode
        and tree.cell_click_run_mode != "sequential"
    ):
        cell_d["click_run_mode"] = str(tree.cell_click_run_mode)
    # Cell fill colour (V3 v0.3.6+).  Same default-omit rule.
    if tree.cell_fill_color:
        cell_d["fill_color"] = str(tree.cell_fill_color)
    # Cell text colour (V3 v0.3.8+).  Same default-omit rule.
    if tree.cell_text_color:
        cell_d["text_color"] = str(tree.cell_text_color)
    if cell_d:
        d["cell"] = cell_d
    return d


def tree_from_dict(data: dict[str, Any]) -> TreeDef:
    _check_schema(data)
    cell_d = data.get("cell") or {}
    if not isinstance(cell_d, dict):
        cell_d = {}

    def _cell_float(key: str, default: float) -> float:
        try:
            return float(cell_d.get(key, default))
        except (TypeError, ValueError):
            return default

    return TreeDef(
        name=data["name"],
        nodes=[_node_from_dict(n) for n in data.get("nodes", [])],
        menus=_load_menus(data.get("menus")),
        folder_layout=data.get("folder_layout", "flat"),
        path_prepend=list(data.get("path_prepend", [])),
        cell_icon=str(cell_d.get("icon", "")),
        cell_icon_data=str(cell_d.get("icon_data", "")),
        cell_icon_format=str(cell_d.get("icon_format", "")),
        cell_text_label=str(cell_d.get("text_label", "")),
        cell_icon_scale=_cell_float("icon_scale", 1.0),
        cell_label_opacity=_cell_float("label_opacity", 1.0),
        cell_text_over_icon=bool(cell_d.get("text_over_icon", False)),
        cell_click_action=str(cell_d.get("click_action", "menu")),
        cell_click_run_mode=str(cell_d.get("click_run_mode", "sequential")),
        cell_fill_color=str(cell_d.get("fill_color", "")),
        cell_text_color=str(cell_d.get("text_color", "")),
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
    # v0.5.0 hard-break: refuse to load v2 files.  The 0.3.x/0.4.x
    # vocabulary (``bool`` / ``float`` / ``file_open`` / ``file_save``
    # / ``enum_radio``) was renamed in v3 to align with JSON Schema +
    # HTML5; mixed-vocabulary loading was rejected in favour of a
    # clean break + migration script.
    if v < SCHEMA_VERSION:
        raise ValueError(
            f"File uses schema_version {v}, but this ScripTree is "
            f"version {SCHEMA_VERSION}.\n"
            f"Run `scriptree migrate <path>` (or "
            f"`scriptree migrate <dir>` for a whole tree) to upgrade.\n"
            f"See help/LLM/scriptree_format.md for the rename map."
        )
