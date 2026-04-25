"""Schema classes for .scriptree and .scriptreetree files.

Pure dataclasses with no IO — serialization lives in core/io.py so that
tests can build models in memory without touching the filesystem.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


SCHEMA_VERSION = 2
"""Bumped to 2 in April 2026 when we added sections.

v1 → v2 migration is transparent: v1 files have no ``sections`` key
and every ParamDef has ``section=""`` by default, which the loader
treats as "legacy flat form — render as one group". A v2 file that
declares sections cannot be loaded by v1 tooling; the schema check
in ``core/io.py`` will raise.
"""


class ParamType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOL = "bool"
    PATH = "path"
    ENUM = "enum"
    MULTISELECT = "multiselect"


class Widget(str, Enum):
    TEXT = "text"
    TEXTAREA = "textarea"
    NUMBER = "number"
    CHECKBOX = "checkbox"
    DROPDOWN = "dropdown"
    FILE_OPEN = "file_open"
    FILE_SAVE = "file_save"
    FOLDER = "folder"
    ENUM_RADIO = "enum_radio"


# Which widgets are valid for each param type. The editor uses this to
# constrain the widget dropdown when the user changes the type.
VALID_WIDGETS: dict[ParamType, tuple[Widget, ...]] = {
    ParamType.STRING: (Widget.TEXT, Widget.TEXTAREA),
    ParamType.INTEGER: (Widget.NUMBER, Widget.TEXT),
    ParamType.FLOAT: (Widget.NUMBER, Widget.TEXT),
    ParamType.BOOL: (Widget.CHECKBOX,),
    ParamType.PATH: (Widget.FILE_OPEN, Widget.FILE_SAVE, Widget.FOLDER),
    ParamType.ENUM: (Widget.DROPDOWN, Widget.ENUM_RADIO),
    ParamType.MULTISELECT: (Widget.DROPDOWN,),
}


def default_widget_for(ptype: ParamType) -> Widget:
    return VALID_WIDGETS[ptype][0]


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
