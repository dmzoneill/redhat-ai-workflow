"""Tests for tool_modules.aa_workflow.src.claude_code_integration module."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tool_modules.aa_workflow.src.claude_code_integration import (
    _check_subprocess_context,
    _try_import_strategy,
    _try_mcp_client_strategy,
    _try_server_strategy,
    create_ask_question_wrapper,
    get_claude_code_capabilities,
    is_claude_code_context,
    test_ask_question,
)

# ---------------------------------------------------------------------------
# is_claude_code_context
# ---------------------------------------------------------------------------


class TestIsClaudeCodeContext:
    def test_returns_true_when_claude_code_env_set(self):
        with patch.dict(os.environ, {"CLAUDE_CODE": "1"}, clear=False):
            assert is_claude_code_context() is True

    def test_returns_true_when_mcp_server_name_is_claude_code(self):
        with patch.dict(
            os.environ,
            {"MCP_SERVER_NAME": "claude-code"},
            clear=False,
        ):
            # Ensure CLAUDE_CODE is not set to test this branch
            env = os.environ.copy()
            env.pop("CLAUDE_CODE", None)
            env["MCP_SERVER_NAME"] = "claude-code"
            with patch.dict(os.environ, env, clear=True):
                assert is_claude_code_context() is True

    def test_returns_true_when_claude_cli_version_set(self):
        env = {"CLAUDE_CLI_VERSION": "1.0.0", "TESTING": "1"}
        with patch.dict(os.environ, env, clear=True):
            assert is_claude_code_context() is True

    def test_returns_false_when_no_env_vars(self):
        env = {"TESTING": "1"}
        with patch.dict(os.environ, env, clear=True):
            assert is_claude_code_context() is False


# ---------------------------------------------------------------------------
# _try_server_strategy
# ---------------------------------------------------------------------------


class TestTryServerStrategy:
    def test_returns_none_when_server_is_none(self):
        assert _try_server_strategy(None) is None

    def test_returns_callable_when_server_has_call_tool(self):
        server = MagicMock()
        server.call_tool = AsyncMock(return_value={"answers": []})
        result = _try_server_strategy(server)
        assert result is not None
        assert callable(result)

    def test_returns_none_when_server_has_no_relevant_attrs(self):
        server = MagicMock(spec=[])  # empty spec = no attributes
        assert _try_server_strategy(server) is None

    def test_returns_none_when_server_has_list_tools_but_no_ask(self):
        server = MagicMock(spec=["list_tools"])
        server.list_tools = MagicMock(return_value=[])
        result = _try_server_strategy(server)
        assert result is None

    def test_server_with_list_tools_containing_ask_user_question(self):
        server = MagicMock(spec=["list_tools"])
        tool_mock = MagicMock()
        tool_mock.name = "AskUserQuestion"
        server.list_tools = MagicMock(return_value=[tool_mock])
        # No call_tool attribute, so still None
        result = _try_server_strategy(server)
        assert result is None

    async def test_ask_via_server_success(self):
        server = MagicMock()
        server.call_tool = AsyncMock(return_value={"answers": ["Yes"]})
        fn = _try_server_strategy(server)
        result = await fn({"questions": []})
        assert result == {"answers": ["Yes"]}

    async def test_ask_via_server_exception_returns_none(self):
        server = MagicMock()
        server.call_tool = AsyncMock(side_effect=RuntimeError("failed"))
        fn = _try_server_strategy(server)
        result = await fn({"questions": []})
        assert result is None

    def test_server_check_exception_returns_none(self):
        """If accessing server attrs raises, return None."""
        server = MagicMock()
        type(server).call_tool = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        # hasattr should catch the error
        result = _try_server_strategy(server)
        assert result is None


# ---------------------------------------------------------------------------
# _try_import_strategy
# ---------------------------------------------------------------------------


class TestTryImportStrategy:
    def test_returns_none_when_claude_code_not_installed(self):
        # By default claude_code is not installable, so this should return None
        result = _try_import_strategy()
        assert result is None


# ---------------------------------------------------------------------------
# _try_mcp_client_strategy
# ---------------------------------------------------------------------------


class TestTryMcpClientStrategy:
    def test_returns_none_when_no_mcp_socket(self):
        env = {"TESTING": "1"}
        with patch.dict(os.environ, env, clear=True):
            result = _try_mcp_client_strategy()
            assert result is None

    def test_returns_callable_when_mcp_socket_set(self):
        with patch.dict(os.environ, {"MCP_SOCKET": "/tmp/mcp.sock"}, clear=False):
            result = _try_mcp_client_strategy()
            assert result is not None
            assert callable(result)


# ---------------------------------------------------------------------------
# _check_subprocess_context
# ---------------------------------------------------------------------------


class TestCheckSubprocessContext:
    def test_does_not_raise(self):
        """This function is informational only; should never raise."""
        _check_subprocess_context()

    def test_handles_missing_proc(self):
        """Should not raise even if /proc is unreadable."""
        with patch("builtins.open", side_effect=PermissionError("denied")):
            _check_subprocess_context()


# ---------------------------------------------------------------------------
# create_ask_question_wrapper
# ---------------------------------------------------------------------------


class TestCreateAskQuestionWrapper:
    def test_returns_none_when_no_strategies_work(self):
        """With no server and no env vars, all strategies fail -> None."""
        env = {"TESTING": "1"}
        with patch.dict(os.environ, env, clear=True):
            result = create_ask_question_wrapper(server=None)
            assert result is None

    def test_returns_callable_with_server_having_call_tool(self):
        server = MagicMock()
        server.call_tool = AsyncMock()
        result = create_ask_question_wrapper(server=server)
        assert result is not None
        assert callable(result)

    def test_tries_strategies_in_order(self):
        """Server strategy is tried first."""
        server = MagicMock()
        server.call_tool = AsyncMock()

        with patch(
            "tool_modules.aa_workflow.src.claude_code_integration._try_server_strategy",
            return_value=lambda x: x,
        ) as mock_server:
            result = create_ask_question_wrapper(server=server)
            mock_server.assert_called_once_with(server)

    def test_falls_through_to_import_strategy(self):
        with patch(
            "tool_modules.aa_workflow.src.claude_code_integration._try_server_strategy",
            return_value=None,
        ):
            with patch(
                "tool_modules.aa_workflow.src.claude_code_integration._try_import_strategy",
                return_value=lambda x: x,
            ) as mock_import:
                result = create_ask_question_wrapper(server=None)
                mock_import.assert_called_once()
                assert result is not None

    def test_falls_through_to_mcp_strategy(self):
        with patch(
            "tool_modules.aa_workflow.src.claude_code_integration._try_server_strategy",
            return_value=None,
        ):
            with patch(
                "tool_modules.aa_workflow.src.claude_code_integration._try_import_strategy",
                return_value=None,
            ):
                with patch(
                    "tool_modules.aa_workflow.src.claude_code_integration._try_mcp_client_strategy",
                    return_value=lambda x: x,
                ) as mock_mcp:
                    result = create_ask_question_wrapper(server=None)
                    mock_mcp.assert_called_once()
                    assert result is not None


# ---------------------------------------------------------------------------
# get_claude_code_capabilities
# ---------------------------------------------------------------------------


class TestGetClaudeCodeCapabilities:
    def test_not_claude_code(self):
        env = {"TESTING": "1"}
        with patch.dict(os.environ, env, clear=True):
            caps = get_claude_code_capabilities()
            assert caps["is_claude_code"] is False
            assert caps["has_ask_question"] is False
            assert caps["has_native_ui"] is False
            assert caps["version"] is None
            assert caps["detection_method"] is None

    def test_claude_code_env_var(self):
        env = {"CLAUDE_CODE": "1", "TESTING": "1"}
        with patch.dict(os.environ, env, clear=True):
            caps = get_claude_code_capabilities()
            assert caps["is_claude_code"] is True
            assert caps["has_native_ui"] is True
            assert caps["detection_method"] == "CLAUDE_CODE env var"

    def test_mcp_server_name_detection(self):
        env = {"MCP_SERVER_NAME": "claude-code", "TESTING": "1"}
        with patch.dict(os.environ, env, clear=True):
            caps = get_claude_code_capabilities()
            assert caps["is_claude_code"] is True
            assert caps["detection_method"] == "MCP_SERVER_NAME"

    def test_claude_cli_version_detection(self):
        env = {"CLAUDE_CLI_VERSION": "2.0.0", "TESTING": "1"}
        with patch.dict(os.environ, env, clear=True):
            caps = get_claude_code_capabilities()
            assert caps["is_claude_code"] is True
            assert caps["version"] == "2.0.0"
            assert caps["detection_method"] == "CLAUDE_CLI_VERSION"

    def test_returns_dict(self):
        caps = get_claude_code_capabilities()
        assert isinstance(caps, dict)
        assert "is_claude_code" in caps
        assert "has_ask_question" in caps
        assert "has_native_ui" in caps
        assert "version" in caps
        assert "detection_method" in caps


# ---------------------------------------------------------------------------
# test_ask_question
# ---------------------------------------------------------------------------


class TestTestAskQuestion:
    async def test_returns_false_when_fn_is_none(self):
        result = await test_ask_question(None)
        assert result is False

    async def test_returns_true_when_fn_returns_answers(self):
        ask_fn = AsyncMock(return_value={"answers": ["Yes"]})
        result = await test_ask_question(ask_fn)
        assert result is True

    async def test_returns_false_when_fn_returns_none(self):
        ask_fn = AsyncMock(return_value=None)
        result = await test_ask_question(ask_fn)
        assert result is False

    async def test_returns_false_when_fn_returns_no_answers_key(self):
        ask_fn = AsyncMock(return_value={"result": "ok"})
        result = await test_ask_question(ask_fn)
        assert result is False

    async def test_returns_false_on_exception(self):
        ask_fn = AsyncMock(side_effect=RuntimeError("test failure"))
        result = await test_ask_question(ask_fn)
        assert result is False

    async def test_passes_correct_data_to_fn(self):
        ask_fn = AsyncMock(return_value={"answers": ["Yes"]})
        await test_ask_question(ask_fn)
        call_args = ask_fn.call_args[0][0]
        assert "questions" in call_args
        assert len(call_args["questions"]) == 1
        assert "question" in call_args["questions"][0]
        assert "options" in call_args["questions"][0]
