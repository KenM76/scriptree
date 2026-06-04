---
topic: pyside6
date: 2026-06-04
status: gotcha
related: [qmenu_per_action_right_click]
---
# QHeaderView right-click needs its own customContextMenuRequested wiring

## What happened

User report from the v0.8.0a36 era: "right-clicked at the top of
the tree with forest open there was no save option." Right-clicking
on the column-label row at the top of a QTreeWidget produced no
context menu, even though right-clicking on the tree body (any
item row) worked correctly.

## Root cause

`QTreeWidget.customContextMenuRequested` fires from the tree's
VIEWPORT — the body area where items are rendered. The
`QHeaderView` (the column-label row Qt installs at the top via
`QTreeView::header()`) is a SEPARATE widget with its own signal
plumbing. Wiring only the tree widget's `customContextMenuRequested`
silently misses the header.

There's no inheritance shortcut: `QHeaderView` is a `QWidget`
sibling of the viewport under the same `QAbstractItemView`, not a
child of it that forwards events upward.

## Fix / recipe

Wire the header's context-menu signal separately, sharing the same
builder helper as the body context menu but with `item=None` to
signal "no per-item context, this is a global tree action."

```python
view = self._tree_widget                       # QTreeWidget
header = view.header()                         # QHeaderView

# Body (already in place pre-a36)
view.setContextMenuPolicy(Qt.CustomContextMenu)
view.customContextMenuRequested.connect(self._on_body_context_menu)

# Header (added in a36)
header.setContextMenuPolicy(Qt.CustomContextMenu)
header.customContextMenuRequested.connect(self._on_header_context_menu)

def _on_header_context_menu(self, pos):
    menu = self._build_tree_context_menu(item=None)   # shared builder
    menu.exec(self._tree_widget.header().mapToGlobal(pos))
```

Note the `mapToGlobal` call: it goes through the header, not the
viewport, because that's where the click landed.

Pinned by
`D:\Dev\ScripTree\tests\test_editor_unhappy_paths_a36.py` (header
right-click case).

## How future-me detects it

- Symptom: right-click works on tree items but not on the column
  header row. Almost always missing
  `header().customContextMenuRequested.connect(...)`.
- Same rule applies to any subwidget Qt installs automatically
  (corner widget, scroll-area corner, etc.). Each one is a separate
  `QWidget` with its own context-menu policy.
- When designing a context menu meant to be "global to the tree,"
  expose a shared builder helper from the start so the header path
  can reuse it without duplication.
