"""category_completer.py — attach a canonical-category autocomplete to a
``QLineEdit`` in the editors (v0.8.0a112).

Both the single-tool editor (``tool_editor.py``) and the tree properties dialog
(``tree_view.py``) have a free-text "Category" field.  This helper drops a
``QCompleter`` over those fields, seeded from the canonical category catalog
(``scriptree.core.category_catalog``), so a person typing a category gets
suggestions from the blessed vocabulary instead of inventing a near-duplicate.

Design notes:
  * **Substring (MatchContains) matching** so typing ``word`` surfaces
    ``MSOffice/Word`` — the user rarely remembers the top-level prefix.
  * **Case-insensitive**, popup completion, no inline auto-replace (the user
    can still type any free-form category — the completer only *suggests*).
  * Degrades to a no-op when the catalog is empty (missing data file) so the
    editor never breaks; the field stays a plain free-text input.
  * Importing this module pulls in Qt, so it lives under ``scriptree/ui/`` and
    is only imported by the editors (never by the headless core/validate path).
"""

from __future__ import annotations

from typing import Any


def attach_category_completer(line_edit: Any) -> bool:
    """Attach a canonical-category ``QCompleter`` to ``line_edit``.

    Returns True if a completer was attached, False if there was nothing to
    suggest (empty catalog) or Qt/lookup failed.  Never raises — a failure here
    must never block opening an editor.
    """
    try:
        from scriptree.core.category_catalog import all_categories_for_completion
        cats = all_categories_for_completion()
        if not cats:
            return False
        from PySide6.QtWidgets import QCompleter
        from PySide6.QtCore import Qt

        completer = QCompleter(cats, line_edit)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        line_edit.setCompleter(completer)
        return True
    except Exception:  # noqa: BLE001 -- autocomplete is a nicety, never fatal
        return False
