"""Tool Registration Helper.

Provides a decorator-based registry for tracking tools registered with FastMCP.
This eliminates manual tool counting and provides accurate tool lists.

Usage:
    from server.tool_registry import ToolRegistry

    def register_tools(server: FastMCP) -> int:
        registry = ToolRegistry(server)

        @registry.tool()
        async def my_tool(arg: str) -> str:
            '''Tool docstring.'''
            return "result"

        @registry.tool(name="custom_name")
        async def another_tool() -> str:
            '''Another tool.'''
            return "result"

        return registry.count
"""

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from fastmcp import FastMCP


class ToolRegistry:
    """Registry for tracking tools registered with FastMCP.

    Wraps the FastMCP server and tracks all tools registered through it,
    providing accurate counts and tool listings.

    Attributes:
        server: The FastMCP server instance
        tools: List of registered tool names
    """

    def __init__(self, server: "FastMCP"):
        """Initialize the registry with a FastMCP server.

        Args:
            server: FastMCP server instance to register tools with
        """
        self.server = server
        self.tools: list[str] = []

    def tool(self, **kwargs: Any) -> Callable:
        """Decorator to register a tool with the server and track it.

        Passes all kwargs to the underlying FastMCP.tool() decorator.

        Args:
            **kwargs: Arguments to pass to FastMCP.tool()
                - name: Optional custom tool name
                - description: Optional tool description

        Returns:
            Decorator function
        """

        def decorator(func: Callable) -> Callable:
            # Use custom name if provided, otherwise use function name
            tool_name = kwargs.get("name", func.__name__)
            self.tools.append(tool_name)

            # Register with the actual FastMCP server
            return self.server.tool(**kwargs)(func)

        return decorator

    @property
    def count(self) -> int:
        """Get the number of registered tools.

        Returns:
            Number of tools registered through this registry
        """
        return len(self.tools)

    def list_tools(self) -> list[str]:
        """Get list of registered tool names.

        Returns:
            List of tool names in registration order
        """
        return self.tools.copy()

    def __len__(self) -> int:
        """Support len() on the registry."""
        return self.count

    def __contains__(self, tool_name: str) -> bool:
        """Support 'in' operator for checking if a tool is registered."""
        return tool_name in self.tools
