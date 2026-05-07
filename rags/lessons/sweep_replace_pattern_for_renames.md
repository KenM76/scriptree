---
topic: v3-process
date: 2026-05-07
status: workflow
related: [backup_first_discipline, powershell_utf8_encoding_writes_bom]
---
# Sweep-replace pattern for renames

## What happened / recipe

v0.2.4 renamed `HexagonWindow → CellWindow` and
`HexagonRegistry → CellRegistry` across 17 files / 166
references in one pass.  The recipe used: `git mv` for files
(preserves history), then a PowerShell read/regex/write loop
that does NOT introduce a UTF-8 BOM.

## Root cause / rationale

A two-step approach:

1. `git mv old.py new.py` — git preserves history through a
   real rename, even though the contents change in the same
   commit.  Don't `Remove-Item` then `New-Item`; that loses
   history.
2. Sweep the references with a regex replace that streams
   each file through `[System.IO.File]::ReadAllText` →
   `-replace` → `WriteAllText` with `UTF8Encoding($false)`.
   This is the BOM-free write (see
   `powershell_utf8_encoding_writes_bom`).

## Fix / recipe

```powershell
# 1. Backup first (see backup_first_discipline lesson)
$ts = Get-Date -Format "yyyyMMdd-HHmmss"
Compress-Archive -Path D:\Dev\ScripTree3\* `
  -DestinationPath "...\ScripTree3-backup-$ts.zip" -Force

# 2. Move files (preserves git history)
git mv scriptree/shell/hexagon_window.py scriptree/shell/cell_window.py
git mv scriptree/shell/hexagon_registry.py scriptree/shell/cell_registry.py

# 3. Sweep references in the surviving tree
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
$files = Get-ChildItem -Path D:\Dev\ScripTree3 -Recurse `
    -Include *.py,*.md,*.json `
    | Where-Object { $_.FullName -notmatch '\.git\\' }
foreach ($f in $files) {
    $text = [System.IO.File]::ReadAllText($f.FullName)
    $new = $text `
        -replace 'HexagonWindow', 'CellWindow' `
        -replace 'HexagonRegistry', 'CellRegistry' `
        -replace 'hexagon_window', 'cell_window' `
        -replace 'hexagon_registry', 'cell_registry'
    if ($new -ne $text) {
        [System.IO.File]::WriteAllText($f.FullName, $new, $utf8NoBom)
    }
}

# 4. Run the tests, eyeball git diff, commit.
```

After the sweep, replace any bare `except:` you uncovered
with `except Exception as exc: _log(f"...: {exc!r}")` so the
next regression in that area shows up loudly.

## How future-me detects it

A rename PR with hundreds of touched lines and clean test
runs is a sign this pattern was followed.  If `git log`
shows the renamed files as "added" (no rename detected),
then `git mv` wasn't used and history is broken.
