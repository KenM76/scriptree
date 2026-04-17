"""Argv template substitution and subprocess spawn.

Pure Python, no Qt. The UI layer wires the subprocess stdout/stderr
streams into an output pane, but the business logic lives here so it
can be unit-tested headlessly.

## Template syntax

Each entry in ``ToolDef.argument_template`` is either:

  "literal"               — emitted as-is
  "{param_id}"            — substituted with the value of that param
  "prefix{param_id}"      — substitution inside a larger token
  "{param_id?--flag}"     — conditional: only emitted (as "--flag") when
                            the referenced bool param is true; dropped
                            otherwise. Must be a standalone token.
  "{param_id?--flag=}"    — conditional flag with value: emitted as
                            ``--flag=<value>`` when the param is truthy

Bools in non-conditional substitution are emitted as "true" / "false".

Empty substitutions (optional non-required params left blank) cause the
whole token to be dropped — so you can write ``--name={name}`` and it'll
either emit ``--name=foo`` or nothing at all.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .model import ParamDef, ParamType, ToolDef


class RunnerError(Exception):
    """Raised when the template can't be resolved (validation error)."""


@dataclass
class ResolvedCommand:
    """Result of resolving a template against a set of values.

    `argv[0]` is the executable; the rest are the arguments. Suitable
    for ``subprocess.Popen(argv, shell=False)``.

    ``env`` holds the full environment block to pass to ``Popen`` — or
    ``None`` if the child should just inherit the parent's environment
    unchanged. Callers use :func:`build_env` to construct it from
    ``ToolDef.env`` + per-configuration overrides.
    """

    argv: list[str]
    cwd: str | None
    env: dict[str, str] | None = None

    def display(self) -> str:
        """Human-readable shell-style representation for the live preview.

        Not safe for actual shell execution — the real spawn uses argv.
        """
        if not self.argv:
            return ""
        return " ".join(shlex.quote(a) for a in self.argv)


_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(\?[^}]*)?\}")


def resolve(
    tool: ToolDef,
    values: dict[str, Any],
    *,
    ignore_required: bool = False,
) -> ResolvedCommand:
    """Turn a ToolDef + values into a ResolvedCommand.

    ``ignore_required`` is used by the live preview so that required
    params left blank still produce a best-effort preview instead of
    raising.
    """
    if not tool.executable:
        raise RunnerError("Tool has no executable.")

    param_map = {p.id: p for p in tool.params}
    errors: list[str] = []

    # Required-value check (skipped for preview).
    if not ignore_required:
        for p in tool.params:
            if p.required and _is_empty(values.get(p.id)):
                errors.append(f"Required parameter {p.label!r} is empty.")
        if errors:
            raise RunnerError("\n".join(errors))

    argv: list[str] = [tool.executable]
    for entry in tool.argument_template:
        if isinstance(entry, list):
            # Token group: resolve each inner token; if ANY comes back
            # as None (dropped), drop the entire group. Otherwise emit
            # all tokens in order. This is how "/S system" style Windows
            # flags work — both tokens appear together or not at all.
            resolved_group: list[str] = []
            drop_group = False
            for inner in entry:
                piece = _resolve_token(inner, param_map, values)
                if piece is None:
                    drop_group = True
                    break
                resolved_group.append(piece)
            if not drop_group:
                argv.extend(resolved_group)
        else:
            emitted = _resolve_token(entry, param_map, values)
            if emitted is None:
                continue
            argv.append(emitted)

    cwd = tool.working_directory
    if not cwd:
        # Default to the executable's directory so tools that read
        # config files relative to their own location still work.
        exe_parent = Path(tool.executable).parent
        cwd = str(exe_parent) if exe_parent.as_posix() else None

    return ResolvedCommand(argv=argv, cwd=cwd)


def _resolve_token(
    token: str,
    param_map: dict[str, ParamDef],
    values: dict[str, Any],
) -> str | None:
    """Return the resolved token, or None to drop it from argv."""
    # Fast path: no placeholders.
    if "{" not in token:
        return token

    # Look for a standalone conditional flag: "{id?--flag}" or "{id?--flag=}"
    m = _PLACEHOLDER_RE.fullmatch(token)
    if m and m.group(2):
        return _resolve_conditional(m, param_map, values)

    # Otherwise do substring substitution; if any referenced param has
    # an empty value, drop the entire token (standard "optional flag"
    # idiom: --name={name} disappears when name is blank).
    any_empty = False

    def sub(match: re.Match[str]) -> str:
        nonlocal any_empty
        name = match.group(1)
        cond = match.group(2)
        if cond:
            raise RunnerError(
                f"Conditional placeholder {{{name}?...}} must be a "
                f"standalone token, not embedded in {token!r}."
            )
        if name not in param_map:
            raise RunnerError(f"Template references unknown parameter {{{name}}}.")
        val = values.get(name, param_map[name].default)
        s = _value_to_str(val, param_map[name])
        if s == "":
            any_empty = True
        return s

    resolved = _PLACEHOLDER_RE.sub(sub, token)
    if any_empty:
        return None
    return resolved


def _resolve_conditional(
    match: re.Match[str],
    param_map: dict[str, ParamDef],
    values: dict[str, Any],
) -> str | None:
    name = match.group(1)
    # group(2) is "?..." — strip the leading "?"
    flag = match.group(2)[1:]
    if name not in param_map:
        raise RunnerError(f"Template references unknown parameter {{{name}}}.")

    param = param_map[name]
    val = values.get(name, param.default)

    if param.type is ParamType.BOOL:
        return flag if _is_truthy(val) else None

    # For non-bool params, "?--flag=" means "emit --flag=<value>" when
    # the value is non-empty, else drop. The trailing separator can be
    # "=" (Unix style: --flag=value) or ":" (Windows style: /FLAG:value)
    # or any character — whatever the flag ends with is kept as the glue.
    if _is_empty(val):
        return None
    value_str = _value_to_str(val, param)
    if flag.endswith(("=", ":")):
        return f"{flag}{value_str}"
    return flag  # plain conditional — emit the flag, ignore the value


def _value_to_str(val: Any, param: ParamDef) -> str:
    if val is None:
        return ""
    if param.type is ParamType.BOOL:
        return "true" if _is_truthy(val) else "false"
    if isinstance(val, (list, tuple)):
        return ",".join(str(x) for x in val)
    return str(val)


def _is_empty(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, str):
        return val == ""
    if isinstance(val, (list, tuple, dict)):
        return len(val) == 0
    return False


def _is_truthy(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes", "on")
    return bool(val)


# --- subprocess execution -------------------------------------------------

@dataclass
class RunResult:
    exit_code: int
    duration_seconds: float


def build_env(
    tool: ToolDef,
    config_env: dict[str, str] | None = None,
    config_path_prepend: list[str] | None = None,
    *,
    base_env: dict[str, str] | None = None,
    global_env: dict[str, str] | None = None,
    global_env_overrides: bool = False,
    global_path_prepend: list[str] | None = None,
    global_path_overrides: bool = False,
) -> dict[str, str] | None:
    """Merge environment overrides into an effective child environment.

    Default layering order (highest priority last)::

        base_env (os.environ by default)
        global_env (application Settings)
        tool.env
        config_env

    When ``global_env_overrides`` is True, the global env moves to
    highest priority::

        base_env
        tool.env
        config_env
        global_env              ← overrides everything

    ``path_prepend`` entries from the tool and the configuration are
    concatenated (tool first, config second) and prepended to the
    resulting ``PATH``. Relative directories are resolved against the
    tool's ``working_directory`` if one is set, else the executable's
    directory.

    Returns ``None`` when there's nothing to override — the caller can
    then pass ``env=None`` to ``Popen`` and inherit the parent env
    verbatim, which is what we want for the common "no custom env"
    case (it keeps error messages + debuggers readable).
    """
    tool_env = dict(tool.env or {})
    cfg_env = dict(config_env or {})
    g_env = dict(global_env or {})
    tool_paths = list(tool.path_prepend or [])
    cfg_paths = list(config_path_prepend or [])
    g_paths = list(global_path_prepend or [])

    if (not tool_env and not cfg_env and not tool_paths
            and not cfg_paths and not g_env and not g_paths):
        return None

    env = dict(base_env if base_env is not None else os.environ)
    if not global_env_overrides:
        # Normal order: os → global → tool → config
        env.update(g_env)
        env.update(tool_env)
        env.update(cfg_env)
    else:
        # Override order: os → tool → config → global
        env.update(tool_env)
        env.update(cfg_env)
        env.update(g_env)

    # PATH prepend: resolve relative dirs against tool.working_directory
    # (else the exe directory) so paths in the sidecar can be written
    # as "./bin" or "vendor" and still behave sanely.
    anchor: Path | None = None
    if tool.working_directory:
        anchor = Path(tool.working_directory)
    elif tool.executable:
        parent = Path(tool.executable).parent
        if parent.as_posix():
            anchor = parent

    def _resolve(d: str) -> str:
        p = Path(d)
        if p.is_absolute() or anchor is None:
            return str(p)
        return str((anchor / p).resolve(strict=False))

    # Assemble the PATH prepend list. Default order (earliest = highest
    # search priority):
    #   [config_paths, tool_paths, global_paths, <original PATH>]
    #
    # When global_path_overrides is True, global goes first:
    #   [global_paths, config_paths, tool_paths, <original PATH>]
    tool_and_cfg = [_resolve(d) for d in (tool_paths + cfg_paths)]
    global_resolved = [_resolve(d) for d in g_paths]

    if global_path_overrides:
        prepend = global_resolved + tool_and_cfg
    else:
        prepend = tool_and_cfg + global_resolved

    if prepend:
        current = env.get("PATH", "")
        env["PATH"] = os.pathsep.join([*prepend, current]) if current else os.pathsep.join(prepend)

    return env


def spawn_streaming(
    cmd: ResolvedCommand,
    on_stdout_line: Callable[[str], None],
    on_stderr_line: Callable[[str], None],
    *,
    on_start: Callable[[subprocess.Popen], None] | None = None,
) -> RunResult:
    """Run the command, streaming stdout/stderr line-by-line to callbacks.

    Blocking — call from a worker thread in the UI. Returns on process
    exit. Uses unbuffered line reading so output appears live.

    ``on_start``, if given, is called synchronously with the freshly
    spawned :class:`subprocess.Popen` object before stream reading
    begins. The UI layer uses this to stash the handle so a Stop
    button can call :meth:`Popen.terminate`/:meth:`Popen.kill` from
    the GUI thread without racing the pump threads.
    """
    import time

    start = time.monotonic()
    proc = subprocess.Popen(
        cmd.argv,
        cwd=cmd.cwd,
        env=cmd.env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,  # line-buffered
    )
    if on_start is not None:
        on_start(proc)

    # Read stdout in this thread and stderr in a helper thread so we
    # don't block on one stream while the other has data.
    import threading

    def _pump(stream: Iterable[str], cb: Callable[[str], None]) -> None:
        for line in stream:
            cb(line.rstrip("\r\n"))

    stderr_thread = threading.Thread(
        target=_pump, args=(proc.stderr, on_stderr_line), daemon=True
    )
    stderr_thread.start()
    _pump(proc.stdout, on_stdout_line)  # type: ignore[arg-type]
    proc.wait()
    stderr_thread.join(timeout=1.0)

    return RunResult(
        exit_code=proc.returncode,
        duration_seconds=time.monotonic() - start,
    )


def spawn_streaming_as_user(
    cmd: ResolvedCommand,
    username: str,
    password: str,
    domain: str,
    on_stdout_line: Callable[[str], None],
    on_stderr_line: Callable[[str], None],
    *,
    on_start: Callable[[subprocess.Popen], None] | None = None,
) -> RunResult:
    """Run the command under a different user via CreateProcessWithLogonW.

    Windows-only. Falls back to ``spawn_streaming`` on other platforms
    (ignoring the credentials — a warning is emitted on stderr).

    The implementation uses ``ctypes`` to call
    ``advapi32.CreateProcessWithLogonW`` directly, passing pipe handles
    for stdout/stderr so output is captured exactly like the regular
    ``spawn_streaming`` path.
    """
    import sys

    if sys.platform != "win32":
        on_stderr_line("[warning] Run-as-user is only supported on Windows.")
        return spawn_streaming(cmd, on_stdout_line, on_stderr_line, on_start=on_start)

    import ctypes
    import ctypes.wintypes as wt
    import time
    import threading
    import msvcrt

    kernel32 = ctypes.windll.kernel32
    advapi32 = ctypes.windll.advapi32

    LOGON_WITH_PROFILE = 0x00000001
    CREATE_NO_WINDOW = 0x08000000
    STARTF_USESTDHANDLES = 0x00000100
    HANDLE_FLAG_INHERIT = 0x00000001
    INFINITE = 0xFFFFFFFF

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wt.DWORD),
            ("lpReserved", wt.LPWSTR),
            ("lpDesktop", wt.LPWSTR),
            ("lpTitle", wt.LPWSTR),
            ("dwX", wt.DWORD), ("dwY", wt.DWORD),
            ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
            ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD),
            ("dwFillAttribute", wt.DWORD),
            ("dwFlags", wt.DWORD),
            ("wShowWindow", wt.WORD),
            ("cbReserved2", wt.WORD),
            ("lpReserved2", ctypes.c_void_p),
            ("hStdInput", wt.HANDLE),
            ("hStdOutput", wt.HANDLE),
            ("hStdError", wt.HANDLE),
        ]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wt.HANDLE),
            ("hThread", wt.HANDLE),
            ("dwProcessId", wt.DWORD),
            ("dwThreadId", wt.DWORD),
        ]

    class SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("nLength", wt.DWORD),
            ("lpSecurityDescriptor", ctypes.c_void_p),
            ("bInheritHandle", wt.BOOL),
        ]

    # Create inheritable pipes for stdout and stderr.
    sa = SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(sa)
    sa.bInheritHandle = True
    sa.lpSecurityDescriptor = None

    stdout_read = wt.HANDLE()
    stdout_write = wt.HANDLE()
    stderr_read = wt.HANDLE()
    stderr_write = wt.HANDLE()

    if not kernel32.CreatePipe(
        ctypes.byref(stdout_read), ctypes.byref(stdout_write),
        ctypes.byref(sa), 0,
    ):
        raise RunnerError(f"CreatePipe(stdout) failed: {ctypes.GetLastError()}")
    if not kernel32.CreatePipe(
        ctypes.byref(stderr_read), ctypes.byref(stderr_write),
        ctypes.byref(sa), 0,
    ):
        kernel32.CloseHandle(stdout_read)
        kernel32.CloseHandle(stdout_write)
        raise RunnerError(f"CreatePipe(stderr) failed: {ctypes.GetLastError()}")

    # Read ends should NOT be inherited by the child.
    kernel32.SetHandleInformation(stdout_read, HANDLE_FLAG_INHERIT, 0)
    kernel32.SetHandleInformation(stderr_read, HANDLE_FLAG_INHERIT, 0)

    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.dwFlags = STARTF_USESTDHANDLES
    si.hStdOutput = stdout_write
    si.hStdError = stderr_write
    # Use NUL for stdin so the child doesn't hang waiting for input.
    si.hStdInput = kernel32.CreateFileW(
        "NUL", 0x80000000, 1, ctypes.byref(sa), 3, 0, None  # GENERIC_READ, OPEN_EXISTING
    )

    pi = PROCESS_INFORMATION()

    # Build command line string.
    cmd_line = " ".join(
        f'"{a}"' if " " in a or '"' in a else a for a in cmd.argv
    )

    # Build environment block (null-terminated key=val pairs, double-null end).
    env_block = None
    if cmd.env is not None:
        parts = [f"{k}={v}" for k, v in cmd.env.items()]
        env_str = "\0".join(parts) + "\0\0"
        env_block = ctypes.create_unicode_buffer(env_str)

    start = time.monotonic()

    # Security: use a ctypes buffer for the password so it can be
    # zeroed after the call. Python strings are immutable and may
    # persist in the string intern pool; a mutable buffer avoids this.
    pw_buf = ctypes.create_unicode_buffer(password)

    ok = advapi32.CreateProcessWithLogonW(
        username,           # lpUsername
        domain or None,     # lpDomain (None = local)
        pw_buf,             # lpPassword (mutable buffer, zeroed below)
        LOGON_WITH_PROFILE, # dwLogonFlags
        None,               # lpApplicationName
        cmd_line,           # lpCommandLine
        CREATE_NO_WINDOW,   # dwCreationFlags
        ctypes.byref(env_block) if env_block else None,
        cmd.cwd,            # lpCurrentDirectory
        ctypes.byref(si),
        ctypes.byref(pi),
    )

    # Zero the password buffer immediately after the API call.
    for i in range(len(pw_buf)):
        pw_buf[i] = '\x00'

    # Close the write ends of the pipes in the parent — the child has
    # its own copies via handle inheritance.
    kernel32.CloseHandle(stdout_write)
    kernel32.CloseHandle(stderr_write)
    kernel32.CloseHandle(si.hStdInput)

    if not ok:
        err = ctypes.GetLastError()
        kernel32.CloseHandle(stdout_read)
        kernel32.CloseHandle(stderr_read)
        raise RunnerError(
            f"CreateProcessWithLogonW failed (error {err}). "
            "Check that the username and password are correct."
        )

    kernel32.CloseHandle(pi.hThread)

    # Wrap the pipe read handles as Python file objects.
    stdout_fd = msvcrt.open_osfhandle(stdout_read.value, os.O_RDONLY)
    stderr_fd = msvcrt.open_osfhandle(stderr_read.value, os.O_RDONLY)
    stdout_file = os.fdopen(stdout_fd, "r", encoding="utf-8", errors="replace")
    stderr_file = os.fdopen(stderr_fd, "r", encoding="utf-8", errors="replace")

    # Notify caller with a lightweight Popen-like wrapper for Stop.
    class _ProcProxy:
        """Minimal Popen-like wrapper for the Stop button."""
        def __init__(self, hProcess: int, pid: int):
            self._hProcess = hProcess
            self.pid = pid
            self.returncode: int | None = None
        def poll(self) -> int | None:
            ret = wt.DWORD()
            if kernel32.GetExitCodeProcess(self._hProcess, ctypes.byref(ret)):
                if ret.value != 259:  # STILL_ACTIVE
                    self.returncode = ret.value
                    return ret.value
            return None
        def terminate(self) -> None:
            kernel32.TerminateProcess(self._hProcess, 1)
        def kill(self) -> None:
            kernel32.TerminateProcess(self._hProcess, 1)

    proxy = _ProcProxy(pi.hProcess, pi.dwProcessId)
    if on_start is not None:
        on_start(proxy)  # type: ignore[arg-type]

    # Pump streams.
    def _pump(stream, cb: Callable[[str], None]) -> None:
        try:
            for line in stream:
                cb(line.rstrip("\r\n"))
        except (OSError, ValueError):
            pass

    stderr_thread = threading.Thread(
        target=_pump, args=(stderr_file, on_stderr_line), daemon=True
    )
    stderr_thread.start()
    _pump(stdout_file, on_stdout_line)

    # Wait for the process to exit.
    kernel32.WaitForSingleObject(pi.hProcess, INFINITE)
    ret = wt.DWORD()
    kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(ret))
    exit_code = ret.value

    stderr_thread.join(timeout=2.0)
    kernel32.CloseHandle(pi.hProcess)

    return RunResult(
        exit_code=exit_code,
        duration_seconds=time.monotonic() - start,
    )


# --- reverse direction: parse an edited argv back into widget values ------

@dataclass
class ReconcileResult:
    """Outcome of ``reconcile_edit``.

    - ``values`` is a dict of ``{param_id: value}`` with any updates
      the user's edit implies. Only IDs that the reconciler could
      identify are present — unchanged widgets stay in the caller's
      starting dict.
    - ``extras`` is a list of argv tokens that didn't match any
      template entry. These persist as user-added extras and are
      appended to the resolved argv at run time.
    - ``ok`` is False when the edited text couldn't be shlex-parsed
      (e.g. an unclosed quote). In that case ``values`` and
      ``extras`` are the caller's starting state — apply nothing.
    """

    values: dict[str, Any]
    extras: list[str]
    ok: bool


_BARE_PLACEHOLDER = re.compile(r"^\{(\w+)\}$")
_CONDITIONAL_PLACEHOLDER = re.compile(r"^\{(\w+)\?([^}]+)\}$")
_EMBEDDED_PLACEHOLDER = re.compile(r"^([^{]*)\{(\w+)\}([^{]*)$")
_FLAG_LOOKING = re.compile(r"^(?:--?[A-Za-z]|/[A-Za-z])")


def reconcile_edit(
    tool: ToolDef,
    edited_text: str,
    current_values: dict[str, Any],
) -> ReconcileResult:
    """Parse an edited command line and reconcile it against ``tool``.

    The strategy is two passes:

    Pass 1 — **flag-bearing entries** (position-independent):
      - Token groups like ``["/S", "{system}"]`` are matched by
        searching argv for the flag literal and then claiming the
        following tokens as the referenced placeholders.
      - Conditional bool flags ``{name?/FLAG}`` are set True when
        ``FLAG`` is present in argv and False when it's absent.
      - Conditional flag-value forms ``{name?--name=}`` match any
        token starting with the prefix and extract the tail.

    Pass 2 — **ordered entries** (literals and bare positionals):
      Walk remaining unconsumed tokens in order. Literals advance
      when they match the current token, otherwise they skip the
      template entry (the user may have deleted them). Bare
      positionals ``{name}`` refuse to consume flag-looking tokens
      (``-x``, ``--foo``, ``/X``) — that skips the template entry
      instead so a deleted positional doesn't cause the next flag
      to be mis-claimed.

    Leftover tokens become extras. See the class docstring for
    the return shape.
    """
    import shlex

    try:
        tokens = shlex.split(edited_text, posix=True)
    except ValueError:
        return ReconcileResult(
            values=dict(current_values),
            extras=[],
            ok=False,
        )

    # Drop the executable token — we always reconstruct it from
    # ``tool.executable`` at render time, so the user can't change
    # which program runs by editing the preview.
    if tokens:
        tokens = tokens[1:]

    consumed = [False] * len(tokens)
    new_values = dict(current_values)

    # Classify template entries into flag (pass 1) vs ordered (pass 2).
    flag_entries: list[tuple[str, Any]] = []
    ordered_entries: list[tuple[str, Any]] = []

    for entry in tool.argument_template:
        if isinstance(entry, list):
            # A token group. If the first element is a literal flag
            # and subsequent elements are bare placeholders, treat it
            # as a position-independent flag group. Otherwise fall
            # through to ordered handling.
            if len(entry) >= 2 and "{" not in entry[0]:
                flag_entries.append(("group", entry))
                continue
            ordered_entries.append(("group_ordered", entry))
            continue
        # Entry is a string.
        m_cond = _CONDITIONAL_PLACEHOLDER.match(entry)
        if m_cond:
            pid = m_cond.group(1)
            flag_val = m_cond.group(2)
            if flag_val.endswith("="):
                flag_entries.append(("cond_eq", (pid, flag_val)))
            else:
                flag_entries.append(("cond_bool", (pid, flag_val)))
            continue
        if _BARE_PLACEHOLDER.match(entry):
            pid = entry[1:-1]
            ordered_entries.append(("positional", pid))
            continue
        # Literal or embedded substitution.
        ordered_entries.append(("literal_or_embedded", entry))

    # --- Pass 1: flag entries --------------------------------------------

    for kind, data in flag_entries:
        if kind == "group":
            entry = data
            flag = entry[0]
            needed = len(entry) - 1
            for i, t in enumerate(tokens):
                if consumed[i] or t != flag:
                    continue
                slot_start = i + 1
                if slot_start + needed > len(tokens):
                    break
                slots = list(range(slot_start, slot_start + needed))
                if any(consumed[j] for j in slots):
                    break
                ok = True
                updates: list[tuple[str, str]] = []
                for j, placeholder in zip(slots, entry[1:]):
                    m = _BARE_PLACEHOLDER.match(placeholder)
                    if not m:
                        ok = False
                        break
                    updates.append((m.group(1), tokens[j]))
                if not ok:
                    break
                consumed[i] = True
                for j in slots:
                    consumed[j] = True
                for pid, val in updates:
                    new_values[pid] = val
                break
        elif kind == "cond_bool":
            pid, flag = data
            found = False
            for i, t in enumerate(tokens):
                if consumed[i]:
                    continue
                if t == flag:
                    new_values[pid] = True
                    consumed[i] = True
                    found = True
                    break
            if not found:
                new_values[pid] = False
        elif kind == "cond_eq":
            pid, flag_prefix = data
            found = False
            for i, t in enumerate(tokens):
                if consumed[i]:
                    continue
                if t.startswith(flag_prefix):
                    new_values[pid] = t[len(flag_prefix):]
                    consumed[i] = True
                    found = True
                    break
            if not found:
                new_values[pid] = ""

    # --- Pass 2: ordered entries -----------------------------------------

    remaining_idx = [i for i in range(len(tokens)) if not consumed[i]]
    cursor = 0
    for kind, data in ordered_entries:
        if cursor >= len(remaining_idx):
            break
        tok_idx = remaining_idx[cursor]
        tok = tokens[tok_idx]

        if kind == "literal_or_embedded":
            if "{" not in data:
                # Plain literal: match exact, else skip template entry.
                if tok == data:
                    consumed[tok_idx] = True
                    cursor += 1
                continue
            # Embedded substitution like "--output={file}" or '"{string}"'.
            m = _EMBEDDED_PLACEHOLDER.match(data)
            if not m:
                continue
            prefix, pid, suffix = m.group(1), m.group(2), m.group(3)
            if tok.startswith(prefix) and (not suffix or tok.endswith(suffix)):
                end = len(tok) - len(suffix) if suffix else len(tok)
                new_values[pid] = tok[len(prefix):end]
                consumed[tok_idx] = True
                cursor += 1
                continue
            # shlex strips outer quotes on parse, so an embedded
            # template like ``"{name}"`` matches any non-flag token
            # as a fallback — the user's ``"hello"`` becomes the
            # shlex token ``hello`` which we then assign to ``name``.
            if prefix == '"' and suffix == '"' and not _FLAG_LOOKING.match(tok):
                new_values[pid] = tok
                consumed[tok_idx] = True
                cursor += 1
            continue

        if kind == "positional":
            pid = data
            # Don't eat a flag-looking token as a positional — that
            # would usually be wrong. Skip this template entry and
            # try the next one against the same token.
            if _FLAG_LOOKING.match(tok):
                continue
            new_values[pid] = tok
            consumed[tok_idx] = True
            cursor += 1
            continue

        if kind == "group_ordered":
            # Fallback for groups whose first element isn't a plain
            # literal flag — treat the whole group sequentially.
            entry = data
            ok = True
            start = tok_idx
            for k, part in enumerate(entry):
                if cursor + k >= len(remaining_idx):
                    ok = False
                    break
                tok_k = tokens[remaining_idx[cursor + k]]
                if "{" in part:
                    m = _BARE_PLACEHOLDER.match(part)
                    if not m:
                        ok = False
                        break
                    new_values[m.group(1)] = tok_k
                elif tok_k != part:
                    ok = False
                    break
            if ok:
                for k in range(len(entry)):
                    consumed[remaining_idx[cursor + k]] = True
                cursor += len(entry)
            continue

    extras = [t for i, t in enumerate(tokens) if not consumed[i]]
    return ReconcileResult(values=new_values, extras=extras, ok=True)


def build_full_argv(
    tool: ToolDef,
    values: dict[str, Any],
    extras: list[str],
    *,
    ignore_required: bool = False,
    config_env: dict[str, str] | None = None,
    config_path_prepend: list[str] | None = None,
    global_env: dict[str, str] | None = None,
    global_env_overrides: bool = False,
    global_path_prepend: list[str] | None = None,
    global_path_overrides: bool = False,
) -> ResolvedCommand:
    """Resolve ``tool`` and append user-added extras.

    Thin wrapper used by both the UI's live preview and the run path
    so the extras are applied consistently. When any env override is
    provided (either via the tool or the active configuration), the
    returned ``ResolvedCommand.env`` carries the merged environment
    block; otherwise it's ``None`` so the child just inherits the
    parent env verbatim.
    """
    cmd = resolve(tool, values, ignore_required=ignore_required)
    env = build_env(
        tool, config_env, config_path_prepend,
        global_env=global_env,
        global_env_overrides=global_env_overrides,
        global_path_prepend=global_path_prepend,
        global_path_overrides=global_path_overrides,
    )
    return ResolvedCommand(
        argv=[*cmd.argv, *extras], cwd=cmd.cwd, env=env
    )
