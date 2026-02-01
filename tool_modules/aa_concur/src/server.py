"""Concur MCP Server - Expense automation tools.

Provides tools for automating expense submission workflows.
"""

import logging

from fastmcp import FastMCP

from .tools_basic import register_tools

logger = logging.getLogger(__name__)


def create_server() -> FastMCP:
    """Create and configure the Concur MCP server."""
    server = FastMCP("aa-concur")

    # Register tools
    tool_count = register_tools(server)
    logger.info(f"Registered {tool_count} concur tools")

    return server


# Create default server instance
server = create_server()

if __name__ == "__main__":
    import asyncio

    asyncio.run(server.run())
