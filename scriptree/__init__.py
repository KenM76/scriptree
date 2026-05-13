"""ScripTree — Universal GUI generator for CLI tools."""

# Source of truth for the runtime version string.  Bump in lockstep
# with ``pyproject.toml::project.version`` — one is read by tools that
# import the package (the About dialogs read ``scriptree.__version__``
# so the user always sees the same number the package advertises),
# the other is consumed by build / package tooling that walks
# ``pyproject.toml`` directly.
__version__ = "0.5.2"
