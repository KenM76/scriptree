"""Tests for the v0.6.28 ``folder_list`` / ``file_list`` widgets and
their schema additions (``must_exist`` / ``min_items`` / ``max_items``).

Covers:

  * Model: enum values + VALID_WIDGETS entry for MULTISELECT.
  * ParamDef: defaults are ``must_exist=False, min_items=0,
    max_items=None`` so legacy params stay unaffected.
  * IO round-trip: byte-stable when at defaults; preserved when set.
  * Widget (Qt-backed via ``pytestqt`` when present, manual when not):
      - ``get_value`` returns ``list[str]`` in row order.
      - ``set_value`` replaces the list and tolerates non-list inputs.
      - ``_add_path`` de-dups, honours ``max_items`` cap.
      - ``must_exist`` rejects non-existent paths added via ``_add_path``
        (interactively); a default / config-loaded list still loads.
      - The Up / Down buttons swap entries.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scriptree.core.io import (
    _param_from_dict, _param_to_dict, load_tool, save_tool,
)
from scriptree.core.model import (
    ParamDef, ParamType, ToolDef, VALID_WIDGETS, Widget,
)


# ===========================================================================
# Model + IO
# ===========================================================================

class TestModelEnumAdditions:

    def test_folder_list_widget_exists(self) -> None:
        assert Widget("folder_list") is Widget.FOLDER_LIST

    def test_file_list_widget_exists(self) -> None:
        assert Widget("file_list") is Widget.FILE_LIST

    def test_both_legal_for_multiselect(self) -> None:
        legal = VALID_WIDGETS[ParamType.MULTISELECT]
        assert Widget.FOLDER_LIST in legal
        assert Widget.FILE_LIST in legal

    def test_folder_list_illegal_for_string(self) -> None:
        # Constructing a ParamDef with an illegal type/widget pair
        # must raise — same contract every other widget honours.
        with pytest.raises(ValueError, match="not valid for type"):
            ParamDef(
                id="x", type=ParamType.STRING,
                widget=Widget.FOLDER_LIST,
            )


class TestParamDefDefaults:

    def test_must_exist_defaults_false(self) -> None:
        p = ParamDef(
            id="folders", type=ParamType.MULTISELECT,
            widget=Widget.FOLDER_LIST, default=[],
        )
        assert p.must_exist is False
        assert p.min_items == 0
        assert p.max_items is None

    def test_min_max_round_trip(self) -> None:
        p = ParamDef(
            id="folders", type=ParamType.MULTISELECT,
            widget=Widget.FOLDER_LIST, default=[],
            must_exist=True, min_items=1, max_items=4,
        )
        assert p.must_exist is True
        assert p.min_items == 1
        assert p.max_items == 4


class TestIORoundTrip:

    def test_defaults_byte_identical(self) -> None:
        """A folder_list param with the new fields at defaults must
        not emit must_exist / min_items / max_items — legacy compact
        form."""
        p = ParamDef(
            id="folders", type=ParamType.MULTISELECT,
            widget=Widget.FOLDER_LIST, default=[],
        )
        d = _param_to_dict(p)
        assert d["widget"] == "folder_list"
        assert "must_exist" not in d
        assert "min_items" not in d
        assert "max_items" not in d

    def test_non_default_fields_emitted(self) -> None:
        p = ParamDef(
            id="folders", type=ParamType.MULTISELECT,
            widget=Widget.FOLDER_LIST, default=[],
            must_exist=True, min_items=1, max_items=10,
        )
        d = _param_to_dict(p)
        assert d["must_exist"] is True
        assert d["min_items"] == 1
        assert d["max_items"] == 10

    def test_round_trip_through_dict(self) -> None:
        p = ParamDef(
            id="files", type=ParamType.MULTISELECT,
            widget=Widget.FILE_LIST, default=["a.txt", "b.txt"],
            file_filter="Text (*.txt);;All (*)",
            must_exist=False, min_items=0, max_items=8,
        )
        d = _param_to_dict(p)
        p2 = _param_from_dict(d)
        assert p2.widget is Widget.FILE_LIST
        assert p2.max_items == 8
        assert p2.file_filter == "Text (*.txt);;All (*)"
        # default preserved
        assert p2.default == ["a.txt", "b.txt"]

    def test_round_trip_through_file(self, tmp_path: Path) -> None:
        t = ToolDef(name="T", executable="echo", params=[
            ParamDef(
                id="folders", type=ParamType.MULTISELECT,
                widget=Widget.FOLDER_LIST, default=[],
                must_exist=True, min_items=2,
            ),
        ])
        p = tmp_path / "t.scriptree"
        save_tool(t, p)
        t2 = load_tool(p)
        f = t2.params[0]
        assert f.widget is Widget.FOLDER_LIST
        assert f.must_exist is True
        assert f.min_items == 2
        assert f.max_items is None


# ===========================================================================
# Widget behaviour (Qt-backed)
# ===========================================================================
#
# pytest-qt's ``qtbot`` fixture is in the dev deps; if it's missing in a
# bare environment, mark the whole class as skipped.
qtbot_module = pytest.importorskip("pytestqt", reason="pytest-qt not installed")


from scriptree.ui.widgets.param_widgets import (  # noqa: E402
    FileListWidget, FolderListWidget,
)


def _mk_folder_param(**kw) -> ParamDef:
    return ParamDef(
        id="folders", type=ParamType.MULTISELECT,
        widget=Widget.FOLDER_LIST, default=kw.pop("default", []),
        **kw,
    )


def _mk_file_param(**kw) -> ParamDef:
    return ParamDef(
        id="files", type=ParamType.MULTISELECT,
        widget=Widget.FILE_LIST, default=kw.pop("default", []),
        **kw,
    )


class TestFolderListWidget:

    def test_initial_value_empty(self, qtbot) -> None:  # noqa: ANN001
        w = FolderListWidget(_mk_folder_param())
        qtbot.addWidget(w)
        assert w.get_value() == []

    def test_default_seeds_list(self, qtbot, tmp_path) -> None:  # noqa: ANN001
        d1 = tmp_path / "a"
        d2 = tmp_path / "b"
        d1.mkdir()
        d2.mkdir()
        w = FolderListWidget(
            _mk_folder_param(default=[str(d1), str(d2)]),
        )
        qtbot.addWidget(w)
        assert w.get_value() == [str(d1), str(d2)]

    def test_set_value_replaces_list(self, qtbot, tmp_path) -> None:  # noqa: ANN001
        w = FolderListWidget(_mk_folder_param())
        qtbot.addWidget(w)
        w.set_value([str(tmp_path / "x"), str(tmp_path / "y")])
        assert w.get_value() == [str(tmp_path / "x"), str(tmp_path / "y")]
        # Tolerates non-list (defensive coercion).
        w.set_value("")
        assert w.get_value() == []

    def test_add_path_dedups(self, qtbot) -> None:  # noqa: ANN001
        w = FolderListWidget(_mk_folder_param())
        qtbot.addWidget(w)
        assert w._add_path("C:/already", validated=True) is True
        assert w._add_path("C:/already", validated=True) is False
        assert w.get_value() == ["C:/already"]

    def test_add_path_respects_max_items(self, qtbot) -> None:  # noqa: ANN001
        w = FolderListWidget(_mk_folder_param(max_items=2))
        qtbot.addWidget(w)
        assert w._add_path("C:/a", validated=True) is True
        assert w._add_path("C:/b", validated=True) is True
        # Cap reached — third add rejected, Add button greyed.
        assert w._add_path("C:/c", validated=True) is False
        w._refresh_state()
        assert w._btn_add.isEnabled() is False

    def test_must_exist_blocks_unvalidated(self, qtbot, tmp_path) -> None:  # noqa: ANN001
        w = FolderListWidget(_mk_folder_param(must_exist=True))
        qtbot.addWidget(w)
        # Non-existent — would normally trigger a QMessageBox; the
        # widget falls back silently if the dialog can't show under
        # the headless test harness.  Either way the path is NOT
        # added (validated=False).
        bogus = str(tmp_path / "does-not-exist")
        # Bypass the QMessageBox by stubbing it out — Qt's modal
        # exec under pytest is undesirable.
        import scriptree.ui.widgets.param_widgets as pw
        called: list[bool] = []

        class _StubBox:
            @staticmethod
            def warning(*_a, **_kw):  # noqa: ANN001
                called.append(True)
                return 0

        monkey = pw.QMessageBox
        pw.QMessageBox = _StubBox  # type: ignore[assignment]
        try:
            assert w._add_path(bogus, validated=False) is False
        finally:
            pw.QMessageBox = monkey
        assert called == [True]
        assert w.get_value() == []
        # But a validated (default / config-loaded) add still works:
        assert w._add_path(bogus, validated=True) is True
        assert w.get_value() == [bogus]

    def test_move_selection_swaps_rows(self, qtbot) -> None:  # noqa: ANN001
        w = FolderListWidget(
            _mk_folder_param(default=["C:/a", "C:/b", "C:/c"]),
        )
        qtbot.addWidget(w)
        # Select middle row, push it up.
        w._list.setCurrentRow(1)
        w._move_selection(-1)
        assert w.get_value() == ["C:/b", "C:/a", "C:/c"]
        # Push it back down.
        w._list.setCurrentRow(0)
        w._move_selection(+1)
        assert w.get_value() == ["C:/a", "C:/b", "C:/c"]

    def test_value_changed_signal_fires(self, qtbot) -> None:  # noqa: ANN001
        w = FolderListWidget(_mk_folder_param())
        qtbot.addWidget(w)
        with qtbot.waitSignal(w.valueChanged, timeout=500):
            w.set_value(["C:/x"])


class TestFileListWidget:

    def test_round_trip_through_widget(self, qtbot) -> None:  # noqa: ANN001
        w = FileListWidget(
            _mk_file_param(default=["x.txt", "y.txt"]),
        )
        qtbot.addWidget(w)
        assert w.get_value() == ["x.txt", "y.txt"]

    def test_pick_paths_uses_file_filter(self, qtbot, monkeypatch) -> None:  # noqa: ANN001
        """The Add button must pass ``param.file_filter`` to
        ``QFileDialog.getOpenFileNames`` so the user sees their
        filter."""
        w = FileListWidget(
            _mk_file_param(file_filter="Text (*.txt);;All (*)"),
        )
        qtbot.addWidget(w)
        captured: list[str] = []

        def _stub(*args, **_kw):  # noqa: ANN001
            # QFileDialog.getOpenFileNames is a static method —
            # args are (parent, title, start_dir, filter).  Capture
            # the filter regardless of how Qt binds it.
            filt = args[-1] if args else ""
            captured.append(filt)
            return ([], filt)

        import scriptree.ui.widgets.param_widgets as pw
        monkeypatch.setattr(
            pw.QFileDialog, "getOpenFileNames", staticmethod(_stub),
        )
        w._pick_paths()
        assert captured == ["Text (*.txt);;All (*)"]
