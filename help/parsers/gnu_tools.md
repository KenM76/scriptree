# GNU-style long help

Unix-family tools — `grep`, `find`, `curl`, `tar`, `ffmpeg` — typically
emit a large `--help` output with a short/long flag per line, an
optional METAVAR, and a description that may wrap across lines.
ScripTree's argparse detector handles the cleanest subset; the
heuristic parser catches the rest.

## The clean subset (easy to parse)

```
Usage: grep [OPTION]... PATTERNS [FILE]...
Search for PATTERNS in each FILE.
Example: grep -i 'hello world' menu.h main.c

Pattern selection and interpretation:
  -E, --extended-regexp     PATTERNS are extended regular expressions
  -F, --fixed-strings       PATTERNS are strings
  -G, --basic-regexp        PATTERNS are basic regular expressions

Miscellaneous:
  -s, --no-messages         suppress error messages
  -v, --invert-match        select non-matching lines
      --help                display this help and exit
      --version             output version information and exit
```

This shape is close enough to argparse that the argparse detector
picks it up. ScripTree extracts:

- Every flag with short + long forms merged.
- The description as the tooltip.
- Sections (`Pattern selection and interpretation:`,
  `Miscellaneous:`) as ScripTree sections in the generated form.

## The messy subset (`ffmpeg` and friends)

Some tools emit a free-form help that's organized for humans rather
than machines:

```
Hyper fast Audio and Video encoder
usage: ffmpeg [options] [[infile options] -i infile]... {[outfile options] outfile}...

Getting help:
    -h      -- print basic options
    -h long -- print more options
    -h full -- print all options (including all format and codec specific options, very long)
...
```

The heuristic parser produces *something* here, but expect to spend
time cleaning up in the editor. This is normal and expected — `ffmpeg`
has thousands of options and no programmatic description of them.

## Writing GNU-style help cleanly

If you're writing a new tool and you want top-tier auto-import:

### 1. Follow the argparse layout

```
Usage: mytool [OPTION]... INPUT
Brief summary of what the tool does.

Options:
  -v, --verbose             Print diagnostic output
  -o, --output=FILE         Write output to FILE (default: stdout)
  -n, --count=N             Limit output to N results
  -m, --mode=MODE           Processing mode: fast, slow, or auto
      --dry-run             Don't actually do anything
      --help                Show this help
      --version             Show version information
```

Even if you're not using Python's argparse, match its layout by hand
and ScripTree's detector will still fire.

### 2. Separate long flag from value with `=`

`--output=FILE` is parsed as a string-valued option. `--output FILE`
is parsed as a group (flag + separate token) and also works. `--output`
alone, with the value implied later, does not parse cleanly — be
explicit.

### 3. Align descriptions with `≥2 spaces`

The heuristic parser splits flag lines on the first run of `≥2 spaces`
or a tab. Use tabs consistently or use spaces consistently; don't mix.

### 4. Group options into labeled sections

```
Input options:
  -i, --input=FILE          Input file
  -e, --encoding=ENC        Input encoding

Output options:
  -o, --output=FILE         Output file
  -f, --format=FMT          Output format
```

The argparse detector picks up "X:" headers as section boundaries and
emits them as ScripTree sections. Your users get a form with
collapsible groups for free.

### 5. List enum choices in the description

```
  -m, --mode=MODE           Mode: one of fast, slow, auto
```

The heuristic parser picks up "one of X, Y, Z" and "X, Y, or Z" as
enum markers and promotes the widget to a dropdown.

### 6. Emit help to stdout, not stderr

The probe captures both streams but prefers stdout. If you print help
to stderr (old convention), the probe still finds it but enum
detection may be less reliable.

## What ScripTree does with a messy `--help`

Even when the heuristic parser has low confidence:

1. It extracts every line that *looks* like a flag (contains `-x` or
   `--xxx` near the start).
2. It creates a ScripTree param for each with type=`string`,
   widget=`text` as a default.
3. It copies the description text verbatim as the tooltip.
4. It opens the editor so the user can fix everything in two minutes.

The editor's flow is built around this "parse + fix" workflow — you're
not expected to get a perfect import from a messy help text. You're
expected to get 80% of the way there and edit the rest manually.

## Common pitfalls

- **Line-wrapped descriptions** — GNU tools often wrap long
  descriptions onto the next line, indented further. The heuristic
  parser stops at the line break, losing the tail of the description.
  Keep each flag's description on one line if possible.
- **Interleaved positional arguments** — `[OPTION]... FILE... [OPTION]...`
  confuses positional detection. Put all positionals at the end of the
  usage line.
- **Multiple usage lines** — `find(1)` has three different usage
  synopses. ScripTree only reads the first. If your tool has multiple
  modes, consider splitting it into multiple `.scriptree` files with
  distinct argument templates.
- **Help paginated through `less`** — some tools invoke a pager when
  stdout is a terminal. The probe isn't a terminal, so this usually
  does the right thing, but if you've got `LESS` or `PAGER` logic,
  make sure it respects `isatty`.
