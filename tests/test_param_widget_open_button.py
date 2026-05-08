"""Tests for the v0.3.9 form-field UX fixes.

Two independent additions to ``scriptree.ui.widgets.param_widgets``:

1. **Checkbox vertical alignment** — ``CheckboxWidget`` now wraps
   the bare ``QCheckBox`` in a vertical layout with a top pad
   computed from ``QFontMetrics(label).lineSpacing()`` so the
   indicator's centre aligns with the first text line's centre,
   even when the description wraps to multiple lines.

2. **Open button on path widgets** — ``_PathPickerBase`` now has
   an ``Open`` button next to ``Browse``.  Clicking it opens the
   path's location in the OS file browser; if the path doesn't
   exist, walks up the parent chain to the closest ancestor that
   does.  The line-edit text is **never** modified.

The Open button's subprocess call is mocked so the tests don't
spawn real Explorer / Finder windows.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from PySide6.QtWidgets import QApplication, QPushButton

_app = QApplication.instance() or QApplication([])

from scriptree.core.model import ParamDef, ParamType, Widget
from scriptree.ui.widgets.param_widgets import (
    CheckboxWidget,
    FileOpenWidget,
    FileSaveWidget,
    FolderWidget,
)


# ===========================================================================
# Checkbox vertical alignment
# ===========================================================================

class TestCheckboxAlignment:

    def _make(self) -> CheckboxWidget:
        param = ParamDef(
            id="agree",
            label="Agree",
            type=ParamType.BOOL,
            widget=Widget.CHECKBOX,
            description="Agree to the terms and conditions of this hypothetical software.",
        )
        return CheckboxWidget(param)

    def test_constructs_without_error(self) -> None:
        w = self._make()
        # Box and label both reachable.
        assert w._box is not None
        assert w._desc_label is not None
        w.close()

    def test_box_held_in_top_aligned_wrapper(self) -> None:
        """The post-fix structure: the QCheckBox lives inside a
        vertical-layout wrapper widget so a top-pad spacer can offset
        the indicator down to the first-line centre."""
        w = self._make()
        # The QCheckBox's parent is the wrapper, NOT the row layout.
        assert w._box.parentWidget() is not w
        w.close()

    def test_label_top_aligned(self) -> None:
        from PySide6.QtCore import Qt
        w = self._make()
        # Label is top-aligned (so multi-line wrapping flows downward
        # from a fixed top edge, matching the indicator).
        assert (
            w._desc_label.alignment() & Qt.AlignmentFlag.AlignTop
            == Qt.AlignmentFlag.AlignTop
        )
        w.close()

    def test_top_pad_within_reasonable_range(self) -> None:
        """The pad must be non-negative and not absurdly large.
        Sanity bound — anything outside [0, 30] would mean the font
        metric or box hint is broken."""
        w = self._make()
        wrapper = w._box.parentWidget()
        assert wrapper is not None
        margins = wrapper.layout().contentsMargins()
        assert 0 <= margins.top() <= 30
        # Other margins are zero so the wrapper doesn't shift the box
        # horizontally or pad the bottom.
        assert margins.left() == 0
        assert margins.right() == 0
        assert margins.bottom() == 0
        w.close()

    def test_clicking_label_still_toggles(self) -> None:
        """Regression — moving the box into a wrapper must not break
        the click-on-label behaviour."""
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        w = self._make()
        before = w._box.isChecked()
        ev = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(5, 5),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        w._on_label_mouse_press(ev)
        assert w._box.isChecked() == (not before)
        w.close()


# ===========================================================================
# Open button on path widgets
# ===========================================================================

def _file_param() -> ParamDef:
    return ParamDef(
        id="f", label="F",
        type=ParamType.PATH, widget=Widget.FILE_OPEN,
    )


def _save_param() -> ParamDef:
    return ParamDef(
        id="f", label="F",
        type=ParamType.PATH, widget=Widget.FILE_SAVE,
    )


def _folder_param() -> ParamDef:
    return ParamDef(
        id="d", label="D",
        type=ParamType.PATH, widget=Widget.FOLDER,
    )


class TestPathPickerOpenButtonPresent:

    def test_file_open_has_open_button(self) -> None:
        w = FileOpenWidget(_file_param())
        assert isinstance(w._btn_open, QPushButton)
        assert w._btn_open.text() == "Open"
        w.close()

    def test_file_save_has_open_button(self) -> None:
        w = FileSaveWidget(_save_param())
        assert isinstance(w._btn_open, QPushButton)
        w.close()

    def test_folder_has_open_button(self) -> None:
        w = FolderWidget(_folder_param())
        assert isinstance(w._btn_open, QPushButton)
        w.close()

    def test_browse_button_still_present(self) -> None:
        """Open is added next to Browse, not replacing it."""
        w = FileOpenWidget(_file_param())
        assert w._btn.text() == "Browse..."
        w.close()

    def test_file_open_has_open_file_button(self) -> None:
        """File fields get a SECOND button — 'Open file' — that
        launches the file with its OS default app (double-click
        equivalent)."""
        w = FileOpenWidget(_file_param())
        assert hasattr(w, "_btn_open_file")
        assert isinstance(w._btn_open_file, QPushButton)
        assert w._btn_open_file.text() == "Open file"
        w.close()

    def test_file_save_has_open_file_button(self) -> None:
        w = FileSaveWidget(_save_param())
        assert hasattr(w, "_btn_open_file")
        assert w._btn_open_file.text() == "Open file"
        w.close()

    def test_folder_does_not_have_open_file_button(self) -> None:
        """Folder fields don't need a separate file-open button —
        their single 'Open' button already does the right thing."""
        w = FolderWidget(_folder_param())
        assert not hasattr(w, "_btn_open_file")
        w.close()


class TestResolveOpenTarget:
    """``_resolve_open_target`` is the pure logic driving the Open
    button — what does it open for a given line-edit value?"""

    def test_empty_returns_none(self) -> None:
        w = FolderWidget(_folder_param())
        w._edit.setText("")
        assert w._resolve_open_target() is None
        w.close()

    def test_existing_file_returns_parent(self, tmp_path: Path) -> None:
        f = tmp_path / "data.txt"
        f.write_text("x", encoding="utf-8")
        w = FileOpenWidget(_file_param())
        w._edit.setText(str(f))
        assert w._resolve_open_target() == str(tmp_path)
        w.close()

    def test_existing_dir_returns_dir(self, tmp_path: Path) -> None:
        w = FolderWidget(_folder_param())
        w._edit.setText(str(tmp_path))
        assert w._resolve_open_target() == str(tmp_path)
        w.close()

    def test_nonexistent_walks_up_to_existing_ancestor(
        self, tmp_path: Path,
    ) -> None:
        # tmp_path/foo/bar/baz.txt — only tmp_path exists.
        target = tmp_path / "foo" / "bar" / "baz.txt"
        w = FileSaveWidget(_save_param())
        w._edit.setText(str(target))
        # No "foo" / "bar" exists yet; ancestor must be tmp_path.
        assert w._resolve_open_target() == str(tmp_path)
        w.close()

    def test_nonexistent_with_existing_intermediate(
        self, tmp_path: Path,
    ) -> None:
        # tmp_path/foo exists; tmp_path/foo/bar does not.
        (tmp_path / "foo").mkdir()
        target = tmp_path / "foo" / "bar" / "missing.dat"
        w = FileSaveWidget(_save_param())
        w._edit.setText(str(target))
        assert w._resolve_open_target() == str(tmp_path / "foo")
        w.close()

    def test_open_does_not_modify_field(self, tmp_path: Path) -> None:
        """Per the user spec: Open never changes the path text,
        even when the displayed path doesn't exist and we end up
        opening an ancestor."""
        target = tmp_path / "missing" / "deeper" / "x.txt"
        w = FileSaveWidget(_save_param())
        w._edit.setText(str(target))
        before = w._edit.text()
        with patch("subprocess.Popen") as m_popen:
            w._open_in_explorer()
        # Popen called exactly once with a list whose argv[1] is the
        # ancestor we expect.
        m_popen.assert_called_once()
        argv = m_popen.call_args.args[0]
        assert argv[1] == str(tmp_path)
        # Field text untouched.
        assert w._edit.text() == before
        w.close()


class TestOpenButtonSubprocessDispatch:

    def test_empty_field_does_not_spawn(self) -> None:
        w = FolderWidget(_folder_param())
        w._edit.setText("")
        with patch("subprocess.Popen") as m_popen:
            w._open_in_explorer()
        m_popen.assert_not_called()
        w.close()

    @pytest.mark.skipif(
        sys.platform != "win32", reason="Windows-specific argv check"
    )
    def test_windows_spawns_explorer(self, tmp_path: Path) -> None:
        w = FolderWidget(_folder_param())
        w._edit.setText(str(tmp_path))
        with patch("subprocess.Popen") as m_popen:
            w._open_in_explorer()
        argv = m_popen.call_args.args[0]
        assert argv[0] == "explorer"
        assert argv[1] == str(tmp_path)
        w.close()

    def test_oserror_swallowed(self, tmp_path: Path) -> None:
        """Open is a convenience — a missing file browser must NOT
        propagate an exception that would abort the user's work."""
        w = FolderWidget(_folder_param())
        w._edit.setText(str(tmp_path))
        with patch("subprocess.Popen", side_effect=OSError("nope")):
            # Should not raise.
            w._open_in_explorer()
        w.close()


class TestOpenFileInDefaultApp:
    """The 'Open file' button on file-picker widgets — launches the
    file with its OS default app (Explorer double-click equivalent)."""

    def test_empty_field_no_op(self) -> None:
        w = FileOpenWidget(_file_param())
        w._edit.setText("")
        with patch("os.startfile") as m_startfile, \
             patch("subprocess.Popen") as m_popen:
            w._open_file_in_default_app()
        assert not m_startfile.called
        assert not m_popen.called
        w.close()

    def test_nonexistent_path_no_op(self, tmp_path: Path) -> None:
        """If the file doesn't exist (e.g. user is mid-typing or
        planning a save target), Open file is a silent no-op — the
        path is NOT created and no app is launched."""
        target = tmp_path / "definitely_missing.txt"
        w = FileOpenWidget(_file_param())
        w._edit.setText(str(target))
        with patch("os.startfile") as m_startfile, \
             patch("subprocess.Popen") as m_popen:
            w._open_file_in_default_app()
        assert not m_startfile.called
        assert not m_popen.called
        # And critically: the file was NOT auto-created.
        assert not target.exists()
        w.close()

    @pytest.mark.skipif(
        sys.platform != "win32",
        reason="os.startfile is Windows-only",
    )
    def test_existing_file_dispatches_via_startfile_on_windows(
        self, tmp_path: Path,
    ) -> None:
        f = tmp_path / "data.txt"
        f.write_text("hello", encoding="utf-8")
        w = FileOpenWidget(_file_param())
        w._edit.setText(str(f))
        with patch("os.startfile") as m_startfile:
            w._open_file_in_default_app()
        m_startfile.assert_called_once_with(str(f))
        w.close()

    def test_open_file_does_not_modify_field(self, tmp_path: Path) -> None:
        f = tmp_path / "data.txt"
        f.write_text("hello", encoding="utf-8")
        w = FileOpenWidget(_file_param())
        w._edit.setText(str(f))
        before = w._edit.text()
        with patch("os.startfile"), patch("subprocess.Popen"):
            w._open_file_in_default_app()
        assert w._edit.text() == before
        w.close()

    def test_folder_falls_back_to_explorer(self, tmp_path: Path) -> None:
        """If the user typed a folder path into a file field and
        clicks 'Open file', open the folder in the file browser
        instead of erroring — same fallback as Explorer's own
        double-click behaviour for directories."""
        w = FileOpenWidget(_file_param())
        w._edit.setText(str(tmp_path))
        with patch("os.startfile") as m_startfile, \
             patch("subprocess.Popen") as m_popen:
            w._open_file_in_default_app()
        # Folder path → location-open dispatch (NOT startfile).
        assert not m_startfile.called
        m_popen.assert_called_once()
        w.close()

    def test_oserror_swallowed(self, tmp_path: Path) -> None:
        """Same defensive contract as the folder Open button —
        startfile / xdg-open failures must NOT propagate."""
        f = tmp_path / "data.txt"
        f.write_text("x", encoding="utf-8")
        w = FileOpenWidget(_file_param())
        w._edit.setText(str(f))
        with patch("os.startfile", side_effect=OSError("no app")):
            w._open_file_in_default_app()  # must not raise
        w.close()
