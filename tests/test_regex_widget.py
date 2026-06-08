"""
test_regex_widget.py — regression tests for the v0.8.0a48+ regex
widget + helper dialog + library.

Pins:

* ``Widget.REGEX`` is a legal widget for ``ParamType.STRING``.
* ``build_widget_for`` returns a ``RegexWidget`` for a regex param.
* The widget's get/set round-trip works.
* Live validation: a valid pattern shows the ✓ badge; an invalid
  pattern shows ✗ + parse error in the tooltip; an empty pattern
  shows neither.
* The inline-flag splitter handles all four shapes (no flags,
  simple flags, multi-letter flags, fancier constructs left intact).
* ``regex_library``: the CommonRegex bridge yields at least the
  expected built-ins (email + phone + link as a smoke check);
  ``load_user_library`` returns an empty list for a missing file;
  ``save_user_library`` / ``load_user_library`` round-trip.

DELIBERATELY NOT tested here:

* The helper dialog UI (Test/Library/Reference tabs) -- exercising
  Qt modal dialogs in pytest tends to hang on Windows, and the
  underlying logic is covered through the library + widget tests.
  Smoke-test the dialog manually before release.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Headless Qt + vendored deps on path.  Mirrors conftest.py for these
# tests so the module imports without the project's pytest plugins.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_VENDOR = Path(__file__).resolve().parent.parent / "lib" / "pypi"
if _VENDOR.is_dir():
    sys.path.insert(0, str(_VENDOR))

from PySide6.QtWidgets import QApplication  # noqa: E402

import pytest  # noqa: E402

from scriptree.core.model import (  # noqa: E402
    ParamDef, ParamType, VALID_WIDGETS, Widget,
)
from scriptree.ui.widgets.param_widgets import build_widget_for  # noqa: E402
from scriptree.ui.widgets.regex_library import (  # noqa: E402
    LibraryEntry, builtin_entries, load_user_library,
    save_user_library, _user_library_path,
)
from scriptree.ui.widgets.regex_widget import (  # noqa: E402
    RegexWidget, _split_inline_flags,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Model wiring
# ---------------------------------------------------------------------------

def test_regex_is_valid_widget_for_string() -> None:
    """``Widget.REGEX`` must be a legal widget choice for STRING
    params; the tool editor's widget dropdown reads from
    ``VALID_WIDGETS`` and we want REGEX selectable."""
    assert Widget.REGEX in VALID_WIDGETS[ParamType.STRING]


def test_regex_widget_value_round_trip(qapp) -> None:
    """``RegexWidget`` is a regex-shaped string widget: ``set_value``
    + ``get_value`` round-trip the raw pattern with no escaping or
    mangling.  The Widget.REGEX param must yield a RegexWidget."""
    pd = ParamDef(
        id="p", label="Pattern", type=ParamType.STRING,
        widget=Widget.REGEX, default=r"\b\w+\b",
    )
    w = build_widget_for(pd)
    assert isinstance(w, RegexWidget)
    assert w.get_value() == r"\b\w+\b"
    w.set_value(r"^foo$")
    assert w.get_value() == r"^foo$"


# ---------------------------------------------------------------------------
# Live validation
# ---------------------------------------------------------------------------

def test_live_validation_valid_pattern_shows_check(qapp) -> None:
    """A valid regex pattern: badge shows ✓ (U+2713) and the
    line-edit border CSS goes green."""
    pd = ParamDef(id="p", label="P", type=ParamType.STRING,
                  widget=Widget.REGEX, default="")
    w = build_widget_for(pd)
    w.set_value(r"^[A-Z][a-z]+$")
    w._validate()  # bypass debounce
    assert w._badge.text() == "✓"
    assert "4caf50" in w._edit.styleSheet()  # the green hex


def test_live_validation_invalid_pattern_shows_cross_and_tooltip(qapp) -> None:
    """An invalid regex: badge shows ✗ (U+2717) and the line-edit
    tooltip carries the parse error so the user can read it on
    hover.  Border is red."""
    pd = ParamDef(id="p", label="P", type=ParamType.STRING,
                  widget=Widget.REGEX, default="")
    w = build_widget_for(pd)
    w.set_value(r"^(unclosed")
    w._validate()
    assert w._badge.text() == "✗"
    assert "Parse error" in w._edit.toolTip()
    assert "e53935" in w._edit.styleSheet()


def test_live_validation_empty_shows_no_badge(qapp) -> None:
    """An empty pattern is the default state: no badge, no border
    colour.  Important because the widget is built with empty
    default for fresh-tool forms and the user shouldn't see a red
    'invalid' state before they've typed anything."""
    pd = ParamDef(id="p", label="P", type=ParamType.STRING,
                  widget=Widget.REGEX, default="")
    w = build_widget_for(pd)
    w._validate()
    assert w._badge.text() == ""
    assert w._edit.styleSheet() == ""


# ---------------------------------------------------------------------------
# Inline-flag splitter
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("",                     ("", "")),
    ("abc",                  ("abc", "")),
    ("(?i)abc",              ("abc", "i")),
    ("(?im)\\d+",            ("\\d+", "im")),
    ("(?imsx).+",            (".+", "imsx")),
    ("(?P<x>foo)",           ("(?P<x>foo)", "")),  # not a flag block
    ("(?i-m)abc",            ("(?i-m)abc", "")),   # fancier construct
    ("(?:abc)",              ("(?:abc)", "")),     # non-capturing group
])
def test_split_inline_flags(text, expected) -> None:
    """Only the canonical ``(?[imsx]+)`` shape gets stripped --
    anything more complex round-trips unchanged so we don't lose
    fancier directives the user may have typed deliberately."""
    assert _split_inline_flags(text) == expected


# ---------------------------------------------------------------------------
# CommonRegex bridge
# ---------------------------------------------------------------------------

def test_builtin_entries_includes_known_patterns() -> None:
    """The built-in library MUST surface email + phone + link at
    minimum; those are the top-3 patterns users will reach for.
    Each entry must have a non-empty pattern string."""
    entries = builtin_entries()
    names = {e.name for e in entries}
    assert "Email address" in names
    assert "Phone number" in names
    assert "URL / link" in names
    for e in entries:
        assert e.pattern.strip(), f"{e.name} has empty pattern"
        assert e.source == "builtin"


# ---------------------------------------------------------------------------
# User library
# ---------------------------------------------------------------------------

def test_user_library_missing_file_returns_empty(monkeypatch, tmp_path) -> None:
    """A fresh user has no library file -- ``load_user_library``
    must return an empty list, NOT raise."""
    monkeypatch.setattr(
        "scriptree.ui.widgets.regex_library._user_library_path",
        lambda: tmp_path / "nope.json",
    )
    assert load_user_library() == []


def test_user_library_save_load_round_trip(monkeypatch, tmp_path) -> None:
    """``save_user_library`` writes; ``load_user_library`` reads back
    the same data.  Crucial for the 'Add current pattern' button --
    next launch must see the saved entry."""
    library_path = tmp_path / "regex_library.json"
    monkeypatch.setattr(
        "scriptree.ui.widgets.regex_library._user_library_path",
        lambda: library_path,
    )
    entries = [
        LibraryEntry(
            name="SKU code",
            pattern=r"^[A-Z]{2}-\d{4}$",
            description="Two letters, dash, four digits",
            flags="",
            source="user",
            notes="",
        ),
        LibraryEntry(
            name="Internal API path",
            pattern=r"/api/v\d+/",
            description="",
            flags="i",
            source="user",
            notes="",
        ),
    ]
    save_user_library(entries)
    assert library_path.exists()

    # Round-trip.
    loaded = load_user_library()
    assert len(loaded) == 2
    assert loaded[0].name == "SKU code"
    assert loaded[0].pattern == r"^[A-Z]{2}-\d{4}$"
    assert loaded[0].source == "user"
    assert loaded[1].flags == "i"


def test_user_library_only_user_entries_persist(monkeypatch, tmp_path) -> None:
    """Built-in entries must NEVER be written to the user file --
    otherwise a future CommonRegex update would conflict with the
    snapshotted copy on disk."""
    library_path = tmp_path / "regex_library.json"
    monkeypatch.setattr(
        "scriptree.ui.widgets.regex_library._user_library_path",
        lambda: library_path,
    )
    mixed = [
        LibraryEntry(name="x", pattern="x", source="user"),
        LibraryEntry(name="email", pattern="@", source="builtin"),
    ]
    save_user_library(mixed)
    raw = json.loads(library_path.read_text(encoding="utf-8"))
    names_on_disk = [r["name"] for r in raw["patterns"]]
    assert names_on_disk == ["x"]


def test_user_library_malformed_row_skipped(
    monkeypatch, tmp_path,
) -> None:
    """A corrupt row in the JSON shouldn't nuke the whole library --
    the loader skips it and returns the rest."""
    library_path = tmp_path / "regex_library.json"
    library_path.write_text(json.dumps({
        "version": 1,
        "patterns": [
            {"name": "good", "pattern": "ok"},
            42,                              # not a dict, skip
            {"pattern": "noname"},           # name defaulted
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(
        "scriptree.ui.widgets.regex_library._user_library_path",
        lambda: library_path,
    )
    loaded = load_user_library()
    assert len(loaded) == 2
    assert loaded[0].name == "good"
    assert loaded[1].name == "(unnamed)"
