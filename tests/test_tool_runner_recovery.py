"""UI integration tests for the missing-executable recovery routing.

Covers the per-scope behavior of ``_offer_missing_executable_recovery``:

* SCOPE_REPLACE_FILE rewrites ``tool.executable`` to the new absolute
  path and saves.
* SCOPE_SCRIPTREE rewrites ``tool.executable`` to the basename, appends
  the directory to ``tool.path_prepend``, saves the .scriptree, AND
  pins ``argv[0]`` to the absolute path for THIS run via
  ``_recovery_argv0_override`` so the immediate run does not have to
  wait for search-path propagation.
* SCOPE_SESSION leaves the .scriptree on disk untouched but adds the
  directory to ``os.environ["PATH"]`` and pins ``argv[0]``.
* SCOPE_USER_PATH / SCOPE_SYSTEM_PATH are similar to SCOPE_SCRIPTREE
  in the .scriptree mutation semantics, but the registry write is
  short-circuited to a fake so the tests don't side-effect the host.

The dialog is monkeypatched to return a pre-canned
``(replacement, scope, directory, apply_to_all)`` tuple — that lets
the tests focus on the routing without driving the Qt event loop.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from scriptree.core.io import load_tool, save_tool  # noqa: E402
from scriptree.core.model import ParamDef, ToolDef  # noqa: E402
from scriptree.ui import recovery_dialog as rd  # noqa: E402
from scriptree.ui import tool_runner as tr_module  # noqa: E402
from scriptree.ui.tool_runner import ToolRunnerView  # noqa: E402


def _saved_tool(
    tmp_path: Path, *, executable: str = ""
) -> tuple[ToolDef, str]:
    tool = ToolDef(
        name="demo",
        executable=executable
        or str(tmp_path / "old_dir" / "missing_tool.exe"),
        argument_template=["{name}"],
        params=[ParamDef(id="name", label="Name", default="hello")],
    )
    path = tmp_path / "demo.scriptree"
    save_tool(tool, path)
    return tool, str(path)


class _FakeDlg:
    """Stand-in for MissingFileRecoveryDialog. Returns canned values
    from the result accessors instead of running an event loop."""

    def __init__(
        self,
        *,
        replacement: str | None,
        scope: str | None,
        directory: str | None,
        apply_to_all: bool = False,
    ) -> None:
        self._r = replacement
        self._s = scope
        self._d = directory
        self._a = apply_to_all

    def exec(self) -> int:
        from PySide6.QtWidgets import QDialog
        return int(QDialog.DialogCode.Accepted)

    def selected_replacement(self) -> str | None:
        return self._r

    def selected_scope(self) -> str | None:
        return self._s

    def selected_directory(self) -> str | None:
        return self._d

    def apply_to_all(self) -> bool:
        return self._a


def _patch_dialog(monkeypatch, **kwargs) -> None:
    def _factory(*_args, **_kw):
        return _FakeDlg(**kwargs)

    monkeypatch.setattr(
        "scriptree.ui.tool_runner.MissingFileRecoveryDialog",
        _factory,
        raising=False,
    )


def _patch_imports_inside_recovery(monkeypatch, **kwargs) -> None:
    """The recovery method does ``from .recovery_dialog import ...``
    inside the function body. Patch the module attribute the import
    statement reaches."""
    fake = type(
        "F",
        (),
        {
            "__init__": lambda self, *a, **k: None,
            "exec": lambda self: 1,
            "selected_replacement": lambda self: kwargs.get("replacement"),
            "selected_scope": lambda self: kwargs.get("scope"),
            "selected_directory": lambda self: kwargs.get("directory"),
            "apply_to_all": lambda self: kwargs.get("apply_to_all", False),
        },
    )
    monkeypatch.setattr(
        rd, "MissingFileRecoveryDialog", fake, raising=False
    )


def test_scope_replace_file_writes_absolute_path(tmp_path, monkeypatch):
    tool, path = _saved_tool(tmp_path)
    new_exe = tmp_path / "found" / "tool.exe"
    new_exe.parent.mkdir()
    new_exe.touch()

    view = ToolRunnerView(tool, file_path=path)
    _patch_imports_inside_recovery(
        monkeypatch,
        replacement=str(new_exe),
        scope=rd.SCOPE_REPLACE_FILE,
        directory=str(new_exe.parent),
    )

    ok = view._offer_missing_executable_recovery(tool.executable)
    assert ok is True
    # In-memory tool got the absolute new path.
    assert Path(view._tool.executable).resolve() == new_exe.resolve()
    # On-disk .scriptree was saved with the same value.
    reloaded = load_tool(path)
    assert Path(reloaded.executable).resolve() == new_exe.resolve()


def test_scope_scriptree_rewrites_executable_to_basename_and_persists(
    tmp_path, monkeypatch
):
    tool, path = _saved_tool(tmp_path)
    new_exe = tmp_path / "newbin" / "tool.exe"
    new_exe.parent.mkdir()
    new_exe.touch()

    view = ToolRunnerView(tool, file_path=path)
    _patch_imports_inside_recovery(
        monkeypatch,
        replacement=str(new_exe),
        scope=rd.SCOPE_SCRIPTREE,
        directory=str(new_exe.parent),
    )

    ok = view._offer_missing_executable_recovery(tool.executable)
    assert ok is True

    # In-memory: executable is now the basename, path_prepend has the
    # new dir, argv[0] override is the absolute path.
    assert view._tool.executable == "tool.exe"
    assert str(new_exe.parent) in view._tool.path_prepend
    assert view._recovery_argv0_override == str(Path(new_exe).resolve())

    # On-disk: same.
    reloaded = load_tool(path)
    assert reloaded.executable == "tool.exe"
    assert str(new_exe.parent) in reloaded.path_prepend


def test_scope_scriptree_idempotent_path_prepend(tmp_path, monkeypatch):
    tool, path = _saved_tool(tmp_path)
    target_dir = tmp_path / "newbin"
    target_dir.mkdir()
    new_exe = target_dir / "tool.exe"
    new_exe.touch()
    # Pre-seed the path_prepend with the same dir.
    tool.path_prepend = [str(target_dir)]
    save_tool(tool, path)

    view = ToolRunnerView(tool, file_path=path)
    _patch_imports_inside_recovery(
        monkeypatch,
        replacement=str(new_exe),
        scope=rd.SCOPE_SCRIPTREE,
        directory=str(target_dir),
    )

    view._offer_missing_executable_recovery(tool.executable)
    # Still only one entry; not duplicated.
    assert view._tool.path_prepend.count(str(target_dir)) == 1


def test_scope_session_pins_argv0_without_modifying_scriptree(
    tmp_path, monkeypatch
):
    tool, path = _saved_tool(tmp_path)
    new_exe = tmp_path / "newbin" / "tool.exe"
    new_exe.parent.mkdir()
    new_exe.touch()
    original_executable = tool.executable

    view = ToolRunnerView(tool, file_path=path)
    _patch_imports_inside_recovery(
        monkeypatch,
        replacement=str(new_exe),
        scope=rd.SCOPE_SESSION,
        directory=str(new_exe.parent),
    )

    # Snapshot PATH so we can assert the dir landed on os.environ.
    import os
    saved_path = os.environ.get("PATH", "")
    try:
        ok = view._offer_missing_executable_recovery(tool.executable)
        assert ok is True
        # tool.executable IS untouched (session-only is transient).
        assert view._tool.executable == original_executable
        # argv override pins the absolute path for THIS run.
        assert view._recovery_argv0_override == \
            str(Path(new_exe).resolve())
        # os.environ["PATH"] now starts with the new directory.
        assert os.environ["PATH"].split(os.pathsep)[0].lower() == \
            str(new_exe.parent.resolve()).lower()
    finally:
        os.environ["PATH"] = saved_path

    # The on-disk .scriptree still has the old (missing) executable —
    # session scope is not supposed to touch it.
    reloaded = load_tool(path)
    assert reloaded.executable == original_executable


def test_scope_user_path_writes_basename_and_calls_registry(
    tmp_path, monkeypatch
):
    tool, path = _saved_tool(tmp_path)
    new_exe = tmp_path / "newbin" / "tool.exe"
    new_exe.parent.mkdir()
    new_exe.touch()

    # Stub out the registry mutation so the test doesn't side-effect.
    captured_calls: list[str] = []

    def _fake_user_path(directory: str):
        captured_calls.append(directory)
        from scriptree.core.path_env import ScopeResult
        return ScopeResult(True, f"fake-success: {directory}")

    monkeypatch.setattr(
        "scriptree.core.path_env.add_to_user_path", _fake_user_path
    )

    view = ToolRunnerView(tool, file_path=path)
    _patch_imports_inside_recovery(
        monkeypatch,
        replacement=str(new_exe),
        scope=rd.SCOPE_USER_PATH,
        directory=str(new_exe.parent),
    )

    ok = view._offer_missing_executable_recovery(tool.executable)
    assert ok is True

    # Registry stub was called with the right dir.
    assert captured_calls == [str(new_exe.parent)]
    # Tool's executable was rewritten to basename and saved.
    assert view._tool.executable == "tool.exe"
    reloaded = load_tool(path)
    assert reloaded.executable == "tool.exe"


def test_scope_scriptree_change_visible_in_env_editor(
    tmp_path, monkeypatch
):
    """Regression for "I picked SCOPE_SCRIPTREE and nothing showed up in
    Edit environment...". The dialog reads ``tool.path_prepend`` directly
    off the in-memory ``ToolDef`` — so the recovery routing must update
    the in-memory copy, not just save to disk."""
    tool, path = _saved_tool(tmp_path)
    new_dir = tmp_path / "newbin"
    new_dir.mkdir()
    new_exe = new_dir / "tool.exe"
    new_exe.touch()

    view = ToolRunnerView(tool, file_path=path)
    _patch_imports_inside_recovery(
        monkeypatch,
        replacement=str(new_exe),
        scope=rd.SCOPE_SCRIPTREE,
        directory=str(new_dir),
    )

    view._offer_missing_executable_recovery(tool.executable)

    # What the env editor reads when you click "Edit environment...".
    assert str(new_dir) in view._tool.path_prepend


def test_recovery_argv0_override_propagates_into_argv(
    tmp_path, monkeypatch
):
    """End-to-end: after a SCOPE_SESSION recovery, the next time the
    runner builds argv it should swap argv[0] to the override (the
    new absolute path), NOT the still-stale tool.executable."""
    tool, path = _saved_tool(tmp_path)
    new_exe = tmp_path / "newbin" / "tool.exe"
    new_exe.parent.mkdir()
    new_exe.touch()

    view = ToolRunnerView(tool, file_path=path)
    _patch_imports_inside_recovery(
        monkeypatch,
        replacement=str(new_exe),
        scope=rd.SCOPE_SESSION,
        directory=str(new_exe.parent),
    )
    view._offer_missing_executable_recovery(tool.executable)

    # Mimic the start_run code path (the relevant 4 lines).
    argv = [tool.executable]  # the stale absolute path the runner built
    override = getattr(view, "_recovery_argv0_override", None)
    argv[0] = override or view._tool.executable

    assert argv[0] == str(Path(new_exe).resolve())
