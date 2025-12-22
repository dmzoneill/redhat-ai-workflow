"""AA quay MCP Server - Standalone entry point.

This module delegates to aa-common for the server infrastructure.
It only specifies which tool modules to load.
"""

import sys
from pathlib import Path

# Ensure aa-common is importable
SERVERS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SERVERS_DIR / "aa-common"))

from src.server import create_mcp_server, run_mcp_server, run_web_server, setup_logging
import asyncio


def main():
    """Run the quay-only MCP server."""
    setup_logging()
    server = create_mcp_server(name="aa-quay", tools=["quay"])
    asyncio.run(run_mcp_server(server))


if __name__ == "__main__":
    main()
