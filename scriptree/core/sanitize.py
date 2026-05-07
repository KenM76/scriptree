"""Input sanitization for form values before they reach subprocess argv.

ScripTree uses ``subprocess.Popen(argv, shell=False)`` so there is no
shell interpretation of metacharacters.  However, some attack vectors
remain:

- **Path traversal** — ``..\\..\\..\\Windows\\System32\\cmd.exe`` in a
  path field could point the tool at an unexpected executable.
- **Shell metacharacters in values** — while Popen doesn't interpret
  them, the *child process* might (e.g. ``cmd /c "..."`` or PowerShell
  ``-Command "..."``) which re-introduces shell expansion.
- **Null bytes** — can truncate strings at the OS level.
- **Control characters** — can confuse terminals and log parsers.

The command-line editor is exempt from sanitization — if a user has
access to that, they're trusted to enter arbitrary text.

This module is pure Python, no Qt imports.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Characters that are dangerous in shell contexts.  Even though Popen
# doesn't use a shell, child processes (cmd.exe, powershell.exe) might
# re-interpret these if the value ends up inside a command string.
_SHELL_META = set(";|&`$<>{}()!")

# Null bytes and ASCII control characters (except tab and newline).
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Path traversal patterns.
_PATH_TRAVERSAL = re.compile(r"(?:^|[\\/])\.\.(?:[\\/]|$)")

# UNC path pattern (\\server\share) — potentially dangerous for
# credential harvesting on Windows.
_UNC_PATH = re.compile(r"^\\\\[^\\]")


@dataclass(frozen=True)
class SanitizeResult:
    """Result of sanitizing a single input value."""

    value: str
    """The original (unmodified) value."""

    warnings: list[str]
    """Human-readable warnings about suspicious content."""

    @property
    def is_clean(self) -> bool:
        return len(self.warnings) == 0


def sanitize_value(
    value: str,
    *,
    is_path: bool = False,
    field_label: str = "",
) -> SanitizeResult:
    """Check a form field value for injection risks.

    Does NOT modify the value — returns warnings that the UI can
    display. The caller decides whether to block submission.

    Parameters
    ----------
    value:
        The raw string value from the form widget.
    is_path:
        True if this field is a path-type parameter (enables
        additional path-specific checks).
    field_label:
        Human-readable field name for warning messages.
    """
    if not value:
        return SanitizeResult(value=value, warnings=[])

    warnings: list[str] = []
    prefix = f"{field_label}: " if field_label else ""

    # Null bytes.
    if "\x00" in value:
        warnings.append(f"{prefix}Contains null byte(s) — may truncate the value.")

    # Control characters.
    if _CONTROL_CHARS.search(value):
        warnings.append(f"{prefix}Contains control characters.")

    # Shell metacharacters.
    found_meta = _SHELL_META.intersection(value)
    if found_meta:
        chars = " ".join(sorted(found_meta))
        warnings.append(
            f"{prefix}Contains shell metacharacters: {chars}"
        )

    # Path-specific checks.
    if is_path:
        if _PATH_TRAVERSAL.search(value):
            warnings.append(
                f"{prefix}Contains path traversal (../) — "
                "may access files outside the expected directory."
            )
        if _UNC_PATH.match(value):
            warnings.append(
                f"{prefix}Contains a UNC path (\\\\server\\share) — "
                "may expose credentials on the network."
            )

    return SanitizeResult(value=value, warnings=warnings)


def sanitize_all_values(
    values: dict[str, str],
    path_fields: set[str] | None = None,
    labels: dict[str, str] | None = None,
) -> list[str]:
    """Sanitize all form values and return a flat list of warnings.

    Parameters
    ----------
    values:
        ``{param_id: value}`` dict from the form.
    path_fields:
        Set of param IDs that are path-type fields.
    labels:
        ``{param_id: human_label}`` for better warning messages.
    """
    all_warnings: list[str] = []
    path_ids = path_fields or set()
    label_map = labels or {}

    for pid, val in values.items():
        if not isinstance(val, str):
            continue
        result = sanitize_value(
            val,
            is_path=pid in path_ids,
            field_label=label_map.get(pid, pid),
        )
        all_warnings.extend(result.warnings)

    return all_warnings


def validate_resolved_path(
    resolved: Path,
    base_dir: Path,
    *,
    allow_symlinks: bool = True,
    allow_traversal: bool = True,
) -> list[str]:
    """Validate a resolved file path against security policies.

    Returns a list of warning strings (empty = safe).

    Parameters
    ----------
    resolved:
        The resolved (absolute) path to check.
    base_dir:
        The base directory the path should stay within (e.g. the
        directory containing the .scriptreetree file).
    allow_symlinks:
        If False, rejects paths that are or contain symlinks.
    allow_traversal:
        If False, rejects paths that resolve outside ``base_dir``.
    """
    from pathlib import Path as _Path
    warnings: list[str] = []

    if not allow_symlinks:
        # Check if the resolved path or any parent is a symlink.
        check = resolved
        while check != check.parent:
            if check.is_symlink():
                warnings.append(
                    f"Path contains a symlink: {check} — "
                    "symlinks are disabled by the allow_symlinks permission."
                )
                break
            check = check.parent

    if not allow_traversal:
        # Check if the resolved path is outside the base directory.
        try:
            resolved.relative_to(base_dir)
        except ValueError:
            warnings.append(
                f"Path {resolved} is outside the base directory "
                f"{base_dir} — path traversal is disabled by the "
                "allow_path_traversal permission."
            )

    return warnings


def split_command(cmd: str) -> list[str]:
    """Split a command string into an argv list without using a shell.

    Cross-platform:
    - On Windows, uses ``CommandLineToArgvW`` for correct handling of
      quoted paths (e.g. ``"C:\\Program Files\\tool.exe" arg1``) and
      Windows-style backslash escaping. POSIX ``shlex.split`` would
      mangle paths like ``C:\\Users\\Ken`` because ``\\U`` is treated
      as an escape.
    - On Linux/macOS, uses :func:`shlex.split` with POSIX mode.

    An empty/whitespace-only input returns an empty list on both
    platforms — we explicitly short-circuit because
    ``CommandLineToArgvW("")`` returns the calling process's exe
    name (documented Windows quirk), which is never what we want.
    """
    import shlex
    import sys
    if not cmd.strip():
        return []
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            fn = ctypes.windll.shell32.CommandLineToArgvW
            fn.restype = ctypes.POINTER(wintypes.LPWSTR)
            fn.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
            argc = ctypes.c_int()
            argv = fn(cmd, ctypes.byref(argc))
            if argv:
                try:
                    return [argv[i] for i in range(argc.value)]
                finally:
                    ctypes.windll.kernel32.LocalFree(argv)
        except (OSError, AttributeError):
            pass  # Fall through to shlex
    return shlex.split(cmd)
