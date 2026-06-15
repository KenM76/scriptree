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

from .discovery import TreeAutoDiscoverConfig
from .model import (
    SCHEMA_VERSION,
    ActionDef,
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
    # Action buttons (V3 v0.8.0a11+).  Same compactness rule as
    # ``menus`` -- omitted entirely when no actions are declared so
    # every legacy ``.scriptree`` round-trips byte-identical.
    if tool.actions:
        d["actions"] = [_action_to_dict(a) for a in tool.actions]
    # v0.8.0a22+ — per-OS overrides.  Same compactness rule as
    # ``actions`` / ``menus``: the block is omitted entirely when
    # ``tool.platforms`` is empty, preserving byte-identical
    # round-trip for every legacy ``.scriptree`` written before
    # this feature.  Each individual override entry's own
    # serialiser further skips fields that aren't actively
    # overriding the default, so a "supported but identical"
    # entry shows up as ``{}`` (vs an omitted key, which means
    # "no explicit support claim").
    if tool.platforms:
        d["platforms"] = _platforms_to_dict(tool.platforms)
    # v0.8.0a25+ category taxonomy.  Omitted from the JSON when
    # empty so legacy tools round-trip byte-identical.
    if tool.category:
        d["category"] = tool.category
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


def _action_to_dict(a: ActionDef) -> dict[str, Any]:
    """Serialise one :class:`ActionDef`.

    Compactness rule (matches :func:`_param_to_dict` /
    :func:`_provider_to_dict`): every optional field is omitted at
    its default so a ``.scriptree`` authored before this feature
    existed and then re-saved through a later loader produces a
    byte-identical file.  Only ``id``, ``label``, and ``argv`` are
    emitted unconditionally -- the first two are required, ``argv``
    appears even when empty because an empty argv is a meaningful
    intent ("run executable with no args") rather than an omission.
    """
    d: dict[str, Any] = {
        "id": a.id,
        "label": a.label,
        "argv": list(a.argv),
    }
    if a.tooltip:
        d["tooltip"] = a.tooltip
    if a.popup != "never":
        d["popup"] = a.popup
    if a.confirm:
        d["confirm"] = a.confirm
    if a.icon:
        d["icon"] = a.icon
    if a.hidden:
        d["hidden"] = True
    if a.section:
        d["section"] = a.section
    return d


def _action_from_dict(raw: dict[str, Any]) -> ActionDef:
    """Build an :class:`ActionDef` from a parsed JSON object.

    ``ActionDef.__post_init__`` enforces structural validity (id
    format, popup enum, argv element types) -- so a malformed
    action raises ``ValueError`` at load time, same fail-loud
    contract the rest of the schema uses.
    """
    return ActionDef(
        id=str(raw.get("id", "")),
        label=str(raw.get("label", "")),
        argv=[str(x) for x in (raw.get("argv") or [])],
        tooltip=str(raw.get("tooltip", "")),
        popup=str(raw.get("popup", "never")),
        confirm=str(raw.get("confirm", "")),
        icon=str(raw.get("icon", "")),
        hidden=bool(raw.get("hidden", False)),
        section=str(raw.get("section", "")),
    )


def _load_actions(raw: Any) -> list[ActionDef]:
    if not isinstance(raw, list):
        return []
    return [_action_from_dict(a) for a in raw if isinstance(a, dict)]


# ---------------------------------------------------------------------------
# Per-OS overrides (v0.8.0a22+) — ``PlatformOverride`` round-trip
# ---------------------------------------------------------------------------

def _platform_override_to_dict(
    ovr: "PlatformOverride",  # noqa: F821 — imported below
) -> dict[str, Any]:
    """Serialise a ``PlatformOverride`` to its JSON shape.

    Each field is emitted only when it carries a non-default
    value (``None``-or-empty-collection is treated as "no
    override").  An override with no fields set serialises as
    an empty ``{}`` -- which is the canonical "supported on
    this OS, identical to default" marker (distinct from
    omitting the OS key entirely, which means "no explicit
    support claim").
    """
    out: dict[str, Any] = {}
    if ovr.executable is not None:
        out["executable"] = str(ovr.executable)
    if ovr.argument_template is not None:
        # ``argument_template`` entries may be strings or lists
        # of strings (the ``TemplateEntry`` shape); pass them
        # through unchanged.  Empty list IS distinct from None
        # for this field -- it means "spawn the executable with
        # no arguments", a deliberate user choice.
        out["argument_template"] = [
            (list(e) if isinstance(e, list) else str(e))
            for e in ovr.argument_template
        ]
    if ovr.path_prepend is not None:
        out["path_prepend"] = list(ovr.path_prepend)
    if ovr.env is not None:
        out["env"] = {str(k): str(v) for k, v in ovr.env.items()}
    if ovr.actions is not None:
        out["actions"] = [_action_to_dict(a) for a in ovr.actions]
    return out


def _platform_override_from_dict(
    raw: Any,
) -> "PlatformOverride":  # noqa: F821
    """Parse a ``PlatformOverride`` from its JSON shape.

    Robust to partial / malformed input -- a missing field
    yields ``None`` (= inherit default at resolution time); a
    malformed value falls back to ``None`` with a defensive
    cast rather than raising.  Tree-loading is too important
    to gate on perfect platform JSON.
    """
    from .model import PlatformOverride  # local import; cycle-safe

    if not isinstance(raw, dict):
        # Treat anything else (including ``None``) as "empty
        # override, supported but no field overrides".
        return PlatformOverride()

    def _str_or_none(v: Any) -> str | None:
        if v is None:
            return None
        try:
            return str(v)
        except Exception:  # noqa: BLE001
            return None

    def _list_or_none(v: Any) -> list[Any] | None:
        if v is None:
            return None
        if isinstance(v, list):
            return list(v)
        return None  # malformed -> inherit default

    def _dict_or_none(v: Any) -> dict[str, str] | None:
        if v is None:
            return None
        if isinstance(v, dict):
            return {str(k): str(val) for k, val in v.items()}
        return None

    return PlatformOverride(
        executable=_str_or_none(raw.get("executable")),
        argument_template=_list_or_none(raw.get("argument_template")),
        path_prepend=_list_or_none(raw.get("path_prepend")),
        env=_dict_or_none(raw.get("env")),
        actions=(
            _load_actions(raw["actions"])
            if "actions" in raw
            else None
        ),
    )


def _platforms_to_dict(
    platforms: dict[str, "PlatformOverride"],  # noqa: F821
) -> dict[str, Any]:
    """Serialise the full ``ToolDef.platforms`` map.

    Returns the dict to assign to JSON's ``platforms`` key.
    Only OS ids in ``OS_IDS`` are emitted -- a key like
    ``"freebsd"`` that snuck in via hand-editing is silently
    dropped to keep the on-disk shape tidy.
    """
    from .platform import OS_IDS

    out: dict[str, Any] = {}
    for os_id in OS_IDS:
        if os_id in platforms:
            out[os_id] = _platform_override_to_dict(platforms[os_id])
    return out


def _normalise_category(raw: Any) -> str:
    """Sanitise a ``category`` field on load.

    Rules enforced (see ``ToolDef.category`` docstring):

    * Non-string input -> ``""``.
    * Strip leading / trailing whitespace AND leading/trailing
      slashes (``"/MSOffice/Word/"`` -> ``"MSOffice/Word"``).
    * Empty segments forbidden: a path with ``"//"`` is treated as
      malformed and reduced to its first non-empty prefix
      (``"a//b"`` -> ``"a"``) so a broken authoring mistake doesn't
      explode the group-pass.  The validator emits a warning when
      this fires.
    * Whitespace-only segments are also dropped.

    Returns the cleaned category string, possibly empty.
    """
    if not isinstance(raw, str):
        return ""
    s = raw.strip().strip("/")
    if not s:
        return ""
    parts: list[str] = []
    for seg in s.split("/"):
        seg = seg.strip()
        if not seg:
            # Empty segment -> stop accumulating; everything past
            # this point is unreachable taxonomy.  See contract above.
            break
        parts.append(seg)
    return "/".join(parts)


def _platforms_from_dict(
    raw: Any,
) -> dict[str, "PlatformOverride"]:  # noqa: F821
    """Parse the JSON ``platforms`` block to the ``ToolDef``
    map shape.  Unknown OS ids are dropped silently."""
    from .platform import OS_IDS

    if not isinstance(raw, dict):
        return {}
    out: dict[str, "PlatformOverride"] = {}  # noqa: F821
    for os_id in OS_IDS:
        if os_id in raw:
            out[os_id] = _platform_override_from_dict(raw[os_id])
    return out


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
        actions=_load_actions(data.get("actions")),
        platforms=_platforms_from_dict(data.get("platforms")),
        category=_normalise_category(data.get("category", "")),
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
    # v0.8.0a50 — emit field.  Same omitted-at-default policy: only
    # write when the author chose 'unselected' so legacy v3 files
    # round-trip byte-identical without an 'emit: selected' key
    # cluttering every multiselect.
    if p.emit and p.emit != "selected":
        d["emit"] = p.emit
    # v0.6.28 — folder_list / file_list options.  Emit only when
    # non-default so legacy params round-trip byte-identical.
    if p.must_exist:
        d["must_exist"] = True
    if p.min_items:
        d["min_items"] = int(p.min_items)
    if p.max_items is not None:
        d["max_items"] = int(p.max_items)
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
    p = ParamDef(
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
        emit=str(d.get("emit", "selected") or "selected"),
        must_exist=bool(d.get("must_exist", False)),
        min_items=int(d.get("min_items", 0) or 0),
        max_items=(
            int(d["max_items"])
            if d.get("max_items") is not None else None
        ),
    )
    # v0.8.0a50+ — stash whether the JSON had an explicit ``default``
    # key.  Used by ``param_load_warnings`` (called from
    # ``scriptree validate``) to flag checkbox_list / dropdown-
    # multi params whose initial state was implicit -- a future
    # ScripTree update could change the implicit default and
    # silently change what gets acted on.  Forcing the author to
    # declare the default explicitly closes that hole.  The
    # attribute is NOT a real dataclass field on purpose: it's
    # load-time provenance, not part of the in-memory contract,
    # and the runtime path never reads it.
    p._default_was_explicit = "default" in d  # type: ignore[attr-defined]
    return p


def param_load_warnings(raw: dict[str, Any], p: ParamDef) -> list[str]:
    """Return human-readable warnings for a param dict that loaded
    cleanly but should be flagged for the author.

    v0.8.0a50+ — when ``widget`` is ``checkbox_list`` or
    ``dropdown``-multiselect AND there is no ``choices_provider``
    (i.e. the choice set is static + author-controlled), the
    ``default`` key MUST be explicitly present in the JSON.  An
    implicit empty default means a future ScripTree update could
    silently change behaviour by changing the implicit default --
    which is exactly the class of bug the author was protecting
    against.  Forcing the field to be present, even when the
    chosen value is ``[]``, makes the choice deliberate.

    Returns an empty list for clean params.  Called from
    ``scriptree validate``; runtime ``load_tool`` / ``load_tree``
    do not consume these warnings (the runtime tolerates implicit
    defaults so existing tools keep working until they're touched).
    """
    out: list[str] = []
    needs_explicit = (
        p.widget in (Widget.CHECKBOX_LIST, Widget.DROPDOWN)
        and p.type is ParamType.MULTISELECT
        and p.choices_provider is None
    )
    if needs_explicit and not getattr(p, "_default_was_explicit", True):
        out.append(
            f"ParamDef {p.id!r} (widget={p.widget.value!r}, "
            f"type={p.type.value!r}): 'default' is implicit.  "
            f"Set it explicitly -- '[]' (none selected), the full "
            f"choices list (all selected), or a partial list -- so "
            f"the form's initial state isn't governed by a default "
            f"value that could change between ScripTree versions."
        )
    return out


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
    # v0.8.0a25+ category taxonomy.  Same convention as ToolDef --
    # omitted when empty so legacy trees round-trip byte-identical.
    if tree.category:
        d["category"] = tree.category
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
    # --- v0.8.0a21+ auto-discover serialisation ----------------------
    #
    # The ``auto_discover`` block and the ``excluded`` list are both
    # emitted only when they carry user-meaningful content, so legacy
    # ``.scriptreetree`` files round-trip byte-identical when loaded
    # and re-saved without ever touching the discovery feature.
    #
    # ``auto_discover`` rules:
    #   * ``None``                       — omit entirely.  Means "the
    #                                      user has never been asked
    #                                      what mode they want"; the
    #                                      MainWindow loader uses
    #                                      this to fire the
    #                                      ``ChooseUpdateModeDialog``
    #                                      on first open.
    #   * default-valued instance         — omit entirely.  Pre-feature
    #                                      semantics: a clean
    #                                      round-trip preserves the
    #                                      original file's byte
    #                                      content even after the
    #                                      author has invoked the
    #                                      feature once and accepted
    #                                      every default.  When the
    #                                      MainWindow loader sees an
    #                                      omitted block it tries the
    #                                      first-open flow again; that
    #                                      is a deliberate ergonomic
    #                                      trade-off (the alternative
    #                                      would be a forced dirty
    #                                      diff on every save).
    #   * non-default instance            — emit every non-default
    #                                      field; omit defaults.
    if tree.auto_discover is not None:
        ad = tree.auto_discover
        ad_default = TreeAutoDiscoverConfig()
        ad_d: dict[str, Any] = {}
        if ad.enabled != ad_default.enabled:
            ad_d["enabled"] = bool(ad.enabled)
        if list(ad.roots) != list(ad_default.roots):
            ad_d["roots"] = list(ad.roots)
        if ad.include_sibling_trees != ad_default.include_sibling_trees:
            ad_d["include_sibling_trees"] = bool(ad.include_sibling_trees)
        if ad.update_mode != ad_default.update_mode:
            ad_d["update_mode"] = str(ad.update_mode)
        # Always emit the block when ``auto_discover`` is non-None,
        # even when every field equals its default.  The PRESENCE of
        # the key (even as ``{}``) is the signal to the loader
        # "user has already been asked which mode to use, do NOT
        # fire the first-load chooser again".  An earlier
        # default-equals-omitted rule looked elegant for round-trip
        # diffs but caused the chooser to re-fire every load for a
        # tree where the user picked the default (``"prompt"``) --
        # the worst kind of "I already told you" UX.  The trade-off
        # is that a user-configured tree introduces a 2-byte
        # ``"auto_discover": {}`` block when their choice happens to
        # equal the defaults; acceptable.
        d["auto_discover"] = ad_d
    if tree.excluded:
        d["excluded"] = list(tree.excluded)
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

    # --- v0.8.0a21+ auto-discover deserialisation ------------------
    #
    # Two distinct "absent" cases drive the TreeDef state:
    #
    #   1. The ``auto_discover`` key is missing OR null.
    #      → ``TreeDef.auto_discover = None``.
    #      The runtime treats this as "user has never been asked
    #      what mode they want"; the editor's first-open path will
    #      fire ``ChooseUpdateModeDialog`` instead of the diff
    #      dialog.  All legacy ``.scriptreetree`` files that
    #      pre-date this feature land here, which is the intended
    #      upgrade ergonomic.
    #
    #   2. The ``auto_discover`` key is present (even as ``{}``).
    #      → ``TreeDef.auto_discover = TreeAutoDiscoverConfig(...)``
    #      with each field falling back to its dataclass default
    #      when the corresponding JSON key is absent.
    #      The runtime treats this as "user has been asked, honour
    #      the chosen mode" — no first-open prompt.
    #
    # Be deliberately liberal in what we accept: a malformed
    # ``update_mode`` value (anything other than ``"off"``,
    # ``"auto"``, ``"prompt"``) falls back to the safe ``"off"``
    # rather than raising, so a hand-edited file that typos the
    # value doesn't break tree loading.
    ad_raw = data.get("auto_discover")
    if ad_raw is None:
        auto_discover: TreeAutoDiscoverConfig | None = None
    else:
        if not isinstance(ad_raw, dict):
            ad_raw = {}
        raw_mode = str(ad_raw.get("update_mode", "prompt"))
        if raw_mode not in ("off", "auto", "prompt"):
            raw_mode = "off"
        auto_discover = TreeAutoDiscoverConfig(
            enabled=bool(ad_raw.get("enabled", True)),
            roots=[str(r) for r in ad_raw.get("roots", ["."])],
            include_sibling_trees=bool(
                ad_raw.get("include_sibling_trees", True),
            ),
            update_mode=raw_mode,  # type: ignore[arg-type]
        )

    return TreeDef(
        name=data["name"],
        nodes=[_node_from_dict(n) for n in data.get("nodes", [])],
        menus=_load_menus(data.get("menus")),
        folder_layout=data.get("folder_layout", "flat"),
        path_prepend=list(data.get("path_prepend", [])),
        category=_normalise_category(data.get("category", "")),
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
        auto_discover=auto_discover,
        excluded=[str(p) for p in data.get("excluded", [])],
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
        # v0.6.26+ — per-node icon override.  Emit only when set so
        # legacy trees stay byte-identical on round-trip.
        if n.icon:
            d["icon"] = n.icon
        if n.icon_data:
            d["icon_data"] = n.icon_data
        if n.icon_format:
            d["icon_format"] = n.icon_format
        return d
    folder: dict[str, Any] = {
        "type": "folder",
        "name": n.name,
        "children": [_node_to_dict(c) for c in n.children],
    }
    if n.display_name is not None:
        folder["display_name"] = n.display_name
    # v0.6.26+ — per-node icon override.  Emit only when set so
    # legacy trees stay byte-identical on round-trip.
    if n.icon:
        folder["icon"] = n.icon
    if n.icon_data:
        folder["icon_data"] = n.icon_data
    if n.icon_format:
        folder["icon_format"] = n.icon_format
    return folder


def _node_from_dict(d: dict[str, Any]) -> TreeNode:
    if d.get("type") == "leaf":
        return TreeNode(
            type="leaf",
            path=d["path"],
            configuration=d.get("configuration"),
            display_name=d.get("display_name"),
            icon=str(d.get("icon", "") or ""),
            icon_data=str(d.get("icon_data", "") or ""),
            icon_format=str(d.get("icon_format", "") or ""),
        )
    return TreeNode(
        type="folder",
        name=d.get("name", ""),
        children=[_node_from_dict(c) for c in d.get("children", [])],
        display_name=d.get("display_name"),
        icon=str(d.get("icon", "") or ""),
        icon_data=str(d.get("icon_data", "") or ""),
        icon_format=str(d.get("icon_format", "") or ""),
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
            f"See docs/LLM/scriptree_format.md for the rename map."
        )
