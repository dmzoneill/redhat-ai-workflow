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

    # Disable scheduler:
    python -m server --agent developer --no-scheduler
"""

import argparse
import asyncio
import logging
import sys
from typing import cast

from fastmcp import FastMCP

# Import shared path resolution utilities
from .tool_paths import PROJECT_DIR, get_tools_file_path


def load_agent_config(agent_name: str) -> list[str] | None:
    """Load tool modules from an agent config file."""
    agent_file = PROJECT_DIR / "personas" / f"{agent_name}.yaml"
    if not agent_file.exists():
        return None

    try:
        import yaml

        with open(agent_file) as f:
            config = yaml.safe_load(f)
        return cast(list[str], config.get("tools", []))
    except Exception:
        return None


def setup_logging() -> logging.Logger:
    """Configure logging for MCP server.

    Logs go to journalctl when running under systemd.
    Format excludes timestamp since journald adds its own.
    Logs to stderr since stdout is reserved for JSON-RPC.
    """
    stream_handler = logging.StreamHandler(sys.stderr)

    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s - %(levelname)s - %(message)s",
        handlers=[stream_handler],
    )
    return logging.getLogger(__name__)


def _get_tool_names_sync(server: FastMCP) -> set[str]:
    """
    Get tool names from FastMCP server synchronously.

    NOTE: This uses FastMCP's internal _components API because:
    1. The public list_tools() method is async
    2. This function is called during synchronous module loading
    3. We need to detect which tools were added by each module

    FastMCP v3 stores tools in providers._components with keys like 'tool:name@'.
    If FastMCP changes this internal structure, this function will need updating.

    TODO: When FastMCP provides a sync API for listing tools, migrate to that.
    See: https://gofastmcp.com/python-sdk/fastmcp-server-server#list_tools

    Args:
        server: FastMCP server instance

    Returns:
        Set of tool names
    """
    tool_names: set[str] = set()
    for provider in server.providers:
        # Access internal _components dict - this is FastMCP v3 specific
        # Keys are formatted as 'tool:name@version'
        components = getattr(provider, "_components", None)
        if components is not None:
            for key in components:
                if key.startswith("tool:"):
                    # Extract name from 'tool:name@version' format
                    name = key.split(":")[1].split("@")[0]
                    tool_names.add(name)
    return tool_names


def _load_single_tool_module(
    tool_name: str, server: FastMCP, tools_before: set[str] | None = None
) -> list[str]:
    """
    Load a single tool module and register its tools.

    Args:
        tool_name: Tool module name
        server: FastMCP server instance
        tools_before: Set of tool names before loading (to detect new tools)

    Returns:
        List of tool names that were loaded, empty list on failure
    """
    logger = logging.getLogger(__name__)

    tools_file = get_tools_file_path(tool_name)

    if not tools_file.exists():
        logger.warning(f"Tools file not found: {tools_file}")
        return []

    import importlib.util

    spec = importlib.util.spec_from_file_location(f"aa_{tool_name}_tools", tools_file)
    if spec is None or spec.loader is None:
        logger.warning(f"Could not create spec for {tool_name}")
        return []

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if hasattr(module, "register_tools"):
        module.register_tools(server)

        # Detect which tools were added by this module (FastMCP v3 compatible)
        tools_after = _get_tool_names_sync(server)
        new_tools = list(tools_after - (tools_before or set()))

        logger.info(f"Loaded {tool_name}: {len(new_tools)} tools")
        return new_tools
    else:
        logger.warning(f"Module aa_{tool_name} has no register_tools function")
        return []


def _register_debug_for_module(server: FastMCP, tool_name: str):
    """
    Register debug tools for a single loaded module.

    Args:
        server: FastMCP server instance
        tool_name: Tool module name
    """
    import importlib.util

    from .debuggable import wrap_all_tools

    tools_file = get_tools_file_path(tool_name)

    if not tools_file.exists():
        return

    spec = importlib.util.spec_from_file_location(
        f"aa_{tool_name}_tools_debug", tools_file
    )
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        wrap_all_tools(server, module)


def create_mcp_server(
    name: str = "aa_workflow",
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

    # Get available modules dynamically
    from .persona_loader import get_available_modules

    available_modules = get_available_modules()

    # Determine which tools to load
    if tools is None:
        tools = list(available_modules)

    # Warn if loading many tools
    if len(tools) > 128:
        logger.warning(f"Loading {len(tools)} tools, may exceed Cursor's limit of 128!")

    # Load all requested tool modules, tracking which tools come from which module
    loaded_modules = []
    tool_to_module: dict[str, str] = {}  # tool_name -> module_name

    for module_name in tools:
        if module_name not in available_modules:
            logger.warning(
                f"Unknown tool module: {module_name}. Available: {sorted(available_modules)}"
            )
            continue

        try:
            # Get current tools before loading (FastMCP v3 compatible)
            tools_before = _get_tool_names_sync(server)

            new_tools = _load_single_tool_module(module_name, server, tools_before)
            if new_tools:
                loaded_modules.append(module_name)
                # Track which tools came from this module
                for tool_name in new_tools:
                    tool_to_module[tool_name] = module_name
        except Exception as e:
            logger.error(f"Error loading {module_name}: {e}")

    # Register debug_tool and wrap all tools with auto-fix hints
    try:
        from .debuggable import register_debug_tool, wrap_server_tools_runtime

        register_debug_tool(server)

        # Register all loaded tools in the debug registry (for source lookup)
        for tool_name in loaded_modules:
            _register_debug_for_module(server, tool_name)

        # Wrap all tools at runtime to add debug hints on failure
        wrapped_count = wrap_server_tools_runtime(server)

        logger.info(
            f"Registered debug_tool and wrapped {wrapped_count} tools for auto-fixing"
        )
    except Exception as e:
        logger.warning(f"Could not register debug_tool: {e}")

    # Initialize dynamic persona loader with tool-to-module mapping
    try:
        from .persona_loader import init_loader

        loader = init_loader(server)
        loader.loaded_modules = set(loaded_modules)
        loader._tool_to_module = tool_to_module.copy()
        logger.info(
            f"Initialized PersonaLoader: {len(loader.loaded_modules)} modules, "
            f"{len(loader._tool_to_module)} tools"
        )
    except Exception as e:
        logger.warning(f"Could not initialize persona loader: {e}")

    # Restore workspace sessions from disk (survives server restarts)
    try:
        from .workspace_state import WorkspaceRegistry

        restored = WorkspaceRegistry.restore_if_empty()
        if restored > 0:
            logger.info(f"Restored {restored} session(s) from previous server run")
    except Exception as e:
        logger.warning(f"Could not restore workspace sessions: {e}")

    logger.info(
        f"Server ready with tools from {len(loaded_modules)} modules: {loaded_modules}"
    )
    return server


# ==================== Scheduler Integration ====================


async def init_scheduler(server: FastMCP) -> bool:
    """Initialize and start the scheduler subsystem.

    The scheduler always starts to enable config watching.
    Jobs are only scheduled if enabled in config.

    Args:
        server: FastMCP server instance for skill execution

    Returns:
        True if scheduler started successfully
    """
    logger = logging.getLogger(__name__)

    # File-based logging for debugging
    from datetime import datetime
    from pathlib import Path  # noqa: F811

    def _log(msg):
        try:
            log_file = Path.home() / ".config" / "aa-workflow" / "scheduler.log"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a") as f:
                f.write(f"{datetime.now().isoformat()} - [main.py] {msg}\n")
        except Exception:
            pass

    _log("init_scheduler called")

    try:
        from tool_modules.aa_workflow.src.notification_engine import (
            init_notification_engine,
            send_notification,
        )
        from tool_modules.aa_workflow.src.poll_engine import init_poll_engine
        from tool_modules.aa_workflow.src.scheduler import (
            init_scheduler as init_cron_scheduler,
        )
        from tool_modules.aa_workflow.src.scheduler import start_scheduler

        from .state_manager import state as state_manager
        from .utils import load_config

        config = load_config()
        schedules_config = config.get("schedules", {})

        scheduler_enabled = state_manager.is_service_enabled("scheduler")
        if not scheduler_enabled:
            logger.info(
                "Scheduler disabled in state.json (will start config watcher only)"
            )

        # Initialize notification engine
        init_notification_engine(server=server, config=config)

        # Create notification callback for scheduler
        async def notification_callback(
            job_name: str,
            skill: str,
            success: bool,
            output: str | None,
            error: str | None,
            channels: list[str],
        ):
            await send_notification(
                job_name=job_name,
                skill=skill,
                success=success,
                output=output,
                error=error,
                channels=channels,
            )

        # Initialize cron scheduler
        scheduler = init_cron_scheduler(
            server=server,
            notification_callback=notification_callback,
        )

        # Initialize poll engine with job execution callback
        async def poll_job_callback(
            job_name: str,
            skill: str,
            inputs: dict,
            notify: list[str],
        ):
            await scheduler._execute_job(
                job_name=job_name,
                skill=skill,
                inputs=inputs,
                notify=notify,
            )

        poll_engine = init_poll_engine(
            server=server,
            job_callback=poll_job_callback,
        )

        # Configure poll engine with sources and jobs (only if enabled)
        if scheduler_enabled:
            poll_engine.configure(
                poll_sources=schedules_config.get("poll_sources", {}),
                poll_jobs=scheduler.config.get_poll_jobs(),
            )

        # Start scheduler (always starts for config watching)
        # Pass add_cron_jobs=False because cron_daemon.py handles cron job execution
        # The MCP server scheduler only does config watching and poll jobs
        _log("Calling start_scheduler(add_cron_jobs=False)")
        await start_scheduler(add_cron_jobs=False)
        _log("start_scheduler() completed")

        # Start poll engine only if scheduler is enabled
        if scheduler_enabled:
            await poll_engine.start()
            logger.info("Scheduler subsystem initialized and started")
            _log("Scheduler subsystem initialized and started")
        else:
            logger.info("Scheduler config watcher started (jobs disabled)")
            _log("Scheduler config watcher started (jobs disabled)")

        return True

    except ImportError as e:
        logger.warning(f"Scheduler dependencies not available: {e}")
        logger.info("Install with: uv add apscheduler croniter")
        _log(f"ImportError: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to initialize scheduler: {e}")
        _log(f"Exception: {e}")
        import traceback

        _log(f"Traceback: {traceback.format_exc()}")
        return False


async def stop_scheduler():
    """Stop the scheduler subsystem gracefully."""
    logger = logging.getLogger(__name__)

    try:
        from tool_modules.aa_workflow.src.poll_engine import get_poll_engine
        from tool_modules.aa_workflow.src.scheduler import (
            stop_scheduler as stop_cron_scheduler,
        )

        await stop_cron_scheduler()

        poll_engine = get_poll_engine()
        if poll_engine:
            await poll_engine.stop()

        logger.info("Scheduler subsystem stopped")
    except Exception as e:
        logger.warning(f"Error stopping scheduler: {e}")


async def run_mcp_server(server: FastMCP, enable_scheduler: bool = True):
    """Run the MCP server in stdio mode (for AI integrations).

    Args:
        server: FastMCP server instance
        enable_scheduler: Whether to start the scheduler subsystem
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting MCP server (stdio mode)...")

    # Initialize scheduler if enabled
    scheduler_started = False
    if enable_scheduler:
        scheduler_started = await init_scheduler(server)

    # Start WebSocket server for real-time skill updates
    ws_server = None
    try:
        from .websocket_server import start_websocket_server

        ws_server = await start_websocket_server()
        logger.info("WebSocket server started for real-time updates")
    except ImportError:
        logger.debug(
            "WebSocket server not available (websockets package not installed)"
        )
    except Exception as e:
        logger.warning(f"Failed to start WebSocket server: {e}")

    # Initialize Memory Abstraction Layer
    try:
        from services.memory_abstraction import (
            MemoryInterface,
            discover_and_load_all_adapters,
            set_memory_interface,
        )

        # Discover and load all memory adapters
        adapters = discover_and_load_all_adapters()
        logger.info(
            f"Discovered {len(adapters)} memory adapters: {list(adapters.keys())}"
        )

        # Create memory interface with WebSocket for events
        memory = MemoryInterface(adapters=adapters, websocket_server=ws_server)
        set_memory_interface(memory)

        # Attach to server for tool access
        server.memory = memory

        logger.info("Memory abstraction layer initialized")
    except ImportError as e:
        logger.debug(f"Memory abstraction not available: {e}")
    except Exception as e:
        logger.warning(f"Failed to initialize memory abstraction: {e}")

    try:
        await server.run_stdio_async()
    finally:
        # Cleanup WebSocket server on shutdown
        if ws_server:
            try:
                from .websocket_server import stop_websocket_server as _stop_ws

                await _stop_ws()
                logger.info("WebSocket server stopped")
            except Exception as e:
                logger.warning(f"Error stopping WebSocket server: {e}")

        # Cleanup scheduler on shutdown
        if scheduler_started:
            await stop_scheduler()


def main():
    """Main entry point with tool selection."""
    # Get available modules for help text
    from .persona_loader import get_available_modules

    available = sorted(get_available_modules())
    # Show base modules (without _basic/_extra suffixes) for cleaner help
    base_modules = sorted(
        {m.replace("_basic", "").replace("_extra", "") for m in available}
    )

    parser = argparse.ArgumentParser(
        description="AA Modular MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Available tool modules (dynamically discovered):
  {', '.join(base_modules)}

  Note: Most modules support _basic and _extra variants (e.g., git_basic, git_extra)

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
        "--name",
        default="",
        help="Server name (default: based on agent or 'aa_workflow')",
    )
    parser.add_argument(
        "--no-scheduler",
        action="store_true",
        help="Disable the cron scheduler subsystem",
    )

    args = parser.parse_args()
    logger = setup_logging()

    # Determine tools to load
    if args.agent:
        # Load from agent config
        tools = load_agent_config(args.agent)
        if tools is None:
            logger.error(f"Agent config not found: {args.agent}")
            logger.info(
                "Available agents: devops, developer, incident, release, universal"
            )
            sys.exit(1)
        server_name = args.name or f"aa-{args.agent}"
        logger.info(f"Loading agent '{args.agent}' with {len(tools)} modules: {tools}")
    elif args.all:
        tools = None  # Load all
        server_name = args.name or "aa_workflow"
        logger.warning("Loading ALL tools - may exceed Cursor's 128 tool limit!")
    elif args.tools:
        tools = [t.strip() for t in args.tools.split(",") if t.strip()]
        server_name = args.name or "aa_workflow"
    else:
        # Default: load persona from config (fallback to developer)
        # This provides the configured default toolset
        from server.utils import load_config

        cfg = load_config()
        default_agent = cfg.get("agent", {}).get("default_persona", "researcher")
        tools = load_agent_config(default_agent)
        if tools is None:
            # Fallback to workflow only if developer persona missing
            tools = ["workflow"]
            server_name = args.name or "aa_workflow"
            logger.info(
                "Starting in dynamic mode - use persona_load() to switch personas"
            )
        else:
            server_name = args.name or f"aa-{default_agent}"
            logger.info(
                f"Loading default agent '{default_agent}' with {len(tools)} modules: {tools}"
            )

    try:
        server = create_mcp_server(name=server_name, tools=tools)
        enable_scheduler = not args.no_scheduler
        asyncio.run(run_mcp_server(server, enable_scheduler=enable_scheduler))
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
