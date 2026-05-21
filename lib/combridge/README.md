# lib/combridge/ — bundled COM-bridge helper

## What lives here

The **combridge** runtime binaries: `combridge.exe`, `ComBridge.Core.dll`,
and the `plugins/` directory.  These are runtime artifacts from the
[KenM76/combridge](https://github.com/KenM76/combridge) repository,
NOT source — combridge has its own repo and its own release cycle.

`combridge.exe` is the replacement for the older `sw_bridge.exe`.  It
exposes a CLI that ScripTree `.scriptree` catalogs can call to drive
COM-aware applications (SolidWorks, Excel, …) through pluggable
adapters.  Bundling it here means the ScripTree portable zip is
self-contained — a noob can download one zip, unzip it, and every
catalog that references combridge runs without a separate install.

## Layout (target)

```
lib/combridge/
├─ combridge.exe                            ← entry point
├─ ComBridge.Core.dll                       ← engine
├─ combridge.deps.json                      ← .NET runtime manifest
├─ combridge.runtimeconfig.json
├─ <plus the .NET runtime DLLs combridge depends on>
└─ plugins/
   ├─ ComBridge.Plugins.Excel.dll
   ├─ ComBridge.Plugins.SolidWorks.dll      ← ships publicly per user direction
   └─ <other vendor adapter plugins>
```

## How to populate

### One-shot, from a local combridge build

```powershell
# From the ScripTree source root:
.\lib\install_combridge.ps1 -LocalSource D:\Dev\combridge\bin\Release\net10.0-windows
```

This copies the build output into `lib/combridge/`, replacing any
prior contents.  Use this on a developer machine where you've built
combridge yourself; it's instant and offline.

### Latest GitHub release (when combridge is published)

```powershell
.\lib\install_combridge.ps1
```

This hits the **KenM76/combridge** GitHub releases API, downloads the
latest release zip, extracts to `lib/combridge/`.  Network-dependent.

### Pinned version

```powershell
.\lib\install_combridge.ps1 -Version v0.1.0
```

## Catalog references

`.scriptree` files reference combridge as:

```jsonc
{
  "executable": "combridge.exe",
  "path_prepend": ["../../lib/combridge"]
}
```

or — preferred — let the ScripTree global PATH-prepend include
`lib/combridge` once so every catalog just says `combridge.exe`.

> The path is relative to the `.scriptree` file's own directory, NOT
> the CWD.  ScripTree's runner resolves it that way intentionally so
> the catalog folder can move.

## Gitignore

Everything in this directory except `.gitkeep` and `README.md` is
gitignored — these are build artifacts, not source.  See the project
`.gitignore` for the rule.
