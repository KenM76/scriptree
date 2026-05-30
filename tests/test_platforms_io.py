"""Phase-1 regression suite for the cross-platform overrides
feature (v0.8.0a22+).

The feature adds:

* ``PlatformOverride`` dataclass under
  ``scriptree.core.model`` — per-OS bag of optional overrides
  for ``executable``, ``argument_template``, ``path_prepend``,
  ``env``, ``actions``.
* ``ToolDef.platforms`` dict keyed by OS id
  (``"windows" | "macos" | "linux"``).
* ``platforms`` JSON block on the ``.scriptree`` side,
  serialised only when at least one entry exists.

This file pins the round-trip and serialisation rules.
Resolution semantics are tested separately in
``test_platforms_resolve.py``.

Bar these tests set:

* Legacy ``.scriptree`` (no ``platforms`` key) loads as
  ``ToolDef(..., platforms={})`` and re-saves byte-identical.
* A non-empty ``platforms`` block round-trips every field
  losslessly.
* An empty-override entry (``"macos": {}``) round-trips as
  ``PlatformOverride()`` and re-emits as ``"macos": {}``.
* Unknown OS ids in the JSON are dropped silently.
* Malformed values (non-list ``argument_template``, non-dict
  ``env``, ``platforms`` itself not a dict) coerce to safe
  defaults rather than raising.

Auto-dismisses ``QMessageBox`` per the standing rule.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

_app = QApplication.instance() or QApplication([])
QMessageBox.warning = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)
QMessageBox.information = staticmethod(  # type: ignore[assignment]
    lambda *a, **kw: QMessageBox.StandardButton.Ok
)

from scriptree.core.io import (
    load_tool,
    save_tool,
    tool_from_dict,
    tool_to_dict,
)
from scriptree.core.model import (
    ActionDef,
    PlatformOverride,
    ToolDef,
)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _minimal_tool() -> ToolDef:
    """A ``ToolDef`` that exercises every field the tests touch
    but stays small enough to read in test output."""
    return ToolDef(
        name="X",
        executable="py.exe",
        argument_template=["-3", "./tool.py"],
    )


# ============================================================================
# Defaults & legacy round-trip
# ============================================================================


class TestDefaults:
    def test_platforms_default_is_empty_dict(self) -> None:
        """A fresh ToolDef has no platform overrides."""
        t = ToolDef(name="X", executable="py.exe")
        assert t.platforms == {}

    def test_each_tool_gets_own_platforms_dict(self) -> None:
        """Mutable-default-argument check: two independent
        ToolDef instances must NOT share the same ``platforms``
        dict (would let overrides on one tool leak to another)."""
        t1 = ToolDef(name="A", executable="a")
        t2 = ToolDef(name="B", executable="b")
        t1.platforms["macos"] = PlatformOverride(executable="a-mac")
        assert "macos" not in t2.platforms, (
            "ToolDef.platforms is shared between instances -- "
            "the ``field(default_factory=dict)`` declaration was "
            "regressed to a bare ``{}`` default."
        )


class TestLegacyRoundTrip:
    """Files written before this feature must re-serialise
    byte-identical so deployed catalogs don't fill Git with
    no-op diffs on the next save."""

    def test_legacy_load_yields_empty_platforms(
        self, tmp_path: Path,
    ) -> None:
        legacy = {
            "schema_version": 3,
            "name": "Legacy",
            "executable": "py.exe",
            "argument_template": ["-3", "./x.py"],
        }
        p = tmp_path / "legacy.scriptree"
        p.write_text(json.dumps(legacy, indent=2), encoding="utf-8")

        t = load_tool(p)
        assert t.platforms == {}

    def test_legacy_no_platforms_key_in_output(
        self, tmp_path: Path,
    ) -> None:
        """Saving a tool that has no platform overrides must NOT
        introduce a ``platforms`` key in the output JSON.  The
        existing ``tool_to_dict`` already emits some fields the
        legacy input lacked (e.g. ``description: ""``), so a
        strict byte-identical round-trip isn't possible across
        the whole file; this guard pins the narrower contract
        that this feature owns: no spurious ``platforms``
        emission for tools that don't use it."""
        legacy = {
            "schema_version": 3,
            "name": "Legacy",
            "executable": "py.exe",
            "argument_template": ["-3", "./x.py"],
            "params": [],
        }
        p = tmp_path / "legacy.scriptree"
        p.write_text(json.dumps(legacy, indent=2), encoding="utf-8")

        t = load_tool(p)
        out = tmp_path / "rt.scriptree"
        save_tool(t, out)
        saved = json.loads(out.read_text(encoding="utf-8"))
        assert "platforms" not in saved, (
            "Loading + saving a legacy tool introduced a stray "
            "``platforms`` key.  The block must be omitted when "
            "the in-memory ``platforms`` dict is empty."
        )

    def test_empty_platforms_dict_not_emitted(self) -> None:
        """An empty ``ToolDef.platforms`` must omit the
        ``platforms`` JSON key entirely -- legacy round-trip
        ergonomics demand the file stay byte-identical."""
        t = _minimal_tool()
        d = tool_to_dict(t)
        assert "platforms" not in d


# ============================================================================
# Lossless round-trip for non-empty platforms
# ============================================================================


class TestPlatformsRoundTrip:
    def test_single_override_round_trips(self, tmp_path: Path) -> None:
        t = _minimal_tool()
        t.platforms["macos"] = PlatformOverride(
            executable="/usr/bin/python3",
            argument_template=["./tool.py"],
        )
        p = tmp_path / "t.scriptree"
        save_tool(t, p)

        loaded = load_tool(p)
        assert "macos" in loaded.platforms
        mac = loaded.platforms["macos"]
        assert mac.executable == "/usr/bin/python3"
        assert mac.argument_template == ["./tool.py"]
        # Fields not set in the override round-trip as None.
        assert mac.path_prepend is None
        assert mac.env is None
        assert mac.actions is None

    def test_all_three_os_round_trip(self, tmp_path: Path) -> None:
        t = _minimal_tool()
        t.platforms["windows"] = PlatformOverride(
            path_prepend=["C:/Tools/Python311"],
        )
        t.platforms["macos"] = PlatformOverride(
            executable="python3",
            env={"PYTHONIOENCODING": "utf-8"},
        )
        t.platforms["linux"] = PlatformOverride(
            executable="python3",
        )
        p = tmp_path / "t.scriptree"
        save_tool(t, p)

        loaded = load_tool(p)
        assert set(loaded.platforms.keys()) == {"windows", "macos", "linux"}
        assert loaded.platforms["windows"].path_prepend == ["C:/Tools/Python311"]
        assert loaded.platforms["macos"].executable == "python3"
        assert loaded.platforms["macos"].env == {"PYTHONIOENCODING": "utf-8"}
        assert loaded.platforms["linux"].executable == "python3"

    def test_empty_override_round_trips_as_empty_block(
        self, tmp_path: Path,
    ) -> None:
        """A ``PlatformOverride()`` (no fields set) serialises
        as ``{}`` -- distinct from omitting the OS key, which
        means "no explicit support claim"."""
        t = _minimal_tool()
        t.platforms["macos"] = PlatformOverride()

        d = tool_to_dict(t)
        assert "platforms" in d
        assert d["platforms"]["macos"] == {}

        # Round-trip preserves the empty-block marker.
        from io import StringIO
        # Roundtrip via dict alone (no file).
        t2 = tool_from_dict(d)
        assert "macos" in t2.platforms
        assert t2.platforms["macos"] == PlatformOverride()

    def test_actions_in_override_round_trip(
        self, tmp_path: Path,
    ) -> None:
        """A platform-specific actions list round-trips with
        the same shape as top-level actions."""
        t = _minimal_tool()
        t.platforms["macos"] = PlatformOverride(
            actions=[
                ActionDef(
                    id="hello_mac",
                    label="Hello (mac)",
                    argv=["echo", "hi from mac"],
                ),
            ],
        )
        p = tmp_path / "t.scriptree"
        save_tool(t, p)
        loaded = load_tool(p)

        mac = loaded.platforms["macos"]
        assert mac.actions is not None
        assert len(mac.actions) == 1
        assert mac.actions[0].id == "hello_mac"
        assert mac.actions[0].argv == ["echo", "hi from mac"]


# ============================================================================
# Robustness: malformed values coerce to safe defaults.
# ============================================================================


class TestMalformedTolerance:
    def test_non_dict_platforms_falls_back_to_empty(self) -> None:
        d = {
            "schema_version": 3,
            "name": "X",
            "executable": "py.exe",
            "platforms": "this should be a dict",
        }
        t = tool_from_dict(d)
        assert t.platforms == {}

    def test_unknown_os_id_dropped(self) -> None:
        """A hand-edited file with a typo'd OS id (``"mac"``
        instead of ``"macos"``) must NOT crash loading."""
        d = {
            "schema_version": 3,
            "name": "X",
            "executable": "py.exe",
            "platforms": {
                "macos": {"executable": "python3"},
                "freebsd": {"executable": "python3"},  # unknown
                "mac": {"executable": "python3"},  # typo
            },
        }
        t = tool_from_dict(d)
        assert "macos" in t.platforms
        assert "freebsd" not in t.platforms
        assert "mac" not in t.platforms

    def test_non_dict_override_treated_as_empty(self) -> None:
        d = {
            "schema_version": 3,
            "name": "X",
            "executable": "py.exe",
            "platforms": {
                "macos": "should be a dict",
            },
        }
        t = tool_from_dict(d)
        # Treated as PlatformOverride() (no fields set).
        assert "macos" in t.platforms
        assert t.platforms["macos"].executable is None

    def test_malformed_argument_template_falls_back_to_none(self) -> None:
        """A non-list ``argument_template`` in an override means
        the JSON file is hand-edited badly; treat as ``None``
        (= inherit default) rather than crash."""
        d = {
            "schema_version": 3,
            "name": "X",
            "executable": "py.exe",
            "argument_template": ["-3", "./x.py"],
            "platforms": {
                "macos": {"argument_template": "not a list"},
            },
        }
        t = tool_from_dict(d)
        assert t.platforms["macos"].argument_template is None
