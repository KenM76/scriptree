---
topic: pyside6
date: 2026-06-03
status: gotcha
related: [qmenu_outside_click_redispatches, popup_menu_root_catalog_path]
---
# Right-clicking a QAction needs an event filter on every QMenu, not customContextMenuRequested

## What happened

While adding per-tool right-click context menus to the popup tree
("right-click a tool to get Uninstall app, Open folder, etc."), the
obvious approach was

```python
menu.setContextMenuPolicy(Qt.CustomContextMenu)
menu.customContextMenuRequested.connect(...)
```

That signal **never fires for clicks on actions** — only for clicks
on the menu's empty area (margins, separators). For the per-action
case Qt simply does not give you a signal at all.

A second trap: even after switching to an event filter, putting the
filter only on the top-level menu catches nothing once a submenu
opens. Qt routes mouse events to the *innermost* menu under the
cursor — if the user right-clicks a leaf in a submenu, only the
submenu sees the event.

## Root cause

`QMenu` treats its actions as internal items, not as child widgets
that receive their own context-menu policy. The published Qt signal
surface for "right-click an action" is empty. The only way in is
the event stream: install a `QObject` event filter that watches
`QEvent.ContextMenu` (Windows synthesises this for right-clicks on
menus) AND `QEvent.MouseButtonPress` with `Qt.MouseButton.RightButton`
as a cross-platform fallback.

For submenu coverage, the filter has to be installed on every QMenu
in the tree — recursively, including any menus that are added later
via `aboutToShow`. A single top-level install is structurally wrong.

## Fix / recipe

Filter class in
`D:\Dev\ScripTree\scriptree\shell\tree_popup.py` (~line 1150-1300),
class `_PerItemContextFilter(QObject)`:

```python
class _PerItemContextFilter(QObject):
    def __init__(self, parent_menu, on_context):
        super().__init__(parent_menu)
        self._on_context = on_context  # callable(action, global_pos)

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.ContextMenu or (
            et == QEvent.MouseButtonPress
            and event.button() == Qt.MouseButton.RightButton
        ):
            menu = obj  # filter is installed per-menu
            act = menu.actionAt(event.pos())
            if act is not None and getattr(act, "_st_context", None):
                gpos = menu.mapToGlobal(event.pos())
                self._on_context(act, gpos)
                return True  # swallow — don't dismiss the parent menu
        return super().eventFilter(obj, event)
```

Recursive install in `_install_per_item_context`
(`D:\Dev\ScripTree\scriptree\shell\tree_popup.py:1305-1345`):

```python
def _install_per_item_context(menu, on_context):
    if getattr(menu, "_st_per_item_filter_installed", False):
        return  # idempotent — re-walks via aboutToShow are safe
    flt = _PerItemContextFilter(menu, on_context)
    flt.setParent(menu)           # dies with the popup, no QObject leak
    menu.installEventFilter(flt)
    menu._st_per_item_filter_installed = True

    for act in menu.actions():
        sub = act.menu()
        if sub is not None:
            _install_per_item_context(sub, on_context)
        # Lazily-populated submenus: re-walk on aboutToShow
        if sub is not None:
            sub.aboutToShow.connect(
                lambda m=sub: _install_per_item_context(m, on_context)
            )
```

Per-action context data: stashed as a plain Python attribute on
the QAction, NOT via `setData`:

```python
act = menu.addAction(label)
act._st_context = {
    "leaf_path": leaf_path,
    "root_catalog_path": root_catalog_path,
    "source_dir": source_dir,
    ...
}
```

`QAction.setData` only stores **one** QVariant — too thin for the
structured per-action context we need (path, catalog, source dir,
kind). A Python attribute on the QAction works because QAction is a
QObject subclass and Python keeps it alive as long as the action
lives.

## How future-me detects it

* Symptom: per-action right-click works on the top-level menu but
  not in submenus. Check the install function — it must recurse,
  and it must also hook `aboutToShow` for lazy submenus.
* Symptom: per-action right-click doesn't fire at all. You're
  probably trying `setContextMenuPolicy(Qt.CustomContextMenu)` —
  that signal does not exist for actions. Use the event filter.
* Symptom: filter fires twice. Check the idempotency sentinel
  `_st_per_item_filter_installed`; without it, every `aboutToShow`
  re-installs a fresh filter.
* Same pattern works for any "I need richer per-item interaction
  on a QMenu" feature (drag-to-reorder, middle-click open in new
  cell, etc.). Event-filter on the menu, look up the action via
  `actionAt(event.pos())`, stash structured data as Python attrs.
