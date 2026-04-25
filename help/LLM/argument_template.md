# Argument template grammar

The `argument_template` field on a `ToolDef` drives argv generation.
`core.runner.resolve` is the canonical implementation; this document
describes the grammar it implements.

## Template shape

`argument_template` is a `list[Entry]` where each `Entry` is either:

- **A string** — one literal or placeholder token, emitted as a single
  argv element. The exception is the *string-passthrough* rule
  (see below): a bare `"{id}"` referring to a `ParamType.STRING`
  param has its value tokenized like argv text.
- **A list of strings** — a **token group**. The group emits together
  or is dropped together. Use a group whenever a flag and its value
  must appear or disappear as a unit.

```python
argument_template = [
    "list-components",                     # single literal token
    "{title}",                              # single placeholder
    ["--out", "{out}"],                     # GROUP — both or neither
    ["--cmd", "{cmd}"],                     # GROUP — mutually droppable
    "{verbose?--verbose}",                  # conditional bool flag
    "{out?--out=}",                         # conditional inline flag-value
]
```

### ⚠️ Most common authoring mistake

If you write a flag and value as a single string with a space:

```json
"--out {out}"
```

…you get **ONE argv token** that literally looks like `--out C:/path` —
a single argument with an embedded space. Most CLIs reject that as an
unknown flag, because they parse flags by looking for `--xxx` at the
start of each argv element, not by searching for `--xxx` inside one.

Always use a **list (token group)** for flag + value pairs:

```json
["--out", "{out}"]
```

Engine behavior:
- `{out}` non-empty → `["--out", "C:/path"]` (two argv tokens).
- `{out}` empty → whole group dropped, neither token emitted.

This is exactly what you want for **mutually exclusive optional
flag+value pairs** — if the user leaves `{cmd}` blank and fills
`{cmd_file}`, only the latter group emits.

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

Substituted with the string form of `values[param_id]`. If the value
is empty (`""`, `None`, or missing), the token is **dropped entirely**
— and if it's inside a group, the whole group drops.

#### String-passthrough auto-split

When **all** of the following hold, the substituted value is treated
as raw argv text and split into multiple argv elements:

1. The template entry is **exactly** `"{id}"` (the placeholder fills
   the whole token — not embedded in a longer string like
   `"--out={x}"` and not a conditional `{id?--flag}` form).
2. The entry is a plain string, **not inside a token group** (lists
   `["--include", "{id}"]` keep their single-token semantics).
3. The referenced param's `type` is `ParamType.STRING`.
4. The value contains whitespace.

Splitting follows shlex / `CommandLineToArgvW` rules — quoted phrases
are preserved as single tokens. So a `string` param holding
`'--include foo --include bar'` placed at `["{flags}"]` produces:

```python
argv = ["mytool", "--include", "foo", "--include", "bar"]
```

…and `'--name "John Doe"'` produces:

```python
argv = ["mytool", "--name", "John Doe"]
```

This is the supported pattern for **repeatable flags** — the user types
multiple flag occurrences into one text field. Use a `string` param
(any `line_edit` / `text` widget) and place its placeholder as a bare
`"{id}"` token.

**What is NOT auto-split** (each keeps existing single-token semantics):

- `path` / `bool` / `int` / `float` / `enum` params — only `STRING`.
- Embedded placeholders: `"--out={x}"` stays one token even if `x`
  contains spaces. (Quote the value if it has spaces, or use a token
  group.)
- Token groups: `["--include", "{x}"]` emits `["--include", "<x>"]`
  with `<x>` as one argv token regardless of whitespace. (Use a bare
  `"{x}"` instead of the group if you want auto-split.)
- Conditional flags: `"{enabled?--flag value}"` emits the literal
  `"--flag value"` as one argv token when `enabled` is truthy.

If shlex can't parse the value (unclosed quote etc.), the runner
falls back to emitting the raw string as a single argv token rather
than raising — so a half-typed value in the live preview doesn't
blow up the runner.

### 3. Conditional flag (bool)

```
{param_id?--flag}
```

For a `bool` param. Emits `--flag` when the value is truthy; emits
nothing when false. Used as a standalone token, not inside a group.

### 4. Conditional flag-value (inline)

```
{param_id?--flag=}
{param_id?/FLAG:}
```

Emits `--flag=<value>` (or `/FLAG:<value>`) as a **single argv token**
when the value is non-empty. Emits nothing when empty. The trailing
separator character (`=` or `:`) is preserved.

Use this form when the CLI accepts `--flag=value` syntax. For
**space-separated** flag-value pairs (most common), use a token group
instead:

```json
["--flag", "{param_id}"]
```

### 5. Multiselect expansion

For a `multiselect` param whose value is a list like `["a", "b", "c"]`:

- `{param_id}` as a standalone token → emits each value as a separate
  argv token: `["a", "b", "c"]`.
- `{param_id?--tag}` → emits `--tag` once if the list is non-empty.
- `{param_id?--tag=}` → emits `--tag=a --tag=b --tag=c`.
- `["--tag", "{param_id}"]` as a group → the group repeats for each
  element: `--tag a --tag b --tag c`.

## Group semantics

A list entry is a group. Inside the group, every token is resolved
in order. If any token resolves to "drop" (empty placeholder), the
**entire group is dropped**. Otherwise all resolved tokens are
appended to argv in order.

```json
["--out", "{out}"]
```

- `out == "x.txt"` → argv gets `--out`, `x.txt`.
- `out == ""` → nothing emitted.

Groups can contain multiple placeholders; all must be non-empty for
the group to emit. Pure-literal groups always emit.

## Full resolution pipeline

Given a `ToolDef`, a `values` dict, and an `extras` list, `resolve`
does:

1. Start with `[exe]` where `exe = tool.executable`.
2. For each entry in `tool.argument_template`:
   - **List entry (group):** resolve each inner token. If any returns
     drop, discard the group; otherwise append all tokens to argv.
   - **String entry (single token):** resolve it. If it returns drop,
     skip it; otherwise append one token to argv.
3. `build_full_argv` additionally appends `extras` verbatim.
4. Return `ResolvedCommand(argv, cwd, env)` where:
   - `cwd = tool.working_directory or dirname(tool.executable)`.
   - `env = build_env(tool, config_env, config_path_prepend, ...)`.

## Quoting

`resolve` never adds quotes. Every argv element is a separate list
entry, and `Popen` receives the list directly — no `shell=True`, no
string joining. Users can type values with spaces, quotes, or
backslashes without any escaping.

The **command preview** string shown in the runner uses platform-aware
quoting for display only (`subprocess.list2cmdline` on Windows,
`shlex.quote` on POSIX); the actual argv is always the unquoted list.

## Validation errors

`resolve` raises `RunnerError` when:

- A required param has no value and is referenced as a plain
  placeholder.
- A placeholder references an unknown `param_id`.
- A conditional form is malformed (embedded in a larger token,
  references a missing param).

Non-required params and conditional flags never trigger validation —
they just drop silently when empty.

## Reference test vectors

(See `tests/test_runner.py` for the authoritative set.)

```python
# Literal + placeholder, flat
template = ["echo", "{msg}"]; values = {"msg": "hi"}
→ [exe, "echo", "hi"]

# Bool flag
template = ["{v?--verbose}"]; values = {"v": True}
→ [exe, "--verbose"]
template = ["{v?--verbose}"]; values = {"v": False}
→ [exe]

# Inline flag-value (Unix =)
template = ["{out?--out=}"]; values = {"out": "x.txt"}
→ [exe, "--out=x.txt"]

# Inline flag-value (Windows :)
template = ["{retry?/R:}"]; values = {"retry": "3"}
→ [exe, "/R:3"]

# Token group (RECOMMENDED for flag + value)
template = [["--out", "{out}"]]; values = {"out": "x.txt"}
→ [exe, "--out", "x.txt"]
template = [["--out", "{out}"]]; values = {"out": ""}
→ [exe]   # whole group dropped

# Mutually-exclusive optional flag+value pairs
template = [["--cmd", "{cmd}"], ["--cmd-file", "{cmd_file}"]]
values = {"cmd": "python x.py", "cmd_file": ""}
→ [exe, "--cmd", "python x.py"]   # only the non-empty group emits

# Multiselect as a repeating group
template = [["--tag", "{tags}"]]; values = {"tags": ["a", "b"]}
→ [exe, "--tag", "a", "--tag", "b"]
```

## Authoring checklist for LLMs generating `.scriptree` files

When you build an `argument_template`, ask:

- **Is this a flag that takes a value (like `--out FILE`)?**
  Use a token group: `["--out", "{file}"]`. Not `"--out {file}"` as
  one string (that becomes a single argv token with a space inside).

- **Is this an optional flag+value pair that should drop if empty?**
  Still a token group. The group drops together when the placeholder
  is empty.

- **Are two optional flags mutually exclusive from the user's POV
  (user fills one or the other)?**
  Use two separate token groups. The engine emits only the non-empty
  one. (ScripTree itself doesn't enforce mutual exclusion — the
  child process does. But the template won't emit both if only one
  value is provided.)

- **Does the CLI accept `--flag=value` inline syntax?**
  You can use `"{id?--flag=}"` as a single token to emit
  `--flag=value` when non-empty, dropped when empty.

- **Is this a standalone boolean toggle?**
  Use `"{id?--flag}"` on a bool param.

- **Is this a required positional argument?**
  Use a bare `"{id}"` — it's a single token; required validation
  catches empty values before argv is built.
