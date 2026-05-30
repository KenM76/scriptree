"""Host-OS detection + per-platform override resolution helpers.

## For humans

ScripTree runs on Windows, macOS, and Linux.  Until v0.8.0a22
the tool definitions themselves were single-platform: a
``.scriptree`` file that said ``executable: "py.exe"`` only
worked on Windows; the same tool on a Mac needed a different
binary and often a fundamentally different argv shape.

This module solves both halves of the problem:

* **Host detection** — :func:`host_os` returns a normalised
  three-value identifier (``"windows"`` / ``"macos"`` /
  ``"linux"``) for the machine ScripTree is currently running
  on.  Internal mapping translates Python's
  ``platform.system()`` ("Windows" / "Darwin" / "Linux") into
  these user-facing names.

* **Resolution** — :func:`resolve_for_host` takes a ``ToolDef``
  and the target OS, then returns a NEW ``ToolDef`` whose
  top-level fields reflect the merged per-platform overrides.
  The original ``ToolDef`` is untouched (editor keeps the full
  cross-platform definition; the runner only ever sees a
  single-OS view).

The resolution merges by *field*: a platform entry that supplies
only ``executable`` inherits the default ``argument_template``;
one that supplies a full ``argument_template`` replaces the
default entirely.  No deep merge inside list / dict values --
the override is whole-field, all-or-nothing per field, which
matches the user's mental model ("for this OS, this is THE
command").

## For maintainers / LLMs

* Pure Python, standard-library only.  No Qt; safe to import
  from the headless ``validate`` / ``migrate`` CLI path.
* The canonical OS identifiers (``"windows"`` / ``"macos"`` /
  ``"linux"``) are exposed as a ``OS_IDS`` tuple so other modules
  can iterate without hand-coding the list.
* Resolution is intentionally *additive*: when a per-OS entry
  has no override for a field, the top-level value is kept.
  This is what lets a tool author leave a platform entry empty
  ("supported, same as default") versus omitting the platform
  entirely ("inherit default, no explicit support claim").
  At the I/O layer the two are distinguishable (key absent vs
  key present with ``{}``); at the resolution layer they look
  the same.
* The resolution helper does NOT consult disk -- it never
  checks whether the resolved ``executable`` exists.  That's
  the runner's job.  Keeps this module pure and testable.
* Why a three-value enum instead of Python's ``sys.platform``
  raw strings: ``sys.platform`` returns ``"win32"`` even on
  64-bit Windows (legacy reasons), which would confuse users.
  ``platform.system()`` returns ``"Darwin"`` for macOS which
  most users wouldn't recognise.  The three-value enum is the
  reader-friendly form authors and the documentation see.
"""
from __future__ import annotations

import platform as _platform
from typing import Literal


# Canonical OS identifiers.  These are the strings that appear
# in ``.scriptree`` JSON's ``platforms`` block and in the
# editor UI; everything else is internal mapping.
OSId = Literal["windows", "macos", "linux"]
OS_IDS: tuple[OSId, ...] = ("windows", "macos", "linux")
"""All three supported OS ids, in editor-tab display order.

Iterate this when building UI lists (the tool editor's
platform tabs, the auto-discover prompt's per-OS hints, etc.)
so a future addition (say ``"bsd"``) ripples through every
surface from one place."""


# Internal mapping from ``platform.system()`` values to the
# canonical ids.  Updated together with ``OS_IDS`` if we ever
# add a fourth platform.
_SYSTEM_TO_ID: dict[str, OSId] = {
    "Windows": "windows",
    "Darwin": "macos",
    "Linux": "linux",
}


# Cached host id.  Computed once on first call; never changes
# during a process lifetime (we don't support hot-swapping the
# OS).
_cached_host: OSId | None = None


def host_os() -> OSId:
    """Return the normalised OS id for the current machine.

    Returns one of ``"windows"``, ``"macos"``, ``"linux"``.

    On an unrecognised platform (BSDs, illumos, hypothetical
    others), falls back to ``"linux"``.  That's the safest
    POSIX-shaped default; tools that require true Linux
    behaviour will fail at run time with a normal missing-
    executable error rather than crashing during resolution.

    Result is cached per-process; calling repeatedly costs a
    dict lookup, not a syscall.

    Example::

        from scriptree.core.platform import host_os
        if host_os() == "macos":
            ...
    """
    global _cached_host
    if _cached_host is not None:
        return _cached_host
    sysname = _platform.system()
    _cached_host = _SYSTEM_TO_ID.get(sysname, "linux")
    return _cached_host


def _reset_host_cache_for_tests() -> None:
    """Drop the cached value so a test can monkey-patch
    ``platform.system`` and verify a fresh detection.

    Not part of the public API; intended only for the
    ``tests/test_platforms_resolve.py`` suite.  Production
    code should never call this.
    """
    global _cached_host
    _cached_host = None


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve_for_host(tool: "ToolDef", *, os: OSId | None = None) -> "ToolDef":  # type: ignore[name-defined]
    """Return a copy of ``tool`` with the host OS's per-platform
    overrides merged into the top-level fields.

    Parameters
    ----------
    tool:
        The ``ToolDef`` to resolve.  Read-only; not mutated.
    os:
        Override target OS.  When ``None`` (typical), uses
        :func:`host_os`.  Tests pass an explicit value to
        exercise non-host variants without monkey-patching
        ``platform.system``.

    Returns
    -------
    A NEW ``ToolDef`` with these fields merged from the chosen
    platform entry (when present) on top of the top-level
    defaults: ``executable``, ``argument_template``,
    ``path_prepend``, ``env``, ``actions``.

    Merge rule: per-field replace, not deep merge.  If
    ``platforms[os].executable`` is ``None`` (or the key is
    missing in the JSON), the top-level ``executable`` is
    kept.  If it's set, it wholly replaces the top-level
    value -- no partial overlay within the field.

    The ``platforms`` field itself is left intact on the
    returned ``ToolDef`` so the editor can still see the full
    cross-platform definition after a resolution pass (useful
    for testing, the Preview-as dropdown, etc.).

    When ``tool.platforms`` is empty (no overrides authored),
    returns a copy with the same top-level values -- the
    function is safe and cheap to call unconditionally on
    every tool, even ones that don't use the feature.

    Does NOT check whether ``executable`` exists on disk.
    That happens at Run time via the existing missing-
    executable recovery flow.
    """
    # Lazy import: this module sits below ``model`` in the
    # dependency graph in spirit -- both ``model`` and ``io``
    # need ``OS_IDS`` -- so we can't unconditionally import
    # ``ToolDef`` at module load.  Late import keeps the
    # cycle broken.
    from .model import ToolDef  # noqa: PLC0415

    if not isinstance(tool, ToolDef):
        raise TypeError(
            f"resolve_for_host expected ToolDef, got "
            f"{type(tool).__name__}"
        )

    target = os if os is not None else host_os()

    # Build kwargs for the new ToolDef by starting from the
    # tool's dataclass fields and selectively replacing the
    # mergeable ones.  ``dataclasses.replace`` does this
    # cleanly -- it copies every non-mentioned field and
    # accepts kwarg overrides for the mentioned ones.
    import dataclasses as _dc

    override = tool.platforms.get(target) if tool.platforms else None
    if override is None:
        # No entry for this OS -- return a shallow copy so the
        # caller gets the "same as default" semantics without
        # accidentally mutating the original via aliasing.
        return _dc.replace(tool)

    # Per-field merge.  Each guard ``getattr ... is not None``
    # mirrors the JSON contract: ``None`` means "not overridden,
    # inherit default", anything else means "replace".
    kwargs: dict = {}
    if override.executable is not None:
        kwargs["executable"] = override.executable
    if override.argument_template is not None:
        kwargs["argument_template"] = list(override.argument_template)
    if override.path_prepend is not None:
        kwargs["path_prepend"] = list(override.path_prepend)
    if override.env is not None:
        kwargs["env"] = dict(override.env)
    if override.actions is not None:
        kwargs["actions"] = list(override.actions)

    return _dc.replace(tool, **kwargs)


__all__ = [
    "OSId",
    "OS_IDS",
    "host_os",
    "resolve_for_host",
]
