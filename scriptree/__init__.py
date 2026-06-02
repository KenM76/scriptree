"""ScripTree — Universal GUI generator for CLI tools.

## For humans

The package root. Importing ``scriptree`` exposes ``__version__``
(the runtime version string the About dialogs display) and
``__build_date__`` (when this version was cut — also shown in the
About dialogs so the user can tell "is this the build I just
pulled?" at a glance).

## For maintainers / LLMs

- ``__version__`` is the single source of truth for the runtime
  version string and MUST stay in lockstep with
  ``pyproject.toml::project.version`` — a test enforces equality, so
  bumping one without the other fails CI.
- ``__build_date__`` is bumped TOGETHER with ``__version__`` to a
  human-readable ``"YYYY-MM-DD HH:MM UTC"`` timestamp at the moment
  the version is cut.  No CI guard — drift is annoying but not
  load-bearing; keep it close-enough by always editing both lines in
  the same commit.
- ``scriptree.help_dialog.show_about`` and other About surfaces read
  both globals so the user always sees exactly the number + build
  date the package advertises; build/packaging tooling reads the
  ``pyproject.toml`` copy.  The version strings must not drift.
- Keep this module import-light: it is imported on the headless
  ``validate`` / ``migrate`` CLI path, so it must not pull in Qt.
"""

# ===========================================================================
# BYTECODE-WRITE GUARD — must run before any sub-module import.
# ===========================================================================
# Setting ``sys.dont_write_bytecode = True`` here means Python skips
# emitting ``__pycache__/*.pyc`` files for every module imported AFTER
# this line.  ScripTree installs commonly live in Dropbox / OneDrive /
# Google Drive folders, where a fresh launch otherwise spawns hundreds
# of ``.pyc`` writes that the cloud client hashes and uploads,
# paralysing the sync engine for 15-30 seconds per launch.  The launcher
# ``.bat`` files set ``PYTHONDONTWRITEBYTECODE=1`` as a first line of
# defence; this is the in-Python belt-and-suspenders so the guarantee
# holds regardless of how ScripTree is started (direct ``python -m``
# invocation, frozen PyInstaller exe, tests, ad-hoc REPL import, ...).
#
# DO NOT remove or weaken this guard.  See
# ``docs/LLM/no_bytecode_policy.md`` for the rationale and the full
# list of things you must not do (flip this back to False, pre-compile
# ``.pyc`` files during packaging, set ``PYTHONPYCACHEPREFIX`` pointing
# into the install tree, etc.).
import sys as _sys
_sys.dont_write_bytecode = True
del _sys


# Source of truth for the runtime version string.  Bump in lockstep
# with ``pyproject.toml::project.version`` — one is read by tools that
# import the package (the About dialogs read ``scriptree.__version__``
# so the user always sees the same number the package advertises),
# the other is consumed by build / package tooling that walks
# ``pyproject.toml`` directly.
__version__ = "0.8.0a25"

# When this version was cut.  Bumped together with ``__version__``
# in the same commit.  Format: ``"YYYY-MM-DD HH:MM TZ"`` where TZ
# is the abbreviation of the build machine's local timezone (e.g.
# ``EDT`` / ``EST`` for the project author).  v0.6.36 switched
# from UTC at user request — the user wants the timestamp they see
# in the About dialog to match their wall clock, not a converted
# value.  Shown in the About dialogs alongside the version number
# so the user can tell which build they're running when revisions
# happen quickly.
__build_date__ = "2026-06-02 15:46 EDT"
