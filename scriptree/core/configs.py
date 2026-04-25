"""Saved configurations for tool runs (sidecar file).

Every .scriptree file may have a sidecar ``<tool>.scriptree.configs.json``
holding one or more **configurations** — named snapshots of form values
plus any extra tokens the user typed into the command preview. The
sidecar is independent of the tool definition so reordering params,
adding new fields, or even editing the .scriptree in another tool can
happen without fighting merge conflicts on the user's saved inputs.

Schema::

    {
      "schema_version": 1,
      "active": "default",
      "configurations": [
        {"name": "default", "values": {"name": "hello"}, "extras": []},
        {"name": "verbose", "values": {"name": "world"}, "extras": ["-v"]}
      ]
    }

If the sidecar file doesn't exist, ``load_configs`` returns ``None`` —
the runner view then falls back to a single in-memory "default"
configuration built from the ParamDef defaults. As soon as the user
saves/renames/edits a configuration the sidecar is created.

Pure-Python, no Qt imports — lives in ``core`` so it's unit-testable
without a QApplication.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


CONFIGS_SCHEMA_VERSION = 1
SIDECAR_SUFFIX = ".configs.json"
TREE_SIDECAR_SUFFIX = ".treeconfigs.json"

# Reserved configuration name — ScripTree creates/overwrites this in
# a tool's sidecar when a tree references a config that doesn't exist.
# Users cannot create or rename to this name.
SAFETREE_CONFIG_NAME = "safetree"

# Names of all UIVisibility boolean fields, used for serialization.
_VIS_FIELDS = (
    "output_pane",
    "extras_box",
    "tools_sidebar",
    "command_line",
    "copy_argv",
    "clear_output",
    "config_bar",
    "env_button",
    "popup_on_error",
    "popup_on_success",
)


@dataclass
class UIVisibility:
    """Controls which UI elements are visible for a configuration.

    All flags default to their "show everything" state. A configuration
    that wants to hide developer-facing chrome (command line editor,
    config bar, etc.) sets the relevant flags to ``False``.

    When ``output_pane`` is ``False`` the output dock/panel is hidden.
    The ``popup_on_error`` and ``popup_on_success`` flags control
    whether a dialog pops up after the process exits when the output
    pane is not visible.
    """

    output_pane: bool = True
    extras_box: bool = True
    tools_sidebar: bool = True
    command_line: bool = True
    copy_argv: bool = True
    clear_output: bool = True
    # Config bar mode: "hidden", "read", or "readwrite".
    # "hidden" = no config bar at all in standalone.
    # "read" = combo to switch configs, but no Save/Delete/Edit/Env buttons.
    # "readwrite" = full config bar with all buttons.
    config_bar: str = "readwrite"
    env_button: bool = True
    popup_on_error: bool = False
    popup_on_success: bool = False

    def is_default(self) -> bool:
        """Return True if every flag is at its factory default."""
        return self == UIVisibility()


@dataclass
class Configuration:
    """One named snapshot of form values + extras.

    Configurations also carry per-run **environment overrides** that
    layer on top of the tool-level ``ToolDef.env`` and
    ``ToolDef.path_prepend``. Leaving them empty means "inherit the
    tool's defaults verbatim", so legacy sidecar files with no env
    fields continue to behave exactly as before.

    ``ui_visibility`` controls which UI elements appear when this
    configuration is active. ``hidden_params`` lists param IDs whose
    widgets should not be rendered — their values are still used from
    the ``values`` dict but the user cannot change them.
    """

    name: str
    values: dict[str, Any] = field(default_factory=dict)
    extras: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    path_prepend: list[str] = field(default_factory=list)
    ui_visibility: UIVisibility = field(default_factory=UIVisibility)
    hidden_params: list[str] = field(default_factory=list)
    prompt_credentials: bool = False
    # "shared" (next to the .scriptree, visible to all users) or
    # "personal" (in the user_configs/ directory). Default "shared"
    # matches legacy sidecar behavior.
    storage: str = "shared"


@dataclass
class ConfigurationSet:
    """The ordered list of configurations for a single tool.

    ``active`` is the name of the currently-selected configuration; it
    must match one of the ``configurations`` entries. An empty list is
    not a valid state — callers should guarantee at least one entry
    (use :func:`default_configuration_set`).

    ``source_filename`` and ``source_locations`` are only populated for
    personal sidecars. They record the tool filename and the parent
    directories where that tool has been loaded from, so a personal
    sidecar moved or copied between machines can be matched up with the
    right tool even when multiple tools share a filename.
    """

    active: str = "default"
    configurations: list[Configuration] = field(default_factory=list)
    source_filename: str = ""
    source_locations: list[str] = field(default_factory=list)

    def find(self, name: str) -> Configuration | None:
        for c in self.configurations:
            if c.name == name:
                return c
        return None

    def active_config(self) -> Configuration:
        c = self.find(self.active)
        if c is not None:
            return c
        # Fall back to the first one and repair the ``active`` pointer.
        if self.configurations:
            self.active = self.configurations[0].name
            return self.configurations[0]
        raise ValueError("ConfigurationSet has no configurations")

    def names(self) -> list[str]:
        return [c.name for c in self.configurations]


def default_configuration_set(values: dict[str, Any] | None = None) -> ConfigurationSet:
    """Build a one-entry set called 'default' seeded with ``values``."""
    return ConfigurationSet(
        active="default",
        configurations=[
            Configuration(name="default", values=dict(values or {}), extras=[])
        ],
    )


def sidecar_path(tool_path: str | Path) -> Path:
    """Return the sidecar path for a given .scriptree file.

    Appends ``.configs.json`` to the full filename (not
    ``with_suffix`` — we want to preserve the ``.scriptree`` extension
    so the file lines up alphabetically in file explorers).
    """
    p = Path(tool_path)
    return p.with_name(p.name + SIDECAR_SUFFIX)


def load_configs(tool_path: str | Path) -> ConfigurationSet | None:
    """Load the sidecar for ``tool_path`` or return ``None`` if missing."""
    path = sidecar_path(tool_path)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return configs_from_dict(data)


def save_configs(tool_path: str | Path, cfg_set: ConfigurationSet) -> None:
    path = sidecar_path(tool_path)
    path.write_text(
        json.dumps(configs_to_dict(cfg_set), indent=2), encoding="utf-8"
    )


def configs_to_dict(cfg_set: ConfigurationSet) -> dict[str, Any]:
    d: dict[str, Any] = {
        "schema_version": CONFIGS_SCHEMA_VERSION,
        "active": cfg_set.active,
        "configurations": [_config_to_dict(c) for c in cfg_set.configurations],
    }
    # Source info is only populated for personal sidecars. Emit only
    # when non-empty to keep shared sidecars compact.
    if cfg_set.source_filename:
        d["source_filename"] = cfg_set.source_filename
    if cfg_set.source_locations:
        d["source_locations"] = list(cfg_set.source_locations)
    return d


def _config_to_dict(c: Configuration) -> dict[str, Any]:
    d: dict[str, Any] = {
        "name": c.name,
        "values": dict(c.values),
        "extras": list(c.extras),
    }
    # Env + path_prepend are only emitted when non-empty so sidecars
    # stay compact for the common "no overrides" case.
    if c.env:
        d["env"] = dict(c.env)
    if c.path_prepend:
        d["path_prepend"] = list(c.path_prepend)
    # UI visibility — only emit when non-default.
    if not c.ui_visibility.is_default():
        vis: dict[str, Any] = {}
        defaults = UIVisibility()
        for f in _VIS_FIELDS:
            val = getattr(c.ui_visibility, f)
            if val != getattr(defaults, f):
                vis[f] = val
        d["ui_visibility"] = vis
    # Hidden params — only emit when non-empty.
    if c.hidden_params:
        d["hidden_params"] = list(c.hidden_params)
    # Prompt credentials — only emit when True.
    if c.prompt_credentials:
        d["prompt_credentials"] = True
    # Storage — emit only when not the default ("shared").
    if c.storage and c.storage != "shared":
        d["storage"] = c.storage
    return d


def _vis_from_dict(raw: dict[str, Any] | None) -> UIVisibility:
    """Deserialize a UIVisibility from a (possibly sparse) dict."""
    if not raw:
        return UIVisibility()
    defaults = UIVisibility()
    kwargs: dict[str, Any] = {}
    for f in _VIS_FIELDS:
        if f in raw:
            if f == "config_bar":
                # String field: "hidden", "read", "readwrite".
                # Legacy bool True → "readwrite", False → "hidden".
                v = raw[f]
                if isinstance(v, bool):
                    kwargs[f] = "readwrite" if v else "hidden"
                else:
                    kwargs[f] = str(v) if v in ("hidden", "read", "readwrite") else "readwrite"
            else:
                kwargs[f] = bool(raw[f])
        else:
            kwargs[f] = getattr(defaults, f)
    return UIVisibility(**kwargs)


def configs_from_dict(data: dict[str, Any]) -> ConfigurationSet:
    v = data.get("schema_version", CONFIGS_SCHEMA_VERSION)
    if v > CONFIGS_SCHEMA_VERSION:
        raise ValueError(
            f"Config sidecar has schema_version {v}, this build only "
            f"understands up to {CONFIGS_SCHEMA_VERSION}."
        )
    raw_configs = data.get("configurations") or []
    configs = [
        Configuration(
            name=str(c.get("name", "")),
            values=dict(c.get("values", {})),
            extras=[str(x) for x in c.get("extras", [])],
            env={
                str(k): str(v) for k, v in (c.get("env") or {}).items()
            },
            path_prepend=[str(p) for p in (c.get("path_prepend") or [])],
            ui_visibility=_vis_from_dict(c.get("ui_visibility")),
            hidden_params=[str(p) for p in (c.get("hidden_params") or [])],
            prompt_credentials=bool(c.get("prompt_credentials", False)),
            storage=str(c.get("storage", "shared")),
        )
        for c in raw_configs
    ]
    if not configs:
        configs = [Configuration(name="default")]
    active = str(data.get("active", configs[0].name))
    if not any(c.name == active for c in configs):
        active = configs[0].name
    source_filename = str(data.get("source_filename", ""))
    source_locations = [
        str(loc) for loc in (data.get("source_locations") or [])
    ]
    return ConfigurationSet(
        active=active,
        configurations=configs,
        source_filename=source_filename,
        source_locations=source_locations,
    )


# --- safetree reserved configuration --------------------------------------


def safetree_visibility() -> UIVisibility:
    """Return the UIVisibility used by the reserved ``safetree`` config.

    Everything hidden, popups enabled so the user still sees results.
    """
    return UIVisibility(
        output_pane=False,
        extras_box=False,
        tools_sidebar=False,
        command_line=False,
        copy_argv=False,
        clear_output=False,
        config_bar="hidden",
        env_button=False,
        popup_on_error=True,
        popup_on_success=True,
    )


def safetree_configuration(values: dict[str, Any] | None = None) -> Configuration:
    """Build the reserved ``safetree`` config for a tool.

    This is created automatically when a tree references a config name
    that no longer exists in a tool's sidecar. All UI chrome is hidden
    and popup dialogs are enabled. ``values`` can be seeded with the
    tool's current defaults.
    """
    return Configuration(
        name=SAFETREE_CONFIG_NAME,
        values=dict(values or {}),
        ui_visibility=safetree_visibility(),
    )


def is_reserved_config_name(name: str) -> bool:
    """Return True if ``name`` is reserved and cannot be used by the user."""
    return name.strip().lower() == SAFETREE_CONFIG_NAME


def ensure_safetree_config(
    tool_path: str | Path,
    default_values: dict[str, Any] | None = None,
) -> None:
    """Create or overwrite the ``safetree`` config in a tool's sidecar.

    If the sidecar exists, adds/replaces the ``safetree`` entry. If not,
    creates a new sidecar with ``default`` + ``safetree`` configurations.
    Always overwrites any existing ``safetree`` with the canonical
    version so the reserved config stays consistent.
    """
    loaded = load_configs(tool_path)
    if loaded is None:
        loaded = default_configuration_set(default_values)
    # Remove any existing safetree entry and add the canonical one.
    loaded.configurations = [
        c for c in loaded.configurations
        if c.name != SAFETREE_CONFIG_NAME
    ]
    loaded.configurations.append(safetree_configuration(default_values))
    save_configs(tool_path, loaded)


# --- tree-level configurations (scriptreetree sidecar) --------------------


@dataclass
class TreeConfiguration:
    """A named mapping of tool-relative-paths to configuration names.

    Each entry in ``tool_configs`` maps a relative tool path (as it
    appears in the ``.scriptreetree`` file) to the name of a
    configuration to apply when that tool is opened in standalone mode.
    """

    name: str
    tool_configs: dict[str, str] = field(default_factory=dict)


@dataclass
class TreeConfigurationSet:
    """Ordered list of tree-level configurations.

    ``active`` is the name of the configuration to use when the tree
    is opened in standalone mode. Must match one of ``configurations``.
    """

    active: str = "default"
    configurations: list[TreeConfiguration] = field(default_factory=list)

    def find(self, name: str) -> TreeConfiguration | None:
        for c in self.configurations:
            if c.name == name:
                return c
        return None

    def active_config(self) -> TreeConfiguration:
        c = self.find(self.active)
        if c is not None:
            return c
        if self.configurations:
            self.active = self.configurations[0].name
            return self.configurations[0]
        raise ValueError("TreeConfigurationSet has no configurations")


def default_tree_configuration_set() -> TreeConfigurationSet:
    """Build a one-entry tree config set called 'default'."""
    return TreeConfigurationSet(
        active="default",
        configurations=[TreeConfiguration(name="default")],
    )


def tree_sidecar_path(tree_path: str | Path) -> Path:
    p = Path(tree_path)
    return p.with_name(p.name + TREE_SIDECAR_SUFFIX)


def load_tree_configs(tree_path: str | Path) -> TreeConfigurationSet | None:
    path = tree_sidecar_path(tree_path)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return tree_configs_from_dict(data)


def save_tree_configs(
    tree_path: str | Path, cfg_set: TreeConfigurationSet
) -> None:
    path = tree_sidecar_path(tree_path)
    path.write_text(
        json.dumps(tree_configs_to_dict(cfg_set), indent=2),
        encoding="utf-8",
    )


def tree_configs_to_dict(cfg_set: TreeConfigurationSet) -> dict[str, Any]:
    return {
        "schema_version": CONFIGS_SCHEMA_VERSION,
        "active": cfg_set.active,
        "configurations": [
            {"name": c.name, "tool_configs": dict(c.tool_configs)}
            for c in cfg_set.configurations
        ],
    }


def tree_configs_from_dict(data: dict[str, Any]) -> TreeConfigurationSet:
    v = data.get("schema_version", CONFIGS_SCHEMA_VERSION)
    if v > CONFIGS_SCHEMA_VERSION:
        raise ValueError(
            f"Tree config sidecar has schema_version {v}, this build "
            f"only understands up to {CONFIGS_SCHEMA_VERSION}."
        )
    raw = data.get("configurations") or []
    configs = [
        TreeConfiguration(
            name=str(c.get("name", "")),
            tool_configs={
                str(k): str(v) for k, v in (c.get("tool_configs") or {}).items()
            },
        )
        for c in raw
    ]
    if not configs:
        configs = [TreeConfiguration(name="default")]
    active = str(data.get("active", configs[0].name))
    if not any(c.name == active for c in configs):
        active = configs[0].name
    return TreeConfigurationSet(active=active, configurations=configs)


# ── Personal configurations (user-local sidecars) ─────────────────────────

# Naming scheme: ``<stem>.NNN-scriptree.configs.json`` for tool sidecars,
# ``<stem>.NNN-scriptreetree.treeconfigs.json`` for tree sidecars.
#
# Putting the 3-digit suffix BEFORE ``scriptree`` has three benefits:
#   1. Alphabetical sort groups all variants of one tool together
#      (``robocopy.000-scriptree..., robocopy.001-scriptree...``).
#   2. A single glob ``*-scriptree.configs.json`` finds every personal
#      tool sidecar in the folder (useful for IT audit).
#   3. The shared sidecar (``robocopy.scriptree.configs.json``) has no
#      digit prefix so it never matches the personal glob.

_PERSONAL_TOOL_RE = re.compile(
    r"^(?P<stem>.+?)\.(?P<num>\d{3})-scriptree\.configs\.json$",
    re.IGNORECASE,
)
_PERSONAL_TREE_RE = re.compile(
    r"^(?P<stem>.+?)\.(?P<num>\d{3})-scriptreetree\.treeconfigs\.json$",
    re.IGNORECASE,
)


def _is_tree_path(tool_path: str | Path) -> bool:
    return str(tool_path).lower().endswith(".scriptreetree")


def _tool_stem(tool_path: str | Path) -> str:
    """Return the tool's filename without its ``.scriptree(tree)`` suffix."""
    name = Path(tool_path).name
    # Strip ``.scriptreetree`` first to avoid the shorter suffix
    # matching a tree file.
    lower = name.lower()
    if lower.endswith(".scriptreetree"):
        return name[: -len(".scriptreetree")]
    if lower.endswith(".scriptree"):
        return name[: -len(".scriptree")]
    return name


def personal_configs_path(
    tool_path: str | Path,
    *,
    suffix_num: int = 0,
    personal_dir: Path | None = None,
) -> Path:
    """Build the path to a personal sidecar file for ``tool_path``.

    ``suffix_num`` is formatted as a zero-padded 3-digit string.  When
    ``personal_dir`` is None the caller is responsible for resolving
    it via :func:`scriptree.core.app_settings.get_personal_configs_dir`
    and passing the result — keeping configs.py Qt-free.
    """
    if personal_dir is None:
        from .app_settings import get_personal_configs_dir
        personal_dir = get_personal_configs_dir()
    stem = _tool_stem(tool_path)
    num = f"{int(suffix_num):03d}"
    if _is_tree_path(tool_path):
        fname = f"{stem}.{num}-scriptreetree.treeconfigs.json"
    else:
        fname = f"{stem}.{num}-scriptree.configs.json"
    return personal_dir / fname


def find_personal_config_candidates(
    tool_path: str | Path,
    *,
    personal_dir: Path | None = None,
) -> list[Path]:
    """Find all personal sidecar files whose filename stem matches.

    Returns candidates sorted numerically by the 3-digit suffix.  The
    caller MUST still verify the file's internal ``source_filename``
    matches the tool being loaded — two different tools may share the
    same stem by coincidence.
    """
    if personal_dir is None:
        from .app_settings import get_personal_configs_dir
        personal_dir = get_personal_configs_dir()
    if not personal_dir.is_dir():
        return []
    stem = _tool_stem(tool_path)
    is_tree = _is_tree_path(tool_path)
    regex = _PERSONAL_TREE_RE if is_tree else _PERSONAL_TOOL_RE

    results: list[tuple[int, Path]] = []
    for entry in personal_dir.iterdir():
        if not entry.is_file():
            continue
        m = regex.match(entry.name)
        if m is None:
            continue
        if m.group("stem").lower() != stem.lower():
            continue
        results.append((int(m.group("num")), entry))
    results.sort(key=lambda t: t[0])
    return [p for _, p in results]


def next_available_suffix_num(
    tool_path: str | Path,
    *,
    personal_dir: Path | None = None,
) -> int:
    """Return max(existing suffix numbers) + 1, or 0 if none exist."""
    cands = find_personal_config_candidates(
        tool_path, personal_dir=personal_dir
    )
    if not cands:
        return 0
    regex = (
        _PERSONAL_TREE_RE if _is_tree_path(tool_path) else _PERSONAL_TOOL_RE
    )
    nums = []
    for p in cands:
        m = regex.match(p.name)
        if m is not None:
            nums.append(int(m.group("num")))
    return (max(nums) + 1) if nums else 0


def load_personal_configs_for(
    tool_path: str | Path,
    *,
    personal_dir: Path | None = None,
) -> tuple[ConfigurationSet | None, list[Path]]:
    """Find the personal sidecar for ``tool_path``.

    Returns a ``(cfg_set, candidates)`` pair:

    - If exactly one candidate's ``source_filename`` matches AND its
      ``source_locations`` contains the tool's parent directory, returns
      ``(cfg_set, [])``.
    - If there are filename-matching candidates but none by location,
      returns ``(None, matches)`` so the caller can prompt the user.
    - If no filename-matching candidate exists, returns ``(None, [])``.
    """
    tool_abs = Path(tool_path).resolve()
    tool_filename = tool_abs.name
    tool_parent = str(tool_abs.parent)

    candidates = find_personal_config_candidates(
        tool_path, personal_dir=personal_dir
    )
    filename_matches: list[tuple[Path, ConfigurationSet]] = []
    for cand in candidates:
        try:
            data = json.loads(cand.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cfg_set = configs_from_dict(data)
        if cfg_set.source_filename.lower() != tool_filename.lower():
            continue
        filename_matches.append((cand, cfg_set))

    # Look for a location match among filename matches.
    for cand, cfg_set in filename_matches:
        locs_normalized = [
            str(Path(loc).resolve()).lower()
            for loc in cfg_set.source_locations
        ]
        if str(Path(tool_parent).resolve()).lower() in locs_normalized:
            return cfg_set, []

    if filename_matches:
        return None, [c for c, _ in filename_matches]
    return None, []


def save_personal_configs(
    tool_path: str | Path,
    cfg_set: ConfigurationSet,
    *,
    suffix_num: int = 0,
    personal_dir: Path | None = None,
) -> Path:
    """Write ``cfg_set`` to a personal sidecar for ``tool_path``.

    Automatically sets ``cfg_set.source_filename`` to the tool's
    filename and ensures the tool's parent directory is in
    ``source_locations``. Returns the path written.
    """
    tool_abs = Path(tool_path).resolve()
    cfg_set.source_filename = tool_abs.name
    parent = str(tool_abs.parent)
    if parent not in cfg_set.source_locations:
        cfg_set.source_locations.append(parent)
    path = personal_configs_path(
        tool_path, suffix_num=suffix_num, personal_dir=personal_dir
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(configs_to_dict(cfg_set), indent=2), encoding="utf-8"
    )
    return path


def save_personal_configs_at(
    path: Path, cfg_set: ConfigurationSet
) -> None:
    """Write ``cfg_set`` to the exact given path (no name mangling)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(configs_to_dict(cfg_set), indent=2), encoding="utf-8"
    )


def add_location_to_personal(
    personal_path: Path,
    tool_abs_parent: str,
    *,
    replace: bool = False,
) -> None:
    """Mutate an existing personal sidecar's ``source_locations``.

    - ``replace=False`` (default): append ``tool_abs_parent`` if not
      already present.
    - ``replace=True``: replace the list with just ``[tool_abs_parent]``.
    """
    data = json.loads(personal_path.read_text(encoding="utf-8"))
    cfg_set = configs_from_dict(data)
    if replace:
        cfg_set.source_locations = [tool_abs_parent]
    elif tool_abs_parent not in cfg_set.source_locations:
        cfg_set.source_locations.append(tool_abs_parent)
    save_personal_configs_at(personal_path, cfg_set)
