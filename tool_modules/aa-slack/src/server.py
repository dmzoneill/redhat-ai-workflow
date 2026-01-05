"""AA Slack MCP Server - Standalone entry point.

This module delegates to server/ for the server infrastructure.
It only specifies which tool modules to load.
"""

import asyncio

from server.main import create_mcp_server, run_mcp_server, setup_logging

# Setup path using shared bootstrap
from tool_modules.common import PROJECT_ROOT  # noqa: F401 - side effect: adds to sys.path


def main():
    """Run the slack-only MCP server."""
    setup_logging()
    server = create_mcp_server(name="aa-slack", tools=["slack"])
    asyncio.run(run_mcp_server(server))


if __name__ == "__main__":
    main()
