"""Core-layer tests for dynamic choice/value providers (v0.6.0).

Covers the *pure* layer only — ``scriptree.core.providers`` +
``scriptree.core.model`` + ``scriptree.core.io`` round-trip + the
loader invariants.  The UI orchestration (spinner / debounce /
Refresh) is exercised separately in the Qt-backed runner tests.

Per the feature spec's test checklist (§10):
  * valid JSON → choices populate; labels/default applied
  * non-zero / timeout / malformed / empty → soft error, no raise
  * depends_on forwarded via stdin JSON
  * topological order honored; cycle → load error
  * provider output sanitized (NUL / control stripped)
  * loader invariants: not-both, select_all pairing, unknown dep
  * sidecar/back-compat: a v3 file without the fields round-trips
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scriptree.core.io import load_tool, save_tool, tool_from_dict
from scriptree.core.model import (
    ParamDef, ParamType, ProviderSpec, ToolDef, Widget,
)
from scriptree.core.providers import (
    DependencyCycleError, provider_run_order, resolve_provider,
)


def _py(code: str) -> list[str]:
    """A provider argv that runs an inline Python snippet."""
    return [sys.executable, "-c", code]


# ===========================================================================
# ProviderSpec validation (model layer)
# ===========================================================================

class TestProviderSpecValidation:

    def test_empty_command_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty argv list"):
            ProviderSpec(command=[])

    def test_non_string_command_rejected(self) -> None:
        with pytest.raises(ValueError, match="must all be strings"):
            ProviderSpec(command=["ok", 3])  # type: ignore[list-item]

    def test_bad_refresh_rejected(self) -> None:
        with pytest.raises(ValueError, match="refresh must be one of"):
            ProviderSpec(command=["x"], refresh="sometimes")

    def test_bad_cache_rejected(self) -> None:
        with pytest.raises(ValueError, match="cache must be one of"):
            ProviderSpec(command=["x"], cache="forever")

    def test_nonpositive_timeout_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be > 0"):
            ProviderSpec(command=["x"], timeout_sec=0)


# ===========================================================================
# ParamDef structural invariants
# ===========================================================================

class TestParamDefInvariants:

    def test_both_static_choices_and_provider_rejected(self) -> None:
        with pytest.raises(ValueError, match="cannot set both"):
            ParamDef(
                id="x", type=ParamType.ENUM, widget=Widget.DROPDOWN,
                choices=["a"],
                choices_provider=ProviderSpec(command=["p"]),
            )

    def test_select_all_only_with_checkbox_list(self) -> None:
        with pytest.raises(ValueError, match="select_all"):
            ParamDef(
                id="x", type=ParamType.MULTISELECT,
                widget=Widget.DROPDOWN, select_all=True,
            )

    def test_select_all_ok_with_checkbox_list(self) -> None:
        p = ParamDef(
            id="x", type=ParamType.MULTISELECT,
            widget=Widget.CHECKBOX_LIST, select_all=True,
        )
        assert p.select_all is True

    def test_self_dependency_rejected(self) -> None:
        with pytest.raises(ValueError, match="trivial cycle"):
            ParamDef(
                id="x", type=ParamType.ENUM, widget=Widget.DROPDOWN,
                choices_provider=ProviderSpec(command=["p"]),
                depends_on=["x"],
            )

    def test_checkbox_list_is_valid_for_multiselect(self) -> None:
        from scriptree.core.model import VALID_WIDGETS
        assert Widget.CHECKBOX_LIST in VALID_WIDGETS[ParamType.MULTISELECT]


# ===========================================================================
# resolve_provider — execution / parse / sanitize
# ===========================================================================

class TestResolveProvider:

    def test_choice_provider_happy_path(self) -> None:
        spec = ProviderSpec(command=_py(
            "import json;print(json.dumps("
            "{'choices':['a','b'],'choice_labels':['A','B'],"
            "'default':['a']}))"
        ))
        r = resolve_provider(
            spec, param_id="p", param_type=ParamType.MULTISELECT,
        )
        assert r.ok
        assert r.choices == ["a", "b"]
        assert r.choice_labels == ["A", "B"]
        assert r.default == ["a"]
        assert r.is_scalar is False

    def test_scalar_provider_happy_path(self) -> None:
        spec = ProviderSpec(command=_py(
            "import json;print(json.dumps({'value':'C:/x'}))"
        ))
        r = resolve_provider(
            spec, param_id="v", param_type=ParamType.PATH,
        )
        assert r.ok
        assert r.is_scalar is True
        assert r.value == "C:/x"

    def test_scalar_coerces_number_and_bool(self) -> None:
        for code, expect in (
            ("{'value': 42}", "42"),
            ("{'value': True}", "true"),
            ("{'value': False}", "false"),
        ):
            spec = ProviderSpec(command=_py(
                f"import json;print(json.dumps({code}))"
            ))
            r = resolve_provider(
                spec, param_id="v", param_type=ParamType.STRING,
            )
            assert r.ok and r.value == expect, (code, r.value)

    def test_nonzero_exit_soft_fails(self) -> None:
        spec = ProviderSpec(command=_py(
            "import sys;sys.stderr.write('boom');sys.exit(2)"
        ))
        r = resolve_provider(
            spec, param_id="p", param_type=ParamType.ENUM,
        )
        assert r.ok is False
        assert "exited with code 2" in r.error
        assert "boom" in r.detail

    def test_timeout_soft_fails(self) -> None:
        spec = ProviderSpec(
            command=_py("import time;time.sleep(5)"),
            timeout_sec=1,
        )
        r = resolve_provider(
            spec, param_id="p", param_type=ParamType.ENUM,
        )
        assert r.ok is False
        assert "timed out" in r.error

    def test_malformed_json_soft_fails(self) -> None:
        spec = ProviderSpec(command=_py("print('not json')"))
        r = resolve_provider(
            spec, param_id="p", param_type=ParamType.ENUM,
        )
        assert r.ok is False
        assert "not valid JSON" in r.error

    def test_empty_choices_soft_fails(self) -> None:
        spec = ProviderSpec(command=_py(
            "import json;print(json.dumps({'choices':[]}))"
        ))
        r = resolve_provider(
            spec, param_id="p", param_type=ParamType.ENUM,
        )
        assert r.ok is False
        assert "non-empty" in r.error

    def test_unlaunchable_command_soft_fails(self) -> None:
        spec = ProviderSpec(command=["definitely-not-a-real-exe-xyz"])
        r = resolve_provider(
            spec, param_id="p", param_type=ParamType.ENUM,
        )
        assert r.ok is False
        assert "could not be launched" in r.error

    def test_nul_and_control_chars_scrubbed(self) -> None:
        # Provider emits a choice with a NUL (chr(0)) and a BEL
        # (chr(7)); both must be stripped before the value could
        # reach argv.  Built via chr() *inside the subprocess* so
        # this test file's own source stays clean ASCII (Python
        # source cannot contain a literal NUL byte).
        spec = ProviderSpec(command=_py(
            "import json;"
            "bad='ok'+chr(0)+'x';"
            "ctrl='cl'+chr(7)+'ean';"
            "print(json.dumps({'choices':[bad,ctrl]}))"
        ))
        r = resolve_provider(
            spec, param_id="p", param_type=ParamType.ENUM,
        )
        assert r.ok
        assert r.choices == ["okx", "clean"]

    def test_depends_on_forwarded_via_stdin(self) -> None:
        spec = ProviderSpec(command=_py(
            "import sys,json;"
            "d=json.load(sys.stdin);"
            "print(json.dumps({'choices':[d['depends_on']['src'],"
            "d['param_id']]}))"
        ))
        r = resolve_provider(
            spec, param_id="dst", param_type=ParamType.ENUM,
            upstream_values={"src": "ALPHA"},
        )
        assert r.ok
        assert r.choices == ["ALPHA", "dst"]


# ===========================================================================
# Dependency graph — topo order + cycle detection
# ===========================================================================

class TestDependencyGraph:

    def _p(self, pid: str, deps: list[str] | None = None) -> ParamDef:
        return ParamDef(
            id=pid, type=ParamType.ENUM, widget=Widget.DROPDOWN,
            choices_provider=ProviderSpec(command=["x"]),
            depends_on=deps or [],
        )

    def test_topo_order_upstream_first(self) -> None:
        a = self._p("a")
        b = self._p("b", ["a"])
        c = self._p("c", ["b"])
        order = provider_run_order([c, b, a])
        assert order.index("a") < order.index("b") < order.index("c")

    def test_cycle_raises(self) -> None:
        a = self._p("a", ["b"])
        b = self._p("b", ["a"])
        with pytest.raises(DependencyCycleError):
            provider_run_order([a, b])

    def test_unknown_dependency_raises(self) -> None:
        a = self._p("a", ["ghost"])
        with pytest.raises(ValueError, match="unknown param"):
            provider_run_order([a])

    def test_non_provider_params_ignored(self) -> None:
        plain = ParamDef(id="plain", type=ParamType.STRING,
                          widget=Widget.TEXT)
        a = self._p("a")
        order = provider_run_order([plain, a])
        assert order == ["a"]


# ===========================================================================
# io.py round-trip + loader invariants
# ===========================================================================

class TestIORoundTrip:

    def test_round_trip_preserves_all_fields(
        self, tmp_path: Path,
    ) -> None:
        t = ToolDef(name="X", executable="echo", params=[
            ParamDef(id="src", type=ParamType.ENUM,
                     widget=Widget.DROPDOWN,
                     choices_provider=ProviderSpec(
                         command=["p", "list"], refresh="on_open")),
            ParamDef(id="pg", type=ParamType.MULTISELECT,
                     widget=Widget.CHECKBOX_LIST,
                     choices_provider=ProviderSpec(
                         command=["p", "sheets"], refresh="on_change",
                         timeout_sec=20, cache="none"),
                     depends_on=["src"], select_all=True),
        ])
        p = tmp_path / "x.scriptree"
        save_tool(t, p)
        t2 = load_tool(p)
        pg = t2.params[1]
        assert pg.select_all is True
        assert pg.depends_on == ["src"]
        assert pg.choices_provider.refresh == "on_change"
        assert pg.choices_provider.timeout_sec == 20
        assert pg.choices_provider.cache == "none"

    def test_legacy_file_byte_compact(self, tmp_path: Path) -> None:
        """A v3 file with no provider fields must not gain
        choices_provider/depends_on/select_all keys on write."""
        from scriptree.core.io import _param_to_dict
        t = ToolDef(name="L", executable="echo", params=[
            ParamDef(id="q", type=ParamType.STRING,
                     widget=Widget.TEXT),
        ])
        d = _param_to_dict(t.params[0])
        assert "choices_provider" not in d
        assert "depends_on" not in d
        assert "select_all" not in d

    def test_loader_rejects_both_choices_and_provider(self) -> None:
        with pytest.raises(ValueError, match="cannot set both"):
            tool_from_dict({
                "schema_version": 3, "name": "B",
                "executable": "echo", "params": [{
                    "id": "a", "type": "enum", "widget": "dropdown",
                    "choices": ["x"],
                    "choices_provider": {"command": ["y"]},
                }],
            })

    def test_loader_rejects_depends_on_cycle(self) -> None:
        with pytest.raises(ValueError, match="cycle"):
            tool_from_dict({
                "schema_version": 3, "name": "B",
                "executable": "echo", "params": [
                    {"id": "a", "type": "enum", "widget": "dropdown",
                     "choices_provider": {"command": ["x"]},
                     "depends_on": ["b"]},
                    {"id": "b", "type": "enum", "widget": "dropdown",
                     "choices_provider": {"command": ["x"]},
                     "depends_on": ["a"]},
                ],
            })

    def test_loader_rejects_unknown_dependency(self) -> None:
        with pytest.raises(ValueError, match="unknown param"):
            tool_from_dict({
                "schema_version": 3, "name": "B",
                "executable": "echo", "params": [
                    {"id": "a", "type": "enum", "widget": "dropdown",
                     "choices_provider": {"command": ["x"]},
                     "depends_on": ["nope"]},
                ],
            })

    def test_loader_rejects_malformed_provider(self) -> None:
        with pytest.raises(
            ValueError, match="invalid 'choices_provider'",
        ):
            tool_from_dict({
                "schema_version": 3, "name": "B",
                "executable": "echo", "params": [
                    {"id": "a", "type": "enum", "widget": "dropdown",
                     "choices_provider": {"command": []}},
                ],
            })


# ===========================================================================
# Permission gate
# ===========================================================================

class TestPermissionGate:

    def test_dynamic_choices_capability_registered(self) -> None:
        from scriptree.core.permissions import CAPABILITIES
        assert "dynamic_choices" in CAPABILITIES

    def test_dynamic_choices_allowed_by_default(self) -> None:
        """The shipped permissions/running/dynamic_choices file is
        writable ⇒ the capability resolves allowed out of the box."""
        from scriptree.core.permissions import (
            load_permissions, reset_cached_permissions,
        )
        reset_cached_permissions()
        ps = load_permissions()
        assert ps.can("dynamic_choices") is True
        reset_cached_permissions()


# ===========================================================================
# Qt-backed orchestration (ToolRunnerView wiring)
# ===========================================================================

@pytest.fixture(scope="module")
def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _emit(code: str) -> ProviderSpec:
    return ProviderSpec(command=_py(code))


class TestRunnerOrchestration:

    def _view(self, tmp_path: Path, params, argv=None):
        from scriptree.core.io import save_tool
        from scriptree.ui.tool_runner import ToolRunnerView
        t = ToolDef(name="T", executable="echo", params=params,
                    argument_template=argv or [])
        p = tmp_path / "t.scriptree"
        save_tool(t, p)
        return ToolRunnerView(load_tool(p), file_path=str(p))

    def test_on_open_populates_choice_and_scalar(
        self, _qapp, tmp_path: Path,
    ) -> None:
        src = ParamDef(
            id="source", type=ParamType.ENUM, widget=Widget.DROPDOWN,
            choices_provider=_emit(
                "import json;print(json.dumps("
                "{'choices':['A','B'],'choice_labels':['Ay','Bee']}))"
            ),
        )
        scal = ParamDef(
            id="active", type=ParamType.PATH, widget=Widget.FILE,
            choices_provider=_emit(
                "import json;print(json.dumps({'value':'C:/x'}))"
            ),
        )
        v = self._view(tmp_path, [src, scal])
        assert v._widgets["source"].get_value() == "A"
        assert v._widgets["active"].get_value() == "C:/x"

    def test_on_change_cascade_via_debounce(
        self, _qapp, tmp_path: Path,
    ) -> None:
        src = ParamDef(
            id="source", type=ParamType.ENUM, widget=Widget.DROPDOWN,
            choices_provider=_emit(
                "import json;print(json.dumps({'choices':['A','B']}))"
            ),
        )
        pages = ParamDef(
            id="pages", type=ParamType.MULTISELECT,
            widget=Widget.CHECKBOX_LIST, depends_on=["source"],
            choices_provider=_emit(
                "import sys,json;d=json.load(sys.stdin);"
                "s=d['depends_on'].get('source','?');"
                "print(json.dumps({'choices':[s+':1',s+':2']}))"
            ),
        )
        # pages provider is on_open by default → set it on_change.
        pages.choices_provider.refresh = "on_change"
        v = self._view(tmp_path, [src, pages])
        pw = v._widgets["pages"]
        assert list(pw._boxes.keys()) == ["A:1", "A:2"]
        v._widgets["source"].set_value("B")
        v._widgets["source"].valueChanged.emit("B")
        # Fire the debounce timer synchronously.
        v._provider_debounce["pages"].timeout.emit()
        assert list(pw._boxes.keys()) == ["B:1", "B:2"]

    def test_refresh_all_button_present_and_works(
        self, _qapp, tmp_path: Path,
    ) -> None:
        src = ParamDef(
            id="source", type=ParamType.ENUM, widget=Widget.DROPDOWN,
            choices_provider=_emit(
                "import json;print(json.dumps({'choices':['A']}))"
            ),
        )
        v = self._view(tmp_path, [src])
        assert getattr(v, "_refresh_all_added", False) is True
        assert "source" in v._provider_refresh_btns
        v._refresh_all_providers()  # must not raise
        assert v._widgets["source"].get_value() == "A"

    def test_provider_failure_is_soft(
        self, _qapp, tmp_path: Path,
    ) -> None:
        bad = ParamDef(
            id="oops", type=ParamType.ENUM, widget=Widget.DROPDOWN,
            choices_provider=_emit("import sys;sys.exit(9)"),
        )
        ok = ParamDef(id="fine", type=ParamType.STRING,
                      widget=Widget.TEXT)
        v = self._view(tmp_path, [bad, ok])
        # Failed provider tracked; the rest of the form is usable.
        assert "oops" in v._provider_errors
        v._widgets["fine"].set_value("hello")
        assert v._widgets["fine"].get_value() == "hello"

    def test_form_session_cache_memoizes(
        self, _qapp, tmp_path: Path,
    ) -> None:
        # Provider writes a marker file each run; with form_session
        # cache + no upstream change, a second _run_provider must
        # NOT spawn again.
        marker = tmp_path / "runs.log"
        code = (
            f"open(r'{marker}','a').write('x');"
            "import json;print(json.dumps({'choices':['Z']}))"
        )
        p = ParamDef(
            id="c", type=ParamType.ENUM, widget=Widget.DROPDOWN,
            choices_provider=ProviderSpec(
                command=_py(code), cache="form_session"),
        )
        v = self._view(tmp_path, [p])
        runs_after_open = marker.read_text().count("x")
        assert runs_after_open == 1
        # Non-bypass re-run hits cache (no new spawn).
        v._run_provider(v._tool.params[0], bypass_cache=False)
        assert marker.read_text().count("x") == 1
        # Explicit Refresh bypasses cache (new spawn).
        v._refresh_provider("c", bypass_cache=True)
        assert marker.read_text().count("x") == 2

    def test_permission_denied_disables_provider_widgets(
        self, _qapp, tmp_path: Path, monkeypatch,
    ) -> None:
        import scriptree.ui.permission_guards as pg
        monkeypatch.setattr(
            pg, "perm_check",
            lambda cap, **kw: cap != "dynamic_choices",
        )
        src = ParamDef(
            id="source", type=ParamType.ENUM, widget=Widget.DROPDOWN,
            choices_provider=_emit(
                "import json;print(json.dumps({'choices':['A']}))"
            ),
        )
        v = self._view(tmp_path, [src])
        w = v._widgets["source"]
        assert w.isEnabled() is False
        assert "disabled by policy" in w.toolTip()


# ===========================================================================
# Editor dialog (ProviderEditorDialog)
# ===========================================================================

class TestProviderEditorDialog:

    def test_enable_fill_apply_sets_provider_and_clears_choices(
        self, _qapp,
    ) -> None:
        from scriptree.ui.provider_editor import (
            ProviderEditorDialog, apply_to_param,
        )
        p = ParamDef(
            id="pages", type=ParamType.MULTISELECT,
            widget=Widget.CHECKBOX_LIST, choices=["o1", "o2"],
        )
        dlg = ProviderEditorDialog(p, ["source", "dest"])
        dlg._enable.setChecked(True)
        dlg._command.setPlainText("prov.exe\nlist\n--json")
        dlg._refresh.setCurrentIndex(
            dlg._refresh.findData("on_change"))
        dlg._timeout.setValue(25)
        dlg._dep_boxes["source"].setChecked(True)
        dlg._select_all.setChecked(True)
        dlg._on_accept()
        apply_to_param(dlg, p)
        assert p.choices_provider.command == ["prov.exe", "list",
                                              "--json"]
        assert p.choices_provider.refresh == "on_change"
        assert p.choices_provider.timeout_sec == 25
        assert p.depends_on == ["source"]
        assert p.select_all is True
        # Mutually exclusive — static choices cleared.
        assert p.choices == [] and p.choice_labels == []

    def test_disable_clears_provider(self, _qapp) -> None:
        from scriptree.ui.provider_editor import (
            ProviderEditorDialog, apply_to_param,
        )
        p = ParamDef(
            id="x", type=ParamType.ENUM, widget=Widget.DROPDOWN,
            choices_provider=ProviderSpec(command=["p"]),
        )
        dlg = ProviderEditorDialog(p, [])
        assert dlg._enable.isChecked() is True  # seeded from existing
        dlg._enable.setChecked(False)
        dlg._on_accept()
        apply_to_param(dlg, p)
        assert p.choices_provider is None

    def test_select_all_gated_to_checkbox_list(self, _qapp) -> None:
        from scriptree.ui.provider_editor import ProviderEditorDialog
        p = ParamDef(id="x", type=ParamType.ENUM,
                     widget=Widget.DROPDOWN)
        dlg = ProviderEditorDialog(p, [])
        assert dlg._select_all.isEnabled() is False

    def test_invalid_command_keeps_dialog_open(self, _qapp) -> None:
        from scriptree.ui.provider_editor import ProviderEditorDialog
        p = ParamDef(id="y", type=ParamType.ENUM,
                     widget=Widget.DROPDOWN)
        dlg = ProviderEditorDialog(p, [])
        dlg._enable.setChecked(True)
        dlg._command.setPlainText("   ")
        dlg._on_accept()
        assert dlg._error.text()  # error surfaced
        assert dlg.result_provider is None  # not accepted
