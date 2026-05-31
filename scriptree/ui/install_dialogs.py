"""Qt dialogs for the drop-install workflow (v0.8.0a23+).

## For humans

Two modal dialogs that sit between the forest cell's drop
handler and ``scriptree.core.app_install``'s pure-logic
install function:

* ``InstallLocationDialog`` — first dialog after a drop is
  detected.  Shows the app name inferred from the source +
  three radio options (Shared / Personal / Browse) with the
  resolved target path under each.  User clicks Install (the
  primary action) or Cancel.

* ``InstallConflictDialog`` — second dialog, fired only when
  the chosen target folder already exists.  Four actions:
  Overwrite / Update (preserve user sidecars) / Rename
  (next available ``-N`` slot) / Cancel.

Both dialogs are stateless data-collectors: they don't touch
the filesystem.  The caller composes them with the core
install function:

    loc = InstallLocationDialog(parent, source)
    if loc.exec() != QDialog.Accepted:
        return
    target_root = loc.chosen_root()

    try:
        result = install_app(source, target_root)
    except InstallError as exc:
        if "already exists" in str(exc):
            cdlg = InstallConflictDialog(parent, source.name)
            if cdlg.exec() != QDialog.Accepted:
                return
            result = install_app(
                source, target_root,
                conflict_mode=cdlg.chosen_mode(),
            )

The exact orchestration is the Phase-3 drop-handler's job;
this module just provides the building blocks.

## For maintainers / LLMs

* Module is in ``scriptree.ui`` because it imports PySide6.
  ``scriptree.core.app_install`` stays headless.
* Both dialogs use ``QFormLayout`` + ``QButtonGroup`` so the
  radio selections stay mutually exclusive without manual
  group-management.
* The path-preview labels under each Location radio update
  live with the inferred app name -- if the user types a
  different name in the (optional) "Install as:" field, the
  Shared / Personal previews update so the user can SEE
  exactly where files will land before clicking Install.
* Browse uses ``QFileDialog.getExistingDirectory`` against
  the previously-selected Browse path (or the user's home
  directory on first open) so successive Browse clicks don't
  re-anchor at ``C:\\``.
* The Conflict dialog presents Update as the default action
  (most users want to preserve their sidecars during an
  upgrade); Rename is the safest second-choice; Overwrite is
  the destructive option and gets a yellow warning label;
  Cancel always closes without changes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ..core.app_install import (
    ConflictMode,
    default_personal_root,
    default_shared_root,
    infer_app_name,
)


# ---------------------------------------------------------------------------
# InstallLocationDialog
# ---------------------------------------------------------------------------

# Sentinel values stored as the radio buttons' ``data()`` -- safer than
# string-typing them everywhere.
_LOC_SHARED = "shared"
_LOC_PERSONAL = "personal"
_LOC_BROWSE = "browse"


class InstallLocationDialog(QDialog):
    """Choose where to install a dropped folder or zip.

    Shows three radio options (Shared / Personal / Browse) with
    the resolved target path under each.  Live updates: if the
    user edits the "Install as:" field, every path preview
    refreshes so the final destination is always visible
    before clicking Install.

    Result via ``chosen_root()`` (the install root, e.g.
    ``R:\\Scriptreeapps``) and ``chosen_app_name()`` (the
    folder name to create under that root).  Caller composes
    them into ``<root>/<name>/``.

    Returns ``QDialog.Accepted`` on Install, ``QDialog.Rejected``
    on Cancel.  Caller must check the return value before
    reading the chosen-* methods.
    """

    def __init__(self, parent: QWidget | None, source: Path) -> None:
        super().__init__(parent)
        self._source = source
        self._inferred_name = infer_app_name(source)
        # The path the user picked in a Browse dialog; empty
        # until they click Browse and choose.  Used as both the
        # "Other" radio's display path and as the resolved root
        # when that radio is selected.
        self._browsed_path: Path | None = None

        self.setWindowTitle("Install ScripTree app")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"<b>Install <code>{source.name}</code> as a ScripTree app.</b>"
        ))

        # Name field (optional).  Defaults to the inferred name;
        # the user can override.
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Install as:"))
        self._name_edit = QLineEdit(self._inferred_name)
        self._name_edit.setToolTip(
            "The folder name to create under the chosen install "
            "root.  Defaults to the dropped item's name with "
            "filesystem-unsafe characters scrubbed."
        )
        self._name_edit.textChanged.connect(self._refresh_previews)
        name_row.addWidget(self._name_edit, stretch=1)
        layout.addLayout(name_row)

        # ----- Location radios + path previews ----------------------
        loc_box = QGroupBox("Install to")
        loc_layout = QVBoxLayout(loc_box)

        self._group = QButtonGroup(self)

        # Shared.
        shared_row = self._build_radio_row(
            _LOC_SHARED,
            "Shared",
            default_shared_root(),
        )
        loc_layout.addLayout(shared_row)

        # Personal.
        personal_row = self._build_radio_row(
            _LOC_PERSONAL,
            "Personal (per-user)",
            default_personal_root(),
        )
        loc_layout.addLayout(personal_row)

        # Browse.
        browse_row = QHBoxLayout()
        self._browse_radio = QRadioButton("Other...")
        self._browse_radio.setProperty("loc", _LOC_BROWSE)
        self._group.addButton(self._browse_radio)
        browse_row.addWidget(self._browse_radio)
        self._browse_path_label = QLabel("(click Browse to pick)")
        self._browse_path_label.setStyleSheet("color: #666;")
        browse_row.addWidget(self._browse_path_label, stretch=1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._on_browse)
        browse_row.addWidget(browse_btn)
        loc_layout.addLayout(browse_row)

        layout.addWidget(loc_box)

        # Default radio: Shared (recommended).  See the design-
        # decision question 1 answers -- both shared + personal
        # are sensible defaults; we pick Shared as the recommended
        # first choice.
        self._shared_radio.setChecked(True)

        # Buttons.
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel,
        )
        install_btn = QPushButton("Install")
        install_btn.setDefault(True)
        btn_box.addButton(
            install_btn, QDialogButtonBox.ButtonRole.AcceptRole,
        )
        layout.addWidget(btn_box)
        btn_box.rejected.connect(self.reject)
        install_btn.clicked.connect(self._on_install)

        self._refresh_previews()

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    def _build_radio_row(
        self,
        loc_id: str,
        label_text: str,
        root: Path,
    ) -> QHBoxLayout:
        """Build a row with a radio + its target-path preview.

        The radio is added to ``self._group``; the preview
        label is stashed on the instance under
        ``self._<loc_id>_preview`` so ``_refresh_previews`` can
        update it when the name field changes.
        """
        row = QHBoxLayout()
        rb = QRadioButton(label_text)
        rb.setProperty("loc", loc_id)
        rb.setProperty("root", str(root))
        self._group.addButton(rb)
        row.addWidget(rb)
        preview = QLabel("")
        preview.setStyleSheet("color: #444; font-family: Consolas, monospace;")
        preview.setWordWrap(True)
        row.addWidget(preview, stretch=1)
        # Stash both the radio AND the preview on the instance
        # under canonical names so other methods can find them.
        setattr(self, f"_{loc_id}_radio", rb)
        setattr(self, f"_{loc_id}_preview", preview)
        return row

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_browse(self) -> None:
        """Open a folder picker; on success, select the Other
        radio and refresh previews."""
        seed = (
            str(self._browsed_path)
            if self._browsed_path is not None else str(Path.home())
        )
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Pick install root",
            seed,
        )
        if not chosen:
            return  # user cancelled the browse
        self._browsed_path = Path(chosen)
        self._browse_radio.setChecked(True)
        self._refresh_previews()

    def _refresh_previews(self) -> None:
        """Refresh the three preview labels to reflect the
        current "Install as:" name."""
        name = self._name_edit.text().strip() or self._inferred_name
        shared_root = Path(
            self._shared_radio.property("root") or default_shared_root()
        )
        personal_root = Path(
            self._personal_radio.property("root")
            or default_personal_root()
        )
        self._shared_preview.setText(str(shared_root / name))
        self._personal_preview.setText(str(personal_root / name))
        if self._browsed_path is not None:
            self._browse_path_label.setText(
                str(self._browsed_path / name)
            )
        else:
            self._browse_path_label.setText("(click Browse to pick)")

    def _on_install(self) -> None:
        """Validate state before accepting.  If Other is
        selected but no path was browsed, refuse and ask the
        user to pick a folder."""
        if (
            self._browse_radio.isChecked()
            and self._browsed_path is None
        ):
            # Don't accept; bounce back to Browse.
            self._browse_path_label.setText(
                "(please click Browse and pick a folder)"
            )
            self._browse_path_label.setStyleSheet("color: #c00;")
            return
        self.accept()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chosen_root(self) -> Path:
        """Return the install root the user selected.

        Always returns an absolute resolved Path.  Caller should
        only call this after ``exec()`` returns ``Accepted``.
        """
        if self._shared_radio.isChecked():
            return Path(
                self._shared_radio.property("root")
                or default_shared_root()
            ).resolve()
        if self._personal_radio.isChecked():
            return Path(
                self._personal_radio.property("root")
                or default_personal_root()
            ).resolve()
        if self._browse_radio.isChecked() and self._browsed_path:
            return self._browsed_path.resolve()
        # Defensive fallback: shouldn't happen with the
        # validation in _on_install, but if it does just use the
        # shared default.
        return default_shared_root().resolve()

    def chosen_app_name(self) -> str:
        """Return the (sanitised) folder name the user wants.

        The "Install as:" field starts populated from
        ``infer_app_name(source)`` -- which already scrubs
        unsafe chars.  If the user edits it, we re-scrub via
        the same helper so a hand-typed ``foo:bar`` doesn't
        produce a target the FS would reject.
        """
        raw = self._name_edit.text().strip() or self._inferred_name
        # Re-scrub through the same sanitiser the core uses for
        # consistency.  ``infer_app_name`` expects a Path; build
        # a throwaway one with the raw name so the function's
        # branch on dir-vs-file doesn't matter (a non-existent
        # path returns ``.stem``, which equals the name in this
        # context).
        return infer_app_name(Path(raw))


# ---------------------------------------------------------------------------
# InstallConflictDialog
# ---------------------------------------------------------------------------

class InstallConflictDialog(QDialog):
    """Choose how to handle a target folder that already exists.

    Four actions:

    * **Update** (default) — replace files that exist in the
      source; LEAVE intact files that only exist at the
      target (the user-edited-sidecar preserve case).
    * **Rename** — install to ``<name>-2`` (or next available).
    * **Overwrite** — destructive; deletes the existing target
      and re-creates from source.  Shown with a yellow warning
      colour so the user sees the destructive nature.
    * **Cancel** — close without installing.

    Result via ``chosen_mode()``: returns a ``ConflictMode``
    value matching what the user picked.  ``QDialog.Rejected``
    return = Cancel (caller should treat as "do nothing").
    """

    def __init__(
        self,
        parent: QWidget | None,
        app_name: str,
        existing_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._chosen: ConflictMode | None = None

        self.setWindowTitle(f"Already installed — {app_name}")
        self.setMinimumWidth(540)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"<b>The folder <code>{app_name}</code> already exists "
            f"in the install location.</b>"
        ))
        if existing_path is not None:
            existing_label = QLabel(str(existing_path))
            existing_label.setStyleSheet(
                "color: #444; font-family: Consolas, monospace;"
            )
            layout.addWidget(existing_label)

        layout.addWidget(QLabel("How would you like to proceed?"))

        # Four radio options.
        self._group = QButtonGroup(self)

        self._rb_update = QRadioButton(
            "Update — replace files in the source; keep your "
            "user-edited files (sidecars, configs)"
        )
        self._rb_update.setToolTip(
            "Per-file: any file that exists in the source replaces "
            "the version at the target; any file that exists at "
            "the target but not in the source is left intact.  "
            "Safest for routine upgrades."
        )
        self._rb_update.setChecked(True)
        self._group.addButton(self._rb_update)
        layout.addWidget(self._rb_update)

        self._rb_rename = QRadioButton(
            "Rename — install as a new copy alongside the existing one"
        )
        self._rb_rename.setToolTip(
            f"Install to ``{app_name}-2`` (or the next available "
            f"numbered slot).  The existing copy is untouched.  "
            f"Use when you want both versions side-by-side."
        )
        self._group.addButton(self._rb_rename)
        layout.addWidget(self._rb_rename)

        self._rb_overwrite = QRadioButton(
            "Overwrite — replace everything (delete existing, "
            "extract fresh)"
        )
        self._rb_overwrite.setStyleSheet(
            "QRadioButton { color: #b58900; }"  # yellow warning hue
        )
        self._rb_overwrite.setToolTip(
            "DESTRUCTIVE: every file in the existing install is "
            "deleted, then the source is copied / extracted fresh.  "
            "Use only when you intend to wipe the old install."
        )
        self._group.addButton(self._rb_overwrite)
        layout.addWidget(self._rb_overwrite)

        # Buttons.
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel,
        )
        proceed_btn = QPushButton("Proceed")
        proceed_btn.setDefault(True)
        btn_box.addButton(
            proceed_btn, QDialogButtonBox.ButtonRole.AcceptRole,
        )
        layout.addWidget(btn_box)
        btn_box.rejected.connect(self._on_cancel)
        proceed_btn.clicked.connect(self._on_proceed)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_proceed(self) -> None:
        if self._rb_overwrite.isChecked():
            self._chosen = ConflictMode.OVERWRITE
        elif self._rb_rename.isChecked():
            self._chosen = ConflictMode.RENAME
        else:
            self._chosen = ConflictMode.UPDATE
        self.accept()

    def _on_cancel(self) -> None:
        self._chosen = ConflictMode.CANCEL
        self.reject()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chosen_mode(self) -> ConflictMode:
        """Return the user's selection.

        ``CANCEL`` is returned both when the dialog was rejected
        (Cancel button or Esc) and when the dialog hasn't been
        executed yet -- callers should rely on ``exec()``'s
        return value as the primary signal.
        """
        return self._chosen or ConflictMode.CANCEL


__all__ = [
    "InstallConflictDialog",
    "InstallLocationDialog",
]
