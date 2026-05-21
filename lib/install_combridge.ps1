<#
.SYNOPSIS
  Populate <ScripTree>\lib\combridge\ with the combridge runtime binaries.

.DESCRIPTION
  combridge ("COM Bridge") is the replacement for sw_bridge — a
  pluggable CLI that drives COM-aware applications (SolidWorks, Excel,
  …) on behalf of ScripTree .scriptree catalogs.  It has its own
  GitHub repository and release cycle; ScripTree just bundles a copy
  of the released binaries so the portable zip is self-contained.

  This script has TWO modes:

    1. -LocalSource <dir>    Copy from a local combridge build output
                             directory.  Used on developer machines.
                             Fast, offline, exact-version control.

    2. (no -LocalSource)     Download the latest release zip from the
                             combridge GitHub repository.  Network-
                             dependent and historically flaky on some
                             corporate networks — if it fails, fall
                             back to mode 1.

  Either way the result is identical: lib/combridge/ contains
  combridge.exe, the engine DLL, the .NET runtime DLLs combridge
  depends on, and the plugins/ subdirectory.

.PARAMETER ScripTreeHome
  The ScripTree install root (the folder containing run_scriptree.bat).
  Defaults to the parent of this script's lib\ folder.

.PARAMETER LocalSource
  Path to a local combridge build output directory (e.g.
  D:\Dev\combridge\bin\Release\net10.0-windows).  When set, the
  contents of that directory are copied into lib/combridge/.

.PARAMETER GithubRepo
  GitHub "owner/name" of the combridge repository to fetch from when
  not using -LocalSource.  Defaults to KenM76/combridge.

.PARAMETER Version
  Specific release tag to download (e.g. "v0.1.0").  When unset, the
  latest published release is used.  Ignored when -LocalSource is set.

.PARAMETER AssetPattern
  Glob the release asset filename must match — first matching asset
  wins.  Defaults to "*combridge*.zip".  Override if the combridge
  release artefact uses a different naming pattern.

.EXAMPLES
  # From a local build
  .\lib\install_combridge.ps1 -LocalSource D:\Dev\combridge\bin\Release\net10.0-windows

  # Latest GitHub release
  .\lib\install_combridge.ps1

  # Pinned version
  .\lib\install_combridge.ps1 -Version v0.1.0

.NOTES
  Network-mode download has historically been unreliable in this
  environment.  When in doubt, build combridge locally and use
  -LocalSource — that path has never failed.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$ScripTreeHome,

    [string]$LocalSource,

    [string]$GithubRepo = 'KenM76/combridge',

    [string]$Version,

    [string]$AssetPattern = '*combridge*.zip'
)

$ErrorActionPreference = 'Stop'

# ── Resolve target directory ──────────────────────────────────────────
if (-not $ScripTreeHome) {
    $ScripTreeHome = Split-Path -Parent $PSScriptRoot
}
$ScripTreeHome  = (Resolve-Path $ScripTreeHome).ProviderPath
$LibDir         = Join-Path $ScripTreeHome 'lib'
$CombridgeDir   = Join-Path $LibDir 'combridge'

Write-Host "ScripTree install: $ScripTreeHome"
Write-Host "Target combridge dir: $CombridgeDir"

function Ensure-EmptyTarget {
    # Wipe target except .gitkeep / README.md so the directory keeps
    # its source-controlled markers across re-runs.
    if (Test-Path $CombridgeDir) {
        Get-ChildItem $CombridgeDir -Force | Where-Object {
            $_.Name -ne '.gitkeep' -and $_.Name -ne 'README.md'
        } | ForEach-Object {
            Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
    } else {
        New-Item -ItemType Directory -Path $CombridgeDir -Force | Out-Null
    }
}

function Verify-Install {
    $exe = Join-Path $CombridgeDir 'combridge.exe'
    if (-not (Test-Path $exe)) {
        throw "combridge.exe not found at $exe after install — the source build may be missing its entry point, or the release zip has an unexpected layout."
    }
    $size = (Get-Item $exe).Length
    Write-Host ("`nDone. combridge.exe in place ({0:N0} bytes)." -f $size)

    # Plugins are optional but expected — report what we found.
    $pluginDir = Join-Path $CombridgeDir 'plugins'
    if (Test-Path $pluginDir) {
        $plugins = Get-ChildItem $pluginDir -Filter '*.dll' -ErrorAction SilentlyContinue
        if ($plugins) {
            Write-Host "Plugins discovered:"
            foreach ($p in $plugins) {
                Write-Host "  - $($p.Name)"
            }
        } else {
            Write-Host "(plugins/ exists but is empty)"
        }
    } else {
        Write-Warning "No plugins/ directory found — combridge will still launch but won't have any vendor adapters."
    }
}

# ── Mode 1: local copy ───────────────────────────────────────────────
if ($LocalSource) {
    $LocalSource = (Resolve-Path $LocalSource -ErrorAction Stop).ProviderPath
    Write-Host "`nMode: local copy"
    Write-Host "Source: $LocalSource"

    if (-not (Test-Path (Join-Path $LocalSource 'combridge.exe'))) {
        throw "Local source $LocalSource does not contain combridge.exe.  Point -LocalSource at the directory that holds the built .exe (typically <combridge>\bin\Release\net10.0-windows)."
    }

    Ensure-EmptyTarget
    Write-Host "`nCopying $LocalSource -> $CombridgeDir ..."

    # Robocopy mirrors a directory faster than Copy-Item for trees
    # with hundreds of small DLLs.  /E recurses, /NFL/NDL/NJH/NJS keep
    # output quiet, /R:1 /W:1 = one retry max so a locked file fails
    # fast instead of hanging the build.  Robocopy uses non-standard
    # exit codes — anything < 8 is success.
    $robo = Start-Process -FilePath 'robocopy.exe' `
        -ArgumentList @($LocalSource, $CombridgeDir, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1') `
        -NoNewWindow -PassThru -Wait
    if ($robo.ExitCode -ge 8) {
        throw "robocopy failed with exit code $($robo.ExitCode) copying $LocalSource -> $CombridgeDir"
    }

    Verify-Install
    exit 0
}

# ── Mode 2: GitHub release download ─────────────────────────────────
Write-Host "`nMode: GitHub release download"
Write-Host "Repo:  $GithubRepo"

# Find the release URL.  Two paths:
#   - explicit -Version  → /repos/<owner>/<repo>/releases/tags/<tag>
#   - default            → /repos/<owner>/<repo>/releases/latest
if ($Version) {
    $apiUrl = "https://api.github.com/repos/$GithubRepo/releases/tags/$Version"
    Write-Host "Target version: $Version"
} else {
    $apiUrl = "https://api.github.com/repos/$GithubRepo/releases/latest"
    Write-Host "Target version: (latest)"
}

try {
    # GitHub API requires a User-Agent header.  Auth is unnecessary
    # for public release metadata but anonymous calls are rate-limited
    # to 60/hour per IP — fine for occasional builds.
    $release = Invoke-RestMethod -Uri $apiUrl -TimeoutSec 30 `
        -Headers @{ 'User-Agent' = 'ScripTree-install_combridge.ps1' }
} catch {
    Write-Error @"
Failed to query GitHub releases API.

  URL:    $apiUrl
  Error:  $($_.Exception.Message)

Causes:
  * Network blocked / offline.
  * Rate limit (60 anonymous calls/hour/IP).
  * Repository doesn't exist or isn't public yet.
  * The combridge release hasn't been published.

WORKAROUND: build combridge locally and use -LocalSource instead:

  .\lib\install_combridge.ps1 -LocalSource <path-to-combridge>\bin\Release\net10.0-windows
"@
    exit 1
}

if (-not $release.assets -or $release.assets.Count -eq 0) {
    Write-Error @"
Release '$($release.tag_name)' has no downloadable assets.  This
typically means the release was tagged but a zip artefact wasn't
attached.  Fall back to -LocalSource until the release is fully
published.
"@
    exit 1
}

# Pick the matching asset.  -like uses wildcards (* / ?) the same way
# the AssetPattern argument is documented.
$asset = $release.assets | Where-Object { $_.name -like $AssetPattern } |
    Select-Object -First 1
if (-not $asset) {
    $available = ($release.assets | ForEach-Object { "  - $($_.name)" }) -join "`n"
    Write-Error @"
No asset matching '$AssetPattern' on release '$($release.tag_name)'.

Available assets:
$available

Override the pattern with -AssetPattern, or use -LocalSource.
"@
    exit 1
}

$downloadUrl = $asset.browser_download_url
$zipFile     = Join-Path $env:TEMP $asset.name
Write-Host "`nDownloading $($asset.name) ($([math]::Round($asset.size / 1MB, 1)) MB)"
Write-Host "  from: $downloadUrl"
Write-Host "  to:   $zipFile"

try {
    Invoke-WebRequest -Uri $downloadUrl -OutFile $zipFile -UseBasicParsing -TimeoutSec 600
} catch {
    Write-Error @"
Download failed.

  URL:    $downloadUrl
  Error:  $($_.Exception.Message)

WORKAROUND: download manually, then re-run with -LocalSource pointing
at the extracted directory.
"@
    exit 1
}

Ensure-EmptyTarget

Write-Host "`nExtracting to $CombridgeDir"
try {
    Expand-Archive -Path $zipFile -DestinationPath $CombridgeDir -Force
} catch {
    Write-Error "Extract failed: $($_.Exception.Message)"
    exit 1
}

# Some release zips wrap their content in a top-level folder
# (e.g. combridge-v0.1.0/...).  Flatten that one level deep if we
# find no combridge.exe at the root but exactly one subdir that has it.
if (-not (Test-Path (Join-Path $CombridgeDir 'combridge.exe'))) {
    $subdirs = @(Get-ChildItem $CombridgeDir -Directory -Force |
        Where-Object { $_.Name -ne 'plugins' })
    if ($subdirs.Count -eq 1) {
        $inner = $subdirs[0].FullName
        if (Test-Path (Join-Path $inner 'combridge.exe')) {
            Write-Host "Release zip wrapped in '$($subdirs[0].Name)/' — flattening."
            Get-ChildItem $inner -Force | ForEach-Object {
                Move-Item $_.FullName $CombridgeDir -Force
            }
            Remove-Item $inner -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# Cleanup.
Remove-Item $zipFile -Force -ErrorAction SilentlyContinue

Verify-Install
