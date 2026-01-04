"""MCP Server - Main Entry Point.

This module provides the MCP server infrastructure that loads tool modules dynamically.
Tool modules are plugins in the tool_modules/ directory.

Usage:
    # Run with specific tools:
    python -m server --tools git,jira,gitlab

    # Run all tools (may exceed tool limits!):
    python -m server --all

    # Run with a persona config (recommended - stays under tool limits):
    python -m server --agent devops

    # Run with web UI:
    python -m server --tools git,jira --web --port 8765
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Directory structure:
# ai-workflow/
#   server/         <- This file is here
#     main.py
#   tool_modules/   <- Plugins are here
#     aa-git/
#     aa-jira/
#     ...
PROJECT_DIR = Path(__file__).parent.parent  # ai-workflow root
TOOL_MODULES_DIR = PROJECT_DIR / "tool_modules"

# Available tool modules - we'll load them dynamically
TOOL_MODULES = {
    "git": 15,
    "jira": 24,
    "gitlab": 35,
    "k8s": 26,
    "prometheus": 13,
    "alertmanager": 6,
    "kibana": 9,
    "konflux": 40,
    "bonfire": 21,
    "quay": 8,
    "appinterface": 7,  # +1 for appinterface_get_user
    "workflow": 28,  # +2 for vpn_connect, kube_login
    "slack": 16,  # +1 for slack_dm_gitlab_user
}


def load_agent_config(agent_name: str) -> list[str] | None:
    """Load tool modules from an agent config file."""
    agent_file = PROJECT_DIR / "personas" / f"{agent_name}.yaml"
    if not agent_file.exists():
        return None

    try:
        import yaml

        with open(agent_file) as f:
            config = yaml.safe_load(f)
        return config.get("tools", [])
    except Exception:
        return None


def get_tool_module(name: str):
    """Dynamically load a tool module."""
    module_dir = TOOL_MODULES_DIR / f"aa-{name}"
    if not module_dir.exists():
        return None

    # Add to path if needed
    src_path = str(module_dir)
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    # Import the tools module
    from importlib import import_module

    try:
        return import_module("src.tools")
    except ImportError:
        return None
    finally:
        # Clean up path to avoid conflicts
        if src_path in sys.path:
            sys.path.remove(src_path)


def setup_logging(web_mode: bool = False) -> logging.Logger:
    """Configure logging based on mode."""
    # In web mode, log to stdout; in MCP mode, log to stderr (stdout is for JSON-RPC)
    handler = logging.StreamHandler(sys.stdout if web_mode else sys.stderr)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[handler],
    )
    return logging.getLogger(__name__)


def create_mcp_server(
    name: str = "aa-workflow",
    tools: list[str] | None = None,
) -> FastMCP:
    """
    Create and configure an MCP server with the specified tools.

    Args:
        name: Server name for identification
        tools: List of tool module names to load (e.g., ["git", "jira"])
               If None, loads all available tools

    Returns:
        Configured FastMCP server instance
    """
    logger = logging.getLogger(__name__)
    server = FastMCP(name)

    # Determine which tools to load
    if tools is None:
        tools = list(TOOL_MODULES.keys())

    # Calculate estimated tool count
    estimated = sum(TOOL_MODULES.get(t, 0) for t in tools)
    if estimated > 128:
        logger.warning(f"Loading ~{estimated} tools, may exceed Cursor's limit of 128!")

    loaded_modules = []

    for tool_name in tools:
        if tool_name not in TOOL_MODULES:
            logger.warning(f"Unknown tool module: {tool_name}. Available: {list(TOOL_MODULES.keys())}")
            continue

        try:
            # Load the module using importlib.util.spec_from_file_location
            module_dir = TOOL_MODULES_DIR / f"aa-{tool_name}"
            tools_file = module_dir / "src" / "tools.py"

            if not tools_file.exists():
                logger.warning(f"Tools file not found: {tools_file}")
                continue

            import importlib.util

            spec = importlib.util.spec_from_file_location(f"aa_{tool_name}_tools", tools_file)
            if spec is None or spec.loader is None:
                logger.warning(f"Could not create spec for {tool_name}")
                continue

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, "register_tools"):
                module.register_tools(server)
                loaded_modules.append(tool_name)
                logger.info(f"Loaded {tool_name} tools")
            else:
                logger.warning(f"Module aa-{tool_name} has no register_tools function")

        except Exception as e:
            logger.error(f"Error loading {tool_name}: {e}")

    # Register debug_tool and wrap all tools with auto-fix hints
    try:
        from .debuggable import register_debug_tool, wrap_all_tools, wrap_server_tools_runtime

        register_debug_tool(server)

        # Register all loaded tools in the debug registry (for source lookup)
        for tool_name in loaded_modules:
            module_dir = TOOL_MODULES_DIR / f"aa-{tool_name}"
            tools_file = module_dir / "src" / "tools.py"
            if tools_file.exists():
                # Import and register in debug registry
                import importlib.util

                spec = importlib.util.spec_from_file_location(f"aa_{tool_name}_tools_debug", tools_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    wrap_all_tools(server, module)

        # Wrap all tools at runtime to add debug hints on failure
        wrapped_count = wrap_server_tools_runtime(server)

        logger.info(f"Registered debug_tool and wrapped {wrapped_count} tools for auto-fixing")
    except Exception as e:
        logger.warning(f"Could not register debug_tool: {e}")

    # Initialize dynamic persona loader
    try:
        from .persona_loader import init_loader

        loader = init_loader(server)
        loader.loaded_modules = set(loaded_modules)
        logger.info("Initialized dynamic persona loader")
    except Exception as e:
        logger.warning(f"Could not initialize persona loader: {e}")

    logger.info(f"Server ready with tools from {len(loaded_modules)} modules: {loaded_modules}")
    return server


async def run_mcp_server(server: FastMCP):
    """Run the MCP server in stdio mode (for AI integrations)."""
    logger = logging.getLogger(__name__)
    logger.info("Starting MCP server (stdio mode)...")
    await server.run_stdio_async()


def run_web_server(server: FastMCP, host: str = "127.0.0.1", port: int = 8765):
    """Run the web UI server for configuration and testing."""
    import uvicorn

    from .web import create_app

    logger = logging.getLogger(__name__)

    app = create_app(server)

    logger.info(f"Starting Web UI at http://{host}:{port}")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )


def main():
    """Main entry point with tool selection."""
    parser = argparse.ArgumentParser(
        description="AA Modular MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Available tool modules:
  {', '.join(sorted(TOOL_MODULES.keys()))}

Available agents (recommended - stays under tool limit):
  devops, developer, incident, release

Examples:
  python -m server --agent devops              # Load DevOps agent tools
  python -m server --agent developer           # Load Developer agent tools
  python -m server --tools git,jira,gitlab     # Load specific tools
  python -m server --all                       # Load ALL tools (may exceed limit!)
        """,
    )
    parser.add_argument(
        "--agent",
        type=str,
        default="",
        help="Load tools for a specific agent (devops, developer, incident, release)",
    )
    parser.add_argument(
        "--tools",
        type=str,
        default="",
        help="Comma-separated list of tool modules to load",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Load all available tool modules (WARNING: may exceed Cursor's 128 tool limit)",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Run web UI server instead of MCP stdio server",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for web server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for web server (default: 8765)",
    )
    parser.add_argument(
        "--name",
        default="",
        help="Server name (default: based on agent or 'aa-workflow')",
    )

    args = parser.parse_args()
    logger = setup_logging(web_mode=args.web)

    # Determine tools to load
    if args.agent:
        # Load from agent config
        tools = load_agent_config(args.agent)
        if tools is None:
            logger.error(f"Agent config not found: {args.agent}")
            logger.info("Available agents: devops, developer, incident, release, universal")
            sys.exit(1)
        server_name = args.name or f"aa-{args.agent}"
        estimated = sum(TOOL_MODULES.get(t, 0) for t in tools)
        logger.info(f"Loading agent '{args.agent}' with ~{estimated} tools: {tools}")
    elif args.all:
        tools = None  # Load all
        server_name = args.name or "aa-workflow"
        logger.warning("Loading ALL tools - may exceed Cursor's 128 tool limit!")
    elif args.tools:
        tools = [t.strip() for t in args.tools.split(",") if t.strip()]
        server_name = args.name or "aa-workflow"
    else:
        # Default: start with workflow tools only (dynamic mode)
        tools = ["workflow"]
        server_name = args.name or "aa-workflow"
        logger.info("Starting in dynamic mode - use persona_load() to switch personas")

    try:
        server = create_mcp_server(name=server_name, tools=tools)

        if args.web:
            run_web_server(server, host=args.host, port=args.port)
        else:
            asyncio.run(run_mcp_server(server))
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
