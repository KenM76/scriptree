# ScripTree — LLM documentation

This folder is for AI agents that need to work on the ScripTree codebase
or generate `.scriptree` / `.scriptreetree` files programmatically.
It is intentionally denser than the human-facing docs: less handholding,
more schema, more invariants.

If you are a human reader, start at [`../README.md`](../README.md) instead.

## Audit the underlying CLI before designing the form

The most common failure mode for AI-generated `.scriptree` files is
**under-coverage** — the model picks the 5 obvious flags from the help
text and ignores the rest. Real users hit the long-tail flags
(`--profile high`, `-pix_fmt yuv420p10le`, `-hwaccel cuda`, `placebo`
preset) and are irritated when forced into a free-form passthrough.

Before you write any params:

1. Run the tool's full help — `tool --help`, `-h full`, `--help-all`,
   `man tool`, whatever the tool exposes. Dump it.
2. Enumerate **every** flag and **every** documented enum value. Don't
   pre-filter to "common." `placebo`, `p7`, `hevc_nvenc`, `+faststart`,
   `yuv420p10le`, `-stats_period` are all things real users hit.
3. Group flags into clusters by what they affect: I/O, encoding /
   quality, filtering, metadata, debug. These become your sections.
4. For each enum-shaped flag, harvest the documented values into
   `choices` — don't truncate the list.

A media-encoding wrapper missing `pix_fmt`, `profile`, `level`,
`hwaccel`, `gop`, `maxrate`/`bufsize`, `movflags`, `metadata`, `-map`,
or stream-codec selectors is **incomplete** for that domain. Equivalent
must-have lists exist for archivers (compression level, threading,
exclude patterns, atime preservation), compilers (optimisation level,
debug info, target arch, sanitizers), network tools (auth, timeout,
retries, proxy), etc. When in doubt, lean toward including the knob
rather than omitting it.

## When the underlying CLI is huge, decompose by user intent

Some CLIs (ffmpeg, imagemagick, git, ssh, openssl, 7z) cover dozens of
distinct workflows. A single mega-`.scriptree` with 80 fields is
unusable; a thin two-flag wrapper is useless. The correct shape is a
**`.scriptreetree` of purpose-built `.scriptree` leaves**, one per
intent the user might pick from a menu.

For ffmpeg, that decomposition is roughly: convert, compress, trim,
resize, crop, rotate, speed, watermark, volume, extract-audio,
extract-frames, gif, thumbnail, concat, subtitles, probe, plus a
single `advanced-passthrough` tool that exposes the raw flags for use
cases the purpose-built tools don't cover.

Each leaf is then small enough (5–25 params) to render cleanly in
tabs. The advanced-passthrough leaf is **mandatory** — it's the
escape hatch when a user needs a flag that didn't make it into a
purpose-built form.

Apply the same intent-decomposition pattern to any CLI whose total
flag surface is larger than ~40 flags or whose help text is divided
into subcommand sections.

## Form design defaults — read before generating any `.scriptree`

After auditing the surface and (if necessary) decomposing into
multiple leaves, lay each leaf out as a sectioned or tabbed form
rather than a flat parameter list. Flat 10+ forms are the second
most common failure mode of AI-generated tools.

**Required layout by param count:**

| Param count | **Required** layout |
|---|---|
| 1 – 4 params  | Flat — no sections |
| 5 – 10 params | Sections — `tab` mode if the groups are workflow-like (Files / Encoding / Time), `collapse` mode if they're just topical buckets |
| 10 + params   | **Always tabs.** A flat 10+ form is a defect. |

Concrete heuristics:

- **Required input/output** → `Files` or `Input` section (always visible).
- **Behavioral toggles, sort orders, format options** → `Pipeline stages` or `Options` section.
- **Power-user knobs (timeouts, debug flags, paths to overrides)** →
  `Advanced` section, **collapsed by default** (`"collapsed": true`).
- Use **tab mode** (`"layout": "tab"`) when the tool has clearly
  separable phases or contexts — e.g. command-line vs. environment vs.
  diagnostics. Use **collapse mode** (`"layout": "collapse"`, the
  default) when the groups are roughly equally important and the user
  may want several open at once.

Section order matters: it's the visible order in the runner. Put the
section the user touches first at the top.

**Defaults must produce a working command for the most common case.**
A required field that defaults to `""` and crashes on Run is broken.
Required fields fall into two buckets: (a) genuinely user-supplied
(input/output paths, the one main thing the tool does) which can have
empty defaults, and (b) anything else, which must have a default that
runs without modification.

Schema for sections lives in [`scriptree_format.md`](scriptree_format.md)
under "`SectionDef` shape" and "Per-section `layout` field". Each
`ParamDef` then carries a `"section": "<name>"` referring to one of
the declared sections.

> **Don't** declare sections and then leave most params with empty
> `section: ""` — that mixes sectioned and unsectioned params and the
> runner renders the orphans in a synthetic "Other" bucket at the end,
> which usually isn't what you want.

## Orientation

- [`architecture.md`](architecture.md) — package layout, the `core` vs
  `ui` split, the cross-platform seam, the hot-loops you should not
  cross.
- [`scriptree_format.md`](scriptree_format.md) — full JSON schema for
  `.scriptree` files, field by field, with every invariant the loader
  enforces.
- [`scriptreetree_format.md`](scriptreetree_format.md) — tree launcher
  format, path resolution rules.
- [`scriptreering_format.md`](scriptreering_format.md) — ring file
  format (master + member cell layout for the cell shell).
- [`scriptreeforest_format.md`](scriptreeforest_format.md) — top-level
  forest container (v0.3.14+): one-per-session workspace that owns
  rings, trees, and tools, with auto-discovery + the priority rule
  + excluded-list semantics.
- [`configurations_sidecar.md`](configurations_sidecar.md) — the sidecar
  JSON format (`<name>.scriptree.configs.json`), including env/PATH
  override fields, UI visibility, hidden parameters, credential prompt,
  tree-level configurations, and the reserved `safetree` config.
  **Ship a "standalone" configuration with every end-user-facing
  tool** — see the "Standalone-mode recipe" section.  Default UI
  visibility shows the command-line preview, copy-argv, env, extras
  box, and tools sidebar; for an end user launching via
  ScripTreeRing those should all be off, with `popup_on_error`
  and `popup_on_success` on for clear close-the-loop feedback.
- [`argument_template.md`](argument_template.md) — the substitution
  grammar that powers `build_full_argv`, with a reference implementation
  sketch and all the edge cases the tests pin down.
- [`param_types_widgets.md`](param_types_widgets.md) — the type × widget
  matrix, allowed combinations, default values per type, coercion rules.
- [`dynamic_providers.md`](dynamic_providers.md) — v0.6.0
  `choices_provider` / `depends_on` / `select_all`: populate a param's
  choices or value from an external command at form-open time
  (cascading dropdowns, dependent checkbox lists, auto-detected
  paths). The full provider stdin/stdout contract.
- [`icon_library.md`](icon_library.md) — **start here for icon
  picking.** The full bundled 52-icon set grouped by category with
  a one-line "use for" hint per glyph, the keyword → icon
  heuristic (`classify_icon`) rule table in match order, the
  decision tree for picking an icon, the embed workflow (PNG, not
  SVG — the portable runtime has no qsvg plugin), and how/when to
  add a new archetype.  Cross-suite mapping conventions
  (operation-by-operation, verb-keeps-the-meaning-distinct,
  vendor-identity-on-the-root-only) with worked examples from
  ffmpeg, outlook migration, and the SolidWorks toolkit.
- [`../host-software-icon-style.md`](../host-software-icon-style.md)
  — the canonical trademark-safe monochrome line-icon spec.
  Required reading before generating a *new* SVG when no §2
  archetype in `icon_library.md` fits.  Defines the invariant
  skeleton (48 grid, `currentColor`, stroke-width 2.5, 1–4
  primitives, mandatory "generic … not the trademark" comment) +
  the legal trademark gate.
- [`parsers/`](parsers) — rules for generating CLI tools whose `--help`
  output will import cleanly into ScripTree on the first try. One file
  per tool family (`python_scripts.md`, `windows_exe.md`,
  `powershell.md`, `gnu_tools.md`). Read these before writing any new
  CLI tool you intend to wrap.

## Security

- `core/permissions.py` — capability-based access control with recursive
  search, secure defaults, per-file inheritance. See `../security.md`.
- `core/sanitize.py` — input sanitization, path validation,
  `split_command()` (no shell).
- Custom menus use `split_command()`, never `shell=True`.
- Parser output is post-sanitized: `probe.py:_sanitize_parsed_tool()`.
- User plugins gated by `load_user_plugins` permission.
- Credential buffer zeroed via `ctypes` after use.

## Key invariants

These hold across the entire codebase. Violating any of them will break
existing tests and user files.

1. **`scriptree/core/` imports nothing from PySide6.** The cross-platform
   seam depends on this. A future Linux GTK fork replaces `ui/`
   wholesale; `core/` must stay portable.
2. **File formats are backward compatible in both directions.** Loaders
   must tolerate missing optional fields; writers must omit empty
   collections so older readers see no diff.
3. **`build_full_argv` is pure and deterministic.** Given the same
   `ToolDef`, values dict, extras list, and env inputs, it returns the
   same `ResolvedCommand`. No filesystem, no network, no clock.
4. **`Popen` always gets a list argv, never `shell=True`.** Quoting is
   the spawner's job, not the user's.
5. **Schema version bumps are additive.** Add new fields, don't rename
   or remove existing ones. Old files keep loading forever.

## Authoring rules that apply to every format file

These apply to **`.scriptree`, `.scriptreetree`, and `.scriptreering`
files alike** — read this before generating any catalog of any
format.

- **Set `schema_version` from the source-of-truth constant, not
  from a doc.**  The current value lives at
  `SCHEMA_VERSION` in `scriptree/core/model.py` for `.scriptree`
  and `.scriptreetree`, and at `_VERSION` in
  `scriptree/shell/ring_io.py` for `.scriptreering`.  **Do NOT
  trust the number embedded in any format doc's title, JSON
  sketch, prose, or "Example" block** — those drift at every
  schema bump and have shipped stale at least once (an LLM
  session wrote `schema_version: 2` for a tree after v3 was
  released; the loader hard-rejected the file).  Always grep the
  constant before writing the field.  The configurations sidecar
  (`<name>.scriptree.configs.json`) has its own separate constant
  (`CONFIGS_SCHEMA_VERSION` in `scriptree/core/configs.py`); it
  rolls independently.
- **Validate by round-trip through the real loader.**  Build the
  dict, call `tool_from_dict` / `tree_from_dict` /
  `load_ring` / `load_forest`, then re-serialise; if anything
  drifts, the file won't load on a user's machine either.  Pure
  JSON validity is not enough — the schema-version gate, type
  coercions, and enum guards only fire inside the loader.

## When generating `.scriptree` files from scratch

- Keep `argument_template` minimal — literals for subcommands,
  `{id}` / `{id?--flag}` / `{id?--flag=}` for param substitution.
- Omit empty `env`, `path_prepend`, and `sections` unless you have a
  reason to serialize them.
- Set `source.mode` to `"manual"` unless you actually ran a parser.
- Omit `menus` unless the tool actually needs custom menus.
- Validate the result by round-tripping through `tool_from_dict` →
  `tool_to_dict` → JSON and confirming the output is stable.
- Do NOT use shell metacharacters in menu `command` strings — they
  are split safely via `split_command()`, not passed to a shell.

## Pre-save checklist

Before saving any generated `.scriptree` or `.scriptreetree`,
verify each of these:

0. **`schema_version` was read from
   `SCHEMA_VERSION` in `scriptree/core/model.py`**, not copied
   from any doc.  Files whose `schema_version` is below the
   build's value may or may not load with in-memory upgrade
   (depends on the version comments in `model.py`); files
   *above* the build's value are hard-rejected (forward-compat
   tripwire).  When in doubt, grep the constant.  Run a final
   `tool_from_dict` / `tree_from_dict` round-trip and confirm
   it returned successfully — that's the only check that
   actually exercises the schema gate.
1. **Required fields default to a working value** — or are explicitly
   user-supplied (input/output paths). Required + `default: ""` +
   no validation = a tool that crashes on Run.
2. **Every enum-shaped flag in the underlying tool's help text has its
   documented values in `choices`.** Don't truncate. Power users will
   be irritated to find `placebo` or `hevc_nvenc` missing.
3. **Filter / expression fields offer 10+ named presets** via `enum` +
   `choices` + `choice_labels` before falling back to a free-form text
   field. See "Preset bundles" in
   [`param_types_widgets.md`](param_types_widgets.md). This is the
   single highest-leverage UX pattern in the schema.
4. **Sections are `tab` mode if the form has 10+ params.** A flat
   10-row scroll is a defect.
5. **Mode switches that gate other fields use `radio`, not
   `checkbox`.** A radio cues the user that the mode comes first; a
   checkbox suggests an independent toggle. See
   [`param_types_widgets.md`](param_types_widgets.md).
6. **One example command the form would emit has been traced through
   by hand and run against the actual binary.** JSON validity is not
   enough — the argv has to actually work. This is the difference
   between "it loads" and "it does the thing."
7. **The catalog carries an embedded icon.** A bare text row in the
   cell menu / tree view is a defect.  Walk the decision tree in
   [`icon_library.md`](icon_library.md) §1: reuse a bundled glyph
   from §2 (52 archetypes covering CAD, office docs, file system,
   data, network, ops verbs, code/build/test, security, hardware,
   media, measurement) — only generate a new SVG when none of the
   §2 archetypes genuinely fit.  When generating, follow
   [`../host-software-icon-style.md`](../host-software-icon-style.md)
   verbatim, then embed it as PNG (`cell.icon_data` base64 of the
   PNG + `cell.icon_format:"png"`; portable runtime has no SVG
   plugin).  Never a vendor's real logo (legal gate).  For a
   multi-leaf suite, vary the icons by operation — see
   `icon_library.md` §7 worked examples (ffmpeg / outlook /
   SolidWorks).  See `scriptree_format.md` → "`cell` sub-object"
   for the schema.
