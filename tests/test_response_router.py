"""Tests for scripts/common/response_router.py - Response routing for Slack commands."""

from unittest.mock import patch

import pytest

# Mock the config manager import that happens in ResponseRouter.__init__
with patch("scripts.common.response_router.ResponseRouter._load_config"):
    from scripts.common.response_router import (
        CommandContext,
        ResponseConfig,
        ResponseFormatter,
        ResponseMode,
        ResponseRouter,
        get_router,
        route_response,
    )


# ==================== ResponseMode ====================


class TestResponseMode:
    """Tests for the ResponseMode enum."""

    def test_values(self):
        assert ResponseMode.THREAD.value == "thread"
        assert ResponseMode.CHANNEL.value == "channel"
        assert ResponseMode.DM.value == "dm"
        assert ResponseMode.EPHEMERAL.value == "ephemeral"

    def test_string_enum(self):
        assert ResponseMode.THREAD == "thread"
        assert isinstance(ResponseMode.THREAD, str)

    def test_construct_from_value(self):
        assert ResponseMode("thread") == ResponseMode.THREAD
        assert ResponseMode("dm") == ResponseMode.DM


# ==================== ResponseConfig ====================


class TestResponseConfig:
    """Tests for the ResponseConfig dataclass."""

    def test_defaults(self):
        rc = ResponseConfig()
        assert rc.mode == ResponseMode.THREAD
        assert rc.channel_id == ""
        assert rc.thread_ts is None
        assert rc.user_id == ""
        assert rc.use_blocks is False
        assert rc.unfurl_links is False
        assert rc.unfurl_media is False

    def test_to_dict_thread_mode(self):
        rc = ResponseConfig(
            mode=ResponseMode.THREAD,
            channel_id="C123",
            thread_ts="1234.5678",
        )
        d = rc.to_dict()
        assert d["channel"] == "C123"
        assert d["thread_ts"] == "1234.5678"
        assert d["unfurl_links"] is False
        assert d["unfurl_media"] is False

    def test_to_dict_channel_mode(self):
        rc = ResponseConfig(
            mode=ResponseMode.CHANNEL,
            channel_id="C123",
            thread_ts="1234.5678",
        )
        d = rc.to_dict()
        assert d["channel"] == "C123"
        # thread_ts should NOT be included when mode is CHANNEL
        assert "thread_ts" not in d

    def test_to_dict_thread_mode_no_ts(self):
        rc = ResponseConfig(
            mode=ResponseMode.THREAD,
            channel_id="C123",
            thread_ts=None,
        )
        d = rc.to_dict()
        assert "thread_ts" not in d


# ==================== CommandContext ====================


class TestCommandContext:
    """Tests for the CommandContext dataclass."""

    def test_defaults(self):
        cc = CommandContext()
        assert cc.channel_id == ""
        assert cc.thread_ts is None
        assert cc.message_ts == ""
        assert cc.user_id == ""
        assert cc.is_dm is False
        assert cc.reply_dm is False
        assert cc.reply_thread is True
        assert cc.command == ""


# ==================== ResponseRouter ====================


class TestResponseRouter:
    """Tests for the ResponseRouter class."""

    def setup_method(self):
        self.router = ResponseRouter(config={"some": "config"})

    def test_init_with_config(self):
        router = ResponseRouter(config={"test": True})
        assert router.config == {"test": True}
        assert router.default_mode == ResponseMode.THREAD

    def test_init_custom_default_mode(self):
        router = ResponseRouter(default_mode=ResponseMode.DM, config={"x": 1})
        assert router.default_mode == ResponseMode.DM

    @patch("scripts.common.response_router.ResponseRouter._load_config")
    def test_init_loads_config_when_empty(self, mock_load):
        router = ResponseRouter()
        mock_load.assert_called_once()

    def test_dm_default_commands(self):
        assert "secrets" in ResponseRouter.DM_DEFAULT_COMMANDS
        assert "credentials" in ResponseRouter.DM_DEFAULT_COMMANDS
        assert "tokens" in ResponseRouter.DM_DEFAULT_COMMANDS
        assert "api_keys" in ResponseRouter.DM_DEFAULT_COMMANDS

    def test_thread_default_commands(self):
        assert "create_jira_issue" in ResponseRouter.THREAD_DEFAULT_COMMANDS
        assert "investigate_alert" in ResponseRouter.THREAD_DEFAULT_COMMANDS

    # ---- route() ----

    def test_route_user_reply_dm(self):
        ctx = CommandContext(
            channel_id="C123",
            user_id="U999",
            reply_dm=True,
        )
        response = self.router.route(ctx)
        assert response.mode == ResponseMode.DM
        assert response.channel_id == ""  # Will be set by sender
        assert response.user_id == "U999"
        assert response.thread_ts is None

    def test_route_dm_default_command(self):
        ctx = CommandContext(
            channel_id="C123",
            user_id="U999",
            command="secrets",
        )
        response = self.router.route(ctx)
        assert response.mode == ResponseMode.DM

    def test_route_is_dm_channel(self):
        ctx = CommandContext(
            channel_id="D123",
            user_id="U999",
            is_dm=True,
        )
        response = self.router.route(ctx)
        assert response.mode == ResponseMode.CHANNEL

    def test_route_in_thread(self):
        ctx = CommandContext(
            channel_id="C123",
            thread_ts="1234.5678",
        )
        response = self.router.route(ctx)
        assert response.mode == ResponseMode.THREAD
        assert response.thread_ts == "1234.5678"

    def test_route_global_default(self):
        ctx = CommandContext(
            channel_id="C123",
            message_ts="99.0",
        )
        response = self.router.route(ctx)
        assert response.mode == ResponseMode.THREAD
        # Should start a thread from the command message
        assert response.thread_ts == "99.0"

    def test_route_global_default_from_config(self):
        router = ResponseRouter(config={"default_response_mode": "channel"})
        ctx = CommandContext(
            channel_id="C123",
            message_ts="99.0",
        )
        response = router.route(ctx)
        assert response.mode == ResponseMode.CHANNEL

    def test_route_sets_channel_and_user(self):
        ctx = CommandContext(
            channel_id="C123",
            user_id="U555",
            thread_ts="1.0",
            message_ts="2.0",
        )
        response = self.router.route(ctx)
        assert response.channel_id == "C123"
        assert response.user_id == "U555"

    # ---- get_routing_options ----

    def test_get_routing_options_dm_command(self):
        opts = self.router.get_routing_options("secrets")
        assert opts["default"] == "dm"
        assert "thread" in opts["available"]
        assert "dm" in opts["available"]
        assert "--reply-dm" in opts["flags"]

    def test_get_routing_options_thread_command(self):
        opts = self.router.get_routing_options("create_jira_issue")
        assert opts["default"] == "thread"

    def test_get_routing_options_unknown_command(self):
        opts = self.router.get_routing_options("unknown")
        assert opts["default"] == "thread"

    def test_get_routing_options_all_modes_available(self):
        opts = self.router.get_routing_options("anything")
        assert set(opts["available"]) == {"thread", "channel", "dm", "ephemeral"}


# ==================== ResponseFormatter ====================


class TestResponseFormatter:
    """Tests for the ResponseFormatter class."""

    def setup_method(self):
        self.formatter = ResponseFormatter()

    def test_format_short_message(self):
        config = ResponseConfig(channel_id="C1", thread_ts="1.0")
        result = self.formatter.format("Hello", config)
        assert result["text"] == "Hello"
        assert result["channel"] == "C1"
        assert result["thread_ts"] == "1.0"

    def test_format_truncates_long_message(self):
        config = ResponseConfig(channel_id="C1")
        long_text = "x" * 5000
        result = self.formatter.format(long_text, config)
        assert len(result["text"]) <= ResponseFormatter.MAX_MESSAGE_LENGTH
        assert result["text"].endswith(ResponseFormatter.TRUNCATION_SUFFIX)

    def test_format_with_blocks(self):
        formatter = ResponseFormatter(use_blocks=True)
        config = ResponseConfig(channel_id="C1")
        result = formatter.format("Hello world", config)
        assert "blocks" in result
        assert result["blocks"][0]["type"] == "section"

    def test_format_no_blocks_by_default(self):
        config = ResponseConfig(channel_id="C1")
        result = self.formatter.format("Hello", config)
        assert "blocks" not in result

    def test_format_error(self):
        result = self.formatter.format_error("Something went wrong")
        assert "Error" in result["text"]
        assert "Something went wrong" in result["text"]

    def test_format_error_with_command(self):
        result = self.formatter.format_error("fail", command="deploy")
        assert "deploy" in result["text"]
        assert "fail" in result["text"]

    def test_format_help(self):
        result = self.formatter.format_help("Usage: /command")
        assert result["text"] == "Usage: /command"
        assert result["unfurl_links"] is False


# ==================== ResponseFormatter Blocks ====================


class TestResponseFormatterBlocks:
    """Tests for _build_blocks."""

    def test_build_blocks_no_headers(self):
        formatter = ResponseFormatter()
        blocks = formatter._build_blocks("Just plain text")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "section"

    def test_build_blocks_with_headers(self):
        formatter = ResponseFormatter()
        text = "Intro text\n## Section One\nContent one\n## Section Two\nContent two"
        blocks = formatter._build_blocks(text)
        # Should have: intro section, header1, content1, header2, content2
        assert len(blocks) == 5

    def test_build_blocks_header_no_content(self):
        formatter = ResponseFormatter()
        text = "\n## Empty Section"
        blocks = formatter._build_blocks(text)
        # Empty intro (skipped) + header only (no content)
        header_blocks = [b for b in blocks if b["type"] == "header"]
        assert len(header_blocks) == 1

    def test_build_blocks_empty_intro(self):
        formatter = ResponseFormatter()
        text = "\n## Section\nContent"
        blocks = formatter._build_blocks(text)
        # Empty first section should be skipped
        types = [b["type"] for b in blocks]
        assert types[0] == "header"


# ==================== Singleton / Convenience ====================


class TestSingletonRouter:
    """Tests for singleton and convenience functions."""

    @patch("scripts.common.response_router._router", None)
    @patch("scripts.common.response_router.ResponseRouter._load_config")
    def test_get_router_creates_singleton(self, mock_load):
        import scripts.common.response_router as mod

        mod._router = None
        router = get_router()
        assert isinstance(router, ResponseRouter)

    @patch("scripts.common.response_router._router", None)
    @patch("scripts.common.response_router.ResponseRouter._load_config")
    def test_route_response_convenience(self, mock_load):
        import scripts.common.response_router as mod

        mod._router = None
        ctx = CommandContext(channel_id="C1", message_ts="1.0")
        response = route_response(ctx)
        assert isinstance(response, ResponseConfig)
