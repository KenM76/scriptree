# Vocabulary — what Ken calls X = what the code calls Y

**Read this first.** ScripTree has many surfaces and several of
them look similar at a glance.  The user (Ken) has a specific
vocabulary for them; the code has different module names; and
historical comments use yet a third set of names.  Mixing these
up has cost real time -- I (the lead engineer) shipped at least
two regressions because I changed the wrong "editor" or "tree"
without checking which one Ken actually meant.

This doc is the cross-reference.  Whenever a user message says
"editor" or "tree" or "forest", look here BEFORE touching code.

---

## Top-level surfaces (the windows the user sees)

| User says | Code surface | What it actually is |
|---|---|---|
| **forest** | `scriptree.shell.cell_window.CellWindow` whose role is the forest hub | The HEX-shaped cell that sits on the desktop and contains/manages all other cells.  One per session.  Lives at the bottom of `ring_main.py`. |
| **forest cell** | same as above | Same thing as "forest" -- the master hex. |
| **cell** | `scriptree.shell.cell_window.CellWindow` (any role) | Any floating hexagon on the desktop.  Bound to one catalog (`.scriptree` / `.scriptreetree` / `.scriptreering`). |
| **ring** | a master `CellWindow` with `role="master"` and `_is_forest_master=False` | A non-forest master cell whose members are docked around it. |
| **developer editor** | `scriptree.ui.main_window.MainWindow` (V1's editor) | The QMainWindow with three docks: **Tools tree** (left), **Form + Output + Run controls** (centre / bottom).  Launched when the user double-right-clicks a cell. |
| **tool editor** | `scriptree.ui.tool_editor.ToolEditorView` | The field-editor widget that opens INSIDE the developer editor's centre stack when the user picks right-click → **Edit** on a tool in the tree.  Shows param rows, executable, sections, menus, etc.  Edits the on-disk `.scriptree`. |
| **standalone runner** | `scriptree.ui.standalone_window.StandaloneWindow` | A separate top-level window that opens when V1 is launched with `-standalone` OR when the user picks right-click → **Open standalone** in the developer editor's tree.  Hides developer chrome; shows the tool's form for end-user execution. |
| **the popup** / **tool menu** | `scriptree.shell.tree_popup.build_tree_popup_menu` (QMenu) | The single-left-click popup on a cell -- a `QMenu` tree of the cell's catalog.  Clicking a leaf launches the standalone runner via `v1_launcher.launch_tool`. |

---

## Panels INSIDE the developer editor

| User says | Code surface | What it is |
|---|---|---|
| **the tree** / **tools tree** | `scriptree.ui.tree_view.TreeLauncherView._tree_widget` (a `QTreeWidget`) | The left-pane tree of the catalog the editor has open.  Single-left-click on a leaf opens that tool's runner in the centre pane.  Right-click is the catalog right-click menu (Open / Edit / Save tree / Uninstall app... etc.). |
| **the form** | `scriptree.ui.tool_runner.ToolRunnerView.form_panel` | The widget showing param rows for the currently-opened tool.  Lives in the **Form dock** (centre of the developer editor). |
| **the output** | `runner.output_panel` | The stdout/stderr stream display.  Lives in the **Output dock** (bottom-left of the developer editor by default; detachable). |
| **the run controls** | `runner.bottom_panel` | The "extras" textarea (free-form argv tokens) PLUS the editable command-line preview.  Lives in the **Run controls dock** (bottom-centre by default; detachable). |
| **extras** | `runner._extras_edit` (QTextEdit inside bottom_panel) | The "Extra arguments" group inside the run controls dock.  Free-form tokens appended to argv at run time. |
| **command line** | `runner._cmd_preview` (editable QTextEdit inside bottom_panel) | The argv preview line.  Lives next to extras inside the run controls dock. |

---

## Catalog file types

| User says | Extension | What it is |
|---|---|---|
| **tool** / **tool definition** | `.scriptree` | One tool: executable + params + argv template + UI visibility.  Edited by `ToolEditorView`. |
| **tree** / **tool tree** | `.scriptreetree` | A nested folder/leaf structure referencing `.scriptree` files (and other `.scriptreetree` files as subtrees).  Edited by `TreeLauncherView`. |
| **ring** / **ring layout** | `.scriptreering` | A multi-cell layout (positions + catalog bindings).  Loaded by the cell shell, not the developer editor. |
| **forest** (the file) | `.scriptreeforest` | The forest's items list + excluded list + auto-discovery config.  Lives at `%APPDATA%/ScripTree/default.scriptreeforest`. |
| **merged tree** | a temp `.scriptreetree` in `%TEMP%` named `scriptreering_merged_<hash>.scriptreetree` | The synthetic catalog built by `merged_tree.build_merged_tree_for_master` when the user double-right-clicks the forest cell.  Aggregates all forest-member catalogs into one tree, opened in the developer editor.  Edits push back to the originating source files via `push_back_to_origins`. |

---

## Gestures (in user terms)

| User says | Code path | What happens |
|---|---|---|
| **single left-click on a cell** | `CellWindow` left-click handler | Toggles the cell's tool-menu popup (the tree popup of its catalog). |
| **double left-click on a cell** | `CellWindow.mouseDoubleClickEvent` | On a non-master cell: opens the standalone runner.  On a master / forest: opens the developer editor with the master's merged tree loaded. |
| **single right-click on a cell** | `CellWindow.contextMenuEvent` | Opens the cell's right-click context menu (Settings, Forest submenu, etc.). |
| **double right-click on a cell** | `CellWindow.mouseDoubleClickEvent` (right button) | Opens the developer editor for the cell's catalog (or merged tree for masters). |
| **single left-click on a tool in the tree** (developer editor) | `_EditableTreeWidget.itemClicked` -> `TreeLauncherView._on_item_activated` -> `MainWindow._on_tool_selected` -> `_show_runner` | Opens the tool's runner in the centre pane.  Should NOT pop new floating windows on every click -- the Form / Output / Run-controls docks already exist and the runner is swapped into them in place. |
| **double left-click on a tool in the tree** (developer editor) | same as above (Qt default for QTreeWidget) | Same as single click in the current design.  Distinct double-click semantics are reserved. |
| **single right-click on a tool in the tree** (developer editor) | `TreeLauncherView._on_header_context_menu` (header) or `_show_context_menu` (body) | Shows the context menu: Open / Edit / Open standalone / Remove / Rename / Uninstall app... / Save tree / Save tree as.  Does NOT launch the tool (a34 made `_EditableTreeWidget.mousePressEvent` swallow right-button before itemClicked fires). |
| **right-click on a tool in the cell popup** | `_PerItemContextFilter.eventFilter` -> `_show_for_action` | Shows a small floating context dialog: Open containing folder / Uninstall app from disk... |

---

## Common confusions to avoid

1. **"editor" alone is ambiguous.**  Ken uses "developer editor" for `MainWindow` and "tool editor" for `ToolEditorView`.  Never say or write "editor" without qualifying which.  If a user message is ambiguous, ask.
2. **"tree" alone is also ambiguous.**  Could be the tree-pane in the developer editor, a `.scriptreetree` catalog file, OR the merged tree.  Read context to disambiguate.
3. **"the popup"** usually means the tool-menu popup on a cell single-click -- NOT the right-click context menu on a tree item (which the user usually calls "right-click menu").
4. **"forest" usually means the forest CELL** (the hex on the desktop), not the `.scriptreeforest` file.  When the user says "the forest didn't save," they usually mean the running forest cell's state -- which IS in the `.scriptreeforest` file, but they're describing the runtime effect, not the file.
5. **"runner" vs "form".**  The runner is the WHOLE widget (form + output + run controls).  The form is just the param-rows panel inside the runner.  When the user says "the form pops up," they might mean the whole runner.

---

## When to consult this doc

Before:

* Reading user feedback that mentions any "X editor" / "Y tree" / "the popup".
* Modifying any of the surfaces above.
* Adding a new event handler or context-menu entry on a widget that has lookalike siblings.
* Writing a test that asserts behaviour on "the editor" or "the tree".

Update this doc:

* After any user feedback that introduces a NEW term.
* After any rename of a code-side class or attribute that appears here.
* As part of every doc audit pass (see `audit_2026-06-04.md` for the
  precedent).

Keep the **User says** column as the authoritative anchor.  Code
classes are renamed sometimes; user vocabulary is more stable.
