"""Help-text parsing package.

## For humans

Public API:

- :func:`probe` — run an executable's ``--help`` and parse the result.
- :func:`parse_text` — parse an already-captured help string.
- :class:`PluginRegistry` — registry of parser plugins.
- :func:`get_default_registry` — lazily-built default registry.

Parsers themselves live in the :mod:`scriptree.core.parser.plugins`
subpackage. Each parser is a module with ``NAME``, ``PRIORITY``, and
a ``detect(text) -> ToolDef | None`` function. User-supplied plugins
can be loaded from directories listed in ``SCRIPTREE_PARSERS_DIR``.

## For maintainers / LLMs

- This package operates at EDITOR time: it converts a CLI's
  ``--help`` text into a ToolDef; it is not on the tool-run path.
- ``__all__`` here is the public surface. Re-exports come from
  ``.plugin_api`` (registry/loaders) and ``.probe`` (probe /
  parse_text / ProbeResult). Adding/removing a public name =>
  update ``__all__`` AND the originating module's ``__all__``.
- ``parse_text`` parses a pre-captured string (no subprocess);
  ``probe`` spawns the exe. Tests and the "re-parse cached text"
  button rely on ``parse_text`` staying probe-free.
- User plugins from ``SCRIPTREE_PARSERS_DIR`` load only when the
  ``load_user_plugins`` permission is granted (enforced in
  ``plugin_api.get_default_registry``), not unconditionally.
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
