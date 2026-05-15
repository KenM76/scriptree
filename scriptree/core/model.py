"""Schema classes for .scriptree and .scriptreetree files.

Pure dataclasses with no IO — serialization lives in core/io.py so that
tests can build models in memory without touching the filesystem.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


SCHEMA_VERSION = 3
"""Bumped to 3 in May 2026 — JSON-Schema-aligned type names.

History
-------

  * v1 (initial) — flat param list, no sections.
  * v2 (Apr 2026) — added ``sections`` and the per-section layout
    field.  v1 files load transparently into v2 (empty sections list
    == flat form).
  * v3 (May 2026) — JSON-Schema-aligned vocabulary:
      type:    ``bool`` → ``boolean``, ``float`` → ``number``
      widget:  ``file_open`` → ``file``, ``file_save`` → ``save_file``,
               ``enum_radio`` → ``radio``
    Hard-break: v3 ScripTree refuses to load v2 files with an
    error message pointing at ``scriptree migrate``.  See
    ``scriptree/cli/migrate.py`` for the upgrade script.

Why JSON Schema for type, HTML5 for widget?  ``.scriptree`` files
are JSON intended to outlive the implementation language.  JSON
Schema is the canonical, language-agnostic vocabulary for JSON
configs.  Widgets aren't a JSON-Schema concept; HTML5 form elements
are the closest canonical equivalent — and that's what LLMs reach
for in UI/web-form contexts.  Aligning both stops the
``int`` / ``bool`` / ``spinbox`` / ``radiobutton`` LLM-noise
problem at the source.
"""


class ParamType(str, Enum):
    """JSON-Schema-aligned parameter types.

    v3 rename map (v2 names listed for historical reference;
    migration handled by ``scriptree migrate``):
      ``bool``  → ``boolean``  (renamed for JSON-Schema canonical)
      ``float`` → ``number``   (JSON-Schema uses ``number`` for all
                                numerics; constrain with min/max if
                                you need integer-only)
    """

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    PATH = "path"
    ENUM = "enum"
    MULTISELECT = "multiselect"


class Widget(str, Enum):
    """HTML5-aligned widget kinds.

    v3 rename map (v2 names listed for historical reference;
    migration handled by ``scriptree migrate``):
      ``file_open``  → ``file``       (HTML5 ``<input type="file">``)
      ``file_save``  → ``save_file``  (verb-noun reads as action)
      ``enum_radio`` → ``radio``      (HTML5 ``<input type="radio">``)
    """

    TEXT = "text"
    TEXTAREA = "textarea"
    NUMBER = "number"
    CHECKBOX = "checkbox"
    DROPDOWN = "dropdown"
    FILE = "file"
    SAVE_FILE = "save_file"
    FOLDER = "folder"
    RADIO = "radio"
    # v0.6.0 — multiselect rendered as a scrollable list of
    # checkboxes (one per choice) with an optional tri-state
    # select-all/none master.  See ``ParamDef.select_all`` and the
    # dynamic-providers feature.
    CHECKBOX_LIST = "checkbox_list"


# Which widgets are valid for each param type. The editor uses this to
# constrain the widget dropdown when the user changes the type.
VALID_WIDGETS: dict[ParamType, tuple[Widget, ...]] = {
    ParamType.STRING: (Widget.TEXT, Widget.TEXTAREA),
    ParamType.INTEGER: (Widget.NUMBER, Widget.TEXT),
    ParamType.NUMBER: (Widget.NUMBER, Widget.TEXT),
    ParamType.BOOLEAN: (Widget.CHECKBOX,),
    ParamType.PATH: (Widget.FILE, Widget.SAVE_FILE, Widget.FOLDER),
    ParamType.ENUM: (Widget.DROPDOWN, Widget.RADIO),
    ParamType.MULTISELECT: (Widget.DROPDOWN, Widget.CHECKBOX_LIST),
}


def default_widget_for(ptype: ParamType) -> Widget:
    return VALID_WIDGETS[ptype][0]


# Allowed values for ProviderSpec.refresh and .cache.  Kept as module
# constants so io.py / validate / the editor share one source of truth.
PROVIDER_REFRESH_MODES = ("on_open", "manual", "on_change")
PROVIDER_CACHE_MODES = ("form_session", "none")
PROVIDER_DEFAULT_TIMEOUT_SEC = 15


@dataclass
class ProviderSpec:
    """A dynamic choices/value provider for a :class:`ParamDef`.

    v0.6.0 — when set, the param's choices (enum / multiselect /
    checkbox_list) **or** its scalar value (text / path / number /
    …) come from running an external ``command`` at form-open /
    refresh time, NOT from a static ``choices`` list baked into the
    ``.scriptree`` file.

    ``command`` is an argv list (never a shell string).  Relative
    paths resolve against the ``.scriptree`` file's directory, same
    as ``ToolDef.executable``; bare names resolve via PATH.

    The provider receives the current values of ``ParamDef.depends_on``
    params as a single JSON object on **stdin**::

        {"depends_on": {"source": "X.SLDDRW"}, "param_id": "pages"}

    and must print one JSON document to **stdout**.  For choice-type
    params::

        {"choices": [...], "choice_labels": [...], "default": [...]}

    For scalar params::

        {"value": "..."}

    Anything other than exit 0 + valid JSON ⇒ the param renders in a
    soft error state; the rest of the form stays usable.

    This object is **pure data** — execution lives in
    ``scriptree.core.providers`` (no Qt, reuses ``core.runner``
    path/env resolution + ``core.sanitize``).
    """

    command: list[str] = field(default_factory=list)
    working_directory: str | None = None
    refresh: str = "on_open"        # on_open | manual | on_change
    timeout_sec: int = PROVIDER_DEFAULT_TIMEOUT_SEC
    cache: str = "form_session"     # form_session | none

    def __post_init__(self) -> None:
        if not isinstance(self.command, list) or not self.command:
            raise ValueError(
                "ProviderSpec.command must be a non-empty argv list "
                f"(got {self.command!r})"
            )
        if not all(isinstance(tok, str) for tok in self.command):
            raise ValueError(
                "ProviderSpec.command entries must all be strings "
                f"(got {self.command!r})"
            )
        if self.refresh not in PROVIDER_REFRESH_MODES:
            raise ValueError(
                f"ProviderSpec.refresh must be one of "
                f"{PROVIDER_REFRESH_MODES}, got {self.refresh!r}"
            )
        if self.cache not in PROVIDER_CACHE_MODES:
            raise ValueError(
                f"ProviderSpec.cache must be one of "
                f"{PROVIDER_CACHE_MODES}, got {self.cache!r}"
            )
        try:
            self.timeout_sec = int(self.timeout_sec)
        except (TypeError, ValueError):
            raise ValueError(
                f"ProviderSpec.timeout_sec must be an int, got "
                f"{self.timeout_sec!r}"
            ) from None
        if self.timeout_sec <= 0:
            raise ValueError(
                f"ProviderSpec.timeout_sec must be > 0, got "
                f"{self.timeout_sec}"
            )


@dataclass
class ParamDef:
    """A single parameter of a tool.

    `id` is the key used in argument templates (`{id}`). It must be a
    valid Python identifier so templates parse unambiguously.
    """

    id: str
    label: str = ""
    description: str = ""
    type: ParamType = ParamType.STRING
    widget: Widget = Widget.TEXT
    required: bool = False
    default: Any = ""
    # Enum/multiselect: list of allowed values.
    choices: list[str] = field(default_factory=list)
    # Parallel to ``choices`` — a human-readable label for each value.
    # An entry may be empty (or the list may be shorter than ``choices``)
    # in which case the value itself is shown as the label. The argv
    # always carries the ``choices`` value, never the label.
    choice_labels: list[str] = field(default_factory=list)
    # Path widgets: QFileDialog-style filter, e.g. "Text (*.txt);;All (*)".
    file_filter: str = ""
    # Section membership. Empty string means "no explicit section" —
    # these params render in a default unnamed group at the top of
    # the form when the tool declares ``sections`` at all. If the
    # tool has no sections at all, this field is ignored.
    section: str = ""
    # When True, the parameter's value is never written to any saved
    # configuration. The user's most recent entry is kept in the form
    # during the session but is lost when the tool is reloaded (the
    # widget returns to ``default``). Useful for passwords, tokens,
    # and other sensitive or scratch values.
    no_persist: bool = False
    # When True, the string-passthrough auto-split rule does NOT
    # apply to this parameter — its value always emits as a single
    # argv token, even when whitespace is present and the placeholder
    # fills the whole template token. Only meaningful for
    # ``ParamType.STRING`` params; ignored otherwise. Use this for a
    # string field that genuinely holds one logical value with spaces
    # (a sentence, a quoted name, etc.) and you don't want it broken
    # apart at emit time.
    no_split: bool = False
    # V0.4.0 — conditional widget visibility + conditional requirement.
    #
    # ``visible_when`` is a tiny expression evaluated against the
    # form's current values; when it returns False the widget is
    # hidden from the form AND its value is omitted from argv
    # assembly (just like an empty required-False field).  When
    # empty (the default), the param is always visible — preserving
    # pre-v0.4.0 behaviour byte-identically.
    #
    # ``required_when`` follows the same expression syntax but
    # triggers the existing required-field validation instead of
    # toggling visibility.  When empty, the static ``required``
    # field above governs.  ``required_when`` overrides ``required``
    # when set — a field is required iff the expression evaluates
    # truthy at the current moment.
    #
    # Grammar (handled by ``visible_when.evaluate`` —
    # ``scriptree.core.visible_when``):
    #
    #   <expr>     := <atom> ( ('AND' | 'OR') <atom> )*
    #   <atom>     := 'NOT' <atom> | '(' <expr> ')' | <comparison>
    #   <comparison> := <ident> <op> <literal>
    #                  | <ident> 'in' '(' <literal_list> ')'
    #   <op>       := '==' | '!='
    #   <literal>  := <quoted_string> | <bare_token>
    #
    # Examples::
    #
    #   "bom_source == 'drawing'"
    #   "bom_type == '3'"
    #   "bom_source in ('insert', 'auto')"
    #   "bom_source == 'drawing' AND drawing_present == 'yes'"
    #   "NOT (mode == 'silent')"
    #
    # Unparseable / unevaluable expressions log a one-line warning
    # and FAIL OPEN — the widget is shown (and treated as not
    # required-when) so a typo in the .scriptree doesn't make a
    # field invisible and impossible to fix from the UI.
    visible_when: str = ""
    required_when: str = ""

    # v0.6.0 — dynamic choice/value providers + cascading params.
    #
    # ``choices_provider``: when set, this param's choices (for
    # enum / multiselect / checkbox_list) OR its scalar value (for
    # text / path / number / …) are produced by running an external
    # command at form-open / refresh time instead of coming from the
    # static ``choices`` list.  Mutually exclusive with a non-empty
    # static ``choices`` (loader raises).  See :class:`ProviderSpec`.
    #
    # ``depends_on``: ids of upstream params whose current values are
    # forwarded to this param's provider on stdin, and whose change
    # re-runs the provider when ``ProviderSpec.refresh == "on_change"``.
    # A ``depends_on`` cycle is a load-time error (fail loud, like a
    # structural ``visible_when`` problem).
    #
    # ``select_all``: only meaningful with ``widget ==
    # CHECKBOX_LIST`` — renders a tri-state master select-all/none
    # control above the list.
    #
    # All three default to "absent" semantics so a v3 file without
    # them is byte-identical and behaves exactly as before.
    choices_provider: ProviderSpec | None = None
    depends_on: list[str] = field(default_factory=list)
    select_all: bool = False

    def label_for_choice(self, value: str) -> str:
        """Return the descriptive label for a choice value, or the value itself.

        If ``choice_labels`` is shorter than ``choices`` or the label
        entry is empty, the value is used verbatim — this is what
        keeps legacy tools without explicit labels looking the same.
        """
        try:
            idx = self.choices.index(value)
        except ValueError:
            return value
        if idx < len(self.choice_labels) and self.choice_labels[idx]:
            return self.choice_labels[idx]
        return value

    def __post_init__(self) -> None:
        if not self.id.isidentifier():
            raise ValueError(
                f"ParamDef.id must be a valid identifier, got: {self.id!r}"
            )
        if self.widget not in VALID_WIDGETS[self.type]:
            raise ValueError(
                f"Widget {self.widget.value!r} is not valid for type "
                f"{self.type.value!r}. Valid widgets: "
                f"{[w.value for w in VALID_WIDGETS[self.type]]}"
            )
        # v0.6.0 — dynamic-provider structural invariants.  These
        # fail loud at construction (and therefore at load), the
        # same stance the schema takes for an invalid widget/type
        # pairing: a structurally-broken provider config is an
        # authoring bug, not a runtime soft-fail.
        if self.choices_provider is not None and self.choices:
            raise ValueError(
                f"ParamDef {self.id!r}: cannot set both a static "
                f"'choices' list and a 'choices_provider'. Use one "
                f"or the other."
            )
        if self.select_all and self.widget is not Widget.CHECKBOX_LIST:
            raise ValueError(
                f"ParamDef {self.id!r}: 'select_all' is only valid "
                f"with widget 'checkbox_list' (got "
                f"{self.widget.value!r})."
            )
        if self.id in self.depends_on:
            raise ValueError(
                f"ParamDef {self.id!r}: 'depends_on' must not list "
                f"the param itself (trivial cycle)."
            )
        if not self.label:
            self.label = self.id.replace("_", " ").capitalize()


@dataclass
class ParseSource:
    """Records how the ToolDef was produced.

    `mode` is one of:
      - "manual"     — user built it from a blank canvas
      - "argparse"   — parsed via argparse detector
      - "click"      — parsed via click detector
      - "docopt"     — parsed via docopt detector
      - "heuristic"  — parsed via generic heuristic
    """

    mode: str = "manual"
    help_text_cached: str | None = None


TemplateEntry = str | list[str]
"""One entry in ``argument_template``.

- A ``str`` is a single argv token. If a bare ``{name}`` inside it
  resolves to empty, the whole token is dropped (existing behavior).
- A ``list[str]`` is a *token group*: all tokens emit together when
  every substitution resolves; if any substitution is empty, the
  whole group drops. This is what lets Windows-style flags like
  ``/S system`` work — two argv tokens that appear together or not
  at all.
"""


@dataclass
class Section:
    """A named, optionally collapsible group of params.

    Sections are purely a rendering hint — they don't affect argv
    assembly. A tool's ``sections`` list defines both the order in
    which sections appear and their initial collapsed state. Param
    membership is stored on each ``ParamDef.section`` (keyed by
    ``Section.name``) so reordering within a section is a simple
    in-place slice swap on ``ToolDef.params``.

    ``layout`` controls how this individual section renders:

    - ``"collapse"`` (default) — a collapsible ``QGroupBox``.
    - ``"tab"`` — rendered as a page in a ``QTabWidget``.

    Consecutive tab-mode sections are grouped into a single tab
    widget; a run of collapse sections between two tab runs creates
    a visual break (separate tab widgets above and below).
    """

    name: str
    collapsed: bool = False
    layout: str = "collapse"  # "collapse" or "tab"


@dataclass
class MenuItemDef:
    """One item in a custom menu bar.

    A menu item is either:
    - An **action** with a ``label`` and a ``command`` (shell command
      string executed when the item is clicked).
    - A **separator** (``label == "-"``).
    - A **submenu** (has ``children`` but no ``command``).

    ``menu`` is the top-level menu name this item belongs to
    (e.g. "Tools", "Reports"). Items with the same ``menu`` value
    are grouped under one menu.
    """

    label: str
    menu: str = ""
    command: str = ""
    children: list[MenuItemDef] = field(default_factory=list)
    shortcut: str = ""
    tooltip: str = ""


@dataclass
class ToolDef:
    """A complete tool definition, serialized as one .scriptree file."""

    name: str
    executable: str
    argument_template: list[TemplateEntry] = field(default_factory=list)
    params: list[ParamDef] = field(default_factory=list)
    description: str = ""
    working_directory: str | None = None
    source: ParseSource = field(default_factory=ParseSource)
    # Optional sections. An empty list means "no sections — render the
    # params as one flat form" (legacy / simple tools). When sections
    # are declared, params are grouped by ``ParamDef.section``; any
    # param whose section name isn't in this list is shown in a default
    # "Other" group at the bottom.
    sections: list[Section] = field(default_factory=list)
    # DEPRECATED — kept for backward compatibility with v2 files that
    # set a tool-level ``section_layout``.  The loader applies it to
    # each section that doesn't already have an explicit ``layout``,
    # then discards it.  New code should set ``Section.layout`` on
    # each section individually.  The writer no longer emits this
    # field — per-section ``layout`` is the canonical representation.
    section_layout: str = "collapse"
    # Tool-level environment variables layered on top of the ambient
    # ``os.environ`` when spawning the child process. Per-configuration
    # overrides (stored in the sidecar) layer on top of these, so the
    # final merge order is: os.environ -> tool.env -> config.env.
    env: dict[str, str] = field(default_factory=dict)
    # Directories prepended to the child's ``PATH`` before spawn. Both
    # the tool's list and the active configuration's list are joined,
    # with tool entries first (so configuration entries have the
    # highest priority). Relative paths are resolved against the
    # tool's ``working_directory``.
    path_prepend: list[str] = field(default_factory=list)
    # Custom menus rendered at the top of the form in standalone mode
    # and as a menu bar extension in the main window. Grouped by
    # ``MenuItemDef.menu`` into top-level menus.
    menus: list[MenuItemDef] = field(default_factory=list)
    # Cell-shell visual settings (V3, optional).  Persisted in the
    # .scriptree JSON so a tool ships with its preferred presentation.
    # All optional; cells fall back to auto-derived letters when none
    # of these are set.  Per the v0.2.7 user direction (2026-05-07):
    # "The icon settings should be stored in the json of the
    # scriptree, scriptreetree or scriptreering file the cell/ring
    # is associated with."
    #
    #   cell_icon         — relative-by-default path to an image file.
    #                       Resolved against the .scriptree's parent
    #                       directory at load time.
    #   cell_icon_data    — base64-encoded image bytes (an "embedded"
    #                       icon).  When set, takes precedence over
    #                       cell_icon (which should be empty in that
    #                       case after Embed).
    #   cell_icon_format  — image format hint for cell_icon_data
    #                       (e.g. "png", "jpg", "svg").  Required if
    #                       cell_icon_data is set.
    #   cell_text_label   — explicit short text override.
    #   cell_icon_scale   — multiplier of the natural inscribed-circle
    #                       size (default 1.0).
    #   cell_label_opacity — multiplier of the cell's transparency
    #                       (default 1.0).
    cell_icon: str = ""
    cell_icon_data: str = ""
    cell_icon_format: str = ""
    cell_text_label: str = ""
    cell_icon_scale: float = 1.0
    cell_label_opacity: float = 1.0
    # Cell single-click behaviour (V3 v0.3.5+).  When the cell shell
    # binds this catalog to a hex / square cell, ``cell_click_action``
    # determines what a single-left-click does:
    #
    #   "menu" (default) — show the popup tool menu (pre-v0.3.5 behaviour).
    #   "run"            — directly run the tool; for ``.scriptreetree``
    #                      catalogs, every leaf runs.  ``cell_click_run_mode``
    #                      then controls whether they fire sequentially
    #                      (one after the previous closes) or in parallel
    #                      (all spawned at once).
    #
    # The ``cell_click_to_run`` capability gates whether the user
    # can flip the action to ``"run"`` from the cell Settings
    # dialog — when denied, the dropdown is locked at ``"menu"``.
    # Always serialised verbatim to the catalog JSON's ``cell``
    # sub-object so the choice travels with the file.
    cell_click_action: str = "menu"        # "menu" | "run"
    cell_click_run_mode: str = "sequential"  # "sequential" | "parallel"
    # Cell fill colour override (V3 v0.3.6+).  Hex string of the
    # form ``"#RRGGBB"`` (lowercase, no alpha — the cell's own
    # ``transparency`` slider controls alpha separately).  Empty
    # string means "use the branding default fill", preserving
    # pre-v0.3.6 cells byte-identical on disk.  Per-cell, NOT
    # group-uniform: a master + members can each have a different
    # fill so a ring can colour-code its tools.
    cell_fill_color: str = ""
    # Cell text colour override (V3 v0.3.8+).  Hex string of the
    # form ``"#RRGGBB"`` (lowercase, no alpha — paint code multiplies
    # the cell's transparency × label_opacity into alpha at render
    # time).  Empty string means "follow the stroke-derived default
    # colour", preserving pre-v0.3.8 cells byte-identical on disk.
    # Applies to both the auto-letter label and any custom text the
    # user has set; icon labels are not tinted.  Per-cell, mirrors
    # the fill-colour pattern.
    cell_text_color: str = ""
    # Interactive stdin (V3 v0.3.0) — when True the runner exposes a
    # send-line widget below the output pane, so the tool can read
    # user input from stdin while running.  Used by tools that
    # implement query-replace-style prompt loops (Emacs M-%) — pick a
    # match, type ``y``/``n``/``!``/``q``, hit Enter.  The runner
    # ALSO requires the ``interactive_stdin`` capability to be
    # granted by the permission system; when missing or read-only the
    # tool runs in normal one-shot mode and a one-line warning is
    # appended to the output pane.  Default ``False`` preserves the
    # one-shot contract for every existing tool.
    interactive: bool = False
    schema_version: int = SCHEMA_VERSION
    # Absolute path of the ``.scriptree`` file this tool was loaded
    # from — populated by ``load_tool()``. Used at run time to resolve
    # relative paths (``executable``, ``working_directory``,
    # ``path_prepend`` entries) against the .scriptree file's own
    # directory rather than against the process's CWD, so the folder
    # containing the tool can be moved without breaking the tool.
    # NOT serialized to disk; derived from the file's own location.
    loaded_from: str | None = None

    def param_by_id(self, param_id: str) -> ParamDef | None:
        for p in self.params:
            if p.id == param_id:
                return p
        return None

    def grouped_params(self) -> list[tuple[Section | None, list[ParamDef]]]:
        """Return params grouped by their section for rendering.

        - If ``self.sections`` is empty, returns a single
          ``(None, all_params)`` tuple — the caller should render a flat
          form with no section headings.
        - Otherwise returns one tuple per declared section in order,
          each holding the subset of params whose ``section`` field
          matches that section's name (preserving their relative order
          in ``self.params``). Params whose section doesn't match any
          declared section are collected into a synthetic trailing
          ``Section("Other")`` so nothing is lost.
        """
        if not self.sections:
            return [(None, list(self.params))]

        by_name: dict[str, list[ParamDef]] = {s.name: [] for s in self.sections}
        orphans: list[ParamDef] = []
        declared = {s.name for s in self.sections}
        for p in self.params:
            if p.section in declared:
                by_name[p.section].append(p)
            else:
                orphans.append(p)

        result: list[tuple[Section | None, list[ParamDef]]] = [
            (s, by_name[s.name]) for s in self.sections
        ]
        if orphans:
            result.append((Section(name="Other"), orphans))
        return result

    def validate(self) -> list[str]:
        """Return a list of human-readable validation errors. Empty = OK."""
        errors: list[str] = []
        if not self.name:
            errors.append("Tool name is empty.")
        if not self.executable:
            errors.append("Executable path is empty.")

        seen_ids: set[str] = set()
        for p in self.params:
            if p.id in seen_ids:
                errors.append(f"Duplicate parameter id: {p.id!r}")
            seen_ids.add(p.id)

        # Every {param_id} in the template must resolve to a param.
        # Walks into groups so grouped tokens are checked too.
        for entry in self.argument_template:
            tokens = entry if isinstance(entry, list) else [entry]
            for token in tokens:
                for ref in _template_refs(token):
                    if ref not in seen_ids:
                        errors.append(
                            f"Template references unknown parameter: {{{ref}}}"
                        )
        return errors


@dataclass
class TreeNode:
    """A node in a .scriptreetree file.

    A node is either a folder (has children, no path) or a leaf (has
    path pointing at a .scriptree or .scriptreetree file, no children).

    The optional ``configuration`` field names the configuration to
    activate when this tool is opened in standalone mode.  When
    ``None`` the tool uses its default (active) configuration.

    The optional ``display_name`` field overrides the label shown in
    the tree view and the standalone tab bar.  When ``None`` the
    tool's own ``ToolDef.name`` is used (leaves) or ``TreeNode.name``
    is used (folders).  Useful when a tool's internal name is
    verbose/technical and you want a friendlier label in the UI.
    """

    type: str  # "folder" or "leaf"
    name: str = ""
    path: str | None = None
    children: list[TreeNode] = field(default_factory=list)
    configuration: str | None = None
    display_name: str | None = None

    def __post_init__(self) -> None:
        if self.type not in ("folder", "leaf"):
            raise ValueError(f"TreeNode.type must be folder or leaf, got {self.type!r}")
        if self.type == "leaf" and self.path is None:
            raise ValueError("leaf TreeNode requires a path")
        if self.type == "folder" and self.path is not None:
            raise ValueError("folder TreeNode must not have a path")


@dataclass
class TreeDef:
    """A .scriptreetree file — a named tree of tool references."""

    name: str
    nodes: list[TreeNode] = field(default_factory=list)
    # Custom menus for the tree — rendered in standalone mode's menu bar.
    menus: list[MenuItemDef] = field(default_factory=list)
    # Tree-level PATH prepend — directories prepended to PATH for every
    # tool launched via this tree. Layered between the global (Settings)
    # PATH prepend and the tool-level (.scriptree) PATH prepend, so
    # tree-wide overrides win over global but lose to per-tool. Surfaced
    # via the missing-executable recovery dialog's "add to .scriptreetree
    # path_prepend" scope (with optional bulk-apply across all loaded
    # trees in the IDE sidebar).
    path_prepend: list[str] = field(default_factory=list)
    # Standalone-mode tab arrangement:
    #   "flat"  — flatten the tree to leaves; one tab per tool
    #             (default; preserves pre-v0.1.9 behavior).
    #   "tabs"  — folders become outer tabs, tools inside each folder
    #             become inner tabs (nested QTabWidget). Top-level
    #             leaves render alongside folder tabs as outer tabs;
    #             nested folders recurse.
    # Users can also flip this at runtime via the standalone window's
    # tab-bar right-click menu — that's an in-session override and
    # doesn't persist back to disk.
    folder_layout: str = "flat"
    # Cell-shell visual settings — same shape as the corresponding
    # fields on ToolDef.  See ToolDef.cell_icon docstring for the
    # full contract.  Per V3 v0.2.7 user direction.
    cell_icon: str = ""
    cell_icon_data: str = ""
    cell_icon_format: str = ""
    cell_text_label: str = ""
    cell_icon_scale: float = 1.0
    cell_label_opacity: float = 1.0
    # Cell single-click action (V3 v0.3.5+).  See the matching
    # docstring on ``ToolDef.cell_click_action`` for the full
    # contract — when set to ``"run"`` on a TreeDef, single-click
    # on the bound cell runs every leaf in the tree according to
    # ``cell_click_run_mode`` (sequential or parallel).
    cell_click_action: str = "menu"        # "menu" | "run"
    cell_click_run_mode: str = "sequential"  # "sequential" | "parallel"
    # Cell fill colour override (V3 v0.3.6+).  See ToolDef.
    cell_fill_color: str = ""
    # Cell text colour override (V3 v0.3.8+).  See ToolDef.
    cell_text_color: str = ""
    schema_version: int = SCHEMA_VERSION


# --- helpers ---------------------------------------------------------------

def _template_refs(token: str) -> list[str]:
    """Extract {param_id} and {param_id?flag} references from a token.

    Supports both forms:
      {name}          -> positional substitution
      {name?--name}   -> conditional flag (emitted only if bool param is true)
    """
    refs: list[str] = []
    i = 0
    while i < len(token):
        if token[i] == "{":
            end = token.find("}", i + 1)
            if end == -1:
                break
            inner = token[i + 1 : end]
            if "?" in inner:
                inner = inner.split("?", 1)[0]
            if inner.isidentifier():
                refs.append(inner)
            i = end + 1
        else:
            i += 1
    return refs
