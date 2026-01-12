"""AA Slack MCP Server - Standalone entry point.

This module delegates to server/ for the server infrastructure.
It only specifies which tool modules to load.
"""

import asyncio

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization


# Now server is importable
from server.main import create_mcp_server, run_mcp_server, setup_logging

# Setup path FIRST - adds project root to sys.path


def main():
    """Run the slack-only MCP server."""
    setup_logging()
    server = create_mcp_server(name="aa_slack", tools=["slack"])
    asyncio.run(run_mcp_server(server))


if __name__ == "__main__":
    main()
