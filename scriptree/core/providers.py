"""Dynamic choice / value providers (v0.6.0).

## For humans

A :class:`~scriptree.core.model.ProviderSpec` on a ``ParamDef`` says
"don't bake the choices into the .scriptree — run this command at
form-open / refresh time and use what it prints."

This module is the **pure execution + parse + sanitize** layer.  It
has NO Qt import (enforced by ``tests/test_core_purity.py``).  The
UI layer (``ui/tool_runner.py``) decides *when* to call
:func:`resolve_provider` (form build, debounced on upstream change,
Refresh click), shows spinner / error state, and never parses
provider output itself.

Hard rules honoured here (from ``architecture.md`` /
``docs/LLM/README.md``):

* ``Popen`` always gets a **list argv**, never ``shell=True``.
* Path / cwd resolution reuses ``runner.resolve_tool_path`` so a
  provider command like ``../sw_bridge/sw_bridge.exe`` resolves
  exactly like the tool's own ``executable``.
* Provider output becomes argv (the chosen values flow into the
  command), so it is sanitized exactly the way parser output is
  (``probe._sanitize_parsed_tool``): **strip NUL bytes and control
  characters; leave every other character verbatim.**  Shell
  metacharacters are deliberately *not* stripped — they are safe
  with ``shell=False``, which every spawn uses.  (The feature memo
  said "strip shell metacharacters"; the codebase's actual, audited
  stance is null/control-only, and we follow the codebase.)
* No provider ever runs during ``build_full_argv`` — by argv time
  the chosen value is an ordinary string.  This module is only
  called from the form-population phase.

## For maintainers / LLMs

* This module must be TOTALLY Qt-free — not even a lazy/function-
  local PySide6 import. ``tests/test_core_purity.py`` greps the
  source for the literal string ``PySide6`` and also runs a
  fresh-interpreter import check. Don't add Qt here, and don't
  import a sibling that would transitively pull Qt onto the
  headless path.
* Error contract: ``resolve_provider`` NEVER raises for
  provider-side failures (non-zero exit, timeout, malformed JSON,
  empty output) — all become ``ProviderResult(ok=False, ...)`` with
  stderr tail in ``detail``. Only a genuine bug in this function
  may propagate. Callers depend on never having to wrap this in
  try/except.
* ``subprocess.run`` is hard-wired ``shell=False`` (explicit kwarg
  for the auditor). ``argv[0]`` is resolved via
  ``runner.resolve_tool_path``; ``argv[1:]`` are passed VERBATIM —
  they are author-written flags, never user input, so they are NOT
  sanitized. Provider OUTPUT is sanitized via ``_scrub`` (NUL +
  C0/C1 controls only). Keep the asymmetry — sanitizing argv[1:]
  would break legitimate flags.
* ``_scrub`` strips ``_CTRL_CHARS`` which already includes ``\\x00``;
  ``_NULL_BYTE`` is defined but unused (mirrors probe's regex set).
  Don't "tighten" scrub to strip shell metacharacters — that
  contradicts the audited codebase stance documented above.
* JSON shape is type-driven, not widget-driven: ENUM / MULTISELECT
  expect ``{"choices": [...]}``; everything else expects
  ``{"value": ...}``. ``_CHOICE_TYPES`` is the single source of
  truth — if ``ParamType`` gains a list-like type, add it there.
* Scalar coercion: JSON ``true``/``false`` → ``"true"``/``"false"``,
  numbers → ``str``, ``null`` → ``""``. This matches the runner's
  truthiness rules — keep them aligned with
  ``runner._is_truthy`` / ``_value_to_str``.
* cwd default mirrors ``runner.resolve``: when ``spec.working_directory``
  is empty, cwd is the resolved command's parent dir (or ``None``
  if that's empty/``.``). Changing one without the other causes
  provider-vs-tool path drift.
* ``provider_run_order`` fails LOUD (``DependencyCycleError`` /
  ``ValueError``) on a cycle or unknown ``depends_on`` — a
  structural authoring bug, distinct from soft runtime failures.
  Kahn's algorithm with sorted queues gives a deterministic order;
  preserve the sorting if you touch it (tests likely assert order).
* ``__all__`` is explicit — update it if you add public API.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scriptree.core.model import ParamType, ProviderSpec
from scriptree.core.runner import resolve_tool_path

# Same regexes / philosophy as ``probe._sanitize_parsed_tool``: NUL
# breaks argv at the OS level; the other C0/C1 controls confuse
# terminals and log viewers if the value is ever echoed.
_NULL_BYTE = re.compile(r"\x00")
_CTRL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Param types whose provider returns a *choice list*.  Everything
# else (string / path / number / boolean / integer) is a *scalar
# value* provider.  ``MULTISELECT`` covers both the ``dropdown`` and
# the ``checkbox_list`` widget — widget is irrelevant here, only the
# type decides the expected JSON shape.
_CHOICE_TYPES = frozenset({ParamType.ENUM, ParamType.MULTISELECT})


def _scrub(s: str) -> str:
    """Strip NUL + control characters; keep everything else verbatim."""
    return _CTRL_CHARS.sub("", s)


@dataclass
class ProviderResult:
    """Outcome of running one provider.

    ``ok=True``  → choices / value are populated and sanitized.
    ``ok=False`` → ``error`` is a one-line human message; ``detail``
                   carries the provider's stderr tail (surfaced in a
                   tooltip / expandable, never swallowed).  The param
                   should render in a soft error state; the rest of
                   the form stays usable; Run is blocked only if the
                   param is ``required``.
    """

    ok: bool = False
    is_scalar: bool = False
    choices: list[str] = field(default_factory=list)
    choice_labels: list[str] = field(default_factory=list)
    default: Any = None
    value: str | None = None
    error: str = ""
    detail: str = ""

    @classmethod
    def failure(cls, error: str, *, detail: str = "",
                is_scalar: bool = False) -> "ProviderResult":
        return cls(ok=False, error=error, detail=detail,
                   is_scalar=is_scalar)


def _stdin_payload(upstream_values: dict[str, str], param_id: str) -> str:
    """The JSON document fed to the provider on stdin.

    Always sent, even when ``depends_on`` is empty — providers may
    ignore it and use their own flags (the ``--exclude-selected``
    example in the feature memo).  Sending it unconditionally keeps
    the contract uniform.
    """
    return json.dumps(
        {"depends_on": dict(upstream_values), "param_id": param_id}
    )


def resolve_provider(
    spec: ProviderSpec,
    *,
    param_id: str,
    param_type: ParamType,
    upstream_values: dict[str, str] | None = None,
    tool_file: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> ProviderResult:
    """Run ``spec.command`` once and return a :class:`ProviderResult`.

    Parameters
    ----------
    spec:
        The validated :class:`ProviderSpec` (its ``__post_init__``
        already guaranteed a non-empty argv list, a legal ``refresh``
        / ``cache``, and a positive ``timeout_sec``).
    param_id / param_type:
        ``param_type`` decides the expected stdout shape — a choice
        list for enum / multiselect, a scalar ``{"value": …}`` for
        everything else.  ``param_id`` is echoed into the stdin
        payload so a single multiplexed provider can tell which
        param it's being asked about.
    upstream_values:
        Current values of this param's ``depends_on`` params.  Sent
        on stdin as ``{"depends_on": {...}, "param_id": "..."}``.
    tool_file:
        ``ToolDef.loaded_from`` — relative ``command[0]`` /
        ``working_directory`` resolve against this file's directory,
        identical to how the tool's own ``executable`` resolves.
    env:
        Effective child environment (the caller builds it with
        ``runner.build_env`` so PATH-prepend / tool.env / config.env
        layering matches the tool itself).  ``None`` ⇒ inherit the
        current process environment.

    Never raises for provider-side failures (non-zero exit, timeout,
    malformed JSON, empty result) — those come back as
    ``ok=False``.  Only a genuinely broken *call* (e.g. a bug in
    this function) would propagate.
    """
    is_scalar = param_type not in _CHOICE_TYPES
    upstream_values = upstream_values or {}

    # Resolve argv[0] (and cwd) against the .scriptree directory, the
    # same rule the tool's own executable uses.  argv[1:] are passed
    # through verbatim — they're literal flags authored in the
    # .scriptree, never user input.
    argv = list(spec.command)
    argv[0] = resolve_tool_path(argv[0], tool_file)

    if spec.working_directory:
        cwd = resolve_tool_path(spec.working_directory, tool_file)
    else:
        # Default to the resolved command's parent dir so a provider
        # that reads sibling files keeps working — mirrors
        # runner.resolve()'s cwd default.
        parent = Path(argv[0]).parent
        cwd = str(parent) if str(parent) not in ("", ".") else None

    stdin_payload = _stdin_payload(upstream_values, param_id)

    try:
        proc = subprocess.run(
            argv,
            input=stdin_payload,
            capture_output=True,
            text=True,
            timeout=spec.timeout_sec,
            cwd=cwd,
            env=env,
            shell=False,  # NEVER shell=True — explicit for the auditor
        )
    except subprocess.TimeoutExpired:
        return ProviderResult.failure(
            f"Provider timed out after {spec.timeout_sec}s "
            f"— click Refresh to retry.",
            is_scalar=is_scalar,
        )
    except (OSError, ValueError) as exc:
        return ProviderResult.failure(
            f"Provider could not be launched: {exc}",
            detail=repr(exc),
            is_scalar=is_scalar,
        )

    stderr_tail = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return ProviderResult.failure(
            f"Provider exited with code {proc.returncode} "
            f"— click Refresh to retry.",
            detail=stderr_tail,
            is_scalar=is_scalar,
        )

    raw = (proc.stdout or "").strip()
    if not raw:
        return ProviderResult.failure(
            "Provider produced no output.",
            detail=stderr_tail,
            is_scalar=is_scalar,
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return ProviderResult.failure(
            f"Provider output was not valid JSON: {exc}",
            detail=(stderr_tail or raw[:500]),
            is_scalar=is_scalar,
        )
    if not isinstance(data, dict):
        return ProviderResult.failure(
            "Provider JSON must be an object "
            '(e.g. {"choices": [...]} or {"value": "..."}).',
            detail=stderr_tail,
            is_scalar=is_scalar,
        )

    if is_scalar:
        return _parse_scalar(data, stderr_tail)
    return _parse_choices(data, stderr_tail)


def _parse_choices(data: dict, stderr_tail: str) -> ProviderResult:
    choices_raw = data.get("choices")
    if not isinstance(choices_raw, list) or not choices_raw:
        return ProviderResult.failure(
            'Provider JSON must contain a non-empty "choices" list.',
            detail=stderr_tail,
        )
    if not all(isinstance(c, (str, int, float)) for c in choices_raw):
        return ProviderResult.failure(
            '"choices" entries must be strings (or numbers).',
            detail=stderr_tail,
        )
    choices = [_scrub(str(c)) for c in choices_raw]

    labels_raw = data.get("choice_labels") or []
    if labels_raw and not isinstance(labels_raw, list):
        return ProviderResult.failure(
            '"choice_labels" must be a list parallel to "choices".',
            detail=stderr_tail,
        )
    labels = [_scrub(str(x)) for x in labels_raw]

    default = data.get("default")
    if isinstance(default, list):
        default = [_scrub(str(x)) for x in default]
    elif isinstance(default, (str, int, float)):
        default = _scrub(str(default))
    else:
        default = None

    return ProviderResult(
        ok=True,
        is_scalar=False,
        choices=choices,
        choice_labels=labels,
        default=default,
        detail=stderr_tail,
    )


def _parse_scalar(data: dict, stderr_tail: str) -> ProviderResult:
    if "value" not in data:
        return ProviderResult.failure(
            'Scalar provider JSON must contain a "value" key '
            '(e.g. {"value": "C:/path/to/thing"}).',
            detail=stderr_tail,
            is_scalar=True,
        )
    val = data["value"]
    if isinstance(val, bool):
        # JSON true/false → the runner's truthiness rules expect
        # "true"/"false"; keep it predictable.
        val = "true" if val else "false"
    elif isinstance(val, (int, float)):
        val = str(val)
    elif val is None:
        val = ""
    elif not isinstance(val, str):
        return ProviderResult.failure(
            '"value" must be a string, number, or boolean.',
            detail=stderr_tail,
            is_scalar=True,
        )
    return ProviderResult(
        ok=True,
        is_scalar=True,
        value=_scrub(val),
        detail=stderr_tail,
    )


# ---------------------------------------------------------------------------
# depends_on dependency graph — topological order + cycle detection
# ---------------------------------------------------------------------------
#
# This is genuinely net-new machinery (``visible_when`` is lazy
# expression-eval with no declared dependency graph, so nothing here
# could be reused from it).  A cycle is a *structural* authoring bug
# → fail loud at load, the same stance ``ParamDef.__post_init__``
# takes for a bad widget/type pairing.  Runtime provider *execution*
# failures still fail soft (see ``ProviderResult``).


class DependencyCycleError(ValueError):
    """Raised when ``depends_on`` edges form a cycle."""


def provider_run_order(params: list[Any]) -> list[str]:
    """Topologically sort param ids by their ``depends_on`` edges.

    Only params that either *have* a ``choices_provider`` or are
    *named in* some provider param's ``depends_on`` participate;
    the order returned lists upstream params before the dependents
    that reference them, so the orchestrator can run providers with
    no upstream first, then dependents.

    Raises :class:`DependencyCycleError` on a cycle, and ``ValueError``
    if a ``depends_on`` names a param id that doesn't exist.
    """
    by_id = {p.id: p for p in params}
    # Nodes we care about: provider params + anything they depend on.
    relevant: set[str] = set()
    for p in params:
        if getattr(p, "choices_provider", None) is not None:
            relevant.add(p.id)
            for dep in getattr(p, "depends_on", []) or []:
                relevant.add(dep)

    # Validate edges point at real params.
    for pid in relevant:
        p = by_id.get(pid)
        if p is None:
            continue
        for dep in getattr(p, "depends_on", []) or []:
            if dep not in by_id:
                raise ValueError(
                    f"ParamDef {pid!r}: depends_on names unknown "
                    f"param {dep!r}."
                )

    # Kahn's algorithm.  Edge dep -> pid (dep must run before pid).
    indeg: dict[str, int] = {pid: 0 for pid in relevant}
    adj: dict[str, list[str]] = {pid: [] for pid in relevant}
    for pid in relevant:
        p = by_id.get(pid)
        if p is None:
            continue
        for dep in getattr(p, "depends_on", []) or []:
            if dep in relevant:
                adj[dep].append(pid)
                indeg[pid] += 1

    queue = sorted([n for n, d in indeg.items() if d == 0])
    order: list[str] = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for m in sorted(adj[n]):
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
        queue.sort()

    if len(order) != len(relevant):
        stuck = sorted(set(relevant) - set(order))
        raise DependencyCycleError(
            f"depends_on cycle detected among params: "
            f"{', '.join(stuck)}"
        )
    return order


__all__ = [
    "ProviderResult",
    "resolve_provider",
    "provider_run_order",
    "DependencyCycleError",
]
