# Tool organization & `category` authoring guide

**For:** anyone (human or LLM) authoring a `.scriptree` or
`.scriptreetree` file — *the* guide for deciding **where a tool lives**, how
to lay it out on disk, and the recommended JSON field order.

**Status:** `category` is mandatory metadata for grouped tools (v0.8.0a25+),
optional and safely omittable for everything else. The on-disk folder
convention and field order below are recommended conventions, not enforced.

---

## What the field does

`category` is a slash-delimited path that tells the ScripTree forest
where this tool belongs in a category hierarchy. When two or more
tools share a top-level category, the forest auto-creates ONE cell
that contains both (a synthesised `.scriptreetree`) instead of
showing N flat cells. Sub-segments become folder nodes inside that
synthesised tree.

> **Single-item categories (the `≥ 2` rule, v0.8.0a101).** A folder is
> synthesised only when a top-level category has **2 or more** members — a lone
> tool under a unique category (e.g. a single `Media/ffmpeg` tool) **passes
> through at the top level** rather than getting its own one-item folder. That
> is deliberate (avoids single-item-folder clutter for auto-discovered
> installs), so setting a category on the *only* tool with that top segment
> won't move it under a folder. To override per forest, turn on **Forest
> settings → "Fold single-item categories into their own folder"**
> (`auto_discover.fold_single_item_categories`, default off) and Re-organise —
> then every categorised tool gets its category folder even when it's alone.

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

> **Canonical category catalog (v0.8.0a112+).** There is now an extensive
> **controlled vocabulary** of ~800 recommended categories across ~185 domains
> (CAD, Office, Media, DevTools, Data, Security, …) in
> [`category_catalog.md`](category_catalog.md) (human/LLM-facing) with a
> machine-readable companion at `scriptree/resources/category_catalog.json`.
> **When choosing where an app goes, pick from that catalog first** so people
> and LLMs converge on the same spelling. The field is still free-form, but
> `python -m scriptree validate` now emits an advisory `[WARN]` when a category
> is a near-duplicate of a catalog entry (casing / plural / typo) or of another
> category in the same forest (e.g. `Demo` vs `Demos`), and the tree/tool
> editors autocomplete the Category field from the catalog.

The ScripTree codebase doesn't *enforce* a vocabulary; categories
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

## On-disk folder layout — mirror the `category`

The `category` metadata and the physical folder layout are two views of the
same hierarchy. Keep them in sync so the tree is predictable on disk **and**
in the forest.

**Convention:** lay each tool out so its folder path under `ScripTreeApps`
matches its category 1:1:

| `category` | on-disk folder |
|---|---|
| `MSOffice/Word` | `ScripTreeApps/MSOffice/Word/<tool>/<tool>.scriptree` |
| `SolidWorks/Export` | `ScripTreeApps/SolidWorks/Export/<tool>/<tool>.scriptree` |
| `Media/ffmpeg` | `ScripTreeApps/Media/ffmpeg/<tool>.scriptree` |

**Folder-vs-loose rule** (when does a tool get its own folder?):

- A domain with **≥ 2** tools → a folder named for the domain.
- A genuine **one-off** → leave it loose at its parent level.
- **Never** wrap a single tool in a folder whose name just repeats the tool
  and adds no grouping (the redundant-wrapper smell).

**Naming & ordering:**

- Folder display names: pick ONE casing convention (Title Case is the house
  style); don't reuse a raw `CamelCaseDirectoryName` verbatim as a label.
- Don't interleave loose leaves among folders — group folders together (or
  loose leaves together) and be consistent within a tree.

**Depth:** the category engine, the synthesiser, and the menu renderers all
recurse with **no cap**, so `A/B/C/D/…` works. Keep it to ~3–4 levels for
menus that stay usable.

---

## Recommended JSON field order

The writers (`tool_to_dict` / `tree_to_dict`) emit keys **stable-at-top →
most-edited-at-bottom**, so a person hand-editing the JSON can `Ctrl+End`
straight to the part they tweak most. Match it when authoring by hand. Order
is cosmetic (the loader is order-independent) — it exists purely for editing
comfort, and `category` sits near the top so "what is this / where does it
belong" is answered in the first lines.

**`.scriptree` (a tool):**

1. `schema_version`, `name`
2. **`category`**, `description` — identity & placement (top)
3. `executable`, `working_directory`, `env`, `path_prepend`, `platforms`,
   `interactive` — the command (rarely edited)
4. `cell` (icon / colours / label) — cosmetic, set once
5. `source` — machine, never hand-edited
6. `menus`, `actions` — extras
7. `sections`, `argument_template`, **`params`** — THE FORM, dead last

**`.scriptreetree` (a tree):**

1. `schema_version`, `name`
2. **`category`**, `folder_layout` — identity & placement (top)
3. `menus`, `path_prepend`, `cell` — chrome / cosmetic
4. `auto_discover`, `excluded` — discovery state (machine)
5. **`nodes`** — the tree (where you add/move/remove tools), dead last

> **Categorise the TREE, not just its leaves.** When a folder contains a
> `.scriptreetree`, the discovery walker represents that whole folder *by the
> tree* and stops — it never looks at the loose `.scriptree` leaves' own
> `category` fields for placement (they're reached *through* the tree). So a
> wrapper tree with **no** `category` is treated as uncategorised and floats out
> as a stand-alone **top-level** cell (and every auto-discovery pass re-adds it),
> even if every leaf inside it is categorised. If you wrap a folder in a
> `.scriptreetree` to give it a guided sub-menu, put the category on the **tree**
> (e.g. `"category": "MSOffice/Outlook"`) so the folder folds in where it belongs.

Per-item order **inside** `params[]` / `nodes[]` stays the natural reading
order (`id → label → type → widget → default → …` for a param) — that's about
reading one item, not jumping to it.

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
