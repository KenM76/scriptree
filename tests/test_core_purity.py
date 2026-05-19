"""Architectural guarantee: the headless path imports no Qt.

The dynamic-providers feature memo assumed a ``tests/test_architecture.py``
already enforced "core/ imports no PySide6".  Reality, discovered
while building the feature:

  * There was no such test.
  * ``scriptree.core`` is **not** wholly Qt-free — ``app_settings``
    has a deliberate module-level ``from PySide6.QtCore import
    QSettings``; ``branding`` / ``cell_metadata`` import Qt **lazily**
    inside functions (guarded, only on a GUI code path).

So a blanket "no PySide6 anywhere in core" rule is *false* for this
codebase and enforcing it would mean refactoring unrelated, working,
intentional code — scope creep the feature doesn't need.

What actually matters (and what the memo was really protecting) is:

  1. ``core/providers.py`` — the new module that spawns subprocesses
     to populate forms — is **totally** Qt-free.
  2. The **headless dispatch path** (``scriptree validate`` /
     ``scriptree migrate`` and ``core.providers``) does not drag Qt
     in, so CI / a server can run them without a display.
  3. No *new* core module sneaks in a **module-level** Qt import.
     ``app_settings`` is the single grandfathered exception; the
     baseline must not grow.

This test enforces exactly those three — the guarantees that are
true and that matter — and nothing stricter.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import scriptree.core as core_pkg

_CORE_DIR = Path(core_pkg.__file__).resolve().parent

# The single grandfathered module allowed a *module-level* PySide6
# import.  Adding to this set should be a deliberate, reviewed act.
_MODULE_LEVEL_QT_ALLOWED = {"app_settings"}


def _core_py_files() -> list[Path]:
    return sorted(
        p for p in _CORE_DIR.rglob("*.py")
        if "__pycache__" not in p.parts
    )


def _module_level_qt_importers() -> set[str]:
    """Core modules with a **top-level** (module-scope) PySide6
    import.  Function-local / class-body lazy imports are fine —
    they don't load Qt until the GUI path actually calls them."""
    offenders: set[str] = set()
    for f in _core_py_files():
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in tree.body:  # module scope only — not ast.walk
            if isinstance(node, ast.Import):
                if any(a.name.split(".")[0] == "PySide6"
                       for a in node.names):
                    offenders.add(f.stem)
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").split(".")[0] == "PySide6":
                    offenders.add(f.stem)
    return offenders


def test_no_new_module_level_qt_import_in_core() -> None:
    """Regression guard: the set of core modules with a module-level
    Qt import must not grow beyond the grandfathered baseline."""
    actual = _module_level_qt_importers()
    new = actual - _MODULE_LEVEL_QT_ALLOWED
    assert not new, (
        "New module-level PySide6 import in scriptree.core: "
        f"{sorted(new)}.  Use a function-local import instead "
        "(see branding.py / cell_metadata.py), or — if truly "
        "unavoidable — add it to _MODULE_LEVEL_QT_ALLOWED with a "
        "reviewed justification."
    )


def test_providers_module_is_totally_qt_free() -> None:
    """The providers module must have NO PySide6 *import* at all —
    not even a lazy / function-local one.  It runs on the headless
    path.

    Implemented as an AST scan of every Import / ImportFrom node
    (module scope AND nested) rather than a raw substring check:
    the module's own docstring legitimately *documents* this
    Qt-free invariant and therefore contains the literal word
    "PySide6" in prose — a substring assert would false-positive on
    the documentation of the very rule it enforces.  We test the
    real invariant (no import statement), not the absence of the
    word.  ``test_headless_path_does_not_import_qt`` below is the
    behavioural backstop."""
    import scriptree.core.providers as prov
    tree = ast.parse(
        Path(prov.__file__).read_text(encoding="utf-8"),
        filename=prov.__file__,
    )
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders += [
                f"line {node.lineno}: import {a.name}"
                for a in node.names
                if a.name.split(".")[0] == "PySide6"
            ]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "PySide6":
                offenders.append(
                    f"line {node.lineno}: from {node.module} import ..."
                )
    assert not offenders, (
        "scriptree.core.providers must not import PySide6 "
        f"(any scope): {offenders}"
    )


def test_headless_path_does_not_import_qt() -> None:
    """Fresh-interpreter check: importing the CLI dispatch targets
    and the providers module must not pull PySide6 into
    ``sys.modules``.  Run in a subprocess so the result is
    independent of whatever an earlier test imported."""
    code = (
        "import sys;"
        "import scriptree.cli.migrate;"
        "import scriptree.cli.validate;"
        "import scriptree.core.providers;"
        "import scriptree.core.io;"
        "import scriptree.core.model;"
        "sys.exit(1 if 'PySide6' in sys.modules else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
        cwd=str(_CORE_DIR.parents[1]),
    )
    assert proc.returncode == 0, (
        "The headless path imported PySide6.\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
