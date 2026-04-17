"""Built-in parser plugins.

Every module in this package whose name does not start with ``_`` is
discovered by the plugin loader at startup. Modules with a leading
underscore (``_core.py``) are helper modules shared between plugins
and are deliberately excluded from discovery.

See ``scriptree.core.parser.plugin_api`` for the plugin protocol and
instructions on writing custom parsers.
"""
