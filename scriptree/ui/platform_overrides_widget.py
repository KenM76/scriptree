"""Tool-editor inline widget for per-OS overrides (v0.8.0a22+).

## For humans

A self-contained QGroupBox the tool editor slots in between the
Tool group and the Parameters area.  Lets an author declare,
within a single ``.scriptree`` file, per-OS variants of:

* ``executable``
* ``argument_template``
* ``path_prepend``

The widget renders three tabs (Windows / macOS / Linux), each
showing the same three fields plus an "Override for this OS"
checkbox.  When the checkbox is unchecked, the fields are
read-only previews of the top-level (default) values, greyed out
so the author can SEE what they'd inherit without editing it.
Checked = editable; the values land in ``tool.platforms[os]``.

A "Preview as" combo at the bottom selects which OS's resolved
argv the command-line preview elsewhere in the editor should
display, independent of which tab is being edited.  The combo
emits ``previewOsChanged`` so the editor can pull the right
``resolve_for_host(tool, os=...)`` view.

## For maintainers / LLMs

* This widget is a strict ``QGroupBox`` -- it doesn't subclass
  the editor or know its internals.  Two public methods do the
  data binding:

      def load_from_tool(self, tool: ToolDef) -> None:
          ...rebuild every tab's state from ``tool.platforms``...

      def apply_to_tool(self, tool: ToolDef) -> None:
          ...write every tab's state back to ``tool.platforms``...

  The editor calls ``load_from_tool`` during construction and
  ``apply_to_tool`` whenever it persists.  The widget emits
  ``changed`` (a plain Qt signal) when ANY tab field mutates so
  the editor can flag the dirty-document state.

* Phase 3 only wires executable / argument_template /
  path_prepend.  The model supports ``env`` and ``actions``
  per-OS too (Phase 1 added them to PlatformOverride), but the
  editor UI for those lives in separate dialogs already
  (Edit environment..., Edit actions...) and bolting per-OS
  variants onto those popups is its own follow-up.  For now,
  ``apply_to_tool`` preserves any existing ``env`` / ``actions``
  override on round-trip -- it reads them off the existing
  PlatformOverride and writes them back unchanged.

* The "Default" view (top-level ``executable`` etc.) is NOT
  represented as a fourth tab.  The author edits the defaults
  in the main editor form above; the tabs here are explicitly
  for *overrides*.  A read-only preview row at the top of each
  tab shows what would be inherited, so the author has the
  full picture without leaving the widget.

* Argument-template fields use the same multi-line text format
  ``_template_to_text`` / ``_text_to_template`` already use in
  the main editor (one entry per line; quoted-list syntax for
  fan-out groups).  Imported lazily to keep this module's
  test-import light.

* Path-prepend uses a simple newline-separated text area.  The
  main editor has a richer Edit-paths dialog; we don't link to
  it from the per-OS tabs because the relative-path resolution
  rules would diverge (paths are anchored on the .scriptree
  file, not on the platform).  Keep it simple, keep it
  consistent.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.discovery import UpdateMode  # only for type proximity
from ..core.platform import OS_IDS, OSId, host_os


# Human-readable OS labels for the tabs.
_OS_LABELS: dict[OSId, str] = {
    "windows": "Windows",
    "macos": "macOS",
    "linux": "Linux",
}

# Inherit indicator -- shown as the placeholder + grey colour on
# read-only fields so the author can tell at a glance "this is
# what I'd get without an override."
_INHERIT_HINT_COLOR = "#888"


class _OsTab(QWidget):
    """The body of one OS's tab.

    Contains the override toggle + three fields (executable,
    argument template, path prepend).  Fields are disabled when
    the toggle is off; when re-enabled, they re-load whatever
    state was last saved for this OS so the author can toggle
    repeatedly without losing work.

    Emits ``changed`` on any state mutation so the parent
    widget can propagate dirty state up to the editor.
    """

    changed = Signal()

    def __init__(self, os_id: OSId) -> None:
        super().__init__()
        self._os_id: OSId = os_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # ----- The override toggle ------------------------------------
        self._override_cb = QCheckBox(
            f"Override for {_OS_LABELS[os_id]}"
        )
        self._override_cb.setToolTip(
            "When unchecked, this OS inherits the top-level "
            "(default) Executable / Argument template / PATH "
            "prepend values.  Check to edit per-OS overrides."
        )
        self._override_cb.toggled.connect(self._sync_enabled)
        self._override_cb.toggled.connect(self.changed)
        layout.addWidget(self._override_cb)

        # ----- Read-only inherited preview (top) ----------------------
        # Visible only while the override is OFF.  Shows the
        # author-visible inherited values so they don't have to
        # scroll up to see what they'd get without overriding.
        self._inherit_box = QGroupBox("Inherited from default")
        inherit_form = QFormLayout(self._inherit_box)
        self._inherit_exe = QLabel("")
        self._inherit_exe.setStyleSheet(f"color: {_INHERIT_HINT_COLOR};")
        self._inherit_argv = QLabel("")
        self._inherit_argv.setStyleSheet(f"color: {_INHERIT_HINT_COLOR};")
        self._inherit_argv.setWordWrap(True)
        self._inherit_paths = QLabel("")
        self._inherit_paths.setStyleSheet(f"color: {_INHERIT_HINT_COLOR};")
        self._inherit_paths.setWordWrap(True)
        inherit_form.addRow("Executable:", self._inherit_exe)
        inherit_form.addRow("Argument template:", self._inherit_argv)
        inherit_form.addRow("PATH prepend:", self._inherit_paths)
        layout.addWidget(self._inherit_box)

        # ----- The edit form (enabled when override is on) ------------
        self._edit_box = QGroupBox(
            f"Override values for {_OS_LABELS[os_id]}"
        )
        edit_form = QFormLayout(self._edit_box)

        self._exe_edit = QLineEdit()
        self._exe_edit.setPlaceholderText(
            "e.g. /usr/bin/osascript (leave blank to inherit)"
        )
        self._exe_edit.textChanged.connect(self.changed)
        edit_form.addRow("Executable:", self._exe_edit)

        self._argv_edit = QPlainTextEdit()
        self._argv_edit.setPlaceholderText(
            "One token per line; quoted-list syntax for fan-out "
            "groups; leave blank to inherit."
        )
        # ``QPlainTextEdit`` has no built-in "fixed line count" API;
        # 4 lines reads naturally without dominating the tab.
        self._argv_edit.setFixedHeight(self._line_px(4))
        self._argv_edit.textChanged.connect(self.changed)
        edit_form.addRow("Argument template:", self._argv_edit)

        self._paths_edit = QPlainTextEdit()
        self._paths_edit.setPlaceholderText(
            "One folder per line; leave blank to inherit."
        )
        self._paths_edit.setFixedHeight(self._line_px(3))
        self._paths_edit.textChanged.connect(self.changed)
        edit_form.addRow("PATH prepend:", self._paths_edit)

        layout.addWidget(self._edit_box)

        # Holding pen for env/actions overrides that other UI paths
        # may set.  This widget doesn't expose env/actions per-OS
        # editing (Phase 3 scope), but we preserve any pre-existing
        # values on round-trip so a tool that already had a
        # PlatformOverride(env=..., actions=...) doesn't lose them
        # when the user opens the editor and saves.
        self._preserved_env: dict[str, str] | None = None
        self._preserved_actions: list[Any] | None = None

        self._sync_enabled(False)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _line_px(n_lines: int) -> int:
        """Approximate pixel height for ``n_lines`` of text in a
        ``QPlainTextEdit``.  18px/line is right for typical
        system fonts; the rendered height is close enough that
        4 lines reads as 4 lines without overflow."""
        return 18 * n_lines + 16  # +16 for padding / scrollbar reserve

    def _sync_enabled(self, checked: bool) -> None:
        """Enable the override form when the toggle is on; show
        the inherited-preview group when it's off.

        Both groups always exist in the layout; visibility is
        toggled rather than re-laying out the tab.  Avoids
        Qt's repaint flicker at tab-switch time."""
        self._inherit_box.setVisible(not checked)
        self._edit_box.setVisible(checked)

    # ------------------------------------------------------------------
    # Inherited-preview API (called by parent on default-fields change)
    # ------------------------------------------------------------------

    def set_inherited(
        self,
        *,
        executable: str,
        argument_template_text: str,
        path_prepend: list[str],
    ) -> None:
        """Refresh the read-only preview rows from the editor's
        current top-level values.  Called whenever the main
        Executable / argument_template / path_prepend fields
        change so the preview stays in sync."""
        self._inherit_exe.setText(executable or "<empty>")
        self._inherit_argv.setText(
            argument_template_text or "<empty>"
        )
        self._inherit_paths.setText(
            "\n".join(path_prepend) if path_prepend else "<empty>"
        )

    # ------------------------------------------------------------------
    # Load / apply -- data binding with PlatformOverride
    # ------------------------------------------------------------------

    def load_from_override(self, override: Any) -> None:
        """Read state from a ``PlatformOverride`` (or ``None``).

        When ``override is None`` (= no entry for this OS in
        ``tool.platforms``), the toggle is off and the form is
        cleared.

        When ``override`` is a ``PlatformOverride()``-with-no-
        fields (= "supported on this OS, identical to default"),
        the toggle is off but the form retains any field values
        that previously sat there (so a re-enable doesn't wipe
        the work).  No fields are populated from an empty
        override -- there's nothing to populate.

        When ``override`` has at least one non-None field, the
        toggle goes on and the form fields are populated.
        """
        # Block ``changed`` while we mutate widgets programmatically.
        self.blockSignals(True)
        try:
            if override is None:
                self._override_cb.setChecked(False)
                # Don't clear -- preserve any in-progress edits.
                self._sync_enabled(False)
                self._preserved_env = None
                self._preserved_actions = None
                return

            # ``override`` is a PlatformOverride.  Even when every
            # field is None we treat the *presence* of the entry
            # as "supported" -- but with no toggleable content, we
            # leave the toggle off.  When ANY field is non-None
            # the toggle goes on.
            has_any = any(
                getattr(override, fld) is not None
                for fld in (
                    "executable", "argument_template",
                    "path_prepend",
                )
            )
            self._override_cb.setChecked(has_any)

            # Populate fields.  ``None`` -> empty field (i.e. the
            # toggle is off and the field shows nothing).
            self._exe_edit.setText(
                override.executable
                if override.executable is not None else ""
            )
            from .tool_editor import _template_to_text  # late import
            self._argv_edit.setPlainText(
                _template_to_text(override.argument_template)
                if override.argument_template is not None else ""
            )
            self._paths_edit.setPlainText(
                "\n".join(override.path_prepend)
                if override.path_prepend is not None else ""
            )

            # Preserve any env / actions override the model carries
            # for future round-trip.  Phase 3 UI doesn't show them.
            self._preserved_env = (
                dict(override.env) if override.env is not None
                else None
            )
            self._preserved_actions = (
                list(override.actions)
                if override.actions is not None else None
            )

            self._sync_enabled(has_any)
        finally:
            self.blockSignals(False)

    def to_override(self) -> Any:
        """Materialise the tab's state as a ``PlatformOverride``,
        or ``None`` when the toggle is off (= "remove entry from
        ``tool.platforms``").

        Returns ``PlatformOverride()`` with the right subset of
        non-None fields populated, plus any preserved env /
        actions from the load step.
        """
        from ..core.model import PlatformOverride
        from .tool_editor import _text_to_template  # late import

        if not self._override_cb.isChecked():
            # Toggle off means "no override for this OS" -- the
            # caller drops the entry from ``tool.platforms``.
            return None

        exe = self._exe_edit.text().strip()
        argv_text = self._argv_edit.toPlainText()
        paths_text = self._paths_edit.toPlainText()
        paths = [
            line.strip() for line in paths_text.splitlines()
            if line.strip()
        ]

        # Field-level "None when empty" mapping: an empty field
        # means "inherit default for this field" even though the
        # OS-level toggle is on.  See the PlatformOverride
        # docstring for the per-field replace contract.
        return PlatformOverride(
            executable=(exe or None),
            argument_template=(
                _text_to_template(argv_text)
                if argv_text.strip() else None
            ),
            path_prepend=(paths or None),
            env=self._preserved_env,
            actions=self._preserved_actions,
        )


class PlatformOverridesWidget(QGroupBox):
    """Editor section for per-OS overrides.

    Renders as a collapsible ``QGroupBox`` with three tabs
    (one per OS).  The widget owns its three child ``_OsTab``s
    plus a "Preview as" combo at the bottom.  The combo
    selects which OS the editor's command-line preview should
    resolve against -- emitted via ``previewOsChanged``.

    Two public methods do the data binding (``load_from_tool``
    and ``apply_to_tool``); the editor calls them when loading
    and saving the tool.
    """

    changed = Signal()
    """Emitted whenever the user mutates any tab's state.  The
    editor connects this to its dirty-document marker."""

    previewOsChanged = Signal(str)
    """Emitted with the chosen OS id (``"windows" | "macos" |
    "linux"``) when the "Preview as" combo changes.  The
    editor uses this to drive the live command-line preview."""

    def __init__(self) -> None:
        super().__init__("Per-OS overrides")
        self.setToolTip(
            "Variant Executable / Argument template / PATH prepend "
            "per host OS.  Leave a tab's 'Override' toggle off to "
            "inherit the top-level defaults on that OS."
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # ----- The three OS tabs -------------------------------------
        self._tabs = QTabWidget()
        self._os_tabs: dict[OSId, _OsTab] = {}
        for os_id in OS_IDS:
            tab = _OsTab(os_id)
            tab.changed.connect(self.changed)
            self._tabs.addTab(tab, _OS_LABELS[os_id])
            self._os_tabs[os_id] = tab

        # Default the visible tab to the current host OS so the
        # author sees their own platform first.
        try:
            self._tabs.setCurrentIndex(OS_IDS.index(host_os()))
        except ValueError:
            self._tabs.setCurrentIndex(0)

        layout.addWidget(self._tabs)

        # ----- "Preview as" combo ------------------------------------
        preview_row = QHBoxLayout()
        preview_row.addWidget(QLabel("Preview command line as:"))
        self._preview_combo = QComboBox()
        for os_id in OS_IDS:
            self._preview_combo.addItem(_OS_LABELS[os_id], os_id)
        # Default to host OS (matches the active tab on first open).
        try:
            self._preview_combo.setCurrentIndex(OS_IDS.index(host_os()))
        except ValueError:
            self._preview_combo.setCurrentIndex(0)
        self._preview_combo.currentIndexChanged.connect(self._emit_preview_os)
        preview_row.addWidget(self._preview_combo)
        preview_row.addStretch(1)
        layout.addLayout(preview_row)

    def _emit_preview_os(self, _idx: int) -> None:
        """Translate the combo's index into the canonical OS id
        and re-emit it on ``previewOsChanged`` for the editor's
        preview consumer."""
        os_id = self._preview_combo.currentData()
        if os_id in OS_IDS:
            self.previewOsChanged.emit(str(os_id))

    # ------------------------------------------------------------------
    # Public data-binding API
    # ------------------------------------------------------------------

    def load_from_tool(self, tool: Any) -> None:
        """Rebuild every tab's state from ``tool.platforms``.

        Also refreshes each tab's inherited-preview rows from
        the tool's top-level defaults so the read-only preview
        is accurate the moment the editor opens.
        """
        from .tool_editor import _template_to_text  # late import

        # Refresh inherited previews from top-level defaults.
        top_argv_text = _template_to_text(tool.argument_template)
        for tab in self._os_tabs.values():
            tab.set_inherited(
                executable=tool.executable,
                argument_template_text=top_argv_text,
                path_prepend=list(tool.path_prepend or []),
            )

        # Load per-OS state.
        platforms = tool.platforms or {}
        for os_id, tab in self._os_tabs.items():
            tab.load_from_override(platforms.get(os_id))

    def apply_to_tool(self, tool: Any) -> None:
        """Write every tab's state into ``tool.platforms``.

        A tab whose override toggle is off causes the OS's key
        to be REMOVED from ``tool.platforms``.  A tab whose
        toggle is on writes its non-None fields into a fresh
        ``PlatformOverride`` (preserving any env / actions that
        were already on the override and aren't editable here).
        """
        if tool.platforms is None:
            tool.platforms = {}
        for os_id, tab in self._os_tabs.items():
            override = tab.to_override()
            if override is None:
                tool.platforms.pop(os_id, None)
            else:
                tool.platforms[os_id] = override

    # ------------------------------------------------------------------
    # Live-refresh hook for the inherited previews.
    # ------------------------------------------------------------------

    def refresh_inherited(
        self,
        *,
        executable: str,
        argument_template_text: str,
        path_prepend: list[str],
    ) -> None:
        """Update every tab's read-only preview rows.

        The editor calls this whenever the user edits the top-
        level Executable / argument_template / path_prepend
        fields so the inherited-preview stays current without
        a full ``load_from_tool`` cycle (which would clobber
        any in-progress edits on the override tabs).
        """
        for tab in self._os_tabs.values():
            tab.set_inherited(
                executable=executable,
                argument_template_text=argument_template_text,
                path_prepend=path_prepend,
            )

    def current_preview_os(self) -> OSId:
        """The OS id currently selected in the 'Preview as'
        combo, or the host OS as a defensive fallback."""
        data = self._preview_combo.currentData()
        if data in OS_IDS:
            return str(data)  # type: ignore[return-value]
        return host_os()


__all__ = ["PlatformOverridesWidget"]
