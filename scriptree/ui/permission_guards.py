"""Reusable helpers for gating widgets / actions / runtime decisions on
ScripTree's capability system.

## For humans

Pre-v0.3.3 the codebase had ~14 capabilities consulted via direct
``perms.can("foo")`` calls scattered through the UI, plus 21
capabilities declared in ``CAPABILITIES`` that nothing read at
runtime.  v0.3.3 closed the gap by wiring every declared capability
to its natural gate point — and to keep those gates consistent and
testable, the boilerplate moved into this module.

Public helpers:

``apply_widget_perm(widget, capability, *, ps=None, tooltip_when_denied=None)``
    Disable ``widget`` when ``capability`` is denied.  Optionally
    overwrites the tooltip so the user can hover and learn *why*
    the control is disabled.

``apply_action_perm(action, capability, *, ps=None, tooltip_when_denied=None)``
    Same, for ``QAction`` (menu item / toolbar action).  ``QAction``
    has ``setEnabled`` / ``setToolTip`` like a widget so the same
    semantics apply.

``apply_text_readonly(text_edit, capability, *, ps=None)``
    Make a ``QPlainTextEdit`` / ``QLineEdit`` read-only when
    ``capability`` is denied.  The widget stays visible (so the
    user can read what's there) but typing is blocked.

``perm_check(capability, *, ps=None) -> bool``
    Thin wrapper around ``ps.can(capability)`` that auto-loads the
    app permissions when ``ps`` is omitted, and returns ``True``
    (allowed) on any error so a misconfigured permission system never
    produces a worse-than-baseline UX — the user sees the same
    behaviour as a developer install with no permissions/ folder.

A denied capability surfaces as ``setEnabled(False)`` (or
``setReadOnly(True)`` for text) rather than ``setVisible(False)``:
hidden controls confuse users ("did this button used to exist?");
disabled controls plus an explanatory tooltip make the IT-driven
lockdown discoverable.

## For maintainers / LLMs

- FAIL-OPEN CONTRACT: ``perm_check`` returns ``True`` (ALLOWED) on
  ANY exception in lookup. This is intentional — a misconfigured /
  half-upgraded install must not lock the user out. Do NOT invert
  this to fail-closed. The genuine deny path comes from
  ``ps.can(capability)`` returning False (a missing capability file
  when a permissions/ dir exists = denied; no permissions/ dir at all
  = everything allowed). That deny→False distinction lives in
  ``core.permissions``, not here.
- These helpers run ONCE at construction time. There is no
  signal-driven re-evaluation by design: permissions don't change
  mid-session in any deployment model; an admin flip needs an app
  restart. Don't add live re-checking without revisiting that
  contract.
- ``apply_action_perm`` is deliberately a thin delegate to
  ``apply_widget_perm`` (``QAction`` mirrors the ``setEnabled`` /
  ``setToolTip`` API). It's kept separate purely as a self-
  documenting call site and a future divergence point — keep it that
  way rather than collapsing the two.
- Every helper returns the resolved permission state (``True`` =
  allowed) so callers can short-circuit (``if not
  apply_widget_perm(...): return``). Preserve that return value
  whenever you touch these.
- The mutating calls (``setEnabled`` / ``setToolTip`` /
  ``setReadOnly``) are wrapped in a broad ``except`` that silently
  passes — a duck-typed object lacking the API must not crash the
  form build. Allowed widgets are left completely untouched.
- ``Any``-typed ``widget`` / ``action`` / ``text_edit`` params are
  intentional: these are duck-typed across QWidget/QAction and test
  doubles. Don't tighten to concrete Qt types.
"""
from __future__ import annotations

from typing import Any

# Default tooltip prefix for any disabled-by-permission control.
_LOCKED_TOOLTIP_PREFIX = "Disabled by IT — capability not granted: "


def perm_check(
    capability: str,
    *,
    ps: Any | None = None,
) -> bool:
    """Return True iff ``capability`` is granted in the current session.

    ``ps`` (PermissionSet) — pass an explicit set when you've already
    loaded one (e.g. for a per-file context).  When omitted, the
    helper consults the cached app-level permissions.

    Errors during lookup default to **allowed** so a misconfigured
    install doesn't lock the user out of basic features.  Real-world
    deployments either ship a permissions/ folder (deny rules apply)
    or don't (everything allowed); the error path defends against
    edge cases like a partial install during an upgrade.
    """
    try:
        if ps is None:
            from ..core.permissions import get_app_permissions
            ps = get_app_permissions()
        return ps.can(capability)
    except Exception:  # noqa: BLE001
        return True


def _denied_tooltip(capability: str, custom: str | None) -> str:
    """Compose the explanatory tooltip shown on a disabled control."""
    if custom:
        return custom
    return _LOCKED_TOOLTIP_PREFIX + capability


def apply_widget_perm(
    widget: Any,
    capability: str,
    *,
    ps: Any | None = None,
    tooltip_when_denied: str | None = None,
) -> bool:
    """Disable ``widget`` when ``capability`` is denied.

    Returns the resolved permission state (True = allowed) so the
    caller can short-circuit further setup in the denied path:

        if not apply_widget_perm(self._btn_save, "save_scriptree"):
            return  # nothing else to wire

    A denied widget gets ``setEnabled(False)`` and an explanatory
    tooltip.  An allowed widget is left untouched.
    """
    allowed = perm_check(capability, ps=ps)
    if not allowed:
        try:
            widget.setEnabled(False)
            widget.setToolTip(_denied_tooltip(capability, tooltip_when_denied))
        except Exception:  # noqa: BLE001
            pass
    return allowed


def apply_action_perm(
    action: Any,
    capability: str,
    *,
    ps: Any | None = None,
    tooltip_when_denied: str | None = None,
) -> bool:
    """``QAction`` variant of ``apply_widget_perm``.

    QAction's ``setEnabled`` / ``setToolTip`` API mirrors QWidget's,
    so the implementation is identical — but kept as a separate
    function so call sites self-document ("this is gating an
    action, not a button") and so future divergences (e.g. setting
    the action's checked-state, hiding from menus on deny) have a
    natural extension point.
    """
    return apply_widget_perm(
        action, capability, ps=ps, tooltip_when_denied=tooltip_when_denied,
    )


def apply_text_readonly(
    text_edit: Any,
    capability: str,
    *,
    ps: Any | None = None,
) -> bool:
    """Make a text widget read-only when ``capability`` is denied.

    Used for the editable command-line preview in
    ``ToolRunnerView`` (gated by ``command_line_editor``) — the
    user can still read what's there, but can't edit it.  Returns
    the permission state for use as a short-circuit.
    """
    allowed = perm_check(capability, ps=ps)
    if not allowed:
        try:
            text_edit.setReadOnly(True)
            text_edit.setToolTip(
                _denied_tooltip(capability, None)
            )
        except Exception:  # noqa: BLE001
            pass
    return allowed
