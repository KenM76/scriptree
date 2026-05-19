"""``python -m scriptree`` entry point.

## For humans

Forwards to :func:`scriptree.main.main`, which itself dispatches to the
``validate`` / ``migrate`` CLI subcommands when invoked as
``python -m scriptree validate <path>`` / ``python -m scriptree migrate
<path>``, and otherwise opens the GUI.

Having this module lets ``python -m scriptree …`` work the same way
``python -m pip …`` does — without it, Python errors with
"No module named scriptree.__main__".

## For maintainers / LLMs

- This is a thin shim only: its sole job is ``sys.exit(main())`` under
  the ``__name__ == "__main__"`` guard. Keep all dispatch/argument
  logic in ``scriptree.main`` so the two entry points (this and the
  ``console_scripts`` entry) stay behaviourally identical.
- ``main()`` returns an int process exit code (``app.exec()`` or a CLI
  subcommand return); it is passed straight to ``sys.exit``.
- Import stays minimal (``sys`` + ``.main.main``) so the headless CLI
  path is not forced to import Qt at module load.
"""
from __future__ import annotations

import sys

from .main import main

if __name__ == "__main__":
    sys.exit(main())
