"""ScripTree — Universal GUI generator for CLI tools.

## For humans

The package root. Importing ``scriptree`` exposes ``__version__``,
the runtime version string the About dialogs display.

## For maintainers / LLMs

- ``__version__`` is the single source of truth for the runtime
  version string and MUST stay in lockstep with
  ``pyproject.toml::project.version`` — a test enforces equality, so
  bumping one without the other fails CI.
- ``scriptree.help_dialog.show_about`` and other About surfaces read
  ``scriptree.__version__`` so the user always sees exactly the number
  the package advertises; build/packaging tooling reads the
  ``pyproject.toml`` copy. The two must not drift.
- Keep this module import-light: it is imported on the headless
  ``validate`` / ``migrate`` CLI path, so it must not pull in Qt.
"""

# Source of truth for the runtime version string.  Bump in lockstep
# with ``pyproject.toml::project.version`` — one is read by tools that
# import the package (the About dialogs read ``scriptree.__version__``
# so the user always sees the same number the package advertises),
# the other is consumed by build / package tooling that walks
# ``pyproject.toml`` directly.
__version__ = "0.6.22"
