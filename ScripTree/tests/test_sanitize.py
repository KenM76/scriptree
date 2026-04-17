"""Tests for the input sanitization module (core/sanitize.py)."""
from __future__ import annotations

from scriptree.core.sanitize import sanitize_all_values, sanitize_value


class TestSanitizeValue:
    def test_clean_string(self) -> None:
        r = sanitize_value("hello world")
        assert r.is_clean

    def test_empty_string(self) -> None:
        r = sanitize_value("")
        assert r.is_clean

    def test_null_byte(self) -> None:
        r = sanitize_value("foo\x00bar")
        assert not r.is_clean
        assert any("null byte" in w for w in r.warnings)

    def test_control_chars(self) -> None:
        r = sanitize_value("foo\x01bar")
        assert not r.is_clean
        assert any("control" in w.lower() for w in r.warnings)

    def test_shell_metacharacters(self) -> None:
        r = sanitize_value("hello; rm -rf /")
        assert not r.is_clean
        assert any("metacharacter" in w for w in r.warnings)

    def test_pipe(self) -> None:
        r = sanitize_value("cat file | grep foo")
        assert not r.is_clean

    def test_backtick(self) -> None:
        r = sanitize_value("`whoami`")
        assert not r.is_clean

    def test_dollar_sign(self) -> None:
        r = sanitize_value("$HOME")
        assert not r.is_clean

    def test_path_traversal(self) -> None:
        r = sanitize_value("..\\..\\Windows\\System32\\cmd.exe", is_path=True)
        assert not r.is_clean
        assert any("traversal" in w for w in r.warnings)

    def test_path_traversal_forward_slash(self) -> None:
        r = sanitize_value("../../etc/passwd", is_path=True)
        assert not r.is_clean

    def test_unc_path(self) -> None:
        r = sanitize_value("\\\\evil-server\\share", is_path=True)
        assert not r.is_clean
        assert any("UNC" in w for w in r.warnings)

    def test_normal_path_is_clean(self) -> None:
        r = sanitize_value("C:\\Users\\Ken\\Documents\\file.txt", is_path=True)
        assert r.is_clean

    def test_path_traversal_ignored_for_non_path(self) -> None:
        """Path traversal check only runs when is_path=True."""
        r = sanitize_value("../../test", is_path=False)
        # No path-specific warnings (may still have shell meta warnings
        # but no "traversal" warning).
        assert not any("traversal" in w for w in r.warnings)

    def test_field_label_in_warning(self) -> None:
        r = sanitize_value("foo\x00bar", field_label="Output file")
        assert any("Output file" in w for w in r.warnings)


class TestSanitizeAllValues:
    def test_all_clean(self) -> None:
        warnings = sanitize_all_values(
            {"name": "hello", "path": "C:\\test"},
            path_fields={"path"},
        )
        assert warnings == []

    def test_mixed(self) -> None:
        warnings = sanitize_all_values(
            {"name": "hello", "evil": "foo;bar"},
            labels={"evil": "Evil field"},
        )
        assert len(warnings) > 0
        assert any("Evil field" in w for w in warnings)

    def test_path_field_checked(self) -> None:
        warnings = sanitize_all_values(
            {"output": "..\\..\\test"},
            path_fields={"output"},
            labels={"output": "Output"},
        )
        assert any("traversal" in w for w in warnings)
