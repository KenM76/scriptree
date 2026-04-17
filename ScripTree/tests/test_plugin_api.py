"""Tests for scriptree.core.parser.plugin_api.

Covers the registry behaviors: priority ordering, name deduplication,
exception tolerance, enable/disable, and loading user plugins from a
filesystem directory via ``load_plugins_from_dir``.
"""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from scriptree.core.model import ParseSource, ToolDef
from scriptree.core.parser.plugin_api import (
    PluginInfo,
    PluginRegistry,
    get_default_registry,
    load_builtin_plugins,
    load_plugins_from_dir,
    reset_default_registry,
)


# --- tiny helpers ----------------------------------------------------------

def _stub_plugin(
    name: str,
    priority: int,
    *,
    returns: ToolDef | None = None,
    raises: Exception | None = None,
    enabled: bool = True,
) -> PluginInfo:
    """Build a PluginInfo whose detect() does a predictable thing."""
    def detect(_text: str) -> ToolDef | None:
        if raises is not None:
            raise raises
        return returns

    return PluginInfo(
        name=name,
        priority=priority,
        description=f"stub-{name}",
        enabled=enabled,
        detect=detect,
        source=f"stub:{name}",
    )


def _tool(name: str) -> ToolDef:
    return ToolDef(
        name=name,
        executable="/bin/echo",
        source=ParseSource(mode=f"stub-{name}"),
    )


# --- registry core behavior ------------------------------------------------

class TestRegistryOrdering:
    def test_sorted_by_priority(self) -> None:
        reg = PluginRegistry()
        reg.add(_stub_plugin("b", 20))
        reg.add(_stub_plugin("a", 10))
        reg.add(_stub_plugin("c", 30))
        assert reg.names() == ["a", "b", "c"]

    def test_priority_tiebreak_by_name(self) -> None:
        reg = PluginRegistry()
        reg.add(_stub_plugin("zulu", 10))
        reg.add(_stub_plugin("alpha", 10))
        reg.add(_stub_plugin("mike", 10))
        assert reg.names() == ["alpha", "mike", "zulu"]

    def test_highest_priority_wins_parse(self) -> None:
        reg = PluginRegistry()
        reg.add(_stub_plugin("low", 50, returns=_tool("low")))
        reg.add(_stub_plugin("high", 10, returns=_tool("high")))
        result = reg.parse("any text")
        assert result is not None
        assert result.name == "high"

    def test_returns_none_when_nothing_matches(self) -> None:
        reg = PluginRegistry()
        reg.add(_stub_plugin("a", 10, returns=None))
        reg.add(_stub_plugin("b", 20, returns=None))
        assert reg.parse("anything") is None


class TestRegistryDedupAndDisable:
    def test_add_replaces_by_name(self) -> None:
        """User plugins override built-ins by sharing a name."""
        reg = PluginRegistry()
        reg.add(_stub_plugin("argparse", 10, returns=_tool("original")))
        reg.add(_stub_plugin("argparse", 10, returns=_tool("override")))
        assert len(reg.plugins) == 1
        result = reg.parse("x")
        assert result.name == "override"

    def test_disabled_plugin_is_skipped(self) -> None:
        reg = PluginRegistry()
        reg.add(_stub_plugin("off", 10, returns=_tool("off"), enabled=False))
        reg.add(_stub_plugin("on", 20, returns=_tool("on")))
        result = reg.parse("x")
        assert result.name == "on"


class TestRegistryExceptionTolerance:
    def test_raising_plugin_does_not_kill_pipeline(self, caplog) -> None:
        reg = PluginRegistry()
        reg.add(_stub_plugin("broken", 10, raises=ValueError("oops")))
        reg.add(_stub_plugin("working", 20, returns=_tool("working")))
        result = reg.parse("x")
        assert result.name == "working"
        assert any("broken" in rec.message for rec in caplog.records)


# --- user plugin loading from a directory ---------------------------------

class TestLoadFromDir:
    def _write(self, dirpath: Path, filename: str, content: str) -> None:
        (dirpath / filename).write_text(textwrap.dedent(content), encoding="utf-8")

    def test_loads_valid_plugin(self, tmp_path: Path) -> None:
        self._write(tmp_path, "my_parser.py", """\
            from scriptree.core.model import ToolDef, ParseSource

            NAME = "my_parser"
            PRIORITY = 15
            DESCRIPTION = "Test plugin"

            def detect(text):
                if "MARKER" in text:
                    return ToolDef(
                        name="detected",
                        executable="/bin/true",
                        source=ParseSource(mode="my_parser"),
                    )
                return None
        """)
        reg = PluginRegistry()
        n = load_plugins_from_dir(reg, tmp_path)
        assert n == 1
        assert "my_parser" in reg.names()
        result = reg.parse("contains MARKER somewhere")
        assert result is not None
        assert result.name == "detected"

    def test_skips_underscore_files(self, tmp_path: Path) -> None:
        self._write(tmp_path, "_helper.py", """\
            NAME = "should_not_load"
            PRIORITY = 15
            def detect(t): return None
        """)
        reg = PluginRegistry()
        n = load_plugins_from_dir(reg, tmp_path)
        assert n == 0
        assert "should_not_load" not in reg.names()

    def test_skips_files_missing_plugin_attrs(self, tmp_path: Path) -> None:
        self._write(tmp_path, "not_a_plugin.py", """\
            # Regular Python file without plugin metadata.
            def helper():
                return 42
        """)
        reg = PluginRegistry()
        n = load_plugins_from_dir(reg, tmp_path)
        assert n == 0

    def test_broken_plugin_does_not_crash_loader(
        self, tmp_path: Path, caplog
    ) -> None:
        self._write(tmp_path, "broken.py", """\
            NAME = "broken"
            PRIORITY = 10
            def detect(t):
                return None
            raise RuntimeError("import-time blowup")
        """)
        # Also add a good plugin to confirm the loader continues.
        self._write(tmp_path, "good.py", """\
            NAME = "good"
            PRIORITY = 20
            def detect(t): return None
        """)
        reg = PluginRegistry()
        n = load_plugins_from_dir(reg, tmp_path)
        # Only the good plugin should load.
        assert n == 1
        assert "good" in reg.names()
        assert "broken" not in reg.names()
        assert any("broken.py" in rec.message for rec in caplog.records)

    def test_nonexistent_dir_returns_zero(self, tmp_path: Path) -> None:
        n = load_plugins_from_dir(PluginRegistry(), tmp_path / "does_not_exist")
        assert n == 0


# --- default registry + built-in loading ----------------------------------

class TestDefaultRegistry:
    def setup_method(self) -> None:
        reset_default_registry()

    def teardown_method(self) -> None:
        # Clear after too so we don't leak state into other test modules.
        reset_default_registry()

    def test_default_registry_has_builtins(self) -> None:
        reg = get_default_registry()
        names = reg.names()
        for expected in ("argparse", "click", "winhelp", "heuristic"):
            assert expected in names, (
                f"Built-in plugin {expected!r} missing from registry "
                f"(loaded: {names})"
            )

    def test_heuristic_is_last(self) -> None:
        reg = get_default_registry()
        # Heuristic must run dead last so other plugins get a chance.
        assert reg.names()[-1] == "heuristic"

    def test_env_var_loads_user_plugins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "custom.py").write_text(textwrap.dedent("""\
            from scriptree.core.model import ToolDef, ParseSource
            NAME = "envvar_plugin"
            PRIORITY = 5
            def detect(text):
                return None
        """), encoding="utf-8")
        monkeypatch.setenv("SCRIPTREE_PARSERS_DIR", str(tmp_path))
        reset_default_registry()
        reg = get_default_registry()
        assert "envvar_plugin" in reg.names()
        # And because priority=5, it should be first.
        assert reg.names()[0] == "envvar_plugin"

    def test_env_var_multiple_dirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dir1 = tmp_path / "a"
        dir2 = tmp_path / "b"
        dir1.mkdir()
        dir2.mkdir()
        (dir1 / "plug_a.py").write_text(
            'NAME = "plug_a"\nPRIORITY = 5\ndef detect(t): return None\n',
            encoding="utf-8",
        )
        (dir2 / "plug_b.py").write_text(
            'NAME = "plug_b"\nPRIORITY = 6\ndef detect(t): return None\n',
            encoding="utf-8",
        )
        monkeypatch.setenv(
            "SCRIPTREE_PARSERS_DIR", f"{dir1}{os.pathsep}{dir2}"
        )
        reset_default_registry()
        reg = get_default_registry()
        assert "plug_a" in reg.names()
        assert "plug_b" in reg.names()


# --- built-in loader contract test ----------------------------------------

class TestBuiltinLoader:
    def test_load_builtin_plugins_finds_four(self) -> None:
        reg = PluginRegistry()
        load_builtin_plugins(reg)
        names = set(reg.names())
        assert {"argparse", "click", "winhelp", "heuristic"}.issubset(names)

    def test_core_helper_module_not_loaded(self) -> None:
        """_core.py starts with an underscore so it must be skipped."""
        reg = PluginRegistry()
        load_builtin_plugins(reg)
        assert "_core" not in reg.names()
        assert "core" not in reg.names()
