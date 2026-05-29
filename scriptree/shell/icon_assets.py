"""Access to the shipped ``icons/`` facet library (v0.6.7).

The repo/deploy ships a curated, trademark-safe monochrome line-icon
set at ``<project root>/icons/icon-<name>.svg`` (see
``docs/host-software-icon-style.md``).  This module locates that
directory and hands back an icon's bytes / base64 so the shell can
give a bare ring/forest hub a real glyph instead of derived letters.

No module-level Qt import (used on shell paths that must stay
light); base64 + pathlib only.
"""
from __future__ import annotations

import base64
import sys
from functools import lru_cache
from pathlib import Path


def _log(msg: str) -> None:
    print(f"[icon_assets] {msg}", file=sys.stderr)


@lru_cache(maxsize=1)
def icons_dir() -> Path | None:
    """The shipped ``icons/`` directory, or ``None`` if not found.

    Walks up from this file until an ``icons/`` folder containing at
    least the canonical ``icon-tool.svg`` is found — same
    walk-up-to-project-root heuristic ``ring_io._project_root`` uses,
    but anchored on the icon set so it works in both the source tree
    and a ``make_portable`` deploy.
    """
    here = Path(__file__).resolve().parent
    for _ in range(8):
        cand = here / "icons"
        if (cand / "icon-tool.svg").is_file():
            return cand
        if here.parent == here:
            break
        here = here.parent
    return None


# Runtime format: PNG, NOT SVG.  The portable/vendored PySide6 in a
# make_portable deploy does NOT register the qsvg image-format
# plugin and does NOT ship the QtSvg module, so
# QPixmap.loadFromData(svg, "SVG") returns False there — every
# embedded-SVG icon resolved blank on the R: drive.  PNG decoding
# is built into QtGui core (no plugin), so it works in every
# deploy.  The .svg files remain the design source-of-truth
# (spec-compliant per docs/host-software-icon-style.md); the .png
# is the rasterised runtime artifact embedded into catalogs / hubs.
BUNDLED_FORMAT = "png"


@lru_cache(maxsize=64)
def bundled_icon_b64(name: str) -> str:
    """Return base64 of ``icon-<name>.png`` from the shipped set, or
    ``""`` if unavailable.  PNG (not SVG) so it renders in the
    plugin-less portable runtime.  Cached — read on every
    forest/ring launch."""
    d = icons_dir()
    if d is None:
        _log("icons/ directory not found; hub icon unavailable")
        return ""
    p = d / f"icon-{name}.png"
    if not p.is_file():
        # Fall back to the SVG only if the PNG is somehow absent
        # (dev tree without rasterised assets).  Will not render in
        # a portable deploy — see BUNDLED_FORMAT note.
        p = d / f"icon-{name}.svg"
        if not p.is_file():
            _log(f"bundled icon {name!r} missing at {p}")
            return ""
    try:
        return base64.b64encode(p.read_bytes()).decode("ascii")
    except OSError as exc:
        _log(f"read {p} failed: {exc!r}")
        return ""


# --- name -> icon heuristic (v0.6.9) --------------------------------------
#
# When a catalog carries no embedded/linked icon, the cell/menu used
# to fall back to ONE generic glyph for everything.  Per user
# direction ("the menu items need more variety for their icons … be a
# little more creative") we classify the tool by keywords in its
# name / filename / executable to a shipped category glyph.  First
# matching rule wins; order matters (specific before generic).  The
# default is ``"tool"`` — a wrench, the universal "some utility".
#
# Trademark note: matching a *vendor word* only selects a GENERIC
# category archetype (e.g. "solidworks" → the generic gear), never a
# vendor mark — the glyphs themselves are trademark-safe by §5.

_ICON_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    # ScripTree's own primitives win first so a name like "Forest
    # hub launcher" or "Tree ring layout" routes here rather than
    # to a generic rule that happens to match a substring ("rest"
    # → web; "build" → build).  Keep keywords specific so common
    # words don't get misrouted.
    ((" ring ", " rings ", "scriptreering", "tree ring",
      "ring hub"), "ring"),
    (("forest", "scriptreeforest", "workspace root"), "forest"),
    (("solidworks", "sldworks", "sw_bridge", "catia", "creo",
      "mechanical", "cad ", "freecad"), "solidworks"),
    # Cutting / fabrication beats plain CAD: a "DXF plasma cut" or
    # "nesting" tool is about the cut, not the drawing editor.
    (("scissors", "cut", "plasma", "laser", "nest", "trim",
      "kerf"), "scissors"),
    (("autocad", "dwg", "dxf", "draft"), "autocad"),
    (("inventor", "fusion360", "3d model", "assembly"), "inventor"),
    (("revit", "bim", "ifc", "archicad"), "revit"),
    (("ruler", "measure", "dimension", "caliper", "gauge"), "ruler"),
    (("git", "svn", "mercurial", "version control", "commit",
      "branch", "vcs"), "versioncontrol"),
    (("powershell", "pwsh", ".ps1", "power shell"), "power"),
    (("terminal", "shell", "bash", "cmd", "console", "cli",
      "command line", "zsh", "sh "), "cli"),
    (("python", ".py", "node", "ruby", "perl", "lua", "script",
      "macro", "automation", "batch", ".bat"), "script"),
    (("compile", "build", "make", "gradle", "maven", "cmake",
      "msbuild", "ninja", "bundler"), "build"),
    (("test", "pytest", "unittest", "lint", "spec", "verify",
      "assert", "qa"), "test"),
    (("debug", "bug", "trace", "profiler", "diagnos"), "bug"),
    (("zip", "archive", "tar", "7z", "compress", "unzip",
      "extract", "gzip", "rar"), "archive"),
    (("package", "installer", "setup", "deploy", "msi", "wheel",
      "npm", "pip "), "package"),
    (("download", "fetch", "pull", "wget", "curl", "get "),
     "download"),
    (("upload", "publish", "push", "sync up", "deploy to"),
     "upload"),
    (("convert", "transcode", "ffmpeg", "transform", "encode",
      "decode", "export", "import"), "convert"),
    (("search", "find", "locate", "index", "lookup", "grep",
      "ripgrep"), "search"),
    (("filter", "sed", "awk", "query", "select ", "where "),
     "filter"),
    (("database", "sql", "postgres", "mysql", "sqlite", "mongo",
      "redis", "db "), "database"),
    (("network", "ping", "tcp", "socket", "port", "dns", "ssh",
      "ftp", "vpn", "lan", "subnet"), "network"),
    (("server", "daemon", "service", "apache", "nginx", "iis",
      "hostname", "webserver"), "server"),
    (("cloud", "aws", "azure", "gcp", "s3 ", "lambda"), "cloud"),
    (("docker", "container", "podman", "kubernetes", "k8s",
      "compose"), "container"),
    (("link", "url", "shortcut", "alias", "symlink"), "link"),
    (("lock", "encrypt", "decrypt", "cipher", "ssl", "tls",
      "credential", "password", "secret"), "lock"),
    (("key", "token", "auth", "license", "keygen"), "key"),
    (("shield", "secure", "security", "firewall", "antivirus",
      "protect", "defender"), "shield"),
    (("schedule", "calendar", "cron", "timer", "reminder"),
     "calendar"),
    (("clock", "time", "stopwatch", "duration", "uptime"),
     "clock"),
    (("chart", "graph", "analytic", "metric", "stat", "report",
      "plot", "dashboard"), "chart"),
    (("spreadsheet", "excel", "csv", "xlsx", " calc"),
     "spreadsheet"),
    (("presentation", "powerpoint", "slide", "pptx", "keynote"),
     "presentation"),
    (("office", "word", "docx", "outlook"), "msoffice"),
    (("pdf", "acrobat"), "pdf"),
    (("email", "mail", "smtp", "imap", "inbox"), "email"),
    (("printer", "print", "plot ", "cups"), "printer"),
    (("audio", "sound", "mp3", "wav", "music", "voice"), "audio"),
    (("video", "movie", "film", "mp4", "stream", "record"),
     "video"),
    (("image", "photo", "picture", "png", "jpg", "jpeg", "svg",
      "raster", "thumbnail"), "image"),
    (("media", "player", "playlist"), "media"),
    (("chip", "cpu", "processor", "firmware", "embedded",
      "arduino", "raspberry"), "chip"),
    (("disk", "drive", "storage", "backup", "volume", "partition",
      "mount"), "server"),
    (("location", "map", "pin", "geo", "gps", "coordinate"),
     "pin"),
    (("edit", "editor", "rename", "modify", "patch", "pencil"),
     "edit"),
    (("settings", "config", "preference", "options", "tune",
      "profile"), "settings"),
    (("web", "http", "browser", "html", "rest", "api", "site"),
     "web"),
    (("window", "gui", "desktop", "app "), "window"),
    (("code", "develop", "ide", "compiler", "sdk", "function"),
     "code"),
    (("document", "doc ", "text", "note", "readme", "manual",
      "report "), "document"),
    (("folder", "directory", "explorer", "tree", "files",
      "filesystem"), "folder"),
)


@lru_cache(maxsize=512)
def classify_icon(
    name: str = "", filename: str = "", executable: str = "",
) -> str:
    """Pick a shipped icon *name* for an icon-less tool by keyword.

    Inputs are matched case-insensitively against the rule table
    above (first hit wins).  Always returns a valid bundled-icon
    name; ``"tool"`` is the generic default so a row is never bare.

    Cached — the cell menu calls this once per leaf per rebuild.
    """
    hay = f" {name} {filename} {executable} ".lower()
    for needles, icon in _ICON_RULES:
        for kw in needles:
            if kw in hay:
                return icon
    return "tool"


@lru_cache(maxsize=1)
def list_bundled_icons() -> tuple[str, ...]:
    """Sorted tuple of bundled icon *names* (the ``<name>`` part of
    ``icon-<name>.png``).  Empty tuple if the set can't be located.

    Used by the cell Settings dialog's "Choose from library…" picker
    so the user can assign a shipped, trademark-safe glyph without
    hunting for an image file.
    """
    d = icons_dir()
    if d is None:
        return ()
    names = sorted(
        p.stem[len("icon-"):]
        for p in d.glob("icon-*.png")
        if p.stem.startswith("icon-")
    )
    return tuple(names)


def bundled_icon_png_path(name: str) -> Path | None:
    """Absolute path to ``icon-<name>.png`` in the shipped set, or
    ``None``.  Distinct from ``bundled_icon_b64`` — callers that want
    to embed via the normal ``embed_icon`` path need the file path."""
    d = icons_dir()
    if d is None:
        return None
    p = d / f"icon-{name}.png"
    return p if p.is_file() else None


__all__ = [
    "icons_dir", "bundled_icon_b64", "BUNDLED_FORMAT",
    "list_bundled_icons", "bundled_icon_png_path", "classify_icon",
]
