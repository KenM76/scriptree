#!/usr/bin/env python3
"""Replace the two-tier ``find_combridge`` helper with a bare-name
``combridge.exe`` call in every Office tool.

Why
---
v0.8.0a25 made the ScripTree runner inject ``<install>/lib/combridge``
into the spawned tool's ``PATH``.  That makes ``combridge.exe``
resolvable by bare name without any discovery code.  The 8-line
``find_combridge`` helper -- env-var check + upward walk fallback --
is now dead weight in the common case.

What this script edits
----------------------
Each tool file has four boilerplate blocks the script removes /
rewrites:

  1. ``COMBRIDGE_REL = Path("lib") / "combridge" / "combridge.exe"``
     constant -- deleted (no longer referenced).
  2. ``def find_combridge(start: Path) -> Path | None: ...``
     function -- deleted (whole def + body).
  3. The call site::

         combridge = find_combridge(here)
         if combridge is None:
             print(
                 "ERROR: could not locate ...",
                 file=sys.stderr,
             )
             return 1

     -- deleted.  The runner guarantees ``combridge.exe`` is on
     PATH; if it ever isn't, ``subprocess.run`` raises
     ``FileNotFoundError`` with a clear OS message and the tool
     exits with that.
  4. ``[str(combridge), <PLUGIN>, "run-script", ...]`` in the
     ``subprocess.run`` call -- replaced with
     ``["combridge.exe", <PLUGIN>, "run-script", ...]``.

Idempotent: re-running on a file that no longer references
``find_combridge`` is a no-op.  Safe on the deployed copies under
``%LOCALAPPDATA%`` and ``R:`` as well as the source tree.

Run via::

    python scripts/bulk_simplify_find_combridge.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TARGET_ROOTS = [
    Path(r"D:\Dev\ScripTreeAppProjects"),
    Path(r"C:\Users\Ken\AppData\Local\ScripTree\Apps"),
    Path(r"R:\ScripTree\ScripTreeApps"),
    Path(r"R:\ScripTreeApps"),
    Path(r"C:\Users\Ken\OneDrive\Kens_Projects\Claude\Software\ScripTreeApps"),
    Path(r"C:\Users\Ken\OneDrive\Kens_Projects\Claude\Software\ScripTree\ScripTreeApps"),
]


# --- Edit 1: COMBRIDGE_REL constant assignment. ----------------------------
# Optional trailing comment-block context: some files don't have one.
COMBRIDGE_REL_RE = re.compile(
    r"^COMBRIDGE_REL\s*=\s*Path\(\"lib\"\)\s*/\s*\"combridge\"\s*/\s*\"combridge\.exe\"\n",
    re.MULTILINE,
)


# --- Edit 2: find_combridge function body (env-var + walk variant). --------
# The function starts at ``def find_combridge`` and ends at ``return None``
# followed by a blank line.  We use a non-greedy match for the body, anchored
# on the first blank-line-after-return-None.
FIND_COMBRIDGE_RE = re.compile(
    r"^def find_combridge\(start: Path\) -> Path \| None:\n"
    r"(?:    .*\n|\n)+?"            # docstring + body lines (non-greedy)
    r"    return None\n"
    r"\n",
    re.MULTILINE,
)


# --- Edit 3: the assignment + None-check at the call site. -----------------
# Pattern:
#     combridge = find_combridge(here)
#     if combridge is None:
#         print(
#             "ERROR: could not locate ..."
#             ...
#             file=sys.stderr,
#         )
#         return 1
#
# Plus an optional trailing blank line.  Some files have slightly different
# indentation depth (always 4 spaces in practice) and slightly different
# wording inside the print() -- we anchor on the structure, not the prose.
CALL_SITE_RE = re.compile(
    r"^    combridge = find_combridge\(here\)\n"
    r"    if combridge is None:\n"
    r"        print\(\n"
    r"(?:            .*\n)+?"        # message lines (non-greedy)
    r"            file=sys\.stderr,\n"
    r"        \)\n"
    r"        return 1\n"
    r"\n?",                          # optional trailing blank line
    re.MULTILINE,
)


# --- Edit 4: subprocess.run argv -- replace ``str(combridge)`` with
# ``"combridge.exe"``.  This is the only literal change to the call.
ARGV_RE = re.compile(r"\bstr\(combridge\)")


# --- Edit 5 (light cosmetic): the module-docstring line that mentions
# walking upward is no longer accurate.  We don't try to rewrite the
# whole docstring, but we do delete the specific sentence so it doesn't
# mislead future maintainers.
WALK_DOC_RE = re.compile(
    r"combridge is located by walking up from this file looking for\n"
    r"``lib/combridge/combridge\.exe`` — a relative discovery so the catalog stays\n"
    r"portable \(no absolute path baked in, per the project's path rule\)\. This\n"
    r"repo does NOT bundle combridge; the app is deployed into a ScripTree install\n"
    r"that ships ``lib/combridge/combridge\.exe``\.",
)
WALK_DOC_REPLACEMENT = (
    "combridge is invoked via a bare ``combridge.exe`` call -- ScripTree's runner\n"
    "prepends ``<install>/lib/combridge`` to ``PATH`` on every spawned tool, so the\n"
    "OS resolves the bundled binary by name.  No discovery code needed; if a tool is\n"
    "launched outside ScripTree (e.g. direct ``python tool.py`` for debugging), set\n"
    "``SCRIPTREE_HOME`` and prepend ``%SCRIPTREE_HOME%/lib/combridge`` to PATH\n"
    "yourself, or just launch through ScripTree's editor."
)


def update_one(path: Path) -> str:
    """Returns "skip" / "already-simplified" / "updated" / "no-match"."""
    try:
        src = path.read_text(encoding="utf-8")
    except OSError:
        return "skip"

    # Already done?  Look for the bare-name call without find_combridge.
    if "def find_combridge" not in src:
        return "already-simplified"

    original = src

    # Apply edits in order (so we don't try to operate on already-changed text).
    src = COMBRIDGE_REL_RE.sub("", src)
    src = FIND_COMBRIDGE_RE.sub("", src)
    src = CALL_SITE_RE.sub("", src)
    src = ARGV_RE.sub('"combridge.exe"', src)
    src = WALK_DOC_RE.sub(WALK_DOC_REPLACEMENT, src)

    # Belt-and-suspenders: verify the file no longer references find_combridge
    # or COMBRIDGE_REL.  If it does, the regex didn't catch something and we
    # should NOT save -- bail loudly.
    if "find_combridge" in src or "COMBRIDGE_REL" in src:
        return "no-match"
    if "str(combridge)" in src:
        return "no-match"
    if src == original:
        return "no-match"

    path.write_text(src, encoding="utf-8")
    return "updated"


def main() -> int:
    rc = 0
    for root in TARGET_ROOTS:
        if not root.exists():
            print(f"missing root: {root}", file=sys.stderr)
            continue
        for f in sorted(root.rglob("*.py")):
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            if "find_combridge" not in text:
                continue
            outcome = update_one(f)
            print(f"  {outcome:18s}  {f}")
            if outcome == "no-match":
                rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
