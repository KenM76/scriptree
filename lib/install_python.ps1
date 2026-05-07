<#
.SYNOPSIS
  Install a portable Python into <ScripTree>\lib\python\.

.DESCRIPTION
  Downloads the python.org "embeddable" zip for the host architecture
  (amd64 / arm64), extracts it into the launcher's lib\python\ folder,
  enables the `site` module so pip works, downloads `get-pip.py`, and
  installs pip. The result is a fully self-contained Python that
  ScripTree can launch without the user installing anything system-
  wide.

  After this script finishes, run_scriptree.bat will pick up
  lib\python\pythonw.exe automatically.

.PARAMETER ScripTreeHome
  The ScripTree install root (the folder containing run_scriptree.bat).
  Defaults to the parent of this script's lib\ folder.

.PARAMETER PythonVersion
  Override the auto-detected latest version. Useful for testing or
  pinning. Default: query python.org for the latest stable release;
  fall back to a hard-coded known-good version if the API is
  unreachable.

.NOTES
  Requires PowerShell 5.1+ (shipped with Windows 10+).
  Requires an internet connection at install time. The resulting
  Python install is fully offline-usable.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$ScripTreeHome,

    [string]$PythonVersion
)

$ErrorActionPreference = 'Stop'

# Resolve ScripTreeHome from the script's own location if not provided.
if (-not $ScripTreeHome) {
    $ScripTreeHome = Split-Path -Parent $PSScriptRoot
}
$ScripTreeHome = (Resolve-Path $ScripTreeHome).ProviderPath
$LibDir        = Join-Path $ScripTreeHome 'lib'
$PythonDir     = Join-Path $LibDir 'python'

Write-Host "ScripTree install: $ScripTreeHome"
Write-Host "Target Python dir: $PythonDir"

# ── 1. Pick a Python version ─────────────────────────────────────────
# Hard-coded fallback -- bumped per ScripTree release. The dynamic
# lookup below tries to find something newer.
$FallbackVersion = '3.13.1'

if (-not $PythonVersion) {
    Write-Host "`nQuerying python.org for the latest stable release..."
    try {
        # python.org's release feed. is_published=true filters out
        # private/draft releases; pre_release=false drops alphas/betas.
        $api = 'https://www.python.org/api/v2/downloads/release/?is_published=true&pre_release=false'
        $releases = Invoke-RestMethod -Uri $api -TimeoutSec 15
        # The feed returns Python 2 too -- filter to Python 3 by name.
        $py3 = $releases | Where-Object { $_.name -match '^Python 3\.\d+\.\d+$' }
        # Sort by [Version] for proper numeric ordering and pick top.
        $latest = $py3 | ForEach-Object {
            $null = $_.name -match 'Python (3\.\d+\.\d+)'
            [pscustomobject]@{ Ver = [Version]$matches[1]; Name = $matches[1] }
        } | Sort-Object Ver -Descending | Select-Object -First 1
        if ($latest) {
            $PythonVersion = $latest.Name
            Write-Host "Latest stable: Python $PythonVersion"
        }
    } catch {
        Write-Warning "Could not reach python.org API: $($_.Exception.Message)"
    }
    if (-not $PythonVersion) {
        $PythonVersion = $FallbackVersion
        Write-Host "Falling back to known-good version: $PythonVersion"
    }
}

# ── 2. Pick the architecture-specific zip ─────────────────────────────
# python.org publishes embeddable builds for amd64 and arm64.
$arch = $env:PROCESSOR_ARCHITECTURE
switch -Wildcard ($arch) {
    'AMD64' { $embedArch = 'amd64' }
    'ARM64' { $embedArch = 'arm64' }
    default {
        throw "Unsupported architecture: $arch. Embeddable Python is only published for amd64 and arm64."
    }
}

$zipUrl  = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-$embedArch.zip"
$zipFile = Join-Path $env:TEMP "python-$PythonVersion-embed-$embedArch.zip"

# Verify the URL exists before downloading. If 404, retry with the
# fallback version -- the API sometimes lists a release whose embed
# build hasn't been published yet (security-only point releases on
# old branches occasionally lack embeds).
function Test-RemoteFile([string]$url) {
    try {
        $req = [System.Net.WebRequest]::Create($url)
        $req.Method = 'HEAD'
        $req.Timeout = 10000
        $resp = $req.GetResponse()
        $resp.Close()
        return $true
    } catch { return $false }
}

if (-not (Test-RemoteFile $zipUrl)) {
    Write-Warning "$zipUrl not found; trying fallback version $FallbackVersion"
    $PythonVersion = $FallbackVersion
    $zipUrl  = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-$embedArch.zip"
    $zipFile = Join-Path $env:TEMP "python-$PythonVersion-embed-$embedArch.zip"
    if (-not (Test-RemoteFile $zipUrl)) {
        throw "Neither the latest detected version nor the fallback ($FallbackVersion) has a $embedArch embed at python.org."
    }
}

# ── 3. Download the embeddable zip ────────────────────────────────────
Write-Host "`nDownloading $zipUrl"
Write-Host "  -> $zipFile"
Invoke-WebRequest -Uri $zipUrl -OutFile $zipFile -UseBasicParsing
$zipBytes = (Get-Item $zipFile).Length
Write-Host ("  done ({0:N1} MB)" -f ($zipBytes / 1MB))

# ── 4. Extract to lib\python\ ─────────────────────────────────────────
if (Test-Path $PythonDir) {
    Write-Host "`nRemoving existing $PythonDir"
    Remove-Item $PythonDir -Recurse -Force
}
New-Item -ItemType Directory -Path $PythonDir -Force | Out-Null

Write-Host "`nExtracting to $PythonDir"
Expand-Archive -Path $zipFile -DestinationPath $PythonDir -Force

# ── 5. Enable `import site` so pip works ──────────────────────────────
# The embeddable distribution ships with `import site` commented out
# in pythonXX._pth. Without it, `python -m pip` fails to find the
# installed packages directory. Uncomment the line so pip works.
$pthFiles = Get-ChildItem $PythonDir -Filter 'python*._pth'
if (-not $pthFiles) {
    throw "No python*._pth file found in $PythonDir -- the embed zip layout may have changed."
}
foreach ($pth in $pthFiles) {
    $content = Get-Content $pth.FullName
    $patched = $content | ForEach-Object {
        if ($_ -match '^\s*#\s*import\s+site\s*$') { 'import site' } else { $_ }
    }
    # Write UTF-8 WITHOUT a BOM. PowerShell 5.1's Set-Content -Encoding utf8
    # writes BOM by default, which Python's _pth parser does NOT handle —
    # the first line ends up "\ufeffpython3XX.zip" instead of
    # "python3XX.zip", which means the stdlib zip is missing from
    # sys.path and Python can't even find the `encodings` module to
    # boot. ASCII-only content + explicit no-BOM UTF-8 keeps it safe.
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllLines(
        $pth.FullName, [string[]]$patched, $utf8NoBom
    )
    Write-Host "Patched $($pth.Name) -- site enabled."
}

# ── 6. Install pip via get-pip.py ─────────────────────────────────────
$pyExe = Join-Path $PythonDir 'python.exe'
if (-not (Test-Path $pyExe)) {
    throw "python.exe not found at $pyExe after extract."
}

$getPipUrl  = 'https://bootstrap.pypa.io/get-pip.py'
$getPipPath = Join-Path $env:TEMP 'get-pip.py'
Write-Host "`nDownloading get-pip.py"
Invoke-WebRequest -Uri $getPipUrl -OutFile $getPipPath -UseBasicParsing

Write-Host "Running get-pip.py with portable Python"
& $pyExe $getPipPath --no-warn-script-location
if ($LASTEXITCODE -ne 0) {
    throw "get-pip.py exited with code $LASTEXITCODE"
}

# ── 7. Clean up temp files ────────────────────────────────────────────
Remove-Item $zipFile -Force -ErrorAction SilentlyContinue
Remove-Item $getPipPath -Force -ErrorAction SilentlyContinue

# ── 8. Run lib/update_lib.py to populate ScripTree's vendored deps ───
$updateLib = Join-Path $LibDir 'update_lib.py'
if (Test-Path $updateLib) {
    Write-Host "`nRunning lib/update_lib.py to populate vendored ScripTree deps..."
    & $pyExe $updateLib --trim
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "update_lib.py exited with code $LASTEXITCODE -- you may need to run it manually."
    }
}

Write-Host "`nDone. Portable Python installed at:"
Write-Host "  $PythonDir"
Write-Host "`nYou can now run run_scriptree.bat -- it will pick up the portable Python automatically."
