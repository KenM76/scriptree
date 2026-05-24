---
topic: v3-process
date: 2026-05-23
status: recipe
related: [make_portable_non_interactive]
---
# Bundling `combridge` into a portable ScripTree release

## What happened

combridge (separate repo `KenM76/combridge` at `D:/Dev/combridge`)
ships as a CLI exe plus a `plugins/` subtree of MEF-loaded DLLs. The
v0.8.0a1 release was the first to bundle it into the portable
ScripTree zip. The plugin layout has a verification trap that prints
a misleading "(plugins/ exists but is empty)" warning even on a
successful install.

## How combridge builds

```powershell
cd D:\Dev\combridge
dotnet build -c Release
```

Outputs:

| Path | What |
|---|---|
| `src/ComBridge.Cli/bin/Release/net10.0-windows/combridge.exe` (+ dlls) | CLI host |
| `<repo-root>/plugins/<PluginName>/*.dll` | One subdir per plugin |

The plugin subdirs are populated by a per-plugin csproj target:

```xml
<Target Name="CopyToPluginsRoot" AfterTargets="Build">
  <ItemGroup>
    <PluginOut Include="$(OutputPath)*" />
  </ItemGroup>
  <Copy SourceFiles="@(PluginOut)"
        DestinationFolder="$(SolutionDir)..\plugins\$(MSBuildProjectName)\" />
</Target>
```

So a clean `dotnet build -c Release` at the repo root yields a
staging layout ready to robocopy.

## Bundling into ScripTree

The bundle script `lib/install_combridge.ps1` in the ScripTree repo
takes a `-LocalSource` directory laid out **side-by-side** the way
the final install expects: CLI files at root, `plugins/<Name>/`
subdirs alongside. Stage the layout in a temp dir before installing:

```powershell
$staging = "$env:TEMP\combridge-staging"
robocopy "D:\Dev\combridge\src\ComBridge.Cli\bin\Release\net10.0-windows" $staging /E
robocopy "D:\Dev\combridge\plugins" "$staging\plugins" /E

# Then:
& "$ScripTreeRepo\lib\install_combridge.ps1" `
    -ScripTreeHome $DestDir `
    -LocalSource $staging
```

`make_portable.py --bundle-combridge` chains the build + staging +
install for you. Prefer that for releases.

## The false-negative warning

`install_combridge.ps1`'s `Verify-Install` step does:

```powershell
$pluginDlls = Get-ChildItem $pluginDir -Filter '*.dll'   # flat
if (-not $pluginDlls) { Write-Warning "(plugins/ exists but is empty)" }
```

That's a FLAT `Get-ChildItem`, not `-Recurse`. Real plugins live one
level deeper (`plugins/<Name>/*.dll`) so the flat scan finds nothing
and warns even on a correct install. The install actually succeeds —
ignore the warning, or fix the script to use `-Recurse -Include '*.dll'`.

## Files / symbols

* `D:/Dev/combridge/` — repo root (separate from ScripTree)
* `D:/Dev/ScripTree/lib/install_combridge.ps1` — copy-into-place
  helper, robocopy-based mirror with /E (recursive)
* `D:/Dev/ScripTree/make_portable.py` — `--bundle-combridge` flag
  invokes the helper after staging
* Final layout in the portable zip:
  `<root>/combridge.exe` + `<root>/plugins/<Name>/*.dll`

## How future-me detects it

* "combridge.exe runs but no plugins load" — check the actual
  destination tree (`Get-ChildItem -Recurse $dest/plugins`), not the
  install script's warning.
* "Install warns about empty plugins/ but the zip works" — known
  false negative; see Verify-Install above.
* If a fresh `dotnet build` doesn't populate `plugins/<Name>/`, the
  `CopyToPluginsRoot` target was probably edited or the plugin csproj
  changed — re-check each plugin csproj for the AfterTargets="Build"
  hook.
