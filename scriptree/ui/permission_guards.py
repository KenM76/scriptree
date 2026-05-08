"""Reusable helpers for gating widgets / actions / runtime decisions on
ScripTree's capability system.

Pre-v0.3.3 the codebase had ~14 capabilities consulted via direct
``perms.can("foo")`` calls scattered through the UI, plus 21
capabilities declared in ``CAPABILITIES`` that nothing read at
runtime.  v0.3.3 closed the gap by wiring every declared capability
to its natural gate point — and to keep those gates consistent and
testable, the boilerplate moved into this module.

Public helpers
--------------

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
    Thin wrapper around ``ps.can(capability)`` that:

    * Auto-loads the app permissions when ``ps`` is omitted.
    * Returns ``True`` (allowed) on any error so a misconfigured
      permission system never produces a worse-than-baseline UX —
      the user sees the same behaviour as a developer install with
      no permissions/ folder deployed.

Design notes
------------

These helpers run **once at construction time**.  Permissions
don't change mid-session in any of ScripTree's deployment models,
so we don't bother with signal-driven re-evaluation.  If an admin
flips a capability while ScripTree is running, the user has to
restart to pick up the change — same contract as Settings has
always documented.

A denied capability surfaces as ``setEnabled(False)`` rather than
``setVisible(False)``.  Hidden controls confuse users ("did this
button used to exist?"); disabled controls + an explanatory
tooltip make the IT-driven lockdown discoverable.
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
