---
topic: portable_zip_bundles_solidworks_interop_strip_before_public
date: 2026-06-21
status: gotcha
related: [combridge_bundle_workflow]
---
# make_portable.py bundles combridge's SolidWorks plugin + SolidWorks SDK interop DLLs — strip the interop DLLs before a PUBLIC release

## What happened (v0.8.0a75 release)

The git-tracked source has NO SolidWorks tools (only generic `icons/icon-
solidworks.*` glyphs).  But `make_portable.py` copies `lib/combridge/` whole,
and the bundled combridge ships a SolidWorks plugin folder
`lib/combridge/plugins/SolidWorks/` containing:

- `ComBridge.Plugins.SolidWorks.dll` (~23 KB) — combridge's OWN plugin
  (KenM76/combridge, MIT).  Yours; fine to ship.
- `SolidWorks.Interop.sldworks.dll` (~2.8 MB)
- `SolidWorks.Interop.swcommands.dll` (~191 KB)
- `SolidWorks.Interop.swconst.dll` (~478 KB)

The three `SolidWorks.Interop.*.dll` are **SolidWorks's own SDK interop
assemblies**, not the user's code — redistributing them in a PUBLIC release is a
licensing concern (and trips the never-publish-SolidWorks rule's spirit).  They
are NOT git-tracked, so a `git ls-files | grep solidworks` check (which only
finds the icons) MISSES them — they only appear in the built portable zip.

## Fix / recipe

Before uploading a public release zip, scan it for SolidWorks-owned assemblies
and strip them (keep combridge's own plugin):

```python
import zipfile, os
src='ScripTree-vX.zip'; tmp=src+'.tmp'
MARK='/plugins/SolidWorks/SolidWorks.Interop.'   # SolidWorks SDK interop only
with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as zout:
    for it in zin.infolist():
        if MARK in it.filename and it.filename.lower().endswith('.dll'):
            continue                              # drop SolidWorks's interop
        zout.writestr(it, zin.read(it.filename))
os.replace(tmp, src)
```

Verify afterward: no `SolidWorks.Interop.*` entries remain; `ComBridge.Plugins.
SolidWorks.dll` still present.  Also confirm there are NO `.csx` entries anywhere
(SolidWorks automation scripts are never-publish) and the plugin's `commands/`
subfolder is empty.

Note: the zip also bundles Microsoft Office interop DLLs
(`Microsoft.Office.Interop.{Excel,Word,PowerPoint,Outlook}.dll`).  Those are
Microsoft Primary Interop Assemblies, which Microsoft permits redistributing —
left in.  SolidWorks's are not redistributable; strip them.

## How future-me detects it

A clean `git ls-files` SolidWorks check is NECESSARY BUT NOT SUFFICIENT for a
public release — combridge (and any other bundled-at-build dependency) can carry
third-party proprietary DLLs that aren't in git.  ALWAYS scan the BUILT release
zip, not just the source tree, before `gh release create`.  Combridge SolidWorks
plugin = keep (yours); `SolidWorks.Interop.*` = strip (SolidWorks's SDK).
