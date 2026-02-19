"""Standalone MCP Server Factory.

Eliminates the need for identical server.py boilerplate in every tool module.
Each module's server.py was copy-pasted with only the name/tools changed.

Usage in tool_modules/aa_git/src/server.py:
    from tool_modules.common.server_factory import make_server_main
    main = make_server_main("aa_git", ["git"])
    if __name__ == "__main__":
        main()

Or run directly from CLI:
    python -m tool_modules.common.server_factory --name aa_git --tools git
"""

import asyncio
from typing import Callable


def make_server_main(name: str, tools: list[str]) -> Callable[[], None]:
    """Create a main() function for a standalone MCP server.

    Args:
        name: Server name (e.g., "aa_git")
        tools: List of tool module names to load (e.g., ["git"])

    Returns:
        A main() function that starts the server.
    """
    # Import here so that tool_modules.common path setup has already run
    import tool_modules.common  # noqa: F401 - sets up sys.path  # noqa: F401 - sets up sys.path

    def main():
        from server.main import create_mcp_server, run_mcp_server, setup_logging

        setup_logging()
        server = create_mcp_server(name=name, tools=tools)
        asyncio.run(run_mcp_server(server))

    return main


def cli_main():
    """CLI entry point: python -m tool_modules.common.server_factory --name aa_git --tools git."""
    import argparse

    parser = argparse.ArgumentParser(description="Run a standalone MCP tool server")
    parser.add_argument("--name", required=True, help="Server name (e.g., aa_git)")
    parser.add_argument(
        "--tools",
        required=True,
        nargs="+",
        help="Tool modules to load (e.g., git jira)",
    )
    args = parser.parse_args()

    main = make_server_main(args.name, args.tools)
    main()


if __name__ == "__main__":
    cli_main()
