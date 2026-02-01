"""Google Calendar Tools - Extra/advanced tools.

This module contains additional calendar tools that are not part of the basic set.
Currently empty - basic tools are in tools_basic.py.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_tools(server: "FastMCP") -> int:
    """Register extra Google Calendar tools with the MCP server.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    # No extra tools currently
    return 0
