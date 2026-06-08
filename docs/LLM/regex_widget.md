# `regex` widget — authoring reference

## What it is

A specialised parameter widget for fields that take a **regex
pattern**. Available since v0.8.0a48 as one of the legal widgets
for `ParamType.STRING`.

It looks like a regular `text` widget — a one-line edit field — but
adds two affordances that make authoring regexes substantially less
error-prone:

1. **Live validation.** As the user types, the field's border turns
   green with a ✓ badge when the pattern parses, red with a ✗ badge
   when it doesn't. The parse error (e.g. "missing closing
   parenthesis") is shown as both the badge tooltip and the
   line-edit tooltip, so hovering anywhere on the field surfaces it.
   Debounced at 150 ms so the colour doesn't flicker on every
   keystroke.

2. **Helper button (🔧).** Opens a modal `Regex helper` dialog with
   three tabs:

   - **Test** — pattern + flag toggles on top, a sample-text editor
     below, **live highlighting** of every match in the sample, and
     a captures table that breaks each match down by group. Lets the
     user verify the pattern works against real input before
     adopting.
   - **Library** — pre-built patterns from the vendored CommonRegex
     package (email, phone, URL, date, IPv4, IPv6, time, money,
     credit-card, bitcoin-address, hex-colour, street-address) plus
     the user's personal library at
     `%APPDATA%/ScripTree/regex_library.json`. Selecting any entry
     populates the Test tab; "Add current pattern..." promotes
     whatever's in the Test tab into the user library.
   - **Reference** — static markdown cheatsheet of regex syntax
     (anchors, character classes, quantifiers, groups, look-around,
     inline flags). Always available, no network needed.

## On the wire

The widget emits a plain string — the regex pattern itself, with
any inline flag block (`(?i)`, `(?im)`, etc.) prepended to the
pattern when the user toggled flags in the helper. Tools that
consume the pattern as a CLI argument or sidecar config value see
no difference from `text` — they just receive a regex string.

## When to use it

Reach for `regex` instead of `text` whenever the parameter's value
will be passed to a regex engine downstream (Python's `re`,
ripgrep, sed, etc.). Examples:

- Filter parameters: "only process files matching this pattern"
- Find/replace tools: the `pattern` field
- Validation rules: pattern checks against user input
- Log scrapers: "match lines that look like this"

For a `text` widget that happens to accept a regex but where the
pattern is rare (e.g. an optional "advanced filter" field), keeping
`text` is fine — `regex` is for fields where the pattern is the
PRIMARY input and the user spends time crafting it.

## `.scriptree` snippet

```json
{
  "id": "pattern",
  "label": "Pattern",
  "type": "string",
  "widget": "regex",
  "default": "\\b[A-Z][a-z]+\\b",
  "description": "Regex applied to each input line.",
  "required": true
}
```

That's the only field-level change. The runtime (`build_widget_for`)
sees `widget == "regex"` and instantiates `RegexWidget` from
`scriptree/ui/widgets/regex_widget.py`.

## Default value

Whatever string the tool ships in `default` is shown verbatim in the
field on first open. A common pattern (no pun intended) is to put a
*placeholder* example in `description` and leave `default` empty so
the user has to think about what they want.

The placeholder shown when `default` is empty is `description[:80]`,
falling back to `e.g. \b[A-Z][a-z]+\b or ^\d{3}-\d{4}$` when the
description is itself empty.

## Flag handling

The helper dialog has four flag checkboxes: `i` (case-insensitive),
`m` (multi-line), `s` (dotall), `x` (verbose). When the user
accepts a pattern with flags set, they're encoded inline as a
`(?flags)` prefix on the saved value. For example, accepting
pattern `foo` with flags `i,m` writes `(?im)foo` into the field.

This is the canonical regex-engine-agnostic way to ship flags with
a pattern — Python's `re`, Perl, ripgrep, ECMAScript, etc. all
understand `(?xxx)`. No special handling needed on the receiving
end.

## User library at `%APPDATA%/ScripTree/regex_library.json`

The user's saved patterns persist to a per-user JSON file at
`QStandardPaths.AppDataLocation/ScripTree/regex_library.json`. On
Windows that's `%APPDATA%/Roaming/ScripTree/regex_library.json`; on
macOS/Linux Qt resolves the equivalent user-data folder.

Schema (`"version": 1`):

```json
{
  "version": 1,
  "patterns": [
    {
      "name": "SKU code",
      "pattern": "^[A-Z]{2}-\\d{4}$",
      "description": "Two letters, dash, four digits",
      "flags": "",
      "notes": ""
    }
  ]
}
```

Per-user (NOT per-workspace) by design — users build a library of
regex over time and reach for the same handful across many tools
and forests. The helper dialog's "Export to forest folder..."
button can copy the library to a folder next to a
`.scriptreeforest` if a user wants it to follow a synced workspace,
but that's one-way; future edits still go back to `%APPDATA%`.

## Validation contract

Patterns are validated via Qt's `QRegularExpression`. This is
PCRE-compatible, so any pattern the user can author here will be
parseable by Python's `re`, the JVM regex engine, JavaScript's
RegExp, ripgrep, etc. with at most cosmetic syntax differences
(named-group shapes, e.g. `(?P<x>...)` vs `(?<x>...)`).

Empty pattern is **not** an error — the validity badge is hidden
and the border is neutral. This is so a freshly-opened tool form
doesn't show a red "invalid" state before the user has typed
anything.

## Common pitfalls

- **Forgetting to escape regex metacharacters in `default`.** When
  embedding a pattern in JSON, write `\\b` (the JSON escape) to
  send `\b` (the regex token) to the engine. The widget reads
  whatever JSON parsing gives it — if you write `\b`, JSON
  interprets that as backspace.
- **Using the wrong regex dialect.** Qt's `QRegularExpression` is
  PCRE-flavoured. If the downstream tool uses POSIX BRE/ERE or some
  exotic dialect, the validation badge may green-light a pattern
  the downstream engine will reject. Test with the actual tool.
- **Flags from the dialog vs. flags in the saved pattern.** If the
  user types a pattern with a `(?i)` prefix manually, then opens
  the helper, the prefix is split off into the flag checkboxes so
  they round-trip cleanly. Don't ship a `default` that has an
  inline flag block AND expect the flag boxes to be unchecked —
  they'll be checked on first open.

## Cross-references

- `scriptree/ui/widgets/regex_widget.py` — the `RegexWidget` class
- `scriptree/ui/widgets/regex_helper.py` — the `RegexHelperDialog`
- `scriptree/ui/widgets/regex_library.py` — CommonRegex bridge +
  user-library JSON I/O
- `lib/_manifests/CommonRegex.md` — the vendored package note
- `tests/test_regex_widget.py` — the regression tests pinning
  validation behaviour + library round-trip
- `docs/LLM/param_types_widgets.md` — the widget-overview reference
  matrix (`regex` row added v0.8.0a48)
