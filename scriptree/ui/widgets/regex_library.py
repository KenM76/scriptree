"""
regex_library.py — the per-user regex-pattern library + the built-in
CommonRegex bridge.

## For humans

The regex helper dialog (``regex_helper.py``) shows two pools of
ready-to-use patterns to the user:

1. **Built-in** patterns — pulled from the vendored ``CommonRegex``
   package (``lib/pypi/commonregex.py``).  Email, phone, link, date,
   ipv4/ipv6, time, money, btc-address, credit-card, hex-color,
   street-address.  Read-only.
2. **User patterns** — saved in
   ``%APPDATA%/ScripTree/regex_library.json`` (or platform equivalent
   via ``QStandardPaths.AppDataLocation``).  The user can add their
   own labelled patterns from any regex field via the helper's
   "Add current pattern" button, and edit / delete them later.

The two pools are unified by ``LibraryEntry`` (one carrier dataclass)
so the dialog's QListWidget can mix them with a ``source`` field for
filtering and right-click affordances ("Edit" / "Delete" are only
offered for ``source == "user"``).

## For maintainers / LLMs

* ``load_user_library()`` / ``save_user_library()`` are the only
  callers that touch the JSON file -- if you add fields to
  ``LibraryEntry``, also update the schema-versioned migration block
  in ``load_user_library`` so older files still round-trip.
* The library JSON has ``"version": 1``.  Bump it AND add a migration
  branch when changing the schema; the file lives in a user data
  folder so users WILL have old copies on disk.
* ``builtin_entries()`` reads the CommonRegex module attributes at
  call time, not import time, so the function is safe to call from a
  cold start when sys.path includes ``lib/pypi``.  The list of
  attribute names is hard-coded (``_BUILTIN_NAMES``) for stability --
  if CommonRegex ever adds a new pattern upstream, manually add the
  attribute name here to surface it.  This is intentional: surfacing
  every public attribute would include test stubs and helper names
  that aren't real patterns.
* Library file is per-user (NOT per-workspace).  The user can move
  it manually if they want it to follow a forest folder; the helper
  dialog's "Export to forest folder" button (a48+) does that for
  them.  Do not silently re-route the path -- that breaks the
  expectation "edit one library, see it everywhere".
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal


# --------------------------------------------------------------------------
# Carriers
# --------------------------------------------------------------------------

@dataclass
class LibraryEntry:
    """One row in the regex library list.

    ``source`` distinguishes built-in (CommonRegex, read-only) from
    user-added entries.  ``flags`` is the inline flag string the
    user toggled on at save time (``"i"`` for IGNORECASE, etc.);
    blank when no flags.
    """
    name: str
    pattern: str
    description: str = ""
    flags: str = ""
    source: Literal["builtin", "user"] = "user"
    notes: str = ""


# --------------------------------------------------------------------------
# Built-in (CommonRegex) bridge
# --------------------------------------------------------------------------

# Hand-curated attribute names from ``commonregex.py``.  Keeping this
# list explicit (instead of using ``dir(commonregex)``) means a future
# CommonRegex upgrade can't silently surface new attributes that
# aren't real patterns (test helpers, internal regex fragments, etc.)
# and we get a deterministic ordering for the dialog.
_BUILTIN_NAMES: tuple[str, ...] = (
    "email",
    "phone",
    "link",
    "ip",          # IPv4
    "ipv6",
    "date",
    "time",
    "price",       # ``money`` is the upstream alias
    "credit_card",
    "btc_address",
    "hex_color",
    "street_address",
)

# Human-friendly metadata for each built-in.  Kept here rather than
# trying to extract from CommonRegex (which has none).  The dialog
# shows ``description`` as the secondary line under the name.
_BUILTIN_META: dict[str, dict[str, str]] = {
    "email":          {"label": "Email address",   "desc": "user@host.tld"},
    "phone":          {"label": "Phone number",    "desc": "+1 (555) 123-4567 / 555-1234 etc."},
    "link":           {"label": "URL / link",      "desc": "http://… https://… www.…"},
    "ip":             {"label": "IPv4 address",    "desc": "192.168.1.1"},
    "ipv6":           {"label": "IPv6 address",    "desc": "2001:db8::1"},
    "date":           {"label": "Date",            "desc": "Jan 1 2026, 1/1/26, 2026-01-01 …"},
    "time":           {"label": "Time of day",     "desc": "9:30, 9:30 am, 21:30"},
    "price":          {"label": "Money / price",   "desc": "$1, $1.00, $1,000.00"},
    "credit_card":    {"label": "Credit card",     "desc": "4111-1111-1111-1111"},
    "btc_address":    {"label": "Bitcoin address", "desc": "1Boa…  or  3Aa…  (legacy/P2SH)"},
    "hex_color":      {"label": "Hex colour",      "desc": "#fff, #ffffff, #ffffffff"},
    "street_address": {"label": "Street address",  "desc": "123 Main Street, 456 Oak Ave …"},
}


def builtin_entries() -> list[LibraryEntry]:
    """Return the built-in regex library, sourced from CommonRegex.

    Reads the vendored ``commonregex`` module at call time so
    ``sys.path`` doesn't need to include ``lib/pypi`` at module
    import.  Any individual attribute that fails to resolve is
    silently skipped (rather than aborting the whole list) so a
    partial CommonRegex still produces a usable library.
    """
    entries: list[LibraryEntry] = []
    try:
        import commonregex  # type: ignore[import-not-found]
    except ImportError:
        # CommonRegex isn't on the path -- happens during certain
        # headless test runs.  Return an empty built-in list rather
        # than raising; the helper dialog will simply show only
        # the user's own patterns.
        return entries
    for name in _BUILTIN_NAMES:
        obj = getattr(commonregex, name, None)
        if obj is None:
            continue
        pattern = getattr(obj, "pattern", None)
        if not pattern:
            continue
        meta = _BUILTIN_META.get(name, {})
        entries.append(LibraryEntry(
            name=meta.get("label") or name.replace("_", " ").title(),
            pattern=pattern,
            description=meta.get("desc", ""),
            flags="",  # CommonRegex patterns are flag-agnostic
            source="builtin",
            notes="",
        ))
    return entries


# --------------------------------------------------------------------------
# User library — JSON load/save
# --------------------------------------------------------------------------

LIBRARY_SCHEMA_VERSION = 1


def _user_library_path() -> Path:
    """Return the canonical path to the user's regex library JSON.

    On Windows this lands at ``%APPDATA%\\ScripTree\\regex_library.json``
    (e.g. ``C:\\Users\\Alice\\AppData\\Roaming\\ScripTree\\...``).
    On macOS / Linux Qt's ``QStandardPaths.AppDataLocation`` gives the
    equivalent user-data folder.  Falls back to ``~/.scriptree/`` if
    Qt isn't importable (only happens in tooling tests).
    """
    try:
        from PySide6.QtCore import QStandardPaths
        base = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation,
        )
        if base:
            return Path(base) / "regex_library.json"
    except ImportError:
        pass
    return Path.home() / ".scriptree" / "regex_library.json"


def load_user_library() -> list[LibraryEntry]:
    """Load the user's saved patterns from disk.

    Returns an empty list when the file doesn't exist yet (a fresh
    user has no library).  Returns whatever parses when the file is
    malformed -- per-entry parse errors skip that one row but don't
    nuke the whole library; a totally unparseable file logs to
    stderr and returns ``[]`` so the user can keep using the helper.

    Schema migrations: if the on-disk version is older than
    ``LIBRARY_SCHEMA_VERSION``, we walk it through the upgrade
    branches here.  Add a new ``if version < N`` block for every
    schema bump.
    """
    path = _user_library_path()
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"[regex_library] load_user_library: {path} unreadable: "
            f"{exc!r}; treating as empty",
            file=sys.stderr,
        )
        return []

    if not isinstance(data, dict):
        print(
            f"[regex_library] load_user_library: {path} top-level not "
            f"a JSON object; treating as empty",
            file=sys.stderr,
        )
        return []

    # Schema migrations live here.  None to do at v1.
    # (Example for the future:
    #     version = int(data.get("version") or 1)
    #     if version < 2: data = _migrate_v1_to_v2(data)
    # )

    raw_entries = data.get("patterns")
    if not isinstance(raw_entries, list):
        return []

    out: list[LibraryEntry] = []
    for row in raw_entries:
        if not isinstance(row, dict):
            continue
        try:
            out.append(LibraryEntry(
                name=str(row.get("name", "")).strip() or "(unnamed)",
                pattern=str(row.get("pattern", "")),
                description=str(row.get("description", "")),
                flags=str(row.get("flags", "")),
                source="user",  # forced — saved entries are user-owned
                notes=str(row.get("notes", "")),
            ))
        except Exception as exc:  # noqa: BLE001 -- skip bad row only
            print(
                f"[regex_library] skipped malformed row {row!r}: {exc!r}",
                file=sys.stderr,
            )
    return out


def save_user_library(entries: list[LibraryEntry]) -> None:
    """Persist the user's patterns to disk.

    Only entries with ``source == "user"`` are written -- the dialog
    composes the on-screen list by concatenating built-ins + user,
    and we don't want to round-trip CommonRegex's patterns into the
    user file (they'd then drift if CommonRegex was updated).

    Writes atomically via a temp file + os.replace so a power
    failure mid-write can't corrupt the library.  Creates the
    parent directory if needed.
    """
    path = _user_library_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": LIBRARY_SCHEMA_VERSION,
        "patterns": [
            {
                "name": e.name,
                "pattern": e.pattern,
                "description": e.description,
                "flags": e.flags,
                "notes": e.notes,
            }
            for e in entries
            if e.source == "user"
        ],
    }

    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        tmp.replace(path)
    except OSError as exc:
        print(
            f"[regex_library] save_user_library: {path} failed: {exc!r}",
            file=sys.stderr,
        )
        # Best-effort cleanup of the orphan tmp file.
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def export_to_forest_folder(forest_dir: Path) -> Path:
    """Export the user's library as a sibling of a .scriptreeforest
    file, returning the written path.

    The helper dialog's "Export to forest folder" button calls this
    when the user wants their library to follow a Dropbox / OneDrive
    -synced workspace.  The original ``%APPDATA%`` copy is left in
    place -- export is one-way; subsequent edits go back to the
    user-data location unless the user manually swaps them.
    """
    forest_dir.mkdir(parents=True, exist_ok=True)
    target = forest_dir / "regex_library.json"
    entries = load_user_library()
    payload = {
        "version": LIBRARY_SCHEMA_VERSION,
        "patterns": [
            asdict(e) | {"source": "user"} for e in entries
            if e.source == "user"
        ],
    }
    with target.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return target


# --------------------------------------------------------------------------
# Convenience: the dialog reads this combined view
# --------------------------------------------------------------------------

def all_entries() -> list[LibraryEntry]:
    """Return built-in + user entries in dialog-display order.

    Built-ins first (they're the obvious starting point for a new
    user), user entries after.  Each pool is shown under its own
    section header in the dialog.
    """
    return builtin_entries() + load_user_library()
