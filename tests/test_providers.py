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
