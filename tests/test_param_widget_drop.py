"""Tests for drag-and-drop file/folder support in param widgets.

The drop handling is split into two layers:

* ``_apply_line_edit_drop`` / ``_apply_plain_text_drop`` — pure logic
  that takes a ``QLineEdit`` / ``QPlainTextEdit`` plus a ``QMimeData``
  and writes the dropped paths in the right shape. This is what the
  tests exercise.
* ``_DroppableLineEdit`` / ``_DroppablePlainTextEdit`` — Qt event
  glue that calls those helpers on real drag/drop events. Verified
  by hand in production; not unit-tested because PySide6 cannot
  reliably round-trip a ``QMimeData`` through a Python-built
  ``QDropEvent`` (the const-pointer return loses concrete type).

The factory tests confirm the build_widget_for path actually
produces droppable subclasses for TEXT, TEXTAREA, FILE_OPEN,
FILE_SAVE, and FOLDER widgets.
"""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit

_app = QApplication.instance() or QApplication([])

from scriptree.core.model import ParamDef, ParamType, Widget  # noqa: E402
from scriptree.ui.widgets.param_widgets import (  # noqa: E402
    FileOpenWidget,
    FileSaveWidget,
    FolderWidget,
    TextAreaWidget,
    TextWidget,
    _apply_line_edit_drop,
    _apply_plain_text_drop,
    _DroppableLineEdit,
    _DroppablePlainTextEdit,
    _local_paths_from_mime,
)


def _mime_with_files(*paths: str) -> QMimeData:
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return md


def _mime_with_text(text: str) -> QMimeData:
    md = QMimeData()
    md.setText(text)
    return md


# --- _local_paths_from_mime -------------------------------------------------

def test_local_paths_extracts_file_urls() -> None:
    md = _mime_with_files("C:/tmp/foo.txt", "C:/tmp/bar.txt")
    paths = _local_paths_from_mime(md)
    norm = [p.replace("\\", "/") for p in paths]
    assert any(p.endswith("/tmp/foo.txt") for p in norm)
    assert any(p.endswith("/tmp/bar.txt") for p in norm)


def test_local_paths_skips_non_file_urls() -> None:
    md = QMimeData()
    md.setUrls([QUrl("https://example.com/foo")])
    assert _local_paths_from_mime(md) == []


def test_local_paths_text_only_returns_empty() -> None:
    md = _mime_with_text("just text")
    assert _local_paths_from_mime(md) == []


def test_local_paths_handles_unwrapped_qobject() -> None:
    """When PySide6 hands us a base QObject (no hasUrls method), the
    helper must return [] rather than crash."""
    class _Bare:
        pass
    assert _local_paths_from_mime(_Bare()) == []


# --- _apply_line_edit_drop -------------------------------------------------

def test_line_edit_apply_replaces_with_first_path() -> None:
    edit = QLineEdit("preexisting")
    consumed = _apply_line_edit_drop(
        edit, _mime_with_files("C:/a/one.txt", "C:/a/two.txt")
    )
    assert consumed is True
    assert edit.text().replace("\\", "/").endswith("/a/one.txt")


def test_line_edit_apply_folder_path() -> None:
    edit = QLineEdit("")
    consumed = _apply_line_edit_drop(
        edit, _mime_with_files("C:/some/folder")
    )
    assert consumed is True
    assert edit.text().replace("\\", "/").endswith("/some/folder")


def test_line_edit_apply_no_files_returns_false() -> None:
    edit = QLineEdit("keep me")
    consumed = _apply_line_edit_drop(edit, _mime_with_text("hello"))
    assert consumed is False
    assert edit.text() == "keep me"


# --- _apply_plain_text_drop ------------------------------------------------

def test_plain_text_apply_inserts_at_cursor() -> None:
    edit = QPlainTextEdit("first line\n")
    cur = edit.textCursor()
    cur.movePosition(cur.MoveOperation.End)
    edit.setTextCursor(cur)

    consumed = _apply_plain_text_drop(
        edit, _mime_with_files("C:/foo.txt")
    )
    assert consumed is True
    text = edit.toPlainText().replace("\\", "/")
    assert text.startswith("first line\n")
    assert "/foo.txt" in text


def test_plain_text_apply_multi_file_one_per_line() -> None:
    edit = QPlainTextEdit("")
    consumed = _apply_plain_text_drop(
        edit, _mime_with_files("C:/a.txt", "C:/b.txt", "C:/c.txt")
    )
    assert consumed is True
    text = edit.toPlainText().replace("\\", "/")
    assert "/a.txt" in text
    assert "/b.txt" in text
    assert "/c.txt" in text
    # Three paths -> at least two newlines between them.
    assert text.count("\n") >= 2


def test_plain_text_apply_no_files_returns_false() -> None:
    edit = QPlainTextEdit("keep me")
    consumed = _apply_plain_text_drop(edit, _mime_with_text("hello"))
    assert consumed is False
    assert edit.toPlainText() == "keep me"


# --- factory wiring --------------------------------------------------------

def test_text_widget_uses_droppable_line_edit() -> None:
    p = ParamDef(id="x", label="X", type=ParamType.STRING, widget=Widget.TEXT)
    w = TextWidget(p)
    assert isinstance(w._edit, _DroppableLineEdit)
    # Subclass of QLineEdit -> all existing QLineEdit APIs still work.
    assert isinstance(w._edit, QLineEdit)


def test_textarea_widget_uses_droppable_plain_text() -> None:
    p = ParamDef(
        id="x", label="X", type=ParamType.STRING, widget=Widget.TEXTAREA
    )
    w = TextAreaWidget(p)
    assert isinstance(w._edit, _DroppablePlainTextEdit)
    assert isinstance(w._edit, QPlainTextEdit)


def test_file_open_widget_uses_droppable_line_edit() -> None:
    p = ParamDef(
        id="x", label="X", type=ParamType.PATH, widget=Widget.FILE_OPEN
    )
    w = FileOpenWidget(p)
    assert isinstance(w._edit, _DroppableLineEdit)


def test_file_save_widget_uses_droppable_line_edit() -> None:
    p = ParamDef(
        id="x", label="X", type=ParamType.PATH, widget=Widget.FILE_SAVE
    )
    w = FileSaveWidget(p)
    assert isinstance(w._edit, _DroppableLineEdit)


def test_folder_widget_uses_droppable_line_edit() -> None:
    p = ParamDef(id="x", label="X", type=ParamType.PATH, widget=Widget.FOLDER)
    w = FolderWidget(p)
    assert isinstance(w._edit, _DroppableLineEdit)
