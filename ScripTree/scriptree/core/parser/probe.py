"""Probe an executable for help text and dispatch to the right parser.

Workflow::

    result = probe(exe_path)
    if result.tool is None:
        # Blank canvas — no help text found, user fills in manually.
        ...
    else:
        editor.open(result.tool)

The probe is best-effort: it tries several common help-flag conventions
with a short timeout and moves on if nothing works. Tools that crash,
launch a GUI, or require arguments before showing help will simply fall
through to the blank-canvas path.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..model import ParseSource, ToolDef
from .plugin_api import get_default_registry


_HELP_ATTEMPTS: tuple[tuple[str, ...], ...] = (
    ("--help",),
    ("-h",),
    ("/?",),
    ("help",),
    # Deliberately NOT included: the empty-args attempt. Tools that
    # require no-args invocation to show usage are rare, and the
    # downside is severe — e.g. ``tasklist`` with no args prints the
    # entire running process table, which looks like "help" to the
    # scorer. If the dedicated help flags all fail, we'd rather fall
    # through to the blank-canvas editor than mis-parse real output.
)

PROBE_TIMEOUT_SECONDS = 5.0
MIN_USEFUL_HELP_CHARS = 40


@dataclass
class ProbeResult:
    tool: ToolDef | None
    """Parsed tool, or None if no help text was recovered."""

    help_text: str | None
    """Raw help text captured, for caching or debugging."""

    used_args: tuple[str, ...] | None
    """Which help-flag variant produced the output."""

    error: str | None = None
    """Human-readable failure reason, if any."""


# Patterns that indicate the tool rejected the help flag we sent rather
# than producing real help. We use this to prefer a longer, clean output
# over an earlier-tried rejection.
_ERROR_PREFIX = re.compile(
    r"^\s*(ERROR|Error|error|Invalid|Unknown|Usage error)[:\s]",
    re.MULTILINE,
)


def _score_help_output(text: str) -> int:
    """Heuristic quality score for a candidate help-text output.

    Longer is generally better, but short error messages like
    ``ERROR: Invalid argument '--help'`` score zero even though they
    clear the minimum length. The probe picks the highest-scoring
    candidate across all attempted help flags.
    """
    if not text or len(text) < MIN_USEFUL_HELP_CHARS:
        return 0
    # Looks like an error rejection: "ERROR:" or "Invalid" in the first
    # couple of lines, AND short (under 500 chars). Real help can be
    # long enough that an ERROR word later in the text shouldn't
    # disqualify it.
    first_chunk = text[:300]
    if _ERROR_PREFIX.search(first_chunk) and len(text) < 500:
        return 0
    return len(text)


def probe(exe_path: str) -> ProbeResult:
    """Try to auto-discover a tool's help text and parse it.

    Tries every help-flag candidate and picks the highest-scoring
    response. This matters because Windows tools reject ``--help``
    with a short error message that passes a naive length threshold
    but is useless for parsing, while their ``/?`` output is what we
    actually want.
    """
    path = Path(exe_path)
    if not exe_path:
        return ProbeResult(tool=None, help_text=None, used_args=None,
                           error="No executable path given.")

    best_text: str | None = None
    best_args: tuple[str, ...] | None = None
    best_score = 0
    for args in _HELP_ATTEMPTS:
        text = _run_help(exe_path, args)
        score = _score_help_output(text or "")
        if score > best_score:
            best_score = score
            best_text = text
            best_args = args

    if best_text is None or best_score == 0:
        return ProbeResult(
            tool=None, help_text=None, used_args=None,
            error="No help text found. Falling back to blank-canvas editor.",
        )

    tool = _parse(best_text)
    if not tool.executable:
        tool.executable = exe_path
    if not tool.name:
        tool.name = path.stem
    return ProbeResult(
        tool=tool, help_text=best_text, used_args=best_args, error=None
    )


def parse_text(help_text: str) -> ToolDef:
    """Dispatch help text to the best parser (argparse → click → heuristic).

    Exposed separately so tests and the "re-parse cached text" button
    don't have to re-probe.
    """
    return _parse(help_text)


# --- internals -------------------------------------------------------------

def _run_help(exe_path: str, args: tuple[str, ...]) -> str | None:
    try:
        proc = subprocess.run(
            [exe_path, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, PermissionError, OSError):
        return None
    except subprocess.TimeoutExpired:
        return None

    # Tools vary in whether they print help to stdout or stderr, and
    # whether they return 0 or nonzero on --help. Accept anything.
    combined = (proc.stdout or "") + (proc.stderr or "")
    return combined if combined.strip() else None


def _parse(help_text: str) -> ToolDef:
    """Dispatch help text to the best parser in the default registry.

    The registry is loaded once and iterated in priority order; the
    first plugin whose ``detect`` returns a non-None ToolDef wins.
    A built-in ``heuristic`` plugin at priority 999 always returns a
    result, so this function never returns None in practice — we
    still type-narrow for safety.
    """
    result = get_default_registry().parse(help_text)
    if result is not None:
        _sanitize_parsed_tool(result)
        return result
    # Fallback — would only reach here if the heuristic plugin was
    # disabled or removed via a user override. Build a minimal stub.
    return ToolDef(
        name="",
        executable="",
        source=ParseSource(mode="none", help_text_cached=help_text),
    )


# Shell metacharacters that should never appear in generated template
# tokens. These could be injected via crafted --help output.
_DANGEROUS_CHARS = re.compile(r"[;|&`$<>!]")


def _sanitize_parsed_tool(tool: ToolDef) -> None:
    """Strip dangerous shell metacharacters from a parser-generated ToolDef.

    This runs after every parser plugin to prevent crafted help text
    from injecting shell commands into the argument template or param
    defaults. Only literal tokens are sanitized — placeholder syntax
    like ``{param_id}`` and ``{param_id?--flag}`` is preserved.
    """
    clean_template: list = []
    for entry in tool.argument_template:
        if isinstance(entry, list):
            clean_template.append([
                _DANGEROUS_CHARS.sub("", tok)
                if "{" not in tok else tok
                for tok in entry
            ])
        elif isinstance(entry, str):
            if "{" not in entry:
                clean_template.append(_DANGEROUS_CHARS.sub("", entry))
            else:
                clean_template.append(entry)
        else:
            clean_template.append(entry)
    tool.argument_template = clean_template

    # Sanitize param defaults — a crafted help text could embed
    # shell metacharacters in default values.
    for param in tool.params:
        if isinstance(param.default, str) and param.default:
            param.default = _DANGEROUS_CHARS.sub("", param.default)

    # Strip control characters (except \t \n \r) from cached help text
    # to prevent terminal escape injection if ever rendered.
    if tool.source.help_text_cached:
        tool.source.help_text_cached = re.sub(
            r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]",
            "",
            tool.source.help_text_cached,
        )


__all__ = ["probe", "parse_text", "ProbeResult"]
