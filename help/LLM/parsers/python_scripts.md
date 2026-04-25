# Python CLI help — LLM rules for clean ScripTree import

You are generating a Python CLI tool and want its `--help` output to be
auto-importable by ScripTree with zero manual tweaks. Follow these
rules verbatim.

## Hard rules

1. **Use `argparse` from the stdlib.** Do not hand-roll. Do not use
   `sys.argv` parsing. Do not write custom usage formatters.
2. **Every `add_argument` call must include a `help=` string.** Even
   trivial flags. The help string is the only tooltip the user gets.
3. **Use `type=int` / `type=float`** for numeric arguments. Do not pass
   strings that happen to look like numbers.
4. **Use `action="store_true"` / `action="store_false"` for booleans.**
   Never use `type=bool`.
5. **Use `choices=[...]` for enums.** ScripTree reads the generated
   `{a,b,c}` in the usage line and produces a dropdown.
6. **Use descriptive METAVARs for path arguments:** `metavar="FILE"`,
   `metavar="DIR"`, `metavar="OUTPUT"`.
7. **Include the word "file", "directory", "folder", or "path" in
   help= strings for path arguments.** ScripTree's widget promotion is
   keyword-driven.
8. **Call `parser.parse_args()` once, at module `main()` level.** No
   multi-pass parsing. No subparsers unless the tool genuinely has
   subcommands.

## Template for a clean tool

```python
import argparse
from pathlib import Path

def main() -> int:
    p = argparse.ArgumentParser(
        prog="mytool",
        description="One sentence describing what this tool does.",
    )
    p.add_argument(
        "input",
        metavar="INPUT",
        help="Path to the input file to process",
    )
    p.add_argument(
        "-o", "--output",
        metavar="OUTPUT",
        help="Path to write the output file (default: stdout)",
    )
    p.add_argument(
        "-n", "--count",
        type=int,
        default=10,
        help="Number of iterations to run",
    )
    p.add_argument(
        "-m", "--mode",
        choices=["fast", "slow", "auto"],
        default="auto",
        help="Processing mode",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print diagnostic output",
    )
    args = p.parse_args()
    # ... implementation ...
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

ScripTree's auto-import from this tool produces: required file-open
picker for `input`, file-save picker for `--output`, number spin box
for `--count`, dropdown for `--mode`, checkbox for `--verbose`. All
with correct tooltips.

## Subcommands (click / typer)

For tools with subcommands, generate **one `.scriptree` file per
subcommand**, not one mega-tool. ScripTree's argument template can
carry the subcommand name as a literal:

```json
"argument_template": ["commit", "{message}", "{files}"]
```

This keeps each form focused and avoids the cross-product of options
from different subcommands.

If you must ship a single CLI with multiple subcommands, use `click`
with nested groups and document each subcommand's help at the
subcommand level (not the top level). ScripTree will probe
`tool subcommand --help` and parse each independently if the user
creates separate `.scriptree` files by running each subcommand as the
"executable" (technically it's `tool subcommand`, which is fine — the
executable field supports multi-token launchers by quoting).

## Do not

- **Do not** use `argparse.HelpFormatter` subclasses that change the
  layout. Stick to the default formatter.
- **Do not** emit help to stderr; it goes to stdout by default and
  that's where ScripTree's probe looks first.
- **Do not** use `sys.exit(0)` when `--help` is requested — argparse
  already handles this. Extra exit calls suppress the help output.
- **Do not** print a "tutorial" or "examples" section longer than ~20
  lines. ScripTree's probe truncates at 64 KB but overly-long help
  confuses the heuristic parser's column detection.
- **Do not** invent your own flag shapes (`+flag`, `-longflag`,
  `--shortflag=x,y,z`). Stick to `-x` / `--xxx` / `--xxx=value` /
  `--xxx VALUE` / `--xxx {a,b,c}`.

## Verifying before shipping

After generating the tool, run:

```
python mytool.py --help > help.txt
```

Then open ScripTree, do **File → New tool from executable...**, pick
`python mytool.py`, and confirm:

1. `source.mode` in the resulting draft is `"argparse"`.
2. Every flag from `help.txt` appears in the params list.
3. Path flags have `file_open` / `file_save` / `folder` widgets.
4. Enum flags have `dropdown` widget with correct choices.
5. Bool flags have `checkbox` widget.
6. Tooltips match the `help=` strings.

If any of these fail, fix the `help=` strings or the argument
definitions — do not manually edit the resulting `.scriptree` file, or
you'll lose the fixes the next time the tool is re-parsed.
