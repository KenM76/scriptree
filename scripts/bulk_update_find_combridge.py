#!/usr/bin/env python3
"""One-shot maintenance: update every ``find_combridge`` helper to
honour the ``SCRIPTREE_HOME`` env var before falling back to the
upward walk.

Before (15 copies, two docstring variants):

    def find_combridge(start: Path) -> Path | None:
        \"\"\"Walk up from *start* looking for ...\"\"\"
        for base in [start, *start.parents]:
            candidate = base / COMBRIDGE_REL
            if candidate.is_file():
                return candidate
        return None

After (every file):

    def find_combridge(start: Path) -> Path | None:
        \"\"\"...
        ScripTree runner injects SCRIPTREE_HOME (v0.8.0a25+); when set
        and the install ships combridge, prefer that.  Falls back to
        the upward walk for legacy launches (manual python ... or
        pre-a25 runners).
        \"\"\"
        # Prefer the runner-supplied install root (works regardless
        # of where this tool was installed on disk).
        home = os.environ.get("SCRIPTREE_HOME")
        if home:
            candidate = Path(home) / COMBRIDGE_REL
            if candidate.is_file():
                return candidate
        # Fall back to the upward walk.
        for base in [start, *start.parents]:
            candidate = base / COMBRIDGE_REL
            if candidate.is_file():
                return candidate
        return None

Idempotent: re-running on a file that already has the new body is
a no-op.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


TARGET_ROOTS = [
    Path(r"D:\Dev\ScripTreeAppProjects"),
    # Already-installed personal-apps copies on Ken's machine.
    Path(r"C:\Users\Ken\AppData\Local\ScripTree\Apps"),
]


# Match the original function body exactly: ``for base in [start, *start.parents]:``
# down to the closing ``return None``.  We keep whatever docstring
# the file had (it varies across files).
OLD_BODY_RE = re.compile(
    r"(    \"\"\".*?\"\"\"\n)"                  # 1: docstring (any content)
    r"    for base in \[start, \*start\.parents\]:\n"
    r"        candidate = base / COMBRIDGE_REL\n"
    r"        if candidate\.is_file\(\):\n"
    r"            return candidate\n"
    r"    return None\n",
    re.DOTALL,
)

NEW_BODY = (
    "\\1"
    "    # v0.8.0a25+: ScripTree's runner exports SCRIPTREE_HOME so\n"
    "    # apps installed outside the install tree (e.g. under\n"
    "    # %LOCALAPPDATA%/ScripTree/Apps) can still find the bundled\n"
    "    # combridge.exe.  We prefer that env var because the upward\n"
    "    # walk below anchors at the script's own folder, which on a\n"
    "    # personal-apps install is unrelated to the ScripTree tree.\n"
    "    home = os.environ.get(\"SCRIPTREE_HOME\")\n"
    "    if home:\n"
    "        candidate = Path(home) / COMBRIDGE_REL\n"
    "        if candidate.is_file():\n"
    "            return candidate\n"
    "    # Fall back to the upward walk for legacy launches.\n"
    "    for base in [start, *start.parents]:\n"
    "        candidate = base / COMBRIDGE_REL\n"
    "        if candidate.is_file():\n"
    "            return candidate\n"
    "    return None\n"
)


# Marker line that tells us this file already has the new body.
ALREADY_DONE_MARKER = 'home = os.environ.get("SCRIPTREE_HOME")'


def update_one(path: Path) -> str:
    """Returns "skip" / "already-done" / "updated" / "no-match"."""
    src = path.read_text(encoding="utf-8")
    if ALREADY_DONE_MARKER in src:
        return "already-done"
    if "def find_combridge(start: Path)" not in src:
        return "skip"

    # The new body uses ``os.environ`` -- make sure ``os`` is imported.
    if "import os\n" not in src and "import os " not in src:
        # Insert ``import os`` after the first ``from __future__`` /
        # other top-level import we can find.
        lines = src.splitlines(keepends=True)
        insert_at = 0
        for i, line in enumerate(lines):
            if line.startswith("from __future__"):
                insert_at = i + 1
            elif line.startswith("import "):
                insert_at = i + 1
                break
        lines.insert(insert_at, "import os\n")
        src = "".join(lines)

    new_src, n = OLD_BODY_RE.subn(NEW_BODY, src, count=1)
    if n == 0:
        return "no-match"
    path.write_text(new_src, encoding="utf-8")
    return "updated"


def main() -> int:
    rc = 0
    for root in TARGET_ROOTS:
        if not root.exists():
            print(f"missing root: {root}", file=sys.stderr)
            continue
        for f in sorted(root.rglob("*.py")):
            if "find_combridge" not in f.read_text(encoding="utf-8"):
                continue
            outcome = update_one(f)
            print(f"  {outcome:13s}  {f}")
            if outcome == "no-match":
                rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
