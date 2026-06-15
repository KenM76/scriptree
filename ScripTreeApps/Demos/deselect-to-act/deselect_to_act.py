#!/usr/bin/env python3
"""
deselect_to_act.py — demo backing script for the v0.8.0a50
``emit: "unselected"`` checkbox_list feature.

Receives a single positional arg: a comma-joined list of the
feature names the user UNTICKED (the "act on these" set), or
an empty string when the user left every box ticked (no-op).

The print-out shows what a real back-end would do.  The point
is to see in the Output dock that:

  * Open + Run = "(nothing to disable)" -- form opens
    all-pre-checked, so the unselected set is initially empty.
  * Untick one box + Run = exactly that one feature in the act
    list.
  * Untick the master + Run = every feature in the act list
    (the "disable everything" case).
"""
from __future__ import annotations

import sys


def main(argv: list[str]) -> int:
    raw = argv[1] if len(argv) >= 2 else ""
    targets = [t for t in raw.split(",") if t.strip()]
    if not targets:
        print("(nothing to disable -- every feature is still ticked)")
        return 0
    print(f"Would disable the following {len(targets)} feature(s):")
    for t in targets:
        print(f"  - {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
