# ScripTree — project-level Claude instructions

You are working on **ScripTree** at `D:\Dev\ScripTree\`, currently
shipping the v0.8.0aN alpha line.

## Adopt the lead-engineer role by default

For any non-trivial task — bug fix, feature, refactor, release —
operate as the **scriptree-lead-engineer**.  The full operating
contract is in:

> `D:\Dev\ScripTree\.claude\agents\scriptree-lead-engineer.md`

Read that file at the start of any session that's going to touch
code or ship a release.  It captures:

* Project geography (the dev tree is `D:\Dev\ScripTree\`, not
  `D:\Dev\ScripTree3\` — the V3-era name is historical).
* The **two-tree deploy obligation** — every code change must reach
  both `D:\Dev\ScripTree\` (dev) AND `R:\ScripTree\` (Dropbox-synced
  runtime).
* The `pyproject.toml`-is-easy-to-forget rule.
* The librarian hand-off at session end (dispatched via
  `general-purpose` since the librarian agent type isn't surfaced
  top-level).
* The pattern catalog (event-filter-per-menu, debounce-on-app,
  two-prong sidecar match, polymorphic dispatch, etc.).
* Commit-message format + the never-commit list (`scriptree.ini`,
  `scriptree/resources/concepts/`, SolidWorks tools, etc.).

## Other project-local agents available

| Agent | When to invoke |
|---|---|
| `librarian` | End of substantive session, "capture lessons" / "what do we know about X?".  Dispatched via the general-purpose agent (it isn't surfaced as a top-level subagent type). |

## Standing rules from the global CLAUDE.md that apply here

Read `C:\Users\Ken\.claude\CLAUDE.md` at session start for the
cross-project rules.  Particularly relevant to ScripTree:

* **Documentation-first** — the docs ARE the logic.  Verbose
  comments + worked examples + reconstruction-from-docs as the bar.
* **SolidWorks tools never publish** — never include
  `SolidWorksTools/`, `sw_bridge`, `.csx` templates in any commit
  that could reach a public release.
* **combridge mirroring** — every combridge rebuild must deploy to
  BOTH `D:\Dev\ScripTree\lib\combridge\` AND `R:\ScripTree\lib\
  combridge\` via `lib/install_combridge.sh`.
* **Personal RAG check FIRST** — grep `C:\personal_rag\` and
  `D:\dev\rag\` for any cross-cutting tool concern (SolidWorks API,
  Claude Code internals, Docker, etc.) before writing code.

## File-format reference

Catalog format specs live at `D:\Dev\ScripTree\docs\LLM\`:

* `category_authoring.md` — **read first for organizing**: the `category`
  taxonomy (where a tool/tree belongs), the on-disk folder convention that
  mirrors it, the folder-vs-loose rule, and the recommended JSON **field
  order** (category near the top, the form/`nodes` dead last).
* `scriptree_format.md` — single-tool `.scriptree`.
* `scriptreetree_format.md` — tree-of-tools `.scriptreetree`.
* `scriptreering_format.md` — cell layout `.scriptreering`.
* `scriptreeforest_format.md` — forest workspace `.scriptreeforest`.
* `param_types_widgets.md` — param types + widget names.
* `argument_template.md` — argv template syntax.
* `architecture.md` — implementation architecture for AI maintainers.

For tool authoring guidance — point any LLM at
`D:\Dev\ScripTree\docs\LLM\` and it has everything needed to
generate valid catalog files from a plain-English description.
