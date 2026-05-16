"""Param widgets (one file per widget type).

## For humans

Package marker for the param-widget layer. The concrete widgets live
in sibling modules (currently consolidated in ``param_widgets``).

## For maintainers / LLMs

- Marker package only — no code, no import-time side effects.
- Every widget in this package must honour the uniform contract
  (``valueChanged`` signal, ``get_value()``, ``set_value()``) so
  ``param_widgets.build_widget_for`` can treat them interchangeably.
"""
