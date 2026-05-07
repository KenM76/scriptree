# GNU-style tools — LLM rules for parseable --help

You are generating a Unix-family CLI tool in any language and want its
`--help` output to be auto-importable by ScripTree.

## Strong recommendation

**Use the language's native argparse equivalent** and let it generate
the help for you:

| Language | Library |
|----------|---------|
| Python   | `argparse` (stdlib) |
| Rust     | `clap` with derive macros |
| Go       | `spf13/cobra` or stdlib `flag` |
| C/C++    | `argp` (GNU) or `CLI11` |
| C#       | `System.CommandLine` |
| Ruby     | `optparse` (stdlib) |

All of these produce help output that ScripTree's argparse detector
recognizes. Rolling your own help text should be a last resort.

## If you must write help by hand

Follow this exact shape:

```
Usage: tool [OPTION]... INPUT
Brief one-line description of what the tool does.

Options:
  -v, --verbose             Print diagnostic output
  -o, --output=FILE         Write output to FILE
  -n, --count=N             Number of iterations (default: 10)
  -m, --mode=MODE           Processing mode: fast, slow, or auto
      --dry-run             Don't actually do anything
  -h, --help                Show this help and exit
      --version             Show version information

Examples:
  tool input.txt
  tool -v -o out.txt input.txt
```

## Hard rules

1. **First line is `Usage: ...`**, not a banner or a summary.
2. **Second line (or third, after a blank) is the description**, one
   sentence.
3. **`Options:` header starts the flag list.** Not `Flags:`, not
   `Arguments:`, not `Switches:`. ScripTree keys on the exact word.
4. **Every flag line starts with exactly 2 spaces.** Tab indentation
   confuses some detectors; pick spaces and stick to them.
5. **Short and long flag forms together**, comma-separated: `-v, --verbose`.
6. **Four-space gap between flag and description** (or at minimum 2).
7. **Use `=VALUE` for inline values**, e.g. `--output=FILE`. This is
   unambiguous to every parser. `--output FILE` (space-separated) also
   works but is weaker.
8. **List enum choices in the description**: "fast, slow, or auto" or
   "one of: fast, slow, auto". ScripTree's heuristic parser promotes
   these to dropdowns.
9. **Describe path arguments with "file", "directory", "folder", or
   "path to"** in the description — triggers widget promotion.
10. **Include `-h, --help` and `--version`** as standard conveniences.
    ScripTree ignores them on import.

## Enum example

```
  -f, --format=FORMAT       Output format: json, yaml, or toml
```

The heuristic parser extracts `["json", "yaml", "toml"]` from the
description by matching "X, Y, or Z" patterns. Alternative form:

```
  -f, --format=FORMAT       Output format [json|yaml|toml]
```

Also recognized. Use whichever reads better for humans.

## Grouped sections

For tools with many options, group into labeled sections:

```
Usage: tool [OPTION]... INPUT
Process files and emit reports.

Input options:
  -i, --input=FILE          Input file
  -e, --encoding=ENC        Input encoding (default: utf-8)

Output options:
  -o, --output=FILE         Output file (default: stdout)
  -f, --format=FORMAT       Output format: json, yaml, or toml

Diagnostic options:
  -v, --verbose             Print diagnostic output
  -q, --quiet               Suppress non-error output
  -h, --help                Show this help
```

ScripTree's argparse detector recognizes "X options:" / "X:" as
section headers and emits them as ScripTree sections. Your form gets
collapsible groups for free.

## Positional arguments

State them in the usage line with angle brackets (required) or square
brackets (optional):

```
Usage: tool [OPTION]... <input> [output]
```

Then describe each in a `positional arguments:` section:

```
Positional arguments:
  input                     Path to the input file
  output                    Path to the output file (default: stdout)
```

ScripTree extracts these as required / optional params with file
pickers.

## Do not

- **Do not** invent new flag syntaxes (`+flag`, `--flag:value`,
  `-flag=val` with single dash). Stick to `-x`, `--xxx`,
  `--xxx=VALUE`, `--xxx VALUE`, `--xxx {a,b,c}`.
- **Do not** use tabs for some flags and spaces for others. Pick one.
- **Do not** wrap long descriptions across lines — the heuristic
  parser stops at the line break. If a description is long, rephrase
  it shorter.
- **Do not** emit help longer than ~8 KB. If your help is huge, split
  the tool into subcommands. Each subcommand gets its own `.scriptree`
  file.
- **Do not** use ANSI color codes in help output. The probe strips them
  but the column positions get miscounted during stripping. Gate
  colors behind `isatty` if you need them for human use.
- **Do not** invoke a pager (`less`, `more`) on help output. The probe
  isn't a terminal; gating through `isatty` does the right thing.

## Verifying before shipping

```
tool --help > help.txt
```

Import into ScripTree via **File → New tool from executable...**.
Confirm:

1. `source.mode` is `argparse` (or `click` / `docopt` for those
   frameworks).
2. Every flag is captured.
3. Path flags have the right picker widget.
4. Enum flags have dropdowns with correct choices.
5. Required positionals are marked required.
6. Sections from `X options:` headers are preserved.

If the import produces `source.mode == "heuristic"`, your help text
didn't match any structured detector. Check the section headers and
the indentation — these are the most common causes.
