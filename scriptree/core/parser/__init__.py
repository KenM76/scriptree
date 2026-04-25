"""Help-text parsing package.

Public API:

- :func:`probe` — run an executable's ``--help`` and parse the result.
- :func:`parse_text` — parse an already-captured help string.
- :class:`PluginRegistry` — registry of parser plugins.
- :func:`get_default_registry` — lazily-built default registry.

Parsers themselves live in the :mod:`scriptree.core.parser.plugins`
subpackage. Each parser is a module with ``NAME``, ``PRIORITY``, and
a ``detect(text) -> ToolDef | None`` function. User-supplied plugins
can be loaded from directories listed in ``SCRIPTREE_PARSERS_DIR``.
"""
from .plugin_api import (
    PluginInfo,
    PluginRegistry,
    get_default_registry,
    load_builtin_plugins,
    load_plugins_from_dir,
    reset_default_registry,
)
from .probe import ProbeResult, parse_text, probe

__all__ = [
    "probe",
    "parse_text",
    "ProbeResult",
    "PluginInfo",
    "PluginRegistry",
    "get_default_registry",
    "load_builtin_plugins",
    "load_plugins_from_dir",
    "reset_default_registry",
]
