"""``python -m scriptree`` entry point.

Forwards to :func:`scriptree.main.main`, which itself dispatches to the
``validate`` / ``migrate`` CLI subcommands when invoked as
``python -m scriptree validate <path>`` / ``python -m scriptree migrate
<path>``, and otherwise opens the GUI.

Having this module lets ``python -m scriptree …`` work the same way
``python -m pip …`` does — without it, Python errors with
"No module named scriptree.__main__".
"""
from __future__ import annotations

import sys

from .main import main

if __name__ == "__main__":
    sys.exit(main())
