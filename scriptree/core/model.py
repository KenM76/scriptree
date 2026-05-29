"""Schema classes for .scriptree and .scriptreetree files.

## For humans

The in-memory shape of a tool definition (``ToolDef``), a tree
catalog (``TreeDef``), and their parts (``ParamDef``, ``Section``,
``MenuItemDef``, ``ProviderSpec``).  These are plain dataclasses —
no file IO, no Qt — so tests and headless tooling can build/inspect
models without a disk or a display.  Reading/writing the JSON lives
in ``core/io.py``; this module is just the data.

## For maintainers / LLMs

Invariants & edit-safety:

* **No IO, no Qt here, ever.** Serialisation is ``core/io.py``'s
  job; this split is what lets ``scriptree validate`` / ``migrate``
  and CI run headless (enforced by ``tests/test_core_purity.py``).
* ``ParamDef.__post_init__`` is the single source of truth for
  structural validity (id is an identifier; widget legal for type;
  the v0.6.0 provider invariants: not-both-static-choices-and-
  provider, ``select_all`` only with ``checkbox_list``, no trivial
  self-cycle in ``depends_on``).  It raises ``ValueError`` — that's
  the "fail loud at load" contract the loader relies on.
* ``VALID_WIDGETS`` is the type→widget matrix.  Adding a widget
  means: new ``Widget`` enum member, registry entry in
  ``ui/widgets/param_widgets.py``, an entry here, AND update the
  pinned set in ``tests/test_canonical_names_v3.py`` (it asserts
  the exact value set, so it WILL fail until you do — that's
  intentional).
* ``SCHEMA_VERSION`` (below) is a HARD gate: v3 refuses v1/v2 files
  via ``io._check_schema``.  Bumping it is a breaking change that
  needs a matching ``cli/migrate.py`` rename map + doc updates.
  Adding optional fields does NOT need a bump (additive rule).
* ``ProviderSpec.__post_init__`` likewise owns provider-spec
  validity (non-empty argv list, legal ``refresh``/``cache``,
  positive timeout).  ``io._provider_from_dict`` defers to it.
* Dataclass field order / defaults are part of the public surface
  — ``io._param_to_dict`` omits fields at their default for
  byte-stable round-trips; don't reorder or change a default
  without checking the writer's compactness rules.
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
    # v0.6.28 — multi-folder picker: an ordered list of folders the
    # user composes themselves via a Browse button.  Each row holds
    # one absolute folder path; the user can Add (opens
    # ``QFileDialog.getExistingDirectory``), Remove, and reorder
    # (Up / Down).  Order is preserved on argv emission.  ``multiselect``
    # type emits a ``list[str]`` — the runner already comma-joins lists
    # into one argv token; per-folder flags use the existing repeating-
    # token argv pattern.  See ``ParamDef.must_exist`` for the on-add
    # validation toggle.
    FOLDER_LIST = "folder_list"
    # v0.6.28 — multi-file picker.  Same shell as ``FOLDER_LIST`` but
    # the Add button opens ``QFileDialog.getOpenFileNames`` and the
    # param's ``file_filter`` is applied.
    FILE_LIST = "file_list"


# Which widgets are valid for each param type. The editor uses this to
# constrain the widget dropdown when the user changes the type.
VALID_WIDGETS: dict[ParamType, tuple[Widget, ...]] = {
    ParamType.STRING: (Widget.TEXT, Widget.TEXTAREA),
    ParamType.INTEGER: (Widget.NUMBER, Widget.TEXT),
    ParamType.NUMBER: (Widget.NUMBER, Widget.TEXT),
    ParamType.BOOLEAN: (Widget.CHECKBOX,),
    ParamType.PATH: (Widget.FILE, Widget.SAVE_FILE, Widget.FOLDER),
    ParamType.ENUM: (Widget.DROPDOWN, Widget.RADIO),
    ParamType.MULTISELECT: (
        Widget.DROPDOWN, Widget.CHECKBOX_LIST,
        Widget.FOLDER_LIST, Widget.FILE_LIST,
    ),
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

    # v0.6.28 — folder_list / file_list options.  All three are
    # additive and ignored by widgets that don't use them, so any
    # legacy param round-trips byte-identical when they sit at their
    # defaults.
    #
    #   ``must_exist`` — when True, the Add button rejects a chosen
    #       path that doesn't currently exist on disk.  Default False
    #       (matches the ``file`` / ``folder`` single-picker
    #       convention — pick first, validate later).  Existence is
    #       checked at the moment the user finishes the dialog, NOT
    #       on every keystroke or on form-load: a list that contained
    #       a since-deleted folder still loads (the runner can
    #       complain at exec time).
    #   ``min_items`` / ``max_items`` — soft caps on the list length.
    #       ``min_items=0`` (default) and ``max_items=None``
    #       (default) impose no limit.  The widget greys the Add
    #       button when ``len(items) >= max_items`` and lights an
    #       error-state border when ``len(items) < min_items``;
    #       the form's validate step surfaces both as standard
    #       "missing required" messages.
    must_exist: bool = False
    min_items: int = 0
    max_items: int | None = None

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
class ActionDef:
    """One named action button on a tool's form.

    Action buttons are fixed-argv presets that live alongside the
    main Run button.  Click an action and the tool's executable is
    spawned with ``[*action.argv]`` appended -- NO ``{param_id}``
    substitution from form fields, NO list fan-out, just the literal
    arg list authored here.  Output streams to the same output pane
    Run uses (prefixed with ``"▶ Action: <label>"`` so the session
    log stays readable when several actions are clicked in
    succession).

    Use this for the common "wrapped CLI has a main flow + 3-5 quick
    side actions" case (``git status --short``,
    ``pip list --outdated``, ``docker ps``, …) where the producer
    used to either cram the side actions into the main form via a
    mode enum + branching ``argument_template``, split the tool into
    several ``.scriptree`` files, or punt to "easier from the
    command line" -- all bad.  An action button shares the tool's
    ``working_directory`` / ``env`` / ``path_prepend`` and the
    currently-selected configuration's overrides, so the side action
    runs in the same context as Run would.

    Schema fields:

      * ``id`` — stable identifier matching ``[a-z_][a-z0-9_]*``
        (starts with a letter or underscore, then any number of
        lowercase letters / digits / underscores), unique within
        the tool.  Used as a permission key
        (``run_action:<tool>:<id>``) and as the stable handle for
        editor tooling.
      * ``label`` — button text shown in the UI.
      * ``tooltip`` — hover text; falls back to ``executable +
        " " + " ".join(argv)`` when empty.
      * ``argv`` — list of literal strings.  May be empty (means
        "run the executable with no arguments").
      * ``popup`` — one of ``"never"`` (default; stream to output
        pane only), ``"auto"`` (also pop a copy-friendly modal when
        the output fits a sensible cap), or ``"always"`` (always
        pop the modal regardless of output size).
      * ``confirm`` — optional confirmation text.  When non-empty,
        a "Are you sure? — <text>" modal must be accepted before
        the action runs.  For destructive presets.
      * ``icon`` — optional bundled-icon-library name (see
        ``docs/LLM/icon_library.md``).  Empty = label-only button.
      * ``hidden`` — when True the action is registered but not
        rendered as a button; useful for actions surfaced
        elsewhere (custom menus, hotkeys in a future version).
      * ``section`` — optional section name; when set, the button
        renders inside that named section instead of the dedicated
        Actions row near Run.  Re-uses the existing
        ``Section.name`` indexing.

    Permission integration:
      Argv elements go through the same ``permissions.check_command``
      gate as Run, so a global "no --force-push" rule blocks the
      action too.  Plus a new ``run_action:<tool>:<action_id>``
      capability gates the BUTTON ITSELF (default-permissive so
      existing permission files don't need editing).
    """

    id: str
    label: str
    argv: list[str] = field(default_factory=list)
    tooltip: str = ""
    popup: str = "never"      # "never" | "auto" | "always"
    confirm: str = ""
    icon: str = ""
    hidden: bool = False
    section: str = ""

    def __post_init__(self) -> None:
        # Fail loud at load -- the schema is supposed to be authored
        # with the LLM authoring docs in front of you; structural
        # problems should surface here, not at click time.
        import re
        if not self.id:
            raise ValueError("ActionDef.id must be non-empty.")
        if not re.match(r"^[a-z_][a-z0-9_]*$", self.id):
            raise ValueError(
                f"ActionDef.id {self.id!r} must match "
                f"[a-z_][a-z0-9_]* (starts with a letter or "
                f"underscore, then lowercase letters / digits / "
                f"underscores -- stable handle for permissions + "
                f"editor tooling)."
            )
        if not self.label:
            raise ValueError(
                f"ActionDef[{self.id}].label must be non-empty."
            )
        if self.popup not in ("never", "auto", "always"):
            raise ValueError(
                f"ActionDef[{self.id}].popup must be one of "
                f"'never' / 'auto' / 'always'; got {self.popup!r}."
            )
        # Argv elements must be strings.  An empty list IS valid
        # (means "run executable with no args"); a list with non-
        # string entries is NOT.
        for i, a in enumerate(self.argv):
            if not isinstance(a, str):
                raise ValueError(
                    f"ActionDef[{self.id}].argv[{i}] must be a "
                    f"string; got {type(a).__name__}."
                )


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
    # Named action buttons rendered alongside the Run button (V3
    # v0.8.0a11+).  Each action carries its own literal argv that
    # gets appended to ``executable`` when the button is clicked,
    # bypassing the main form's ``argument_template`` and the
    # ``{token}`` substitution machinery.  Sharing the tool's
    # ``working_directory`` / ``env`` / ``path_prepend`` and the
    # currently-selected configuration's overrides, so an action
    # runs in the same context as Run.  See ``ActionDef`` for the
    # per-action field contract.  Default empty list keeps every
    # legacy ``.scriptree`` round-tripping byte-identical -- nothing
    # is emitted to disk when no actions are declared.
    actions: list[ActionDef] = field(default_factory=list)
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
    # Superimpose the text label ON TOP of the icon (V3 v0.6.9+).
    # Default False keeps the historical "icon XOR text" behaviour
    # (icon present → text suppressed) byte-identical on disk.  When
    # True the cell paints BOTH: the icon, then the text label
    # (explicit override or auto-letters) in a legible band over it.
    cell_text_over_icon: bool = False
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

        # Action button IDs must be unique within the tool (they're
        # used as permission keys and as the editor's stable handle).
        # ``ActionDef.__post_init__`` already rejects bad id formats
        # at construction time; here we catch the cross-action
        # duplicate case the per-action check can't see.  Also flag
        # any action whose ``section`` references an undeclared
        # section -- a typo there silently moves the button into
        # the synthetic "Other" group, which is rarely what was
        # intended.
        seen_action_ids: set[str] = set()
        declared_section_names = {s.name for s in self.sections}
        for a in self.actions:
            if a.id in seen_action_ids:
                errors.append(f"Duplicate action id: {a.id!r}")
            seen_action_ids.add(a.id)
            if a.section and a.section not in declared_section_names:
                errors.append(
                    f"Action {a.id!r}.section references undeclared "
                    f"section {a.section!r}; declare it under "
                    f"``sections`` or leave the action's section empty."
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
    # v0.6.26+ — optional per-node icon override.  Mirrors the
    # ``cell.icon*`` triplet on ``ToolDef`` / ``TreeDef``:
    #
    #   * ``icon`` — bundled-icon name (e.g. ``"build"`` →
    #     ``icons/icon-build.png``) OR a relative/absolute path
    #     to an image file.  Cheapest option; uses the shipped
    #     trademark-safe set.
    #   * ``icon_data`` — base64-encoded PNG bytes for a custom
    #     embedded glyph.  Use when none of the shipped icons fit
    #     and a path-link would be fragile.
    #   * ``icon_format`` — image-format hint for ``icon_data``
    #     (``"png"`` for portable runtime; SVG renders blank on
    #     the vendored PySide6 — see ``cell_metadata.py`` notes).
    #
    # For **folders**: the menu submenu marker (the chevron-y row)
    # shows this glyph instead of the OS folder icon.  Useful for
    # "this folder collects scissors workflows" / "this folder is
    # the test-suite group" cues without separating the tools.
    # For **leaves**: this OVERRIDES the bound catalog's own
    # ``cell.icon_data`` for this leaf only — handy when the same
    # ``.scriptree`` is referenced from multiple trees and one of
    # them wants a different glyph.  All three fields are
    # emitted only when non-empty so legacy trees round-trip
    # byte-identical.
    icon: str = ""
    icon_data: str = ""
    icon_format: str = ""

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
    # Superimpose text over icon (V3 v0.6.9+).  See ToolDef.
    cell_text_over_icon: bool = False
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
