"""AA alertmanager MCP Server - Standalone entry point.

This module delegates to server/ for the server infrastructure.
It only specifies which tool modules to load.
"""

import sys
from pathlib import Path

# Ensure server module is importable
PROJECT_DIR = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_DIR))

import asyncio

from server.main import create_mcp_server, run_mcp_server, setup_logging


def main():
    """Run the alertmanager-only MCP server."""
    setup_logging()
    server = create_mcp_server(name="aa-alertmanager", tools=["alertmanager"])
    asyncio.run(run_mcp_server(server))


if __name__ == "__main__":
    main()
