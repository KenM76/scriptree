# ScripTree — LLM documentation

This folder is for AI agents that need to work on the ScripTree codebase
or generate `.scriptree` / `.scriptreetree` files programmatically.
It is intentionally denser than the human-facing docs: less handholding,
more schema, more invariants.

If you are a human reader, start at [`../README.md`](../README.md) instead.

## Orientation

- [`architecture.md`](architecture.md) — package layout, the `core` vs
  `ui` split, the cross-platform seam, the hot-loops you should not
  cross.
- [`scriptree_format.md`](scriptree_format.md) — full JSON schema for
  `.scriptree` files, field by field, with every invariant the loader
  enforces.
- [`scriptreetree_format.md`](scriptreetree_format.md) — tree launcher
  format, path resolution rules.
- [`configurations_sidecar.md`](configurations_sidecar.md) — the sidecar
  JSON format (`<name>.scriptree.configs.json`), including env/PATH
  override fields, UI visibility, hidden parameters, credential prompt,
  tree-level configurations, and the reserved `safetree` config.
- [`argument_template.md`](argument_template.md) — the substitution
  grammar that powers `build_full_argv`, with a reference implementation
  sketch and all the edge cases the tests pin down.
- [`param_types_widgets.md`](param_types_widgets.md) — the type × widget
  matrix, allowed combinations, default values per type, coercion rules.
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

## When generating `.scriptree` files from scratch

- Always set `schema_version` to the current value (check `core/io.py`).
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
