"""
branding_loader.py — load branding/branding.config.json from the project root.

## For humans

Resolution strategy: walk up from this file's directory until we find a
directory that contains ``branding/branding.config.json``.  This is
portable — no env-var dependency, no hardcoded path.

## For maintainers / LLMs

- The resolved root is the directory that *contains* ``branding/`` —
  ``_find_project_root`` returns the parent of ``branding/``, not the
  ``branding/`` dir itself.  ``load_forest._project_root`` and
  ``ring_io._project_root`` use the SAME heuristic; if you change the
  marker file here, change it in all three or path resolution diverges.
- The docstring of ``_find_project_root`` still mentions a ``CLAUDE.md``
  marker; the code only checks ``branding/branding.config.json``.  Trust
  the code — do not re-add a ``CLAUDE.md`` check (it would shorten the
  resolved root in some deployments and break relative path storage).
- The walk is capped at 10 levels and also stops at the filesystem root
  (``parent == current``); both guards are needed — drive roots on
  Windows do not always satisfy ``parent == current`` cleanly.
- On failure this RAISES ``FileNotFoundError`` (it does not return a
  fallback).  Callers that need a soft fallback must catch it; the
  forest layer deliberately uses its own ``_project_root`` that falls
  back to ``Path.cwd()`` instead of reusing this function.
- ``load_branding`` reads with explicit ``encoding="utf-8"`` — keep that;
  the JSON contains non-ASCII brand strings.
- The error message references "ScripTree2"; this is cosmetic but stale.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _log(msg: str) -> None:
    print(f"[branding_loader] {msg}", file=sys.stderr)


def _find_project_root(start: Path) -> Path:
    """Walk up from `start` until we find a dir with branding/branding.config.json."""
    current = start.resolve()
    for _ in range(10):  # guard against infinite walk
        candidate = current / "branding" / "branding.config.json"
        if candidate.is_file():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    raise FileNotFoundError(
        f"Could not locate branding/branding.config.json starting from {start}. "
        "Ensure you are running from within the ScripTree2 project tree."
    )


def load_branding() -> dict:
    """Return the parsed branding.config.json as a plain dict.

    Raises FileNotFoundError if the project root cannot be determined.
    """
    start = Path(__file__).resolve().parent  # apps/shell/
    project_root = _find_project_root(start)
    config_path = project_root / "branding" / "branding.config.json"
    _log(f"Loading branding from {config_path}")
    with config_path.open(encoding="utf-8") as fh:
        return json.load(fh)


def about_app_html(branding: dict | None) -> str:
    """Return the canonical rich-text body for every "About <brand>" surface.

    v0.8.0a121 — SINGLE SOURCE for the About-box content.  Two UI surfaces
    show "about the app" information and they must never drift:

      * ``cell_window.CellWindow._show_about`` — the standard cell menu's
        "About <brand>" message box;
      * ``forest_controller.ForestController._build_about_dialog`` — the
        first tab of the forest hub's two-tab "About…" dialog (a120).

    a120 accidentally re-inlined the HTML in the controller (the exact
    duplication a117's ``_show_about`` extraction existed to prevent), so
    the builder now lives here, next to the branding it renders.  Content:
    long app name, tagline, ``scriptree.__version__`` and — when set —
    ``scriptree.__build_date__`` (users identify fast-moving builds by the
    date; see the ``__init__`` docstring).  Qt-free on purpose: this module
    stays import-light and the string is plain rich-text HTML that QLabel /
    QMessageBox render identically.
    """
    b = branding or {}
    brand = b.get("appName", "App")
    app_name_long = b.get("appNameLong", brand)
    tagline = b.get("tagline", "")
    try:
        from scriptree import __version__ as _ver
    except Exception:  # noqa: BLE001
        _ver = "(unknown)"
    try:
        from scriptree import __build_date__ as _bd  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        _bd = ""
    build_line = f"<br><b>Built:</b> {_bd}" if _bd else ""
    return (
        f"<b>{app_name_long}</b><br>"
        f"{tagline}<br><br>"
        f"<b>Version:</b> {_ver}"
        f"{build_line}"
    )
