---
topic: v3-architecture
date: 2026-06-04
status: gotcha
related: [popup_menu_root_catalog_path, personal_sidecar_two_prong_match]
---
# auto-organise generates leaf paths with a doubled ScripTree/Apps/ segment

## What happened

User's forest referenced
``C:/Users/Ken/AppData/Local/ScripTree/Apps/_groups/MSOffice__auto.scriptreetree``
-- an auto-generated catalog the category auto-organise feature
writes when grouping installed apps by category.  The catalog's
Word leaves were stored as e.g.::

    "path": "../ScripTree/Apps/Word/batch-find-replace/batch-find-replace.scriptree"

The catalog's parent directory is::

    C:\Users\Ken\AppData\Local\ScripTree\Apps\_groups\

Path resolution at load time prepends the catalog's parent to the
relative ``path``, so the runtime tried to open::

    C:\Users\Ken\AppData\Local\ScripTree\Apps\_groups\..\ScripTree\Apps\Word\batch-find-replace\batch-find-replace.scriptree
    ↓ collapse the .. ↓
    C:\Users\Ken\AppData\Local\ScripTree\Apps\ScripTree\Apps\Word\batch-find-replace\batch-find-replace.scriptree

Note the doubled ``\ScripTree\Apps\`` -- ``..`` ascends to ``Apps\``,
then the path continues with ``ScripTree\Apps\Word\...`` so the
``ScripTree\Apps\`` segment appears twice.  The file doesn't exist
there; the actual tool is at ``...\Apps\Word\batch-find-replace\...``
(one fewer segment).

Symptom the user saw: every Word tool under MSOffice in the forest
was missing / broken; right-clicking them showed nothing usable.

## Root cause

The auto-organise generator (see task IDs 4 / 98-100 / 102-105 in
the project task log -- "category taxonomy + auto-organise" and
the auto-classify chain) appears to compute leaf paths relative
to the WRONG base directory.  It treats the personal-apps
ROOT (``C:\...\ScripTree\Apps\``) as the catalog's reference
point, but the catalog actually lives at
``C:\...\ScripTree\Apps\_groups\`` -- one level deeper.  The
generator's relative-path math forgets the extra hop, so it emits
``../ScripTree/Apps/Word/`` when it should emit ``../Word/``.

The same generator also references tools at paths that don't
exist on disk (e.g. ``style-sanitizer`` shown nested under Word,
but the actual installed tool is at ``Apps\style-sanitizer\``,
peer of ``Word\``).  This is a separate bug in the
category-classification step -- the auto-organiser puts tools
in the wrong category hierarchy based on its taxonomy guesses.

## Fix / recipe

### Immediate (one-off patch of a broken catalog)

```python
import json, shutil
from datetime import datetime
from pathlib import Path

p = Path("C:/Users/Ken/AppData/Local/ScripTree/Apps/_groups/MSOffice__auto.scriptreetree")
shutil.copy2(p, p.with_suffix(
    f".scriptreetree.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
))

data = json.loads(p.read_text(encoding="utf-8"))

def fix(node):
    if node.get("type") == "folder":
        kept = []
        for child in node.get("children", []):
            if child.get("type") == "leaf":
                old = child.get("path", "")
                # Drop leaves whose target doesn't exist on disk.
                if "style-sanitizer" in old:
                    continue
                # Strip the doubled segment.
                child["path"] = old.replace(
                    "../ScripTree/Apps/Word/", "../Word/",
                )
            kept.append(child)
            if child.get("type") == "folder":
                fix(child)
        node["children"] = kept

for top in data.get("nodes", []):
    fix(top)

p.write_text(json.dumps(data, indent=2), encoding="utf-8")
```

Verify by re-loading via ``scriptree.core.io.load_tree`` and
walking leaves to confirm every ``.path`` resolves to an
existing file.

### Permanent (the auto-organiser itself)

The generator that produces ``<group>__auto.scriptreetree`` files
must compute the relative path from the CATALOG FILE's parent
directory, not from the personal-apps root.  When the catalog
lives one level deeper (e.g. in ``_groups/``), the relative path
needs one more ``..`` -- OR (simpler) the generator should write
ABSOLUTE leaf paths and let the load-time resolver handle the
rest.  The hand-authored ``MSOffice.scriptreetree`` next to the
broken auto file uses absolute paths and works fine; the
auto-generator should follow the same convention.

A separate fix is needed for the misclassification ("Apps that
aren't Word tools get put under the Word folder").  The
classification step needs to actually inspect the tool's
metadata (category field?  file location?  parser detection?)
rather than guessing from the parent folder name.

## How future-me detects it

* User reports tools missing from a category-grouped tree in the
  forest, especially under a ``_groups\<Category>__auto.scriptreetree``
  catalog.
* ``load_tree(<auto-catalog>)`` succeeds but a leaf-existence walk
  reports every Word/etc. leaf as missing.
* The reported missing paths contain a doubled segment like
  ``...\Apps\ScripTree\Apps\Word\...``.
* The user's hand-authored sibling catalog (without ``__auto``
  suffix) works correctly -- distinguishing user error from
  generator bug.

## Diagnostic command

```python
from scriptree.core.io import load_tree
from pathlib import Path

cat = "C:/Users/Ken/AppData/Local/ScripTree/Apps/_groups/<X>__auto.scriptreetree"
tree = load_tree(cat)

def walk(node, base, missing):
    if node.type == "leaf" and node.path:
        p = Path(node.path)
        if not p.is_absolute():
            p = (base / p).resolve()
        if not p.is_file():
            missing.append(str(p))
    elif node.type == "folder":
        for c in node.children:
            walk(c, base, missing)

missing = []
for n in tree.nodes:
    walk(n, Path(cat).parent, missing)
print(f"missing leaves: {len(missing)}")
for m in missing[:5]:
    print(f"  {m}")
# Look for doubled segments in the paths to confirm the bug.
```
