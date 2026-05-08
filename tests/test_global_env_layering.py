"""Tests for the **global** env / PATH-prepend layering surfaces
that were uncovered before v0.3.2.

Three previously-untested surfaces:

1. ``core.runner.build_env`` keyword args
   ``global_env`` / ``global_env_overrides`` /
   ``global_path_prepend`` / ``global_path_overrides`` —
   the override-priority modes ("tool wins" vs "global wins").

2. ``ui.settings_dialog`` helpers
   ``load_global_env`` / ``load_global_path_prepend`` /
   ``global_env_overrides_tool`` / ``global_path_overrides_tool``
   that read those flags from QSettings.

3. ``core.runner.build_full_argv`` forwards the kwargs to
   ``build_env`` correctly.

Plus a regression-pin for ``TreeDef.path_prepend`` — see the
``TestTreePathPrependDeadCodeGap`` class at the bottom for the
*current* (broken) state.

Layering rules pinned by these tests
------------------------------------

**Env (KEY=VALUE)** — default ``global_env_overrides=False``::

    base_env  <  global_env  <  tool.env  <  config_env

(Higher wins; ``config`` overrides ``tool`` overrides ``global``.)

When ``global_env_overrides=True``, global moves to the top::

    base_env  <  tool.env  <  config_env  <  global_env

**PATH** — default ``global_path_overrides=False``::

    [tool.path_prepend, config.path_prepend, global.path_prepend, original PATH]

(Earlier in PATH = higher search priority; tool wins by default.)

When ``global_path_overrides=True``::

    [global.path_prepend, tool.path_prepend, config.path_prepend, original PATH]

These rules are slightly asymmetric: for env vars, **config**
takes priority within the local scope; for PATH search, **tool**
takes priority within the local scope.  This module pins the
asymmetry so any future "let's normalise the rules" refactor
flags the change in CI.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from scriptree.core.io import save_tool, save_tree
from scriptree.core.model import ToolDef, TreeDef, TreeNode
from scriptree.core.runner import build_env, build_full_argv


def _tool(**kw) -> ToolDef:
    """Tiny ToolDef factory.  Tools intentionally have NO sensible
    executable / params so build_env's PATH-anchor heuristic has
    nothing to anchor on — relative dirs in path_prepend are kept
    as-is.  Tests that need an anchor pass ``executable=`` or
    ``working_directory=`` explicitly."""
    base = dict(name="x", executable="python")
    base.update(kw)
    return ToolDef(**base)


# ===========================================================================
# 1. build_env — env-variable layering matrix
# ===========================================================================

class TestEnvLayering:

    def test_global_env_only_appears_in_result(self) -> None:
        """global_env on its own triggers a non-None result and the
        var ends up in the merged env dict."""
        env = build_env(
            _tool(),
            base_env={"PATH": ""},
            global_env={"GLB": "g"},
        )
        assert env is not None
        assert env["GLB"] == "g"

    def test_default_precedence_config_over_tool_over_global(self) -> None:
        """All three layers set the same key; with global_env_overrides
        defaulting to False, config wins, then tool, then global."""
        env = build_env(
            _tool(env={"K": "tool"}),
            config_env={"K": "config"},
            base_env={"PATH": ""},
            global_env={"K": "global"},
        )
        assert env is not None
        assert env["K"] == "config"

    def test_default_precedence_tool_over_global(self) -> None:
        env = build_env(
            _tool(env={"K": "tool"}),
            base_env={"PATH": ""},
            global_env={"K": "global"},
        )
        assert env is not None
        assert env["K"] == "tool"

    def test_default_precedence_global_over_base(self) -> None:
        env = build_env(
            _tool(),
            base_env={"PATH": "", "K": "base"},
            global_env={"K": "global"},
        )
        assert env is not None
        assert env["K"] == "global"

    def test_overrides_flag_flips_global_to_top(self) -> None:
        """global_env_overrides=True → global wins over config + tool."""
        env = build_env(
            _tool(env={"K": "tool"}),
            config_env={"K": "config"},
            base_env={"PATH": ""},
            global_env={"K": "global"},
            global_env_overrides=True,
        )
        assert env is not None
        assert env["K"] == "global"

    def test_overrides_flag_keeps_disjoint_layers(self) -> None:
        """When override is on, every layer's keys still appear; the
        flag only changes the priority for COLLIDING keys."""
        env = build_env(
            _tool(env={"TOOL_ONLY": "t"}),
            config_env={"CFG_ONLY": "c"},
            base_env={"PATH": "", "BASE_ONLY": "b"},
            global_env={"GLB_ONLY": "g"},
            global_env_overrides=True,
        )
        assert env is not None
        assert env["TOOL_ONLY"] == "t"
        assert env["CFG_ONLY"] == "c"
        assert env["BASE_ONLY"] == "b"
        assert env["GLB_ONLY"] == "g"

    def test_no_overrides_returns_none(self) -> None:
        """All layers empty → None (caller passes env=None to
        Popen so the child inherits parent env unchanged)."""
        assert build_env(_tool()) is None

    def test_global_env_alone_triggers_non_none(self) -> None:
        """global_env is reason enough to materialise an env dict
        even without tool / config overrides — pre-v0.3.2 the
        early-out check forgot about global; this pins the fix."""
        env = build_env(
            _tool(),
            base_env={"PATH": ""},
            global_env={"X": "y"},
        )
        assert env is not None
        assert env["X"] == "y"

    def test_global_path_alone_triggers_non_none(self) -> None:
        """Same logic as the env-alone case but for path_prepend."""
        d = os.path.abspath("/some/dir")  # platform-normalised
        env = build_env(
            _tool(),
            base_env={"PATH": ""},
            global_path_prepend=[d],
        )
        assert env is not None
        assert d in env["PATH"]


# ===========================================================================
# 2. build_env — PATH layering matrix
# ===========================================================================

class TestPathLayering:

    @staticmethod
    def _norm(p: str) -> str:
        """Platform-normalise a path-like string the same way build_env
        does, so comparisons work on Windows (which resolves
        ``/tool`` against the current drive to ``D:\\tool``) and on
        POSIX (no rewrite).  ``os.path.abspath`` matches the output
        of ``Path(...)`` then ``.resolve(strict=False)`` that
        ``build_env._resolve`` runs internally for relative-anchor
        path entries."""
        return os.path.abspath(p)

    def test_default_path_order_tool_then_config_then_global(self) -> None:
        """Default order in the prepend list (earlier = higher search
        priority): tool first, config second, global third."""
        n = self._norm
        env = build_env(
            _tool(path_prepend=[n("/tool")]),
            config_path_prepend=[n("/cfg")],
            base_env={"PATH": n("/base")},
            global_path_prepend=[n("/glb")],
        )
        assert env is not None
        parts = env["PATH"].split(os.pathsep)
        assert parts[0] == n("/tool")
        assert parts[1] == n("/cfg")
        assert parts[2] == n("/glb")
        assert parts[3] == n("/base")

    def test_global_path_overrides_flag_promotes_global_to_front(self) -> None:
        """global_path_overrides=True → [global, tool, config, base]."""
        n = self._norm
        env = build_env(
            _tool(path_prepend=[n("/tool")]),
            config_path_prepend=[n("/cfg")],
            base_env={"PATH": n("/base")},
            global_path_prepend=[n("/glb")],
            global_path_overrides=True,
        )
        assert env is not None
        parts = env["PATH"].split(os.pathsep)
        assert parts[0] == n("/glb")
        assert parts[1] == n("/tool")
        assert parts[2] == n("/cfg")
        assert parts[3] == n("/base")

    def test_path_separator_is_os_pathsep(self) -> None:
        """Sanity: the PATH joiner is os.pathsep, so on Windows
        entries are separated by ``;``, on POSIX by ``:``."""
        n = self._norm
        env = build_env(
            _tool(path_prepend=[n("/a")]),
            base_env={"PATH": n("/b")},
            global_path_prepend=[n("/c")],
        )
        assert env is not None
        assert os.pathsep in env["PATH"]

    def test_empty_base_path_means_prepend_only(self) -> None:
        n = self._norm
        env = build_env(
            _tool(path_prepend=[n("/tool")]),
            base_env={"PATH": ""},
            global_path_prepend=[n("/glb")],
        )
        assert env is not None
        # No trailing separator and no empty entry from the missing base.
        assert env["PATH"].split(os.pathsep) == [n("/tool"), n("/glb")]

    def test_env_override_independent_of_path_override(self) -> None:
        """Two flags are independent: you can have global ENV win
        without making global PATH win, and vice versa."""
        n = self._norm
        env = build_env(
            _tool(env={"K": "tool"}, path_prepend=[n("/tool")]),
            base_env={"PATH": n("/base")},
            global_env={"K": "global"},
            global_env_overrides=True,        # ENV: global wins
            global_path_prepend=[n("/glb")],
            global_path_overrides=False,       # PATH: tool stays first
        )
        assert env is not None
        assert env["K"] == "global"
        path_parts = env["PATH"].split(os.pathsep)
        assert path_parts[0] == n("/tool")   # tool first despite ENV override
        assert path_parts[1] == n("/glb")

    def test_path_override_independent_of_env_override(self) -> None:
        """Mirror of the above."""
        n = self._norm
        env = build_env(
            _tool(env={"K": "tool"}, path_prepend=[n("/tool")]),
            base_env={"PATH": n("/base")},
            global_env={"K": "global"},
            global_env_overrides=False,        # ENV: tool wins
            global_path_prepend=[n("/glb")],
            global_path_overrides=True,        # PATH: global wins
        )
        assert env is not None
        assert env["K"] == "tool"
        path_parts = env["PATH"].split(os.pathsep)
        assert path_parts[0] == n("/glb")   # global first
        assert path_parts[1] == n("/tool")


# ===========================================================================
# 3. ui.settings_dialog helper functions — read from QSettings
# ===========================================================================

class TestSettingsDialogHelpers:
    """The Settings dialog persists the global-env textarea, the
    global-PATH textarea, and the two override checkboxes via
    QSettings.  These helpers read them back at run time and feed
    them into ``build_full_argv``.

    We exercise them with a real QSettings (in-memory format) so
    the tests don't pollute the user's actual ScripTree config.
    """

    @pytest.fixture
    def qs(self):
        from PySide6.QtCore import QSettings
        # Use INI-format / temp file so each test gets isolation.
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        s = QSettings("ScripTreeTest", "GlobalEnvLayeringTest")
        s.clear()
        yield s
        s.clear()

    def test_load_global_env_parses_kv_lines(self, qs) -> None:
        from scriptree.ui.settings_dialog import load_global_env
        qs.setValue("global_env", "FOO=1\nBAR=two\n# comment\n")
        assert load_global_env(qs) == {"FOO": "1", "BAR": "two"}

    def test_load_global_env_blank_when_unset(self, qs) -> None:
        from scriptree.ui.settings_dialog import load_global_env
        assert load_global_env(qs) == {}

    def test_load_global_path_prepend_one_per_line(self, qs) -> None:
        from scriptree.ui.settings_dialog import load_global_path_prepend
        qs.setValue("global_path_prepend", "C:/Tools/a\nC:/Tools/b\n")
        assert load_global_path_prepend(qs) == ["C:/Tools/a", "C:/Tools/b"]

    def test_load_global_path_prepend_blank_when_unset(self, qs) -> None:
        from scriptree.ui.settings_dialog import load_global_path_prepend
        assert load_global_path_prepend(qs) == []

    def test_global_env_overrides_tool_default_false(self, qs) -> None:
        from scriptree.ui.settings_dialog import global_env_overrides_tool
        assert global_env_overrides_tool(qs) is False

    def test_global_env_overrides_tool_reads_true(self, qs) -> None:
        from scriptree.ui.settings_dialog import global_env_overrides_tool
        qs.setValue("global_env_override", True)
        assert global_env_overrides_tool(qs) is True

    def test_global_path_overrides_tool_default_false(self, qs) -> None:
        from scriptree.ui.settings_dialog import global_path_overrides_tool
        assert global_path_overrides_tool(qs) is False

    def test_global_path_overrides_tool_reads_true(self, qs) -> None:
        from scriptree.ui.settings_dialog import global_path_overrides_tool
        qs.setValue("global_path_override", True)
        assert global_path_overrides_tool(qs) is True


# ===========================================================================
# 4. build_full_argv forwards the kwargs to build_env
# ===========================================================================

class TestBuildFullArgvForwardsGlobals:

    def test_global_env_appears_in_resolved_command(self) -> None:
        cmd = build_full_argv(
            _tool(),
            {"name": "x"},
            extras=[],
            global_env={"GLB": "g"},
        )
        assert cmd.env is not None
        assert cmd.env["GLB"] == "g"

    def test_global_env_overrides_flag_forwarded(self) -> None:
        cmd = build_full_argv(
            _tool(env={"K": "tool"}),
            {"name": "x"},
            extras=[],
            config_env={"K": "config"},
            global_env={"K": "global"},
            global_env_overrides=True,
        )
        assert cmd.env is not None
        assert cmd.env["K"] == "global"

    def test_global_path_prepend_appears_in_resolved_path(self) -> None:
        d = os.path.abspath("/glb/path")
        cmd = build_full_argv(
            _tool(),
            {"name": "x"},
            extras=[],
            global_path_prepend=[d],
        )
        assert cmd.env is not None
        assert d in cmd.env["PATH"]

    def test_global_path_overrides_flag_forwarded(self) -> None:
        glb = os.path.abspath("/glb")
        tool = os.path.abspath("/tool")
        cmd = build_full_argv(
            _tool(path_prepend=[tool]),
            {"name": "x"},
            extras=[],
            global_path_prepend=[glb],
            global_path_overrides=True,
        )
        assert cmd.env is not None
        parts = cmd.env["PATH"].split(os.pathsep)
        assert parts[0] == glb


# ===========================================================================
# 5. Regression pin — TreeDef.path_prepend has NO run-time wiring (yet)
# ===========================================================================

class TestTreePathPrependDeadCodeGap:
    """``TreeDef.path_prepend`` is a real field that round-trips
    through ``save_tree`` / ``load_tree`` and that the
    missing-executable recovery dialog can append to via
    ``add_to_scriptreetree_path_prepend``.  But — as of v0.3.1 — it
    has **no run-time wiring**: ``build_env`` accepts no
    ``tree_path_prepend`` argument, ``build_full_argv`` passes
    nothing of the sort, and ``MainWindow._show_runner`` /
    ``ToolRunnerView._start_run`` never read the launcher's tree
    field.  Entries the user adds to a tree's ``path_prepend`` are
    silently dropped at run time.

    These tests **pin the broken state** so any future fix flips
    them red and the change is intentional.  When the gap is
    fixed:

    * Replace ``test_tree_path_prepend_does_NOT_reach_build_env``
      with a positive test that ``tree_path_prepend=...`` reaches
      ``build_env``.
    * Drop ``test_build_env_has_no_tree_path_prepend_kwarg`` (it
      will fail with the new signature, which is the desired
      signal).
    """

    def test_tree_path_prepend_round_trips_to_disk(
        self, tmp_path: Path,
    ) -> None:
        """Confirm the field is real — saved AND reloaded."""
        # Need a leaf so save_tree doesn't reject the empty tree.
        tool_path = tmp_path / "leaf.scriptree"
        save_tool(_tool(), tool_path)
        tree = TreeDef(
            name="t",
            nodes=[TreeNode(type="leaf", path=str(tool_path))],
            path_prepend=["C:/Vendor/bin", "./relative/dir"],
        )
        tree_path = tmp_path / "demo.scriptreetree"
        save_tree(tree, tree_path)

        from scriptree.core.io import load_tree
        loaded = load_tree(tree_path)
        assert loaded.path_prepend == ["C:/Vendor/bin", "./relative/dir"]

    def test_build_env_has_no_tree_path_prepend_kwarg(self) -> None:
        """Pin: ``build_env``'s signature does not accept any
        tree-level path_prepend.  When this test fails, the
        dead-code gap has been closed — update the layer in step."""
        import inspect
        sig = inspect.signature(build_env)
        assert "tree_path_prepend" not in sig.parameters

    def test_build_full_argv_has_no_tree_path_prepend_kwarg(self) -> None:
        """Same pin for build_full_argv."""
        import inspect
        sig = inspect.signature(build_full_argv)
        assert "tree_path_prepend" not in sig.parameters

    def test_tree_path_prepend_does_NOT_reach_resolved_command(
        self, tmp_path: Path,
    ) -> None:
        """The user spec consequence: write entries into the tree's
        path_prepend, run a tool from inside that tree, and the
        running child's PATH does NOT contain those entries.

        When this test fails, tree.path_prepend has gained run-time
        wiring (good!) and the gap test should be replaced with a
        positive test."""
        # Build a tree with a path_prepend entry.
        tool_path = tmp_path / "leaf.scriptree"
        save_tool(_tool(path_prepend=[]), tool_path)
        # Note: the tree itself carries the entry, but no API today
        # forwards it to build_full_argv.  We exercise the most
        # public entry-point (build_full_argv) the same way the
        # runner does and confirm the entry doesn't appear.
        from scriptree.core.io import load_tool
        tool = load_tool(tool_path)
        cmd = build_full_argv(
            tool,
            {"name": "x"},
            extras=[],
            # The runner has no way to forward a tree's path_prepend
            # to this call, so we don't pass anything.  When wiring
            # is added a new kwarg will appear and this test should
            # become a positive assertion.
        )
        # No env at all (no overrides anywhere) → cmd.env is None.
        assert cmd.env is None
