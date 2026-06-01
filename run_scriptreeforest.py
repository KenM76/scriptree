#!/usr/bin/env python3
"""ScripTree forest launcher.

Thin wrapper around ``run_scriptreering.py`` that adds the
``--forest`` argv entry so the cell shell starts in forest mode.

Why a separate launcher instead of just an extra flag the user has
to remember?  Two reasons:

  1. The forest is a different mental model (top-level workspace,
     auto-discovery, persistent layout) — having its own .bat /
     desktop shortcut makes the entry point obvious.
  2. We can pin a different single-instance namespace later if
     forest sessions need to be isolated from bare ring sessions
     (currently they share the primary, which is the right
     default).

Everything else — Python search, dependency check, sibling-import
shim, self-healing — is identical to ``run_scriptreering.py`` and
runs verbatim because we delegate to its main().
"""
import sys

# Bytecode-write guard — see docs/LLM/no_bytecode_policy.md.  MUST be
# set before any other import.  Prevents ``__pycache__/*.pyc`` writes
# that would trigger Dropbox/OneDrive sync storms when ScripTree is
# installed in a cloud-synced folder.  Do not remove.
sys.dont_write_bytecode = True

import os
from pathlib import Path

if __name__ == "__main__":
    # Inject the forest flag and chain into the ring launcher's
    # main().  Using the env var keeps argv tidy for downstream
    # logging — the user sees "run_scriptreeforest" in the title
    # bar and process list rather than a confusing "--forest".
    os.environ.setdefault("SCRIPTREE_FOREST_MODE", "1")

    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))

    # The ring launcher does its own ``_check_python_version``,
    # ``_inject_vendored_libs``, ``_self_heal_bundled_python``, and
    # ``_publish_scriptree_env`` at module-load time — importing
    # the module triggers all of that.  Then we delegate to the
    # same ``main()`` it imports from ``scriptree.shell.ring_main``.
    import run_scriptreering  # type: ignore[import-not-found]
    sys.exit(run_scriptreering.main())
