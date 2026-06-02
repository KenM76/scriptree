"""Tests for the ``scriptree validate`` lint pass (v0.8.0a25+).

Pins the three contract points from
``FEATURE_REQUEST_validate_unsectioned_form_lint.md``:

  * A flat >4-param form prints a ``[WARN]`` but still validates.
  * A 3-param flat form prints no warning.
  * A properly sectioned form prints no warning.
  * Exit code is 0 by default even when warnings are present.
  * ``--strict`` promotes warnings to a non-zero exit.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scriptree.cli.validate import (
    LINT_SECTION_THRESHOLD,
    LINT_TAB_THRESHOLD,
    _lint_tool,
    main as validate_main,
)
from scriptree.core.io import save_tool
from scriptree.core.model import (
    ParamDef, ParamType, Section, ToolDef, Widget,
)


def _param(idx: int) -> ParamDef:
    return ParamDef(
        id=f"p{idx}",
        label=f"P{idx}",
        type=ParamType.STRING,
        widget=Widget.TEXT,
    )


def _tool(n_params: int, *, sections: list[Section] | None = None) -> ToolDef:
    return ToolDef(
        name="t",
        executable="echo",
        argument_template=[],
        params=[_param(i) for i in range(n_params)],
        sections=sections or [],
    )


# ---------------------------------------------------------------------------
# _lint_tool direct unit tests
# ---------------------------------------------------------------------------


class TestLintTool:
    def test_small_flat_form_no_warning(self) -> None:
        # 3 params, no sections -- under the threshold.
        assert _lint_tool(_tool(3)) == []

    def test_exactly_at_threshold_no_warning(self) -> None:
        # The trigger is STRICTLY > threshold.
        assert _lint_tool(_tool(LINT_SECTION_THRESHOLD)) == []

    def test_over_threshold_no_sections_warns(self) -> None:
        warns = _lint_tool(_tool(LINT_SECTION_THRESHOLD + 1))
        assert len(warns) == 1
        assert "no sections" in warns[0]
        # Not yet at the tab threshold -- shouldn't recommend tab mode.
        assert "tab" not in warns[0].lower()

    def test_over_tab_threshold_no_sections_warns_tab(self) -> None:
        warns = _lint_tool(_tool(LINT_TAB_THRESHOLD))
        assert len(warns) == 1
        # Should specifically mention tab mode.
        assert "tab" in warns[0].lower()

    def test_sectioned_form_no_warning(self) -> None:
        secs = [Section(name="A"), Section(name="B"), Section(name="C")]
        assert _lint_tool(_tool(8, sections=secs)) == []

    def test_collapse_only_at_tab_threshold_warns(self) -> None:
        # Sectioned but only collapse-mode at 10+ params -> nudge.
        secs = [
            Section(name="A", layout="collapse"),
            Section(name="B", layout="collapse"),
        ]
        warns = _lint_tool(_tool(LINT_TAB_THRESHOLD, sections=secs))
        assert len(warns) == 1
        assert "tab" in warns[0].lower()

    def test_tab_mode_at_tab_threshold_no_warning(self) -> None:
        secs = [
            Section(name="A", layout="tab"),
            Section(name="B", layout="tab"),
        ]
        assert _lint_tool(_tool(LINT_TAB_THRESHOLD, sections=secs)) == []


# ---------------------------------------------------------------------------
# End-to-end via the CLI's ``main()``.  Capture stdout and check
# exit codes against the feature request's acceptance criteria.
# ---------------------------------------------------------------------------


class TestCliMain:
    def test_flat_13_param_warns_exit_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        p = tmp_path / "big.scriptree"
        save_tool(_tool(13), p)
        rc = validate_main([str(p)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "[WARN]" in out
        assert "13 params" in out
        assert "tab" in out.lower()

    def test_flat_3_param_no_warn(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        p = tmp_path / "small.scriptree"
        save_tool(_tool(3), p)
        rc = validate_main([str(p)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "[WARN]" not in out

    def test_sectioned_no_warn(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        secs = [Section(name="A"), Section(name="B")]
        p = tmp_path / "sectioned.scriptree"
        save_tool(_tool(7, sections=secs), p)
        rc = validate_main([str(p)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "[WARN]" not in out

    def test_strict_promotes_to_nonzero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        p = tmp_path / "big.scriptree"
        save_tool(_tool(13), p)
        rc = validate_main([str(p), "--strict"])
        out = capsys.readouterr().out
        assert rc == 1
        assert "[WARN]" in out
        assert "--strict" in out

    def test_legacy_2tuple_validate_one_still_works(
        self, tmp_path: Path,
    ) -> None:
        """Belt-and-suspenders: the public API ``validate_one`` MUST
        still return a 2-tuple ``(ok, msg)``.  Existing tests
        (test_canonical_names_v3.py) unpack it that way."""
        from scriptree.cli.validate import validate_one
        p = tmp_path / "legacy.scriptree"
        save_tool(_tool(3), p)
        result = validate_one(p)
        assert len(result) == 2
        ok, msg = result
        assert ok is True
        assert "Valid" in msg
