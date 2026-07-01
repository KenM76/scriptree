"""Build a NEW portable ScripTree copy that includes the user's local tools (a94).

## Why this module exists (and why it can't reuse ``make_portable.py``)

Feature **A1** — the forest's *"Make a portable copy (incl. local tools)"* action —
produces a self-contained ScripTree folder at a user-chosen destination, copies
every tool that lives *outside* the install tree into it, and leaves the current
install + live forest UNTOUCHED.

The dev script ``make_portable.py`` (repo root) does the heavy app-copy, but it is
explicitly **dev-only**: it lists itself in its own exclude set and is therefore
NOT present in a deployed runtime tree (``R:\\ScripTree`` has no
``make_portable.py``).  So A1 — which runs from the *runtime* — cannot import it.
This module re-implements the small, runtime-needed slice as a package-native,
headless-testable primitive.

## The three pure pieces (Qt-free)

1. :func:`copy_install_tree` — ``shutil.copytree`` of the current install root into
   an EMPTY destination, skipping VCS/cache/test/dev junk (``_ignore``).  Never
   deletes anything: it writes only into an empty/new dir (``dirs_exist_ok=True``).
2. :func:`rebase_install_items_to_external` — re-point forest items that already
   live under the CURRENT install's ``ScripTreeApps`` at the EXTERNAL copy's
   ``ScripTreeApps`` (where :func:`copy_install_tree` mirrored them).  The
   apps/personal tools are handled by the existing
   :mod:`scriptree.shell.portable_consolidate` primitive
   (``execute_consolidation`` + ``rebase_forest_items``) with
   ``install_apps_root=<dest>/ScripTreeApps``.
3. :func:`save_forest_for_external_install` — serialise the rebased forest so that
   paths under ``<dest>/ScripTreeApps`` are tagged ``root: "install"`` (which
   resolves correctly when the portable copy runs FROM ``dest``).  ``save_forest``
   computes the ``install`` base from ``forest_io._project_root()``; this helper
   temporarily points that resolver at ``dest`` for the duration of the write, so
   the destination's install root — not this machine's — is used.

## How A1 composes them (the GUI wrapper lives in ForestController)

    copy_install_tree(install_root, dest)                  # app + install tools
    plan   = plan_consolidation(work, install_apps_root=dest_apps)
    result = execute_consolidation(plan, install_apps_root=dest_apps,
                                   on_collision="rename")   # apps/personal -> dest
    rebase_forest_items(work, result)                       # apps/personal items
    rebase_install_items_to_external(work, current_install_apps=cur_apps,
                                     dest_apps=dest_apps)    # install items mirror
    save_forest_for_external_install(work, dest_autoload, dest)   # root:install
    (dest / "portable").write_text(...)                     # portable sentinel

``work`` is a DEEP COPY of the live forest, so the current session is untouched.

## Safety invariants

* **Never deletes user data.**  :func:`copy_install_tree` refuses a non-empty dest
  and only writes into an empty/new folder — no ``rmtree`` of a user-picked path.
* **The live install + forest are untouched** — all rebasing happens on a deep copy
  and all writes go under ``dest``.
* **Private tools travel but are flagged.**  The GUI surfaces
  ``ForestController._private_tool_warning`` (content-scanning) before the copy, so
  the user knows a SolidWorks/private payload will be in the (shareable) copy.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from scriptree.shell import forest_io

# ── Exclusion patterns (ported from make_portable.py, tuned for a personal
#    portable copy: KEEP docs/ user_configs/ scripts/ so help + the user's own
#    configs travel; additionally drop the SOURCE's _portable_data and the dev
#    rags so we don't carry stale state or dev-only material). ──────────────
EXCLUDE_DIRS = {
    ".git", ".claude", ".vscode", ".idea", ".pytest_cache", "__pycache__",
    ".mypy_cache", ".ruff_cache", "node_modules", "htmlcov", ".tox",
    "tests",            # dev test suite — not needed at runtime
    "_portable_data",   # the SOURCE's portable state — we write a fresh one
    "rags",             # dev RAG / lessons — not needed at runtime
}
EXCLUDE_FILES = {
    ".gitignore", ".gitattributes", ".editorconfig", "out.txt", ".coverage",
    "make_portable.py",
    # Per-machine / private state — recent-file MRU, per-tool dock layouts,
    # absolute machine paths, an ``install.personal_root`` override.  This is on
    # the project's never-commit list; shipping it in a SHAREABLE copy would
    # leak the author's history + tool names AND can point the copy off-tree.
    # The fresh copy must start with clean per-machine state.
    "scriptree.ini", "scriptree.ini.bak",
}
EXCLUDE_EXTS = {".pyc", ".pyo", ".log", ".tmp", ".bak", ".swp"}


def _ignore(dirpath: str, names: list[str]) -> list[str]:
    """``shutil.copytree`` ignore callback — skip VCS/cache/test/dev junk."""
    skip: list[str] = []
    for n in names:
        if n in EXCLUDE_DIRS or n in EXCLUDE_FILES:
            skip.append(n)
            continue
        if os.path.splitext(n)[1].lower() in EXCLUDE_EXTS:
            skip.append(n)
    return skip


# ── Private-tool (SolidWorks) content detection ──────────────────────────
# Shared by the forest controller's pre-copy caution and the install-tree scan.
# We inspect actual file/dir NAMES + a loose catalog's TEXT, not just a folder
# name — a neutrally-named folder can still hold ``sw_bridge.exe`` + ``*.csx``.
_PRIVATE_NAME = __import__("re").compile(
    r"solidworks|sw_bridge|solidworkstools", __import__("re").I,
)


def is_private_name(name: str) -> bool:
    """True when a file/dir name denotes private SolidWorks automation."""
    low = name.lower()
    return bool(_PRIVATE_NAME.search(name)) or low.endswith(".csx") or (
        "solidworks.interop" in low and low.endswith(".dll")
    )


def folder_has_private_tools(folder) -> bool:
    """True when anything under ``folder`` looks like private SolidWorks tooling
    (``os.walk`` over names — does NOT read file contents, for speed over a
    potentially large ScripTreeApps tree)."""
    try:
        for root, dirs, files in os.walk(folder):
            if _PRIVATE_NAME.search(root):
                return True
            for nm in (*dirs, *files):
                if is_private_name(nm):
                    return True
    except OSError:
        pass
    return False


def file_is_private(f) -> bool:
    """True when a single catalog file is (or references) private SolidWorks
    automation — checks its name, then scans its (small) text for the tokens."""
    f = Path(f)
    if is_private_name(f.name):
        return True
    try:
        txt = f.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    return bool(_PRIVATE_NAME.search(txt)) or ".csx" in txt


def prune_items_outside_external(forest, dest_apps) -> list[str]:
    """Drop forest items whose tool does NOT live under ``dest_apps`` after all
    rebasing, returning the dropped paths.

    A traveling item (install-mirrored or apps/personal-consolidated) ends up
    under ``dest_apps``.  Anything still elsewhere — a copy that FAILED, or a
    tool under no known root — cannot travel with the portable copy; leaving it
    in the exported forest would serialise a root that DANGLES on the
    destination machine (e.g. a ``root:personal`` ref resolving to the dest's
    empty app-data).  So we prune those, keeping the exported forest coherent:
    it references only tools that physically exist in the copy.  (``excluded``
    is left untouched — a rooted entry re-resolves on the dest, and a stale
    legacy string simply never matches.)
    """
    dest_apps = Path(dest_apps).resolve()

    def _under(p: str) -> bool:
        try:
            return Path(p).resolve().is_relative_to(dest_apps)
        except (ValueError, OSError):
            return False

    keep, dropped = [], []
    for it in forest.items:
        (keep if _under(it.path) else dropped).append(it)
    forest.items = keep
    return [it.path for it in dropped]


def copy_install_tree(src_root: Path, dest: Path) -> None:
    """Copy the install at ``src_root`` into ``dest`` (which must be empty or new).

    Skips the dev/VCS/cache material in :data:`EXCLUDE_DIRS` / files / exts.
    Refuses a NON-EMPTY destination (raises ``FileExistsError``) so we never
    ``rmtree`` a folder the user picked by mistake — A1 only ever writes into a
    fresh/empty directory.
    """
    src_root = Path(src_root)
    dest = Path(dest)
    if dest.exists() and dest.is_dir() and any(dest.iterdir()):
        raise FileExistsError(
            f"Destination {dest} is not empty — choose an empty or new folder."
        )
    # dirs_exist_ok=True tolerates the empty dir a folder-picker returns; the
    # emptiness check above guarantees we never overwrite real content.
    shutil.copytree(src_root, dest, ignore=_ignore, dirs_exist_ok=True)


def rebase_install_items_to_external(
    forest, *, current_install_apps: Path, dest_apps: Path,
) -> int:
    """Re-point items under the CURRENT install's ``ScripTreeApps`` at ``dest_apps``.

    :func:`copy_install_tree` mirrors the current install (including its
    ``ScripTreeApps``) into the destination, so an install-rooted forest item's
    file already exists at ``dest_apps / <same rel>``.  Pointing the item there
    (and its ``catalog_path``) makes the exported forest reference the COPY, not
    this machine.  Items NOT under the current install (apps/personal — already
    rebased by ``rebase_forest_items`` — or ``outside``) are left untouched.
    Returns the count rebased.
    """
    cur = Path(current_install_apps).resolve()
    dest_apps = Path(dest_apps)
    n = 0
    for it in forest.items:
        try:
            rel = Path(it.path).resolve().relative_to(cur)
        except (ValueError, OSError):
            continue  # not under the current install tree
        new_path = str(dest_apps / rel)
        if it.catalog_path:
            try:
                crel = Path(it.catalog_path).resolve().relative_to(cur)
                it.catalog_path = str(dest_apps / crel)
            except (ValueError, OSError):
                it.catalog_path = new_path
        it.path = new_path
        n += 1
    return n


def save_forest_for_external_install(forest, dest_forest_file, dest_root) -> None:
    """Save ``forest`` so paths under ``<dest_root>/ScripTreeApps`` tag ``root:install``.

    ``forest_io.save_forest`` derives the ``install`` base from
    ``forest_io._project_root()`` (this machine's install).  For an EXTERNAL copy
    we want the *destination's* install root, so we temporarily redirect that
    resolver at ``dest_root`` for the single synchronous write, then restore it.
    Runs on the GUI thread with no concurrent ``known_roots`` callers, so the
    swap is safe; ``finally`` guarantees restoration even on error.
    """
    dest_root = Path(dest_root)
    orig = forest_io._project_root
    forest_io._project_root = lambda: dest_root  # type: ignore[assignment]
    try:
        forest_io.save_forest(forest, Path(dest_forest_file))
    finally:
        forest_io._project_root = orig  # type: ignore[assignment]


def external_autoload_path(dest_root: Path) -> Path:
    """The portable-mode forest-autoload file inside an external copy:
    ``<dest>/_portable_data/<default forest filename>`` (mirrors
    ``forest_io.default_autoload_path`` under portable mode, which is
    ``portable_data_root()/<filename>`` with NO brand subdir)."""
    return Path(dest_root) / "_portable_data" / forest_io._DEFAULT_FOREST_FILENAME
