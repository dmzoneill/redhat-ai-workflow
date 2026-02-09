"""Tests for server.tool_registry module.

Tests the ToolRegistry class that wraps FastMCP for decorator-based
tool registration and tracking.
"""

from unittest.mock import MagicMock

import pytest

from server.tool_registry import ToolRegistry


@pytest.fixture
def mock_server():
    """Create a mock FastMCP server."""
    server = MagicMock()
    # server.tool() returns a decorator that returns the function unchanged
    server.tool.return_value = lambda func: func
    return server


@pytest.fixture
def registry(mock_server):
    """Create a ToolRegistry with a mock server."""
    return ToolRegistry(mock_server)


class TestToolRegistryInit:
    """Tests for ToolRegistry initialization."""

    def test_init_stores_server(self, mock_server):
        """Registry should store the server reference."""
        reg = ToolRegistry(mock_server)
        assert reg.server is mock_server

    def test_init_empty_tools_list(self, mock_server):
        """Registry should start with an empty tools list."""
        reg = ToolRegistry(mock_server)
        assert reg.tools == []

    def test_init_count_is_zero(self, mock_server):
        """Registry should start with count of zero."""
        reg = ToolRegistry(mock_server)
        assert reg.count == 0


class TestToolDecorator:
    """Tests for the @registry.tool() decorator."""

    def test_register_tool_by_function_name(self, registry):
        """Decorator without name kwarg should use function name."""

        @registry.tool()
        async def my_tool():
            """My tool docstring."""
            return "result"

        assert "my_tool" in registry.tools
        assert registry.count == 1

    def test_register_tool_with_custom_name(self, registry):
        """Decorator with name kwarg should use custom name."""

        @registry.tool(name="custom_name")
        async def another_tool():
            """Another tool."""
            return "result"

        assert "custom_name" in registry.tools
        assert "another_tool" not in registry.tools
        assert registry.count == 1

    def test_register_multiple_tools(self, registry):
        """Registering multiple tools should track all of them."""

        @registry.tool()
        async def tool_a():
            return "a"

        @registry.tool()
        async def tool_b():
            return "b"

        @registry.tool(name="tool_c_custom")
        async def tool_c():
            return "c"

        assert registry.count == 3
        assert "tool_a" in registry.tools
        assert "tool_b" in registry.tools
        assert "tool_c_custom" in registry.tools

    def test_decorator_returns_callable(self, registry):
        """The decorated function should remain callable."""

        @registry.tool()
        async def my_tool():
            return "hello"

        # The function should be callable (it was passed through server.tool())
        assert callable(my_tool)

    def test_decorator_passes_kwargs_to_server(self, registry, mock_server):
        """All kwargs should be forwarded to server.tool()."""

        @registry.tool(name="custom", description="A custom tool")
        async def my_tool():
            return "result"

        mock_server.tool.assert_called_with(name="custom", description="A custom tool")
        assert mock_server.tool.call_count >= 1

    def test_decorator_preserves_registration_order(self, registry):
        """Tools should be stored in registration order."""

        @registry.tool()
        async def first():
            pass

        @registry.tool()
        async def second():
            pass

        @registry.tool()
        async def third():
            pass

        assert registry.tools == ["first", "second", "third"]


class TestCount:
    """Tests for the count property."""

    def test_count_empty(self, registry):
        """Count should be 0 when no tools registered."""
        assert registry.count == 0

    def test_count_after_registration(self, registry):
        """Count should reflect number of registered tools."""

        @registry.tool()
        async def tool_one():
            pass

        assert registry.count == 1

        @registry.tool()
        async def tool_two():
            pass

        assert registry.count == 2


class TestListTools:
    """Tests for the list_tools method."""

    def test_list_tools_empty(self, registry):
        """list_tools should return empty list when no tools registered."""
        assert registry.list_tools() == []

    def test_list_tools_returns_copy(self, registry):
        """list_tools should return a copy, not a reference."""

        @registry.tool()
        async def my_tool():
            pass

        result = registry.list_tools()
        result.append("extra_tool")
        # Original should not be modified
        assert "extra_tool" not in registry.tools
        assert registry.count == 1

    def test_list_tools_has_all_tools(self, registry):
        """list_tools should contain all registered tool names."""

        @registry.tool()
        async def alpha():
            pass

        @registry.tool(name="beta_custom")
        async def beta():
            pass

        result = registry.list_tools()
        assert result == ["alpha", "beta_custom"]


class TestDunderMethods:
    """Tests for __len__ and __contains__."""

    def test_len(self, registry):
        """len() should return the count of registered tools."""
        assert len(registry) == 0

        @registry.tool()
        async def tool_a():
            pass

        assert len(registry) == 1

        @registry.tool()
        async def tool_b():
            pass

        assert len(registry) == 2

    def test_contains_registered_tool(self, registry):
        """'in' operator should return True for registered tools."""

        @registry.tool()
        async def my_tool():
            pass

        assert "my_tool" in registry

    def test_contains_unregistered_tool(self, registry):
        """'in' operator should return False for unregistered tools."""
        assert "nonexistent" not in registry

    def test_contains_with_custom_name(self, registry):
        """'in' operator should work with custom tool names."""

        @registry.tool(name="custom")
        async def my_tool():
            pass

        assert "custom" in registry
        assert "my_tool" not in registry


class TestEdgeCases:
    """Tests for edge cases."""

    def test_duplicate_tool_names_allowed(self, registry):
        """Registering tools with duplicate names should add both."""
        # Note: This tests current behavior; duplicates are tracked.

        @registry.tool(name="dupe")
        async def tool_1():
            pass

        @registry.tool(name="dupe")
        async def tool_2():
            pass

        assert registry.count == 2
        assert registry.tools.count("dupe") == 2

    def test_empty_name_kwarg(self, registry):
        """Empty string name should be used as-is."""

        @registry.tool(name="")
        async def my_tool():
            pass

        # name="" is falsy, so it falls back to func.__name__
        # Because kwargs.get("name", func.__name__) with name="" returns ""
        assert "" in registry.tools

    def test_server_tool_raises(self, mock_server):
        """If server.tool() raises, the error propagates."""
        mock_server.tool.side_effect = RuntimeError("Server error")
        reg = ToolRegistry(mock_server)

        with pytest.raises(RuntimeError, match="Server error"):

            @reg.tool()
            async def bad_tool():
                pass
