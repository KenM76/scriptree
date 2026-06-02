#!/usr/bin/env python3
"""Revert the per-tool ``SCRIPTREE_HOME`` patch from
bulk_update_find_combridge.py.

Tools shouldn't need to know about ScripTree's install layout --
the runner should make the upward-walk-from-script-location
strategy succeed by creating a ``lib`` junction at the personal
apps root.  See the v0.8.0a25 commit that adds that.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TARGET_ROOTS = [
    Path(r"D:\Dev\ScripTreeAppProjects"),
    Path(r"C:\Users\Ken\AppData\Local\ScripTree\Apps"),
]


# Match the v0.8.0a25 SCRIPTREE_HOME-checking body and replace it
# with the original two-line "for base in [start, *start.parents]"
# walk.  Anchored on the comment block so we don't strip code that
# happens to use os.environ for other reasons.
NEW_BODY_RE = re.compile(
    r"    # v0\.8\.0a25\+: ScripTree's runner exports SCRIPTREE_HOME so\n"
    r"    # apps installed outside the install tree \(e\.g\. under\n"
    r"    # %LOCALAPPDATA%/ScripTree/Apps\) can still find the bundled\n"
    r"    # combridge\.exe\.  We prefer that env var because the upward\n"
    r"    # walk below anchors at the script's own folder, which on a\n"
    r"    # personal-apps install is unrelated to the ScripTree tree\.\n"
    r"    home = os\.environ\.get\(\"SCRIPTREE_HOME\"\)\n"
    r"    if home:\n"
    r"        candidate = Path\(home\) / COMBRIDGE_REL\n"
    r"        if candidate\.is_file\(\):\n"
    r"            return candidate\n"
    r"    # Fall back to the upward walk for legacy launches\.\n"
    r"    for base in \[start, \*start\.parents\]:\n",
    re.DOTALL,
)
ORIGINAL_BODY_REPLACEMENT = "    for base in [start, *start.parents]:\n"


def update_one(path: Path) -> str:
    src = path.read_text(encoding="utf-8")
    new_src, n = NEW_BODY_RE.subn(ORIGINAL_BODY_REPLACEMENT, src, count=1)
    if n == 0:
        return "no-change"
    path.write_text(new_src, encoding="utf-8")
    return "reverted"


def main() -> int:
    for root in TARGET_ROOTS:
        if not root.exists():
            print(f"missing root: {root}", file=sys.stderr)
            continue
        for f in sorted(root.rglob("*.py")):
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            if "SCRIPTREE_HOME" not in text:
                continue
            outcome = update_one(f)
            if outcome != "no-change":
                print(f"  {outcome:9s}  {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
