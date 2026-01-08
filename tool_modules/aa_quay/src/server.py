"""AA Quay MCP Server - Standalone entry point.

This module delegates to server/ for the server infrastructure.
It only specifies which tool modules to load.
"""

import asyncio

# Now server is importable
from server.main import create_mcp_server, run_mcp_server, setup_logging

# Setup path FIRST - adds project root to sys.path
from tool_modules.common import PROJECT_ROOT  # noqa: F401 - side effect


def main():
    """Run the quay-only MCP server."""
    setup_logging()
    server = create_mcp_server(name="aa_quay", tools=["quay"])
    asyncio.run(run_mcp_server(server))


if __name__ == "__main__":
    main()
