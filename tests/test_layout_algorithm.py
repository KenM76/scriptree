"""Pin the layout algorithm via the pure-Python simulator.

The simulator at ``tools/layout_sim.py`` models the entire cell-layout
contract without Qt — slot allocation, drag/release, collapse, forest
move, etc.  Every scenario in that file becomes a pytest case here so
algorithm regressions surface in CI.

The Qt widget code that ports this algorithm (next major refactor)
should keep these scenarios green: the model and the implementation
must agree.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "tools"))

import layout_sim as L  # noqa: E402


@pytest.mark.parametrize(
    "scenario", L.SCENARIOS, ids=[s.__name__ for s in L.SCENARIOS],
)
def test_scenario(scenario, capsys) -> None:
    """Run a single scenario from the simulator.  Failure means the
    layout algorithm violated a stated rule."""
    scenario()
    # Scenario prints its trace; suppress the captured output unless
    # the test fails (pytest re-prints captured stdout on failure).
    capsys.readouterr()
