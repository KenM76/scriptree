# Python CLI help — writing it so ScripTree can parse it

ScripTree has dedicated detectors for the three big Python CLI
frameworks: `argparse`, `click`, and `docopt`. Using any of these gets
you a clean auto-import with zero manual tweaking in most cases.

## argparse (strongly recommended)

### What works out of the box

`argparse --help` output has a rigid structure:

```
usage: my_tool.py [-h] [--verbose] [--count N] [--mode {fast,slow}] INPUT

Description paragraph goes here.

positional arguments:
  INPUT                 Path to the input file

options:
  -h, --help            show this help message and exit
  --verbose             Print extra diagnostic output
  --count N             Number of iterations (default: 10)
  --mode {fast,slow}    Processing mode
```

ScripTree's argparse detector recognizes this shape with very high
confidence and pulls out:

- Every flag, including short + long forms.
- The METAVAR (`N`, `INPUT`) as a hint for type detection.
- Enum choices from `{fast,slow}` syntax.
- The description text, verbatim, as the tooltip.
- Positional arguments as required params.

### How to write it cleanly

```python
import argparse

def main():
    p = argparse.ArgumentParser(
        description="Process a file and emit a report.",
    )
    p.add_argument("input", help="Path to the input file")
    p.add_argument("--output", "-o", help="Path to write the report",
                   metavar="FILE")
    p.add_argument("--count", type=int, default=10,
                   help="Number of iterations")
    p.add_argument("--mode", choices=["fast", "slow"], default="fast",
                   help="Processing mode")
    p.add_argument("--verbose", action="store_true",
                   help="Print extra diagnostic output")
    args = p.parse_args()
```

### Tips for best auto-parse

1. **Always provide a `help=` string.** ScripTree uses it both as the
   tooltip and for widget promotion — descriptions containing "file",
   "path to", "directory", "port", "number of", etc. bump the widget
   from a plain text box to a file picker / spin box.
2. **Use descriptive METAVARs for path arguments**. `metavar="FILE"`
   or `metavar="DIR"` helps the detector pick the right widget when
   the description is ambiguous.
3. **Use `choices=[...]` for enums.** argparse prints them as
   `{a,b,c}` in the usage line, which ScripTree recognizes instantly.
4. **Use `action="store_true"`** for flags — not `type=bool`. The
   detector treats `store_true` as a checkbox and `type=bool` as a
   string (because bool-from-string is a footgun anyway).
5. **Use `type=int` / `type=float`** where appropriate so the detector
   can pick a spin box.
6. **Avoid writing a custom `usage=` string** unless you know what
   you're doing. The default format is what the detector expects.

### Example with all the right moves

```python
p = argparse.ArgumentParser(description="Resize images in a folder.")
p.add_argument("input_dir", metavar="INPUT_DIR",
               help="Directory containing images to resize")
p.add_argument("output_dir", metavar="OUTPUT_DIR",
               help="Directory to write resized images to")
p.add_argument("--width", type=int, default=800,
               help="Target width in pixels")
p.add_argument("--height", type=int, default=600,
               help="Target height in pixels")
p.add_argument("--format", choices=["jpg", "png", "webp"], default="jpg",
               help="Output file format")
p.add_argument("--overwrite", action="store_true",
               help="Overwrite existing files in the output directory")
```

ScripTree auto-generates: two folder pickers, two number spin boxes, a
three-option dropdown, and a checkbox. Zero edits needed.

## click

### Help output shape

```
Usage: my_tool [OPTIONS] INPUT

  Process a file and emit a report.

Options:
  -o, --output FILE       Path to write the report
  --count INTEGER         Number of iterations  [default: 10]
  --mode [fast|slow]      Processing mode
  --verbose               Print extra diagnostic output
  --help                  Show this message and exit.
```

The click detector recognizes this shape and extracts flags, types
(`INTEGER`, `FILE`, `DIRECTORY`), choices (`[fast|slow]`), and
descriptions.

### Tips

1. **Use click's built-in types**: `click.Path(exists=True)`,
   `click.File()`, `click.INT`, `click.Choice([...])`. Each prints a
   recognizable hint in the help output.
2. **Provide `help=` on every option**, same reason as argparse.
3. **Use `click.Path(file_okay=True, dir_okay=False)`** to disambiguate
   file-vs-folder picker selection.
4. **Subcommands** are parsed one level deep by ScripTree. For a tool
   like `git commit`, create a dedicated `.scriptree` per subcommand
   with the subcommand name as a literal in the argument template.

## docopt

docopt parses the help string itself at run time, which means you write
the help first and the parser follows. This also means the shape is
fully under your control — and ScripTree can detect it if you follow
the conventional layout:

```
Usage:
  my_tool [options] <input>
  my_tool -h | --help

Options:
  -o FILE, --output=FILE    Write report to FILE
  --count=N                 Number of iterations [default: 10]
  --mode=MODE               Processing mode: fast or slow [default: fast]
  --verbose                 Print extra diagnostic output
  -h, --help                Show this screen
```

### Tips

1. **Indent `Options:` entries by exactly 2 spaces.** docopt tolerates
   other indentations but ScripTree's detector keys on "2 spaces + flag".
2. **Separate flag and description with at least 2 spaces.** Use 4+ for
   safety.
3. **Show defaults explicitly** as `[default: value]` — docopt uses
   this and so does ScripTree.
4. **Document enum choices in the description** (`fast or slow`). The
   heuristic parser picks them up even without a dedicated `[a|b]`
   block.

## typer

Typer wraps click, so the help output shape is similar. The click
detector handles it. Typer's auto-generated metavar for Path parameters
is `PATH`, which ScripTree's detector treats as a file picker hint.

### Tips

1. **Annotate parameter types explicitly** (`int`, `Path`, `bool`).
2. **Use `typer.Option(..., help="...")`** — the help string flows into
   click's output and thence into ScripTree.
3. **Use `Path` from `pathlib`** for file/folder arguments.

## What to avoid

- **Hand-rolled `print("Usage: ...")`** — the heuristic parser may
  catch some of it, but you'll spend more time tweaking in the editor
  than you would have spent adopting argparse.
- **ANSI color codes in help output.** The probe strips them, but
  multi-line entries with embedded colors confuse layout-sensitive
  detectors. If you need colored help for humans, gate it behind
  `isatty`.
- **Help text longer than 8 KB.** ScripTree truncates at 64 KB but
  multi-screen help usually means poor organization and worse
  parsing. Split the tool into subcommands if it's getting unwieldy.
- **Custom formatters that reorder sections.** argparse's
  `RawDescriptionHelpFormatter` is fine; custom formatters that put
  `options:` before `usage:` break detection.
