---
topic: v3-process
date: 2026-06-04
status: workflow
related: [beta_style_report_per_session]
---
# Vocabulary discipline: ask which "editor"/"tree"/"popup" before editing code

## What happened

In v0.8.0a35 a user complaint about "the popup" / "the editor" was
mapped by the lead engineer to the wrong surface. The user's actual
complaint was about right-click behaviour in the developer-editor
tree — which had already been fixed in a34. The engineer guessed
"left-click in the tools tree" instead and changed
`_on_tool_selected`. The result was a regression that had to be
reverted in v0.8.0a38.

The user message had pointed at "the tree" without further
qualification, and ScripTree has multiple lookalike surfaces that
can plausibly be called "the tree."

## Root cause

ScripTree's UI has at least five surfaces a user might call by a
generic name:

| Generic term | Likely referent | Code symbol |
|---|---|---|
| "developer editor" / "the editor" | `MainWindow` (V1's QMainWindow with tools tree, form, output, run controls) | `scriptree/shell/main_window.py::MainWindow` |
| "tool editor" | `ToolEditorView` (field-by-field editor that opens via right-click → Edit) | `ToolEditorView` |
| "standalone runner" | `StandaloneWindow` (separate window launched via `-standalone`) | `StandaloneWindow` |
| "the popup" / "tool menu" | `build_tree_popup_menu` (single-left-click cell popup) | `scriptree/shell/tree_popup.py` |
| "the tree" | Could be developer-editor's `TreeLauncherView`, a `.scriptreetree` catalog file on disk, OR the merged tree (forest-in-editor) | several |

A bare reference like "fix the editor's tree popup" is genuinely
three-way ambiguous. Guessing rather than asking is a regression
factory.

## Fix / recipe

1. **Ask before editing** when the user's term is one of the
   ambiguous ones above and the referent is not 100% clear from
   the immediate context. Cost of asking: one round-trip. Cost of
   guessing wrong: a regression, a revert, and rebuilding trust.
2. **Maintain the glossary** at
   `D:\Dev\ScripTree\docs\LLM\glossary.md` (added in v0.8.0a39).
   When the user introduces a new term, add it to the glossary
   immediately with its code-symbol referent.
3. **Quote back the referent** in the response before changing
   code: "By 'editor' you mean MainWindow (the developer editor),
   right? — about to change `_on_tool_selected`."
4. **If you must guess**, guess the LEAST destructive interpretation
   first and confirm before committing.

## How future-me detects it

- Trigger phrases: "the editor," "the tree," "the popup," "the
  menu," "the runner," "this tree," "the tool editor." Any of
  these without an unambiguous code-path-level referent should
  pause for confirmation.
- Read the glossary at `docs/LLM/glossary.md` BEFORE acting on any
  surface-name-bearing user request.
- A revert in the immediately-prior session (like the a35→a38
  revert) is a strong signal the vocabulary was ambiguous — bias
  even harder toward asking.
