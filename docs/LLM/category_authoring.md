# `category` authoring guide

**For:** anyone (human or LLM) authoring a `.scriptree` or
`.scriptreetree` file.

**Status:** mandatory metadata for grouped tools (v0.8.0a25+);
optional and safely omittable for everything else.

---

## What the field does

`category` is a slash-delimited path that tells the ScripTree forest
where this tool belongs in a category hierarchy. When two or more
tools share a top-level category, the forest auto-creates ONE cell
that contains both (a synthesised `.scriptreetree`) instead of
showing N flat cells. Sub-segments become folder nodes inside that
synthesised tree.

The field lives at the top level of the `.scriptree` JSON next to
`name`, `executable`, etc.:

```json
{
  "name": "Style Sanitizer",
  "executable": "...",
  "category": "MSOffice/Word",
  "argument_template": [],
  "params": []
}
```

`.scriptreetree` files use the same field at their top level if
you want the tree to fold under a higher-level synthesised tree
alongside flat tools.

---

## Authoring rules (the loader enforces these)

| Rule | Example OK | Example NOT OK |
|---|---|---|
| Forward slashes only — not OS separators | `"MSOffice/Word"` | `"MSOffice\\Word"` |
| No leading or trailing slash | `"MSOffice/Word"` | `"/MSOffice/Word/"` |
| No empty segments | `"MSOffice/Word"` | `"MSOffice//Word"` |
| Omit when empty / uncategorised | (omit the field) | `"category": ""` (cosmetic, no harm) |
| Case-preserving | `"MSOffice/Word"` displays as `MSOffice/Word` | — |
| Case-insensitive at the bucket level | `"MSOffice"` and `"msoffice"` collide into one tree | — |

The loader **sanitises malformed inputs** at load time (strips
leading/trailing slashes, drops empty segments, treats non-string
values as empty). You won't get an error popup — you'll get the
cleaned value, which is sometimes empty.

---

## Picking a category — recommended conventions

The ScripTree codebase doesn't enforce a vocabulary; categories
are user-chosen. Here are the suggested patterns Ken uses in the
shipped catalog (v0.8.0a25 onward):

| Pattern | Meaning | Worked example |
|---|---|---|
| `<Vendor>/<App>` | Tool drives a specific commercial app | `MSOffice/Word`, `MSOffice/Excel`, `Adobe/Photoshop`, `SolidWorks/Drawings` |
| `<Domain>` | Top-level grouping for a workflow domain | `DevTools`, `Networking`, `MediaConvert` |
| `<Domain>/<Sub>` | Sub-grouping within a domain | `DevTools/Git`, `DevTools/Build`, `MediaConvert/Audio` |
| `<Project>` | Project-private grouping | `MyProject`, `ClientFoo` |
| (omitted) | Uncategorised — flat cell on the forest | — |

Two practical guidelines:

1. **Top segment = the thing that's likely to grow.** If you
   foresee 5 SolidWorks tools, choose `SolidWorks/<area>` so the
   forest folds them into one cell. If a tool truly stands alone,
   leave the category off.
2. **Don't over-nest.** Three or four levels deep is the limit
   before the menu becomes unwieldy. The forest doesn't enforce a
   depth cap, but cell-popup menus with 4+ nested submenus get
   awkward.

---

## What auto-grouping looks like at runtime

Suppose the user has these installed:

```
ScripTreeApps/StyleSanitizer.scriptree     category=MSOffice/Word
ScripTreeApps/WordCounter.scriptree        category=MSOffice/Word
ScripTreeApps/CellAggregator.scriptree     category=MSOffice/Excel
ScripTreeApps/GitStatus.scriptree          category=DevTools
ScripTreeApps/RandomTool.scriptree         (no category)
```

The forest's auto-organise pass runs at discovery time and produces:

```
<personal-apps>/_groups/MSOffice.scriptreetree
  ├─ folder "Excel"
  │   └─ leaf CellAggregator -> ScripTreeApps/CellAggregator.scriptree
  └─ folder "Word"
      ├─ leaf StyleSanitizer -> ScripTreeApps/StyleSanitizer.scriptree
      └─ leaf WordCounter    -> ScripTreeApps/WordCounter.scriptree
```

The forest then shows **three cells**:

| Cell | Backed by | Why |
|---|---|---|
| `MSOffice` (tree cell) | the synthesised `.scriptreetree` | 3 items shared the `MSOffice/*` prefix |
| `GitStatus` | `GitStatus.scriptree` | only one tool in `DevTools` → passthrough |
| `RandomTool` | `RandomTool.scriptree` | uncategorised → passthrough |

Single-click the `MSOffice` cell → menu pops with sub-folders
`Excel` and `Word`, each with the corresponding tools.

---

## The 2-or-more rule

A top-level category synthesises a tree only when its full subtree
contains **≥ 2 items**. A solo `DevTools/Git` tool passes through
as a flat cell, not a `DevTools.scriptreetree` containing one
leaf. Reasoning: a "tree of one" reads as clutter — extra click,
no organisation benefit.

The threshold is currently fixed at 2; a future setting may expose
it. Don't author for a different value.

---

## What the user sees on next launch

* No category change → no forest change.
* New category that's a singleton → tool appears as a flat cell at
  the next refresh.
* New category that pairs up with an existing tool → both tools
  fold into a synthesised tree cell; the old flat cells disappear.
* Removed category from a tool → tool peels back out to a flat
  cell on the next refresh.

The synthesised trees live at
`<default_personal_root()>/_groups/<TopSegment>.scriptreetree`.
They carry a `synthesised_by` marker; the forest knows to
overwrite them every pass and to prune ones whose categories
disappeared. Don't hand-edit them — they'll be rewritten.

---

## Authoring against the loader

When you author a `.scriptree`, the validator
(`python -m scriptree validate <path>`) flags malformed values:

| Authored value | Validator says | Stored as |
|---|---|---|
| `"category": "MSOffice/Word"` | OK | `"MSOffice/Word"` |
| `"category": "/MSOffice/Word/"` | OK (silently sanitised) | `"MSOffice/Word"` |
| `"category": "MSOffice//Word"` | OK (silently truncated) | `"MSOffice"` |
| `"category": ["MSOffice", "Word"]` | OK (silently treated as empty) | `""` |
| `"category": ""` | OK (no-op) | `""` (field omitted on save) |
| (omitted entirely) | OK | `""` (field omitted on save) |

The silent sanitisation is by design — a malformed category should
not block the user from running their tool. The cleaner behaviour
is "show the tool anyway, just don't group it."

---

## Examples from the shipped catalog

```json
// MSOffice apps
{ "category": "MSOffice/Word" }
{ "category": "MSOffice/Excel" }
{ "category": "MSOffice/PowerPoint" }
{ "category": "MSOffice/Outlook" }

// SolidWorks (private, never published)
{ "category": "SolidWorks/Drawings" }
{ "category": "SolidWorks/Parts" }
{ "category": "SolidWorks/Macros" }

// ScripTree management
{ "category": "ScripTree" }   // top-level grouping
```
