# Argument template grammar

The `argument_template` field on a `ToolDef` drives argv generation.
`core.runner.build_full_argv` is the canonical implementation; this
document describes the grammar it implements.

## Template shape

`argument_template` is a `list[str]`. Each string is a **line** (for
historical reasons — the editor shows one per row). A line contains one
or more **tokens** separated by whitespace. Tokens on the same line
form a **group**: they emit together or not at all.

```python
argument_template = [
    "list-components",      # 1 line, 1 token — a literal
    "{title}",              # 1 line, 1 token — a placeholder
    "/S {system}",          # 1 line, 2 tokens — a group
    "{verbose?--verbose}",  # conditional flag
    "{out?--out=}",         # conditional flag-with-value
]
```

## Token forms

### 1. Literal

```
list-components
```

Emitted as-is. Never quoted, never conditional. Used for subcommand
names and fixed flags.

### 2. Plain placeholder

```
{param_id}
```

Substituted with the string form of `values[param_id]`. If the value is
empty (`""`, `None`, or missing), the token is **dropped entirely** —
and if it's part of a multi-token group, the whole group drops.

### 3. Conditional flag (bool)

```
{param_id?--flag}
```

For a `bool` param. Emits `--flag` when the value is truthy; emits
nothing when false. Never quoted.

### 4. Conditional flag-value

```
{param_id?--flag=}
{param_id?/FLAG:}
```

Emits `--flag=<value>` (or `/FLAG:<value>`) as a **single argv token**
when the value is non-empty. Emits nothing when empty. The trailing
separator can be `=` (Unix style) or `:` (Windows style).

Use this form for options that accept inline values. For space-separated
flag-value pairs, use a group instead:

```
--flag {param_id}
```

### 5. Multiselect expansion

For a `multiselect` param whose value is a list like `["a", "b", "c"]`:

- `{param_id}` emits each value as a separate argv token.
- `{param_id?--tag}` emits `--tag` once if the list is non-empty.
- `{param_id?--tag=}` emits `--tag=a --tag=b --tag=c`.
- `--tag {param_id}` emits `--tag a --tag b --tag c` (the group repeats
  for each list element).

## Group semantics

Tokens on the same line form a group. The group emits **only if every
placeholder in the group has a non-empty value** (or is a literal).

```
/S {system}
```

- If `system == "foo"` → `["/S", "foo"]`.
- If `system == ""` → nothing (the `/S` drops with its value).

Literals-only groups always emit. A group with multiple placeholders
requires all of them to be non-empty.

## Full resolution pipeline

Given a `ToolDef`, a `values` dict, and an `extras` list,
`build_full_argv` does:

1. Start with `[exe]` where `exe = tool.executable`.
2. For each line in `tool.argument_template`:
   a. Tokenize the line on whitespace.
   b. Resolve every token — literal, placeholder, or conditional.
   c. If any required placeholder resolves to empty, drop the group.
   d. Otherwise append all resolved argv tokens from the group.
3. Append `extras` verbatim.
4. Return `ResolvedCommand(argv, cwd, env)` where:
   - `cwd = tool.working_directory or dirname(tool.executable)`.
   - `env = build_env(tool, config_env, config_path_prepend)`.

## Quoting

`build_full_argv` never adds quotes. Every argv element is a separate
list entry, and Popen receives the list directly — no `shell=True`, no
string joining. This means users can type values with spaces, quotes,
or backslashes without any escaping.

The **command preview** string shown in the runner uses a
`shlex.join`-style quoter for display only; the actual argv is always
the unquoted list.

## Validation errors

`build_full_argv` raises `ValueError` when:

- A required param has no value and is referenced as a plain
  placeholder.
- A placeholder references an unknown `param_id`.
- A `{id?--flag}` form is used on a non-bool param.
- A `{id?--flag=}` form is used on a `multiselect` param (use the group
  form instead).

Literal-only templates never fail validation.

## Reference test vectors

(See `tests/test_runner.py` for the authoritative set.)

```python
# Plain placeholder
template = ["echo", "{msg}"]; values = {"msg": "hi"}
→ [exe, "echo", "hi"]

# Bool flag
template = ["{v?--verbose}"]; values = {"v": True}
→ [exe, "--verbose"]
template = ["{v?--verbose}"]; values = {"v": False}
→ [exe]

# Flag-value (inline, Unix =)
template = ["{out?--out=}"]; values = {"out": "x.txt"}
→ [exe, "--out=x.txt"]
template = ["{out?--out=}"]; values = {"out": ""}
→ [exe]

# Flag-value (inline, Windows :)
template = ["{retry?/R:}"]; values = {"retry": "3"}
→ [exe, "/R:3"]
template = ["{retry?/R:}"]; values = {"retry": ""}
→ [exe]

# Flag-value (group)
template = ["--out {out}"]; values = {"out": "x.txt"}
→ [exe, "--out", "x.txt"]
template = ["--out {out}"]; values = {"out": ""}
→ [exe]

# Multiselect
template = ["{tags}"]; values = {"tags": ["a", "b"]}
→ [exe, "a", "b"]
template = ["--tag {tags}"]; values = {"tags": ["a", "b"]}
→ [exe, "--tag", "a", "--tag", "b"]
```
