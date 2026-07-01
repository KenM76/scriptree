# An uncategorised wrapper `.scriptreetree` floats to the forest top level (a94)

**Tag:** [authoring] [forest-discovery]
**Version:** observed under v0.8.0a94 (mechanism is a25+).
**Files (code):** `scriptree/shell/forest_discover.py` (priority-rule walker),
`scriptree/core/categorize.py` (`group_by_category`), `scriptree/shell/forest_controller.py`
(~2064-2090 — builds `GroupCandidate` from discovered items, reads the **tree's**
`category` at line 2080).
**Files (fixed):** `…/MSOffice/Outlook/outlook-migration/OutlookMigration.scriptreetree`
(R: deploy + `D:/Dev/ScripTreeApps/…`) — added `"category": "MSOffice/Outlook"`.

## Symptom

The user's forest "keeps putting the Outlook migration tools at the top level
instead of under the Office area where they belong." The *other* Outlook tools
(attachment-extractor, draft-generator, mailbox-auditor) folded into the
`MSOffice` cell correctly; only the migration **suite** sat at the top — and it
came back on every load even after removing the cell.

## Root cause (three interacting rules)

1. **Discovery priority rule (folder-vs-loose).** `forest_discover`'s walker, for
   each folder D: if D has a `*.scriptreering` → emit ring, STOP; **elif D has a
   `*.scriptreetree` → emit the tree(s), STOP**; else emit the loose `*.scriptree`.
   The `outlook-migration/` folder contains `OutlookMigration.scriptreetree`, so
   the folder is represented by **that one tree** — the 7 loose `.scriptree`
   inside are reached *through* the tree, never discovered/categorised
   individually. So only the **tree's** own `category` decides placement.
2. **Grouping needs a category.** `group_by_category` folds an item into the
   synthesised `MSOffice` cell only if it carries `category: "MSOffice/…"`. An
   item with an **empty** category is a *passthrough* → it becomes a stand-alone
   **top-level** cell.
3. **The wrapper tree had no `category`.** Each leaf `.scriptree` carried
   `"category": "MSOffice/Outlook"`, but `OutlookMigration.scriptreetree` itself
   did not (a deliberate-but-wrong choice — its README said "No category sits on
   the tree itself"). Since the leaves are invisible to grouping (rule 1), the
   uncategorised tree (rule 2) floated to the top. Auto-discovery re-runs every
   load, so it reappeared each time (rule 2 again).

## Fix

Add the category to the **tree**, not (only) the leaves:

```jsonc
{
  "schema_version": 3,
  "name": "Outlook Migration",
  "category": "MSOffice/Outlook",   // <-- this line; folds the suite under MSOffice/Outlook
  "nodes": [ … ]
}
```

`forest_controller` reads `getattr(tree, "category", "")` (line ~2080), so a
tree's category flows into `group_by_category` exactly like a tool's. After
re-organising, the suite appears as a sub-tree leaf under `MSOffice → Outlook`.

## Two gotchas when applying it

* **Re-organise (or restart) to apply** — `category` only changes how the *next*
  discovery/group pass places the folder. Forest menu → "Re-organise (re-run
  category grouping)".
* **An explicitly-pinned forest item wins over grouping.** If the tree was also
  saved as an explicit `items[]` entry in the `.scriptreeforest` (with a
  position), that pinned cell stays at the top regardless of category until it's
  removed and re-discovered. (The user's `my.scriptreeforest` had exactly this,
  plus a duplicate `MSOffice.scriptreetree` + `MSOffice__auto.scriptreetree` pair
  — the `__auto` suffix is the collision-avoidance name from `_pick_filename`.)

## Reusable takeaway

**A wrapper `.scriptreetree` that represents a whole folder MUST carry its own
`category`** — the loose-tool categories inside it are dead weight for placement
(the priority rule stops at the tree). Any folder you wrap in a `.scriptreetree`
to get a guided sub-menu will float to the forest top unless the tree itself is
categorised. (Authoring rule worth adding to `docs/LLM/category_authoring.md`:
"categorise the tree, not just its leaves, when the tree represents the folder.")
