# Windows-style executable help

Windows tools predating the Unix conventions use `/flag` arguments,
respond to `/?` instead of `--help`, and emit short, column-aligned
usage blocks. Examples: `find.exe`, `xcopy.exe`, `robocopy.exe`,
`reg.exe`, and many legacy Microsoft utilities.

ScripTree's heuristic parser handles these formats — there's no
dedicated detector because there's no single standard — but you can
improve auto-detection by following the conventions on this page.

## The canonical shape

```
FOO - One-line summary of what this tool does.

Usage: foo.exe [/A] [/B value] [/MODE:mode] <input>

  /A              Enable mode A.
  /B value        Set option B to the given value.
  /MODE:mode      Choose mode: fast, slow, or auto.
  /V              Verbose output.
  /?              Show this help.

Examples:
  foo.exe /A /B 10 C:\input.txt
```

## What ScripTree extracts

- **Every line that starts with whitespace + `/flag`** becomes a param.
- `/flag value` or `/flag:value` → string-valued option.
- `/flag` alone → boolean flag.
- `/flag:choice1|choice2|choice3` or a description ending in "X, Y, or
  Z" → enum (heuristic).
- Positional args from the `<angle>` or `[bracket]` tokens in the
  usage line.

The widget promotion rules (file picker, spin box, etc.) work the same
as for Unix tools — they key on description keywords like "file",
"path", "directory", "number of", etc.

## Writing help text for maximum parse quality

### 1. Start with a `Usage:` line

ScripTree keys on the word `Usage:` at the start of a line (or after
one blank line) as the entry point. Without it, positionals and the
flag list aren't anchored.

```
Usage: foo.exe [/A] [/B value] <input> [output]
```

### 2. One flag per line, indented by at least 2 spaces

```
  /A              Enable mode A.
  /B value        Set option B.
```

Flags at column 1 are skipped (they look like prose). Flags at column
≥2 are extracted.

### 3. Align descriptions in a column

Two or more spaces between the flag (with its value, if any) and the
description. ScripTree splits on `≥2 spaces`; tabs also work but be
consistent.

### 4. Use `/FLAG:value` notation for inline values

```
  /MODE:mode      Set processing mode.
```

ScripTree detects this as a string-valued option. For booleans, omit
the value:

```
  /V              Verbose output.
```

### 5. List enum choices explicitly

```
  /MODE:mode      Processing mode: fast, slow, or auto.
```

or

```
  /MODE:fast|slow|auto    Processing mode.
```

The parser picks up either form. The second is clearer for humans and
machines both.

### 6. Describe path arguments as "file" / "folder"

```
  /OUT file       Output file to write results to.
  /LOG folder     Directory to write log files into.
```

Words like "file", "folder", "directory", "path to", "output file",
"input file" in the description promote the widget from a plain text
box to a file picker.

### 7. Respond to all the probe arguments

ScripTree's probe tries `--help`, `-h`, `/?`, and `help` in that order.
Native Windows tools should at minimum respond to `/?`. If you also
support `--help`, even better — ScripTree will get the same output
either way.

## Example: a small Windows-style tool

```
FILEFIND - Search a directory for files matching a pattern.

Usage: filefind.exe [/S] [/D days] [/OUT file] <folder> <pattern>

  <folder>        Directory to search.
  <pattern>       File name pattern (wildcards allowed).
  /S              Recurse into subdirectories.
  /D days         Only match files modified in the last <days> days.
  /OUT file       Write matches to this file instead of the console.
  /MODE:mode      Output format: text, csv, or json.
  /?              Show this help.

Examples:
  filefind.exe C:\projects *.log
  filefind.exe /S /D 7 /OUT recent.txt C:\projects *.cs
```

ScripTree's auto-import produces:

- Two required positionals: `folder` (folder picker) and `pattern`
  (text).
- `/S` as a checkbox labeled "Recurse into subdirectories".
- `/D` as a number spin box ("days" in the description).
- `/OUT` as a file_save picker ("file" in the description).
- `/MODE` as a dropdown with three choices.

Zero edits needed. The key is writing the help to look like this
document — once you internalize the shape, every Windows-style tool
you write will import cleanly.

## What not to do

- **Don't** put descriptions on a separate line from the flag. ScripTree
  pairs flag-and-description by line.
- **Don't** use mixed indentation (some flags at column 2, others at
  column 4). The parser locks onto the first flag's column and expects
  all others to match.
- **Don't** rely on box-drawing characters or ASCII art for layout.
  They confuse column detection.
- **Don't** emit help through `MessageBox.Show` — it has to go to
  stdout for the probe to capture it.
