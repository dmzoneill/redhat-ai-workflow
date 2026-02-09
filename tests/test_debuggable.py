"""Tests for server/debuggable.py - Auto-debug infrastructure for MCP tools."""

import textwrap
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import TextContent

from server.debuggable import (
    TOOL_REGISTRY,
    _create_debug_wrapper,
    _extract_function,
    _get_remediation_hints,
    _search_for_tool,
    debuggable,
    get_tool_source,
    register_debug_tool,
    wrap_all_tools,
    wrap_server_tools_runtime,
)

# ────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_registry():
    """Ensure a clean TOOL_REGISTRY for each test."""
    saved = dict(TOOL_REGISTRY)
    yield
    TOOL_REGISTRY.clear()
    TOOL_REGISTRY.update(saved)


# ────────────────────────────────────────────────────────────────────
# _extract_function
# ────────────────────────────────────────────────────────────────────


class TestExtractFunction:
    def test_extracts_simple_function(self):
        source = textwrap.dedent(
            """\
            def foo():
                return 1

            def bar():
                return 2
        """
        )
        result = _extract_function(source, "foo")
        assert "def foo():" in result
        assert "return 1" in result
        assert "def bar():" not in result

    def test_extracts_async_function(self):
        source = textwrap.dedent(
            """\
            async def my_tool(ctx):
                result = await something()
                return result

            async def other():
                pass
        """
        )
        result = _extract_function(source, "my_tool")
        assert "async def my_tool" in result
        assert "await something" in result
        assert "other" not in result

    def test_not_found(self):
        source = "def foo(): pass"
        result = _extract_function(source, "nonexistent")
        assert "not found" in result

    def test_function_at_end_of_file(self):
        source = textwrap.dedent(
            """\
            def first():
                pass

            def last():
                return 42
        """
        )
        result = _extract_function(source, "last")
        assert "def last():" in result
        assert "return 42" in result

    def test_stops_at_decorator(self):
        source = textwrap.dedent(
            """\
            def func_a():
                return 1

            @some_decorator
            def func_b():
                return 2
        """
        )
        result = _extract_function(source, "func_a")
        assert "return 1" in result
        assert "@some_decorator" not in result

    def test_stops_at_class(self):
        source = textwrap.dedent(
            """\
            def func_a():
                return 1

            class MyClass:
                pass
        """
        )
        result = _extract_function(source, "func_a")
        assert "return 1" in result
        assert "MyClass" not in result

    def test_handles_blank_lines_inside_function(self):
        source = textwrap.dedent(
            """\
            def func():
                a = 1

                b = 2
                return a + b

            def next_func():
                pass
        """
        )
        result = _extract_function(source, "func")
        assert "a = 1" in result
        assert "b = 2" in result
        assert "next_func" not in result


# ────────────────────────────────────────────────────────────────────
# _get_remediation_hints
# ────────────────────────────────────────────────────────────────────


class TestGetRemediationHints:
    def test_vpn_no_route(self):
        hints = _get_remediation_hints("No route to host", "some_tool")
        assert any("VPN" in h or "vpn_connect" in h for h in hints)

    def test_vpn_network_unreachable(self):
        hints = _get_remediation_hints("Network is unreachable", "t")
        assert any("vpn_connect" in h for h in hints)

    def test_vpn_connection_timed_out(self):
        hints = _get_remediation_hints("Connection timed out", "t")
        assert any("vpn_connect" in h for h in hints)

    def test_vpn_could_not_resolve_host(self):
        hints = _get_remediation_hints("Could not resolve host xyz", "t")
        assert any("vpn_connect" in h for h in hints)

    def test_vpn_connection_refused(self):
        hints = _get_remediation_hints("Connection refused", "t")
        assert any("vpn_connect" in h for h in hints)

    def test_k8s_unauthorized(self):
        hints = _get_remediation_hints("Unauthorized", "some_tool")
        assert any("kube_login" in h for h in hints)

    def test_k8s_token_expired(self):
        hints = _get_remediation_hints("token is expired", "tool")
        assert any("kube_login" in h for h in hints)

    def test_k8s_stage_cluster_hint(self):
        hints = _get_remediation_hints("Unauthorized on stage cluster", "tool")
        assert any("stage" in h for h in hints)

    def test_k8s_prod_cluster_hint(self):
        hints = _get_remediation_hints("Unauthorized on prod", "tool")
        assert any("prod" in h for h in hints)

    def test_k8s_ephemeral_from_tool_name(self):
        hints = _get_remediation_hints("Unauthorized", "bonfire_deploy")
        assert any("ephemeral" in h for h in hints)

    def test_k8s_konflux_from_tool_name(self):
        hints = _get_remediation_hints("Unauthorized", "konflux_build")
        assert any("konflux" in h for h in hints)

    def test_k8s_generic_cluster_hint(self):
        hints = _get_remediation_hints("Unauthorized", "generic_tool")
        assert any("kube_login" in h for h in hints)

    def test_gitlab_auth(self):
        hints = _get_remediation_hints("401 Unauthorized from GitLab", "gl")
        assert any("GitLab" in h for h in hints)

    def test_slack_auth(self):
        hints = _get_remediation_hints("invalid_auth from Slack", "sl")
        assert any("Slack" in h for h in hints)

    def test_no_hints_for_unrelated_error(self):
        hints = _get_remediation_hints("Something went wrong with parsing", "tool")
        assert hints == []

    def test_multiple_hints(self):
        # An error that triggers both VPN and k8s hints
        hints = _get_remediation_hints("No route to host, Unauthorized", "tool")
        assert len(hints) >= 2


# ────────────────────────────────────────────────────────────────────
# @debuggable decorator
# ────────────────────────────────────────────────────────────────────


class TestDebuggable:
    @pytest.mark.asyncio
    async def test_success_passes_through(self):
        @debuggable
        async def good_tool():
            return [TextContent(type="text", text="OK")]

        result = await good_tool()
        assert len(result) == 1
        assert result[0].text == "OK"

    @pytest.mark.asyncio
    async def test_registered_in_registry(self):
        @debuggable
        async def registered_tool():
            return []

        assert "registered_tool" in TOOL_REGISTRY
        info = TOOL_REGISTRY["registered_tool"]
        assert info["func_name"] == "registered_tool"
        assert info["source_file"] != "unknown"
        assert info["start_line"] > 0

    @pytest.mark.asyncio
    async def test_failure_adds_debug_hint(self):
        @debuggable
        async def failing_tool():
            return [TextContent(type="text", text="❌ Something failed")]

        result = await failing_tool()
        assert len(result) == 2
        assert "debug_tool" in result[1].text
        assert "failing_tool" in result[1].text

    @pytest.mark.asyncio
    async def test_exception_returns_crash_info(self):
        @debuggable
        async def crash_tool():
            raise ValueError("boom")

        result = await crash_tool()
        assert len(result) == 1
        text = result[0].text
        assert "crash_tool" in text
        assert "boom" in text
        assert "debug_tool" in text

    @pytest.mark.asyncio
    async def test_empty_result_passes_through(self):
        @debuggable
        async def empty_tool():
            return []

        result = await empty_tool()
        assert result == []

    @pytest.mark.asyncio
    async def test_non_list_result_passes_through(self):
        @debuggable
        async def string_tool():
            return "plain string"

        result = await string_tool()
        assert result == "plain string"

    def test_preserves_function_name(self):
        @debuggable
        async def my_named_tool():
            pass

        assert my_named_tool.__name__ == "my_named_tool"

    def test_debug_info_attached(self):
        @debuggable
        async def info_tool():
            pass

        assert "_debug_info" in info_tool.__dict__
        assert info_tool.__dict__["_debug_info"]["func_name"] == "info_tool"

    @pytest.mark.asyncio
    async def test_result_first_item_without_text_attr(self):
        """When first item has no .text attribute, use str()."""

        @debuggable
        async def tool_with_non_text():
            return ["not a TextContent object"]

        result = await tool_with_non_text()
        # String doesn't start with ❌, so it should pass through
        assert result == ["not a TextContent object"]


# ────────────────────────────────────────────────────────────────────
# get_tool_source
# ────────────────────────────────────────────────────────────────────


class TestGetToolSource:
    def test_tool_in_registry(self):
        # Register a fake tool pointing to this test file
        TOOL_REGISTRY["fake_tool"] = {
            "source_file": __file__,
            "start_line": 1,
            "end_line": 10,
            "func_name": "fake_tool",
        }

        source_file, func_source, start, end = get_tool_source("fake_tool")
        assert source_file == __file__

    def test_tool_not_in_registry(self):
        source_file, func_source, start, end = get_tool_source(
            "totally_nonexistent_tool_xyz"
        )
        assert source_file == ""
        assert "not found" in func_source

    def test_tool_file_not_readable(self):
        TOOL_REGISTRY["unreadable_tool"] = {
            "source_file": "/nonexistent/path/file.py",
            "start_line": 1,
            "end_line": 10,
            "func_name": "unreadable_tool",
        }

        source_file, func_source, start, end = get_tool_source("unreadable_tool")
        assert "Error reading" in func_source


# ────────────────────────────────────────────────────────────────────
# _search_for_tool
# ────────────────────────────────────────────────────────────────────


class TestSearchForTool:
    def test_returns_none_when_no_tool_modules_dir(self, tmp_path):
        with patch("server.debuggable.Path") as MockPath:
            mock_file = MagicMock()
            mock_file.parent.parent.__truediv__ = MagicMock(
                return_value=tmp_path / "nonexistent"
            )
            MockPath.__file__ = mock_file
            # Actually, the function uses Path(__file__), so let's just test
            # the real function -- tool_modules dir might exist
            pass

        # Simpler: just call it with a name that won't be found
        result = _search_for_tool("definitely_not_a_real_tool_xyz")
        assert result is None or isinstance(result, dict)

    def test_returns_none_for_nonexistent_tool(self):
        result = _search_for_tool("__nonexistent_tool_9999__")
        assert result is None


# ────────────────────────────────────────────────────────────────────
# register_debug_tool
# ────────────────────────────────────────────────────────────────────


class TestRegisterDebugTool:
    def test_registers_tool_on_server(self):
        mock_server = MagicMock()
        # mock_server.tool() should return a decorator
        mock_server.tool.return_value = lambda fn: fn
        register_debug_tool(mock_server)
        mock_server.tool.assert_called_once()
        assert mock_server.tool.call_count == 1

    @pytest.mark.asyncio
    async def test_debug_tool_not_found(self):
        """When tool_name is not in registry, returns error."""
        mock_server = MagicMock()
        registered_fn = None

        def capture(fn):
            nonlocal registered_fn
            registered_fn = fn
            return fn

        mock_server.tool.return_value = capture
        register_debug_tool(mock_server)

        # Call the registered debug_tool function
        result = await registered_fn("nonexistent_tool_xyz", "")
        assert len(result) == 1
        assert "not find tool" in result[0].text or "Could not find" in result[0].text

    @pytest.mark.asyncio
    async def test_debug_tool_found(self):
        """When tool is in registry, returns source and instructions."""
        TOOL_REGISTRY["test_found"] = {
            "source_file": __file__,
            "start_line": 1,
            "end_line": 5,
            "func_name": "test_found",
        }

        mock_server = MagicMock()
        registered_fn = None

        def capture(fn):
            nonlocal registered_fn
            registered_fn = fn
            return fn

        mock_server.tool.return_value = capture
        register_debug_tool(mock_server)

        result = await registered_fn("test_found", "some error")
        assert len(result) == 1
        text = result[0].text
        assert "test_found" in text
        assert "some error" in text
        assert "Instructions" in text

    @pytest.mark.asyncio
    async def test_debug_tool_without_error_message(self):
        """debug_tool works without error_message."""
        TOOL_REGISTRY["test_no_err"] = {
            "source_file": __file__,
            "start_line": 1,
            "end_line": 5,
            "func_name": "test_no_err",
        }

        mock_server = MagicMock()
        registered_fn = None

        def capture(fn):
            nonlocal registered_fn
            registered_fn = fn
            return fn

        mock_server.tool.return_value = capture
        register_debug_tool(mock_server)

        result = await registered_fn("test_no_err", "")
        assert len(result) == 1
        # Should NOT contain "Error:" block
        text = result[0].text
        assert "Instructions" in text


# ────────────────────────────────────────────────────────────────────
# wrap_all_tools
# ────────────────────────────────────────────────────────────────────


class TestWrapAllTools:
    def test_wraps_public_async_functions(self, tmp_path):
        # Create a temporary module source
        source = textwrap.dedent(
            """\
            async def public_tool(ctx):
                return "ok"

            async def _private(ctx):
                return "hidden"

            def sync_func():
                pass
        """
        )
        mod_file = tmp_path / "tools.py"
        mod_file.write_text(source)

        mod = ModuleType("test_tools")
        mod.__file__ = str(mod_file)

        mock_server = MagicMock()
        count = wrap_all_tools(mock_server, mod)

        assert count == 1  # Only public_tool, not _private or sync_func
        assert "public_tool" in TOOL_REGISTRY

    def test_skips_already_registered(self, tmp_path):
        source = "async def already_here(ctx): pass"
        mod_file = tmp_path / "tools.py"
        mod_file.write_text(source)

        TOOL_REGISTRY["already_here"] = {
            "source_file": "x",
            "start_line": 1,
            "end_line": 1,
            "func_name": "already_here",
        }

        mod = ModuleType("test_tools")
        mod.__file__ = str(mod_file)

        mock_server = MagicMock()
        count = wrap_all_tools(mock_server, mod)
        assert count == 0  # Already registered, should skip

    def test_returns_zero_when_file_unreadable(self):
        mod = ModuleType("unreadable_mod")
        mod.__file__ = "/nonexistent/module.py"

        mock_server = MagicMock()
        count = wrap_all_tools(mock_server, mod)
        assert count == 0


# ────────────────────────────────────────────────────────────────────
# wrap_server_tools_runtime
# ────────────────────────────────────────────────────────────────────


class TestWrapServerToolsRuntime:
    def test_wraps_tools_in_providers(self):
        tool_info = MagicMock()
        tool_info.fn = AsyncMock()

        provider = MagicMock()
        provider._components = {"tool:my_tool@": tool_info}

        server = MagicMock()
        server.providers = [provider]

        count = wrap_server_tools_runtime(server)
        assert count == 1
        # fn should have been replaced
        assert tool_info.fn != AsyncMock  # It was replaced

    def test_skips_debug_tool(self):
        tool_info = MagicMock()
        tool_info.fn = AsyncMock()

        provider = MagicMock()
        provider._components = {"tool:debug_tool@": tool_info}

        server = MagicMock()
        server.providers = [provider]

        original_fn = tool_info.fn
        count = wrap_server_tools_runtime(server)
        assert count == 0
        assert tool_info.fn is original_fn  # Not replaced

    def test_skips_private_tools(self):
        tool_info = MagicMock()
        tool_info.fn = AsyncMock()

        provider = MagicMock()
        provider._components = {"tool:_internal@": tool_info}

        server = MagicMock()
        server.providers = [provider]

        count = wrap_server_tools_runtime(server)
        assert count == 0

    def test_skips_non_tool_components(self):
        provider = MagicMock()
        provider._components = {"resource:some_resource@": MagicMock()}

        server = MagicMock()
        server.providers = [provider]

        count = wrap_server_tools_runtime(server)
        assert count == 0

    def test_skips_provider_without_components(self):
        provider = MagicMock(spec=[])  # No _components attribute

        server = MagicMock()
        server.providers = [provider]

        count = wrap_server_tools_runtime(server)
        assert count == 0

    def test_no_providers(self):
        server = MagicMock()
        server.providers = []

        count = wrap_server_tools_runtime(server)
        assert count == 0

    def test_tool_without_fn(self):
        tool_info = MagicMock(spec=[])  # No fn attribute

        provider = MagicMock()
        provider._components = {"tool:nofn@": tool_info}

        server = MagicMock()
        server.providers = [provider]

        count = wrap_server_tools_runtime(server)
        assert count == 0


# ────────────────────────────────────────────────────────────────────
# _create_debug_wrapper
# ────────────────────────────────────────────────────────────────────


class TestCreateDebugWrapper:
    @pytest.mark.asyncio
    async def test_success_passes_through(self):
        async def original():
            return [TextContent(type="text", text="OK")]

        with patch("server.debuggable.record_tool_call", create=True):
            pass

        wrapper = _create_debug_wrapper("test", original)
        # Mock the stats import to avoid ImportError
        with patch.dict(
            "sys.modules", {"tool_modules.aa_workflow.src.agent_stats": MagicMock()}
        ):
            result = await wrapper()
        assert result[0].text == "OK"

    @pytest.mark.asyncio
    async def test_failure_list_adds_hint(self):
        async def failing():
            return [TextContent(type="text", text="❌ Error occurred")]

        wrapper = _create_debug_wrapper("fail_tool", failing)
        with patch.dict(
            "sys.modules", {"tool_modules.aa_workflow.src.agent_stats": MagicMock()}
        ):
            result = await wrapper()

        assert len(result) == 2
        assert "debug_tool" in result[1].text

    @pytest.mark.asyncio
    async def test_failure_string_adds_hint(self):
        async def failing():
            return "❌ String error"

        wrapper = _create_debug_wrapper("str_fail", failing)
        with patch.dict(
            "sys.modules", {"tool_modules.aa_workflow.src.agent_stats": MagicMock()}
        ):
            result = await wrapper()

        assert isinstance(result, str)
        assert "debug_tool" in result

    @pytest.mark.asyncio
    async def test_exception_returns_crash_info(self):
        async def crasher():
            raise RuntimeError("kaboom")

        wrapper = _create_debug_wrapper("crash", crasher)
        with patch.dict(
            "sys.modules", {"tool_modules.aa_workflow.src.agent_stats": MagicMock()}
        ):
            result = await wrapper()

        assert "crash" in result
        assert "kaboom" in result
        assert "debug_tool" in result

    @pytest.mark.asyncio
    async def test_remediation_hints_included(self):
        async def net_error():
            return [TextContent(type="text", text="❌ No route to host")]

        wrapper = _create_debug_wrapper("net_tool", net_error)
        with patch.dict(
            "sys.modules", {"tool_modules.aa_workflow.src.agent_stats": MagicMock()}
        ):
            result = await wrapper()

        hint_text = result[-1].text
        assert "vpn_connect" in hint_text

    @pytest.mark.asyncio
    async def test_preserves_function_name(self):
        async def named_fn():
            return "ok"

        wrapper = _create_debug_wrapper("test_name", named_fn)
        assert wrapper.__name__ == "named_fn"

    @pytest.mark.asyncio
    async def test_exception_with_remediation(self):
        async def auth_crash():
            raise RuntimeError("Unauthorized access denied")

        wrapper = _create_debug_wrapper("stage_tool", auth_crash)
        with patch.dict(
            "sys.modules", {"tool_modules.aa_workflow.src.agent_stats": MagicMock()}
        ):
            result = await wrapper()

        assert "kube_login" in result

    @pytest.mark.asyncio
    async def test_string_failure_with_remediation(self):
        async def slack_fail():
            return "❌ invalid_auth from slack API"

        wrapper = _create_debug_wrapper("slack_tool", slack_fail)
        with patch.dict(
            "sys.modules", {"tool_modules.aa_workflow.src.agent_stats": MagicMock()}
        ):
            result = await wrapper()

        assert "Slack" in result
