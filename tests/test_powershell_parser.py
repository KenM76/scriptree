"""Tests for the PowerShell parser plugin.

Covers detection, parameter extraction, type mapping, template generation,
and edge cases (switch params, skipped types, multiple parameter sets).
"""
from __future__ import annotations

import textwrap

import pytest

from scriptree.core.parser.plugins.powershell import (
    _extract_cmdlet_name,
    _extract_parameters,
    _flag_to_id,
    _flag_to_label,
    _map_type,
    detect,
    looks_like_powershell_help,
)

# --- sample help texts ------------------------------------------------------

HELP_NEW_LOCAL_USER = textwrap.dedent("""\
    NAME
        New-LocalUser

    SYNTAX
        New-LocalUser [-Name] <string> -Password <securestring> [-AccountNeverExpires] [-Description <string>] [-Disabled] [-FullName <string>] [-WhatIf] [-Confirm]  [<CommonParameters>]

        New-LocalUser [-Name] <string> -NoPassword [-AccountNeverExpires] [-Description <string>] [-Disabled] [-FullName <string>] [-WhatIf] [-Confirm]  [<CommonParameters>]


    PARAMETERS
        -AccountNeverExpires

            Required?                    false
            Position?                    Named
            Accept pipeline input?       true (ByPropertyName)
            Parameter set name           (All)
            Aliases                      None
            Dynamic?                     false

        -Confirm

            Required?                    false
            Position?                    Named
            Accept pipeline input?       false
            Parameter set name           (All)
            Aliases                      cf
            Dynamic?                     false

        -Description <string>

            Required?                    false
            Position?                    Named
            Accept pipeline input?       true (ByPropertyName)
            Parameter set name           (All)
            Aliases                      None
            Dynamic?                     false

        -Disabled

            Required?                    false
            Position?                    Named
            Accept pipeline input?       true (ByPropertyName)
            Parameter set name           (All)
            Aliases                      None
            Dynamic?                     false

        -FullName <string>

            Required?                    false
            Position?                    Named
            Accept pipeline input?       true (ByPropertyName)
            Parameter set name           (All)
            Aliases                      None
            Dynamic?                     false

        -Name <string>

            Required?                    true
            Position?                    0
            Accept pipeline input?       true (ByValue, ByPropertyName)
            Parameter set name           (All)
            Aliases                      None
            Dynamic?                     false

        -NoPassword

            Required?                    true
            Position?                    Named
            Accept pipeline input?       true (ByPropertyName)
            Parameter set name           NoPassword
            Aliases                      None
            Dynamic?                     false

        -Password <securestring>

            Required?                    true
            Position?                    Named
            Accept pipeline input?       true (ByPropertyName)
            Parameter set name           Password
            Aliases                      None
            Dynamic?                     false

        -WhatIf

            Required?                    false
            Position?                    Named
            Accept pipeline input?       false
            Parameter set name           (All)
            Aliases                      wi
            Dynamic?                     false

        <CommonParameters>
            This cmdlet supports the common parameters: Verbose, Debug,
            ErrorAction, ErrorVariable, WarningAction, WarningVariable,
            OutBuffer, PipelineVariable, and OutVariable.

    INPUTS
        None

    OUTPUTS
        System.Object
""")

HELP_GET_LOCAL_GROUP = textwrap.dedent("""\
    NAME
        Get-LocalGroup

    SYNTAX
        Get-LocalGroup [[-Name] <string[]>]  [<CommonParameters>]

        Get-LocalGroup [[-SID] <SecurityIdentifier[]>]  [<CommonParameters>]


    PARAMETERS
        -Name <string[]>

            Required?                    false
            Position?                    0
            Accept pipeline input?       true (ByValue, ByPropertyName)
            Parameter set name           Default
            Aliases                      None
            Dynamic?                     false

        -SID <SecurityIdentifier[]>

            Required?                    false
            Position?                    0
            Accept pipeline input?       true (ByValue, ByPropertyName)
            Parameter set name           SecurityIdentifier
            Aliases                      None
            Dynamic?                     false

        <CommonParameters>
            This cmdlet supports the common parameters.

    INPUTS
        System.String[]

    OUTPUTS
        System.Object
""")

HELP_SIMPLE_SWITCH_ONLY = textwrap.dedent("""\
    NAME
        Enable-LocalUser

    SYNTAX
        Enable-LocalUser [-Name] <string>  [<CommonParameters>]

    PARAMETERS
        -Name <string>

            Required?                    true
            Position?                    0
            Accept pipeline input?       true (ByValue, ByPropertyName)
            Parameter set name           (All)
            Aliases                      None
            Dynamic?                     false

        <CommonParameters>
            This cmdlet supports the common parameters.

    INPUTS
        None

    OUTPUTS
        System.Object
""")

NOT_POWERSHELL = textwrap.dedent("""\
    usage: git commit [-m <msg>] [-a] [--amend]

    options:
      -m <msg>   commit message
      -a         stage all modified files
      --amend    amend the previous commit
""")


# --- detection --------------------------------------------------------------

class TestDetection:
    def test_detects_powershell_help(self) -> None:
        assert looks_like_powershell_help(HELP_NEW_LOCAL_USER) is True

    def test_rejects_non_powershell(self) -> None:
        assert looks_like_powershell_help(NOT_POWERSHELL) is False

    def test_requires_parameters_header(self) -> None:
        text = "NAME\n    Foo\n\nSYNTAX\n    Foo\n"
        assert looks_like_powershell_help(text) is False


# --- cmdlet name extraction -------------------------------------------------

class TestCmdletName:
    def test_extracts_name(self) -> None:
        assert _extract_cmdlet_name(HELP_NEW_LOCAL_USER) == "New-LocalUser"

    def test_extracts_get_local_group(self) -> None:
        assert _extract_cmdlet_name(HELP_GET_LOCAL_GROUP) == "Get-LocalGroup"


# --- parameter extraction ---------------------------------------------------

class TestParameterExtraction:
    def test_new_local_user_param_count(self) -> None:
        params = _extract_parameters(HELP_NEW_LOCAL_USER)
        # Should find: AccountNeverExpires, Confirm, Description, Disabled,
        # FullName, Name, NoPassword, Password, WhatIf
        assert len(params) == 9

    def test_name_is_required_positional(self) -> None:
        params = _extract_parameters(HELP_NEW_LOCAL_USER)
        name_param = next(p for p in params if p.flag == "Name")
        assert name_param.required is True
        assert name_param.position == "0"
        assert name_param.type_tag == "string"

    def test_switch_param_has_no_type(self) -> None:
        params = _extract_parameters(HELP_NEW_LOCAL_USER)
        disabled = next(p for p in params if p.flag == "Disabled")
        assert disabled.type_tag == ""
        assert disabled.required is False

    def test_securestring_type_captured(self) -> None:
        params = _extract_parameters(HELP_NEW_LOCAL_USER)
        password = next(p for p in params if p.flag == "Password")
        assert password.type_tag == "securestring"

    def test_param_set_captured(self) -> None:
        params = _extract_parameters(HELP_NEW_LOCAL_USER)
        no_pw = next(p for p in params if p.flag == "NoPassword")
        assert no_pw.param_set == "NoPassword"

    def test_get_local_group_skips_sid(self) -> None:
        """SID has type SecurityIdentifier[] which is pipeline-only."""
        params = _extract_parameters(HELP_GET_LOCAL_GROUP)
        flags = [p.flag for p in params]
        assert "Name" in flags
        assert "SID" in flags  # extracted, but detect() will skip it


# --- type mapping -----------------------------------------------------------

class TestTypeMapping:
    def test_string_maps(self) -> None:
        from scriptree.core.model import ParamType, Widget
        assert _map_type("string") == (ParamType.STRING, Widget.TEXT)

    def test_int32_maps(self) -> None:
        from scriptree.core.model import ParamType, Widget
        assert _map_type("int32") == (ParamType.INTEGER, Widget.NUMBER)

    def test_empty_is_switch(self) -> None:
        from scriptree.core.model import ParamType, Widget
        assert _map_type("") == (ParamType.BOOL, Widget.CHECKBOX)

    def test_securestring_skipped(self) -> None:
        assert _map_type("securestring") is None

    def test_unknown_type_defaults_to_string(self) -> None:
        from scriptree.core.model import ParamType, Widget
        assert _map_type("SomeFutureType") == (ParamType.STRING, Widget.TEXT)

    def test_bool_maps_to_checkbox(self) -> None:
        from scriptree.core.model import ParamType, Widget
        assert _map_type("bool") == (ParamType.BOOL, Widget.CHECKBOX)


# --- ID / label synthesis ---------------------------------------------------

class TestIdLabel:
    def test_camel_to_snake(self) -> None:
        assert _flag_to_id("AccountNeverExpires", set()) == "account_never_expires"

    def test_simple_name(self) -> None:
        assert _flag_to_id("Name", set()) == "name"

    def test_uniqueness(self) -> None:
        used = {"name"}
        assert _flag_to_id("Name", used) == "name_2"

    def test_label_splits_camel(self) -> None:
        assert _flag_to_label("AccountNeverExpires") == "Account Never Expires"

    def test_label_simple(self) -> None:
        assert _flag_to_label("Name") == "Name"


# --- full detect (integration) ---------------------------------------------

class TestDetect:
    def test_new_local_user(self) -> None:
        tool = detect(HELP_NEW_LOCAL_USER)
        assert tool is not None
        assert tool.name == "New-LocalUser"
        assert tool.executable == "powershell.exe"
        # Template should start with -NoProfile -Command New-LocalUser
        assert tool.argument_template[:3] == [
            "-NoProfile", "-Command", "New-LocalUser"
        ]
        # Source mode should be powershell.
        assert tool.source.mode == "powershell"

    def test_skips_securestring_params(self) -> None:
        tool = detect(HELP_NEW_LOCAL_USER)
        assert tool is not None
        ids = [p.id for p in tool.params]
        assert "password" not in ids  # securestring → skipped

    def test_skips_common_params(self) -> None:
        tool = detect(HELP_NEW_LOCAL_USER)
        assert tool is not None
        ids = [p.id for p in tool.params]
        assert "confirm" not in ids
        assert "what_if" not in ids

    def test_name_is_positional(self) -> None:
        tool = detect(HELP_NEW_LOCAL_USER)
        assert tool is not None
        # Name is positional 0, so template entry is just "{name}"
        assert "{name}" in tool.argument_template

    def test_switch_becomes_conditional(self) -> None:
        tool = detect(HELP_NEW_LOCAL_USER)
        assert tool is not None
        # Disabled is a switch → "{disabled?-Disabled}"
        assert "{disabled?-Disabled}" in tool.argument_template

    def test_value_param_becomes_group(self) -> None:
        tool = detect(HELP_NEW_LOCAL_USER)
        assert tool is not None
        # Description takes a value → ["-Description", "{description}"]
        assert ["-Description", "{description}"] in tool.argument_template

    def test_get_local_group_skips_pipeline_types(self) -> None:
        tool = detect(HELP_GET_LOCAL_GROUP)
        assert tool is not None
        ids = [p.id for p in tool.params]
        # SID is SecurityIdentifier[] → pipeline-only → skipped
        assert "sid" not in ids
        # Name <string[]> should be kept
        assert "name" in ids

    def test_returns_none_for_non_powershell(self) -> None:
        assert detect(NOT_POWERSHELL) is None

    def test_simple_one_param(self) -> None:
        tool = detect(HELP_SIMPLE_SWITCH_ONLY)
        assert tool is not None
        assert tool.name == "Enable-LocalUser"
        assert len(tool.params) == 1
        assert tool.params[0].id == "name"
        assert tool.params[0].required is True

    def test_param_set_required_downgraded(self) -> None:
        """Params in non-(All) sets should not be marked required."""
        tool = detect(HELP_NEW_LOCAL_USER)
        assert tool is not None
        # NoPassword is required in the NoPassword set, but since
        # there are multiple sets it should be downgraded to optional.
        no_pw = next((p for p in tool.params if p.id == "no_password"), None)
        assert no_pw is not None
        assert no_pw.required is False


class TestRegistryIntegration:
    """Verify the plugin is discoverable via the registry."""

    def test_powershell_in_registry(self) -> None:
        from scriptree.core.parser.plugin_api import (
            PluginRegistry,
            load_builtin_plugins,
        )
        reg = PluginRegistry()
        load_builtin_plugins(reg)
        assert "powershell" in reg.names()

    def test_registry_parses_powershell_help(self) -> None:
        from scriptree.core.parser.plugin_api import (
            PluginRegistry,
            load_builtin_plugins,
        )
        reg = PluginRegistry()
        load_builtin_plugins(reg)
        tool = reg.parse(HELP_NEW_LOCAL_USER)
        assert tool is not None
        assert tool.source.mode == "powershell"
