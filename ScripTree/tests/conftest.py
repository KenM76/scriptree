"""Shared pytest fixtures for the ScripTree test suite.

Most of this is about isolating tests from the real user_configs and
permissions directories so accidental leftover files don't make later
tests flaky.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_user_configs_dir(tmp_path_factory, monkeypatch):
    """Redirect personal configs to a per-session temp dir.

    Prevents test runs from polluting the real ``ScripTree/user_configs/``
    and keeps tests deterministic.
    """
    user_dir = tmp_path_factory.mktemp("user_configs")
    monkeypatch.setenv("SCRIPTREE_USER_CONFIGS_DIR", str(user_dir))
    yield user_dir
