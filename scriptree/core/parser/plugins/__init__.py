"""Built-in parser plugins.

## For humans

Every module in this package whose name does not start with ``_`` is
discovered by the plugin loader at startup. Modules with a leading
underscore (``_core.py``) are helper modules shared between plugins
and are deliberately excluded from discovery.

See ``scriptree.core.parser.plugin_api`` for the plugin protocol and
instructions on writing custom parsers.

## For maintainers / LLMs

- These plugins run at EDITOR time (turning a CLI's ``--help`` into a
  ToolDef), never at tool-run time.
- Discovery is by leading-underscore convention only: a new shared
  helper MUST start with ``_`` or the loader will try to treat it as
  a plugin and ``_plugin_from_module`` will (silently) reject it.
- A valid plugin module must expose ``NAME``, ``PRIORITY``, and a
  callable ``detect``; optionally ``DESCRIPTION``/``ENABLED``. Change
  the protocol here => also update ``plugin_api._plugin_from_module``.
- Priority ordering is global across this package and user dirs;
  ``heuristic`` at ``PRIORITY=999`` is the guaranteed catch-all, so
  don't add another always-returns plugin at a lower priority or it
  will starve the specific parsers.
"""
