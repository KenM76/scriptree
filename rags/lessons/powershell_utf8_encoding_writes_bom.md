---
topic: pyside6
date: 2026-05-07
status: gotcha
related: [sweep_replace_pattern_for_renames]
---
# PowerShell -Encoding utf8 writes a BOM

## What happened

After a sweep-replace rename run via PowerShell
`Set-Content -Encoding utf8`, some Python files broke at
import — no obvious diff in the visible bytes.  Hex-dump
showed `EF BB BF` at the start of every rewritten file.

## Root cause

Windows PowerShell 5.1's `-Encoding utf8` produces UTF-8 WITH
BOM.  PowerShell 7's behaviour was changed but 5.1 (the default
on Windows 10/11) still emits the BOM.  Most Python tools
tolerate it, but it can break parsers that look for `# -*- coding:`
on line 1, source-map readers, and a handful of editors that
don't auto-strip.

## Fix / recipe

Use the .NET `UTF8Encoding($false)` constructor (the `$false`
disables the BOM):

```powershell
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($path, $text, $utf8NoBom)
```

For file reads, `[System.IO.File]::ReadAllText($path)` auto-
detects and strips a BOM if present, so the round-trip is
clean as long as the WRITE side is BOM-free.

## How future-me detects it

A file modified via PowerShell that suddenly fails to parse,
or a `git diff` showing a phantom change at the very start of
a file with no visible content change.  `od -c file | head -1`
reveals `\357 \273 \277` (the BOM bytes) at offset 0.
