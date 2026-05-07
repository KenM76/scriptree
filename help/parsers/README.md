# Writing help text that ScripTree can parse

ScripTree tries hard to auto-generate a form from a tool's `--help`
output, but it can only work with what the tool gives it. If you're
writing a CLI tool and you'd like ScripTree to produce a clean form on
first import, follow the conventions for your tool's language/platform:

- [`python_scripts.md`](python_scripts.md) — Python CLIs using
  `argparse`, `click`, `docopt`, or `typer`.
- [`windows_exe.md`](windows_exe.md) — Windows-style executables with
  `/flag` arguments, short usage blocks, and `/?` help.
- [`powershell.md`](powershell.md) — PowerShell cmdlets parsed from
  `Get-Help` output.
- [`gnu_tools.md`](gnu_tools.md) — GNU-style long help for
  Unix-family tools (`grep`, `find`, `curl`, `ffmpeg`-style free-form).

## How ScripTree reads help text

ScripTree's probe calls the tool with `--help`, then `-h`, then `/?`,
then `help`, taking the first response that produces at least 50
characters of non-error output. It then runs detectors in this order:

1. **argparse detector** (priority 10) — looks for `usage:` and
   `options:` / `optional arguments:` section headers in the canonical
   argparse layout.
2. **click detector** (priority 20) — looks for `Usage: ... [OPTIONS]`
   and a numbered `Options:` section.
3. **PowerShell detector** (priority 25) — looks for `NAME` /
   `PARAMETERS` section headers from `Get-Help` output. Extracts
   switch parameters, typed parameters, positionals, and parameter
   set metadata. See [`powershell.md`](powershell.md).
4. **Windows help detector** (priority 30) — looks for all-caps usage
   lines with `/flag` arguments and `Parameter List:` headers.
5. **heuristic parser** (priority 999) — fallback that tokenizes each
   line looking for flag patterns like `-x, --xxx VALUE` and promotes
   widgets based on keyword matches in the description.

Only the first detector to match wins. If none match, the heuristic
parser always runs and produces *something* — even for unusual help
formats, you usually get an editable draft.

## What "clean" means

A help format is "clean" when ScripTree's auto-parse produces a form
that needs zero manual corrections. That means:

- Every flag is detected with the right type (bool vs. string vs. enum).
- Every flag's description is captured as the widget tooltip.
- Path flags are promoted to file / folder pickers.
- Enum flags show their choices as a dropdown.
- Required positional arguments are detected and marked required.

If your tool emits standard `argparse --help` output and uses
descriptive `help=` strings on every argument, you'll get a clean form
on first import. If you roll your own help printer without following a
known shape, expect to tune a few things in the editor.

## The fastest route: use a parser library

If you're starting a new tool and want zero-friction ScripTree import:

- Python → use `argparse` (stdlib, zero dependencies, best ScripTree
  support).
- Python with subcommands → use `click` or `typer`.
- C#/.NET → use `System.CommandLine` and make sure `-h` / `--help`
  prints the standard output it generates.
- Rust → `clap` with derive macros produces argparse-shaped help.
- Go → `cobra` or the stdlib `flag` package with a custom usage fn that
  mimics argparse.

Hand-rolled `Console.WriteLine("Usage: foo <arg>")` help always ends up
in the blank-canvas workflow. That's fine — it just takes 60 seconds of
manual work per tool.

## User plugins

ScripTree supports user-authored parser plugins loaded from directories
listed in the `SCRIPTREE_PARSERS_DIR` environment variable.

**Security:** user plugins execute Python code at import time. For this
reason, user plugin loading is **gated by the `load_user_plugins`
permission**. If the permission file is missing or read-only, only
built-in parsers are loaded.

## Post-parse sanitization

All parser output (built-in and user) is automatically sanitized:

- Shell metacharacters (`;|&`$<>{}()!`) are stripped from literal
  tokens in the argument template and from param default values
- Control characters are stripped from cached help text

This prevents crafted `--help` output from injecting dangerous content
into the generated `.scriptree` file.
