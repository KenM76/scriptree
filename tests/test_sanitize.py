"""Tests for the input sanitization module (core/sanitize.py)."""
from __future__ import annotations

from scriptree.core.sanitize import (
    sanitize_all_values, sanitize_all_values_detailed, sanitize_value,
)


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


class TestRegexFieldsAreExempt:
    """v0.8.0a49+ -- regex-widget fields skip the sanitizer entirely
    because their valid content is full of ``_SHELL_META`` characters
    (``|`` ``(`` ``)`` ``{`` ``}`` ``$`` etc.).  Adding warnings for
    every metacharacter in a regex was 100% false-positive noise.
    The skip is independent of the global ``is_globally_muted``
    flag.
    """

    def test_regex_field_with_metacharacters_produces_no_warnings(
        self,
    ) -> None:
        warnings = sanitize_all_values(
            {"pattern": r"(foo|bar){2,5}$"},
            labels={"pattern": "Pattern"},
            regex_ids={"pattern"},
        )
        assert warnings == [], (
            f"regex field should be skipped, got: {warnings}"
        )

    def test_regex_skip_does_not_affect_other_fields(self) -> None:
        warnings = sanitize_all_values(
            {
                "pattern": r"(foo|bar){2,5}$",   # regex -- skipped
                "name": "evil;rm -rf /",          # plain -- still flagged
            },
            labels={"pattern": "Pattern", "name": "Name"},
            regex_ids={"pattern"},
        )
        # The plain "name" field should still produce warnings;
        # only the regex field is exempt.
        assert any("Name" in w for w in warnings)
        assert not any("Pattern" in w for w in warnings)

    def test_detailed_variant_also_skips_regex_fields(self) -> None:
        detailed = sanitize_all_values_detailed(
            {
                "pat": r"^\d+$",
                "shell": "echo $HOME",
            },
            labels={"pat": "Pattern", "shell": "Shell"},
            regex_ids={"pat"},
        )
        fids = [fid for _w, fid in detailed]
        assert "pat" not in fids
        # The shell field's ``$`` should still trigger a warning.
        assert "shell" in fids

    def test_regex_ids_unset_keeps_old_behaviour(self) -> None:
        """When ``regex_ids`` is not passed (older call-sites), the
        sanitizer behaves exactly as before -- nothing gets
        silently skipped."""
        warnings_without_skip = sanitize_all_values(
            {"pattern": r"(foo|bar)"},
            labels={"pattern": "Pattern"},
        )
        # ``(`` and ``)`` and ``|`` are all in _SHELL_META, so
        # without the regex exemption we MUST see warnings.
        assert len(warnings_without_skip) > 0
