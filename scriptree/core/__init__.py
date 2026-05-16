"""Pure-Python core — no GUI imports. Portable across platforms.

## For humans

The ``scriptree.core`` package holds the headless business logic:
model, IO, runner, sanitization, permissions, configs, providers,
etc. It is designed to run without a display so unit tests and a
server / CI can exercise it without a QApplication.

## For maintainers / LLMs

* This package is the headless layer; importing it must NOT pull Qt
  into ``sys.modules`` via the CLI dispatch path. ``tests/
  test_core_purity.py`` enforces this.
* Exactly one module — ``app_settings`` — is grandfathered to carry
  a module-level ``from PySide6.QtCore import QSettings``. Every
  other module that needs Qt must import it lazily inside a function.
* ``providers.py`` must stay TOTALLY Qt-free (no lazy import either)
  because it runs on the headless dispatch path.
* Adding a new module-level Qt import anywhere here is a deliberate,
  reviewed act — it requires editing the allow-set in the purity
  test, not just the code.
"""
