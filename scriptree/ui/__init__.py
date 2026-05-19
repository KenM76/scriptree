"""PySide6 UI layer — swappable seam for cross-platform forks.

## For humans

Package marker for the PySide6 UI layer. Everything Qt-specific lives
under this package so a cross-platform fork has a single seam to swap.

## For maintainers / LLMs

- Marker package only — no code. Do not add import-time side effects
  here; modules under ``scriptree.ui`` import Qt and must stay off the
  headless ``validate`` / ``migrate`` CLI path in ``scriptree.main``.
- Treat this package boundary as the platform seam: keep all
  ``QFileDialog`` / native-dialog usage and Qt event overrides inside
  it, not in ``scriptree.core``.
"""
