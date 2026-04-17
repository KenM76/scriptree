"""Parser plugin API.

A parser plugin is a Python module that exposes three required
attributes::

    NAME: str                                 # unique identifier
    PRIORITY: int                             # lower = tried first
    detect(help_text: str) -> ToolDef | None  # the parser itself

And optionally::

    DESCRIPTION: str     # human-readable blurb (shown in the UI)
    ENABLED: bool        # default-enabled flag (default True)

Plugins are loaded from two sources:

1. **Built-in** — every module under ``scriptree.core.parser.plugins``
   whose name does *not* start with ``_``. The underscore convention
   hides shared helper modules (``_core.py``) from the discovery pass.

2. **User** — any directory listed in the ``SCRIPTREE_PARSERS_DIR``
   environment variable, separated by ``os.pathsep`` (``;`` on
   Windows, ``:`` on Unix). Each ``.py`` file in such a directory is
   imported as a standalone module and checked for the plugin
   attributes. Files whose names start with ``_`` are skipped.

The registry runs plugins in ascending priority order; the first one
whose ``detect`` returns a non-None ``ToolDef`` wins. A built-in
``heuristic`` plugin at ``PRIORITY=999`` is the catch-all — it always
returns a result, so probes never fall through to nothing.

## Writing a new plugin

Drop a file like this into any directory on ``SCRIPTREE_PARSERS_DIR``::

    # my_custom_parser.py
    from scriptree.core.model import ToolDef, ParamDef

    NAME = "my_custom"
    PRIORITY = 15               # between argparse (10) and click (20)
    DESCRIPTION = "Parser for MyTool's weird --manual format"

    def detect(help_text: str) -> ToolDef | None:
        if "MYTOOL MANUAL" not in help_text:
            return None
        # ... build and return a ToolDef ...
        return ToolDef(...)

Restart ScripTree. Done.

## Testing

Tests that want a clean registry should call ``reset_default_registry()``
between runs. The singleton is lazy so the next access rebuilds it.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import pkgutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..model import ToolDef

logger = logging.getLogger(__name__)


# --- plugin info dataclass -------------------------------------------------

@dataclass
class PluginInfo:
    """Metadata + callable for one loaded parser plugin."""

    name: str
    priority: int
    description: str
    enabled: bool
    detect: Callable[[str], ToolDef | None]
    source: str
    """Origin of the plugin — module name for built-ins, file path for
    user plugins. Used by the registry's debug views."""


# --- registry --------------------------------------------------------------

@dataclass
class PluginRegistry:
    """Ordered collection of parser plugins.

    ``add()`` deduplicates by name (later additions replace earlier
    ones), which is how user plugins override built-ins — give your
    user plugin the same ``NAME`` as the one you want to replace.
    """

    plugins: list[PluginInfo] = field(default_factory=list)

    def add(self, info: PluginInfo) -> None:
        self.plugins = [p for p in self.plugins if p.name != info.name]
        self.plugins.append(info)
        self.plugins.sort(key=lambda p: (p.priority, p.name))

    def parse(self, help_text: str) -> ToolDef | None:
        """Run plugins in priority order; return the first hit.

        A plugin that raises is logged and skipped — one bad plugin
        doesn't kill the pipeline.
        """
        for plugin in self.plugins:
            if not plugin.enabled:
                continue
            try:
                result = plugin.detect(help_text)
            except Exception as e:  # noqa: BLE001 - plugins are untrusted
                logger.warning(
                    "Parser plugin %r raised %s: %s; skipping.",
                    plugin.name, type(e).__name__, e,
                )
                continue
            if result is not None:
                return result
        return None

    def names(self) -> list[str]:
        return [p.name for p in self.plugins]

    def by_name(self, name: str) -> PluginInfo | None:
        for p in self.plugins:
            if p.name == name:
                return p
        return None


# --- module → PluginInfo adapter ------------------------------------------

def _plugin_from_module(module: Any, source: str) -> PluginInfo | None:
    """Extract plugin info from an imported module.

    Returns None if the module lacks the required attributes, which
    is how we silently ignore helper modules like ``_core.py`` and
    accidental Python files in plugin directories.
    """
    name = getattr(module, "NAME", None)
    detect = getattr(module, "detect", None)
    if name is None or not callable(detect):
        return None
    try:
        priority = int(getattr(module, "PRIORITY", 100))
    except (TypeError, ValueError):
        logger.warning(
            "Plugin %s has invalid PRIORITY; defaulting to 100.", source
        )
        priority = 100
    return PluginInfo(
        name=str(name),
        priority=priority,
        description=str(getattr(module, "DESCRIPTION", "")),
        enabled=bool(getattr(module, "ENABLED", True)),
        detect=detect,
        source=source,
    )


# --- loaders ---------------------------------------------------------------

def load_builtin_plugins(registry: PluginRegistry) -> None:
    """Load every module under ``scriptree.core.parser.plugins`` whose
    name does not start with an underscore."""
    from . import plugins as plugins_pkg

    for mod_info in pkgutil.iter_modules(plugins_pkg.__path__):
        if mod_info.name.startswith("_"):
            continue
        full = f"{plugins_pkg.__name__}.{mod_info.name}"
        try:
            module = importlib.import_module(full)
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to import built-in plugin %s: %s", full, e)
            continue
        info = _plugin_from_module(module, full)
        if info is None:
            logger.debug("Module %s is not a valid parser plugin; skipping.", full)
            continue
        registry.add(info)


def load_plugins_from_dir(registry: PluginRegistry, dir_path: Path) -> int:
    """Load every ``.py`` file in ``dir_path`` as a user plugin.

    Returns the number of plugins successfully loaded. Files whose
    names start with ``_`` are skipped (same convention as built-ins).
    """
    if not dir_path.is_dir():
        return 0
    loaded = 0
    for py_file in sorted(dir_path.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        module_name = f"scriptree_user_parser_{py_file.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                logger.warning("Cannot create spec for %s; skipping.", py_file)
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to load user plugin %s: %s", py_file, e)
            continue
        info = _plugin_from_module(module, str(py_file))
        if info is None:
            logger.debug(
                "User file %s is not a valid parser plugin; skipping.", py_file
            )
            continue
        registry.add(info)
        loaded += 1
    return loaded


# --- default registry singleton -------------------------------------------

_default_registry: PluginRegistry | None = None


def get_default_registry() -> PluginRegistry:
    """Return the lazily-initialized default registry.

    The first call loads built-in plugins. User plugins from
    ``SCRIPTREE_PARSERS_DIR`` are only loaded if the
    ``load_user_plugins`` permission is granted. Subsequent calls
    return the cached registry. Call ``reset_default_registry()`` to
    force a rebuild (useful in tests).
    """
    global _default_registry
    if _default_registry is None:
        reg = PluginRegistry()
        load_builtin_plugins(reg)
        # User plugins are a security-sensitive operation — only load
        # if the permission system allows it. Import here to avoid
        # circular imports at module level.
        try:
            from ..permissions import get_app_permissions
            perms = get_app_permissions()
            can_load_user = perms.can("load_user_plugins")
        except Exception:  # noqa: BLE001
            can_load_user = False
        if can_load_user:
            user_dirs = os.environ.get("SCRIPTREE_PARSERS_DIR", "")
            for raw in user_dirs.split(os.pathsep):
                raw = raw.strip()
                if raw:
                    loaded = load_plugins_from_dir(reg, Path(raw))
                    if loaded:
                        logger.info(
                            "Loaded %d user plugin(s) from %s", loaded, raw
                        )
        else:
            logger.debug(
                "User plugin loading disabled by permissions."
            )
        _default_registry = reg
    return _default_registry


def reset_default_registry() -> None:
    """Drop the cached default registry. The next ``get_default_registry()``
    call will rebuild it from scratch."""
    global _default_registry
    _default_registry = None


__all__ = [
    "PluginInfo",
    "PluginRegistry",
    "load_builtin_plugins",
    "load_plugins_from_dir",
    "get_default_registry",
    "reset_default_registry",
]
