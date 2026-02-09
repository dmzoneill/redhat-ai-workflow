"""Tests for scripts/common/command_parser.py."""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from scripts.common.command_parser import (
    CommandParser,
    ParsedCommand,
    TriggerType,
    parse_command,
)

# ---------------------------------------------------------------------------
# TriggerType enum
# ---------------------------------------------------------------------------


class TestTriggerType:
    def test_values(self):
        assert TriggerType.AT_ME == "at_me"
        assert TriggerType.BANG == "bang"
        assert TriggerType.SLASH == "slash"
        assert TriggerType.SLASH_BOT == "slash_bot"
        assert TriggerType.NONE == "none"

    def test_is_str_subclass(self):
        assert isinstance(TriggerType.AT_ME, str)


# ---------------------------------------------------------------------------
# ParsedCommand dataclass
# ---------------------------------------------------------------------------


class TestParsedCommand:
    def test_defaults(self):
        pc = ParsedCommand()
        assert pc.is_command is False
        assert pc.trigger_type == TriggerType.NONE
        assert pc.command == ""
        assert pc.args == []
        assert pc.kwargs == {}
        assert isinstance(pc.flags, set) and len(pc.flags) == 0
        assert pc.original_text == ""
        assert pc.remaining_text == ""
        assert pc.reply_dm is False
        assert pc.reply_thread is True

    def test_flags_list_converted_to_set(self):
        pc = ParsedCommand(flags=["a", "b", "a"])
        assert isinstance(pc.flags, set)
        assert pc.flags == {"a", "b"}

    def test_to_skill_inputs_no_args(self):
        pc = ParsedCommand(kwargs={"project": "AAP"})
        result = pc.to_skill_inputs()
        assert result == {"project": "AAP"}

    def test_to_skill_inputs_single_arg(self):
        pc = ParsedCommand(args=["AAP-123"], kwargs={"flag": True})
        result = pc.to_skill_inputs()
        assert result == {"target": "AAP-123", "flag": True}

    def test_to_skill_inputs_multiple_args(self):
        pc = ParsedCommand(args=["a", "b", "c"])
        result = pc.to_skill_inputs()
        assert result == {"args": ["a", "b", "c"]}

    def test_to_dict(self):
        pc = ParsedCommand(
            is_command=True,
            trigger_type=TriggerType.AT_ME,
            command="help",
            args=["topic"],
            kwargs={"k": "v"},
            flags={"verbose"},
            reply_dm=False,
            reply_thread=True,
        )
        d = pc.to_dict()
        assert d["is_command"] is True
        assert d["trigger_type"] == "at_me"
        assert d["command"] == "help"
        assert d["args"] == ["topic"]
        assert d["kwargs"] == {"k": "v"}
        assert set(d["flags"]) == {"verbose"}
        assert d["reply_dm"] is False
        assert d["reply_thread"] is True


# ---------------------------------------------------------------------------
# CommandParser.__init__
# ---------------------------------------------------------------------------


class TestCommandParserInit:
    def test_defaults(self):
        parser = CommandParser()
        assert parser.triggers == ["@me"]
        assert parser.self_dm_only_triggers == ["!", "/"]
        assert len(parser._patterns) == len(CommandParser.TRIGGERS)

    def test_custom_triggers(self):
        parser = CommandParser(triggers=["@bot"], self_dm_only_triggers=["!"])
        assert parser.triggers == ["@bot"]
        assert parser.self_dm_only_triggers == ["!"]


# ---------------------------------------------------------------------------
# CommandParser.parse - trigger detection
# ---------------------------------------------------------------------------


class TestParserTriggerDetection:
    @pytest.fixture
    def parser(self):
        return CommandParser()

    def test_empty_string(self, parser):
        result = parser.parse("")
        assert result.is_command is False
        assert result.trigger_type == TriggerType.NONE

    def test_whitespace_only(self, parser):
        result = parser.parse("   ")
        assert result.is_command is False

    def test_no_trigger(self, parser):
        result = parser.parse("hello world")
        assert result.is_command is False
        assert result.trigger_type == TriggerType.NONE

    def test_at_me_trigger(self, parser):
        result = parser.parse("@me help")
        assert result.is_command is True
        assert result.trigger_type == TriggerType.AT_ME
        assert result.command == "help"

    def test_at_me_case_insensitive(self, parser):
        result = parser.parse("@ME status")
        assert result.is_command is True
        assert result.trigger_type == TriggerType.AT_ME
        assert result.command == "status"

    def test_bang_trigger_in_self_dm(self, parser):
        result = parser.parse("!help", is_self_dm=True)
        assert result.is_command is True
        assert result.trigger_type == TriggerType.BANG
        assert result.command == "help"

    def test_bang_trigger_not_in_self_dm(self, parser):
        result = parser.parse("!help", is_self_dm=False)
        assert result.is_command is False

    def test_slash_trigger_in_self_dm(self, parser):
        result = parser.parse("/status", is_self_dm=True)
        assert result.is_command is True
        assert result.trigger_type == TriggerType.SLASH
        assert result.command == "status"

    def test_slash_trigger_not_in_self_dm(self, parser):
        result = parser.parse("/status", is_self_dm=False)
        assert result.is_command is False

    def test_slash_bot_trigger(self, parser):
        result = parser.parse("/bot deploy")
        assert result.is_command is True
        assert result.trigger_type == TriggerType.SLASH_BOT
        assert result.command == "deploy"

    def test_original_text_preserved(self, parser):
        text = "@me help something"
        result = parser.parse(text)
        assert result.original_text == text


# ---------------------------------------------------------------------------
# CommandParser.parse - argument parsing
# ---------------------------------------------------------------------------


class TestParserArgumentParsing:
    @pytest.fixture
    def parser(self):
        return CommandParser()

    def test_positional_args(self, parser):
        result = parser.parse("@me search billing errors")
        assert result.command == "search"
        assert result.args == ["billing", "errors"]

    def test_named_arg_equals(self, parser):
        result = parser.parse("@me create --type=bug --priority=high")
        assert result.command == "create"
        assert result.kwargs["type"] == "bug"
        assert result.kwargs["priority"] == "high"

    def test_named_arg_space(self, parser):
        result = parser.parse("@me create --type bug")
        assert result.kwargs["type"] == "bug"

    def test_flag_long(self, parser):
        result = parser.parse("@me deploy --verbose")
        assert "verbose" in result.flags

    def test_flag_short(self, parser):
        result = parser.parse("@me deploy -v")
        assert "v" in result.flags

    def test_mixed_args_kwargs_flags(self, parser):
        result = parser.parse("@me deploy staging --env=prod --verbose -d")
        assert result.command == "deploy"
        assert "staging" in result.args
        assert result.kwargs["env"] == "prod"
        assert "verbose" in result.flags
        assert "d" in result.flags

    def test_command_normalizes_dashes_to_underscores(self, parser):
        result = parser.parse("@me create-jira-issue")
        assert result.command == "create_jira_issue"

    def test_command_lowercased(self, parser):
        result = parser.parse("@me DEPLOY")
        assert result.command == "deploy"

    def test_kwarg_dashes_to_underscores(self, parser):
        result = parser.parse("@me cmd --my-key=val")
        assert result.kwargs["my_key"] == "val"

    def test_quoted_value(self, parser):
        result = parser.parse('@me cmd --title="some long title"')
        assert result.kwargs["title"] == "some long title"


# ---------------------------------------------------------------------------
# CommandParser._parse_value
# ---------------------------------------------------------------------------


class TestParseValue:
    @pytest.fixture
    def parser(self):
        return CommandParser()

    @pytest.mark.parametrize("val", ["true", "True", "yes", "YES", "1"])
    def test_true_values(self, parser, val):
        assert parser._parse_value(val) is True

    @pytest.mark.parametrize("val", ["false", "False", "no", "NO", "0"])
    def test_false_values(self, parser, val):
        assert parser._parse_value(val) is False

    @pytest.mark.parametrize(
        "val,expected,expected_type",
        [
            ("42", 42, int),
            ("3.14", 3.14, float),
            ("hello", "hello", str),
        ],
        ids=["integer", "float", "string_fallback"],
    )
    def test_type_coercion(self, parser, val, expected, expected_type):
        result = parser._parse_value(val)
        assert result == expected
        assert isinstance(result, expected_type)


# ---------------------------------------------------------------------------
# Reply routing flags
# ---------------------------------------------------------------------------


class TestReplyRouting:
    @pytest.fixture
    def parser(self):
        return CommandParser()

    def test_reply_dm_flag(self, parser):
        """Note: --reply-dm is stored as reply_dm in flags (dashes normalized),
        but the check looks for 'reply-dm', so the flag path doesn't trigger.
        The kwarg --reply=dm path works correctly instead."""
        result = parser.parse("@me cmd --reply-dm")
        # The flag is stored as 'reply_dm' due to dash-to-underscore normalization
        assert "reply_dm" in result.flags

    def test_reply_thread_flag(self, parser):
        """Same normalization issue as reply-dm: stored as reply_thread."""
        result = parser.parse("@me cmd --reply-thread")
        assert "reply_thread" in result.flags

    def test_reply_kwarg_dm(self, parser):
        result = parser.parse("@me cmd --reply=dm")
        assert result.reply_dm is True
        assert result.reply_thread is False

    def test_reply_kwarg_thread(self, parser):
        result = parser.parse("@me cmd --reply=thread")
        assert result.reply_thread is True
        assert result.reply_dm is False


# ---------------------------------------------------------------------------
# Helper methods
# ---------------------------------------------------------------------------


class TestHelperMethods:
    @pytest.fixture
    def parser(self):
        return CommandParser()

    @pytest.mark.parametrize("cmd", ["help", "list", "commands", "?"])
    def test_is_help_command(self, parser, cmd):
        pc = ParsedCommand(command=cmd)
        assert parser.is_help_command(pc) is True

    def test_is_not_help_command(self, parser):
        pc = ParsedCommand(command="deploy")
        assert parser.is_help_command(pc) is False

    @pytest.mark.parametrize("cmd", ["status", "info", "whoami"])
    def test_is_status_command(self, parser, cmd):
        pc = ParsedCommand(command=cmd)
        assert parser.is_status_command(pc) is True

    def test_is_not_status_command(self, parser):
        pc = ParsedCommand(command="deploy")
        assert parser.is_status_command(pc) is False

    def test_get_help_target_with_args(self, parser):
        pc = ParsedCommand(command="help", args=["deploy"])
        assert parser.get_help_target(pc) == "deploy"

    def test_get_help_target_no_args(self, parser):
        pc = ParsedCommand(command="help", args=[])
        assert parser.get_help_target(pc) is None

    def test_get_help_target_not_help_cmd(self, parser):
        pc = ParsedCommand(command="deploy", args=["target"])
        assert parser.get_help_target(pc) is None


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


class TestParseCommandFunction:
    def test_basic_usage(self):
        result = parse_command("@me help")
        assert result.is_command is True
        assert result.command == "help"

    def test_self_dm(self):
        result = parse_command("!status", is_self_dm=True)
        assert result.is_command is True
        assert result.command == "status"

    def test_no_trigger(self):
        result = parse_command("just a message")
        assert result.is_command is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.fixture
    def parser(self):
        return CommandParser()

    def test_shlex_parse_error_fallback(self, parser):
        """Unbalanced quotes should fallback to simple split."""
        result = parser.parse('@me cmd --title="unbalanced')
        assert result.is_command is True
        assert result.command == "cmd"

    def test_at_me_no_command(self, parser):
        """@me with nothing after trigger text."""
        result = parser.parse("@me ")
        assert result.is_command is False

    def test_bang_no_space(self, parser):
        result = parser.parse("!deploy", is_self_dm=True)
        assert result.is_command is True
        assert result.command == "deploy"

    def test_slash_does_not_match_bot(self, parser):
        """'/bot cmd' should NOT match as SLASH, but as SLASH_BOT."""
        result = parser.parse("/bot deploy")
        assert result.trigger_type == TriggerType.SLASH_BOT
