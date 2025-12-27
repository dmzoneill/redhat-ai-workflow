"""AA Slack MCP Server - Standalone Entry Point.

This server provides proactive Slack integration with:
- Background message polling and event detection
- MCP tools for reading/sending messages
- MCP resources for pending message queue
- Persistent state for restart survival

Can run standalone or be loaded as a plugin via aa-common.

Usage:
    # Standalone mode
    python -m src.server

    # With auto-start listener
    python -m src.server --auto-start

    # As systemd/pm2 durable process
    python -m src.server --auto-start --persist
"""

import argparse
import asyncio
import logging
import os
import signal
import sys

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .tools import get_manager, register_tools

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


def setup_logging(debug: bool = False):
    """Configure logging."""
    level = logging.DEBUG if debug else logging.INFO

    # In MCP mode, log to stderr (stdout is for JSON-RPC)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

    logging.basicConfig(level=level, handlers=[handler])

    # Reduce noise from httpx
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


class SlackMCPServer:
    """
    Production-grade Slack MCP Server with lifecycle management.

    Features:
    - Background listener with auto-start option
    - Graceful shutdown handling
    - State persistence across restarts
    - MCP notification support (when available)
    """

    def __init__(
        self,
        auto_start_listener: bool = False,
        persist_state: bool = True,
    ):
        """
        Initialize the server.

        Args:
            auto_start_listener: Start the background listener automatically
            persist_state: Use persistent SQLite state (vs in-memory)
        """
        self.auto_start_listener = auto_start_listener
        self.persist_state = persist_state

        self.server = FastMCP("aa-slack")
        self._manager = None
        self._shutdown_event = asyncio.Event()

    async def setup(self):
        """Set up the server components."""
        # Register tools
        tool_count = register_tools(self.server)
        logger.info(f"Registered {tool_count} Slack tools")

        # Initialize manager
        self._manager = await get_manager()

        # Validate environment
        try:
            xoxc = os.getenv("SLACK_XOXC_TOKEN", "")
            d_cookie = os.getenv("SLACK_D_COOKIE", "")

            if not xoxc or not d_cookie:
                logger.warning(
                    "SLACK_XOXC_TOKEN and SLACK_D_COOKIE not set. "
                    "Slack tools will fail until credentials are provided."
                )
            else:
                logger.info("Slack credentials found in environment")

        except Exception as e:
            logger.warning(f"Environment validation: {e}")

        # Auto-start listener if configured
        if self.auto_start_listener:
            try:
                await self._manager.start()
                logger.info("Background listener started automatically")
            except Exception as e:
                logger.error(f"Failed to start listener: {e}")

    async def shutdown(self):
        """Clean shutdown of all components."""
        logger.info("Shutting down Slack MCP server...")

        if self._manager:
            await self._manager.stop()

        logger.info("Shutdown complete")

    def setup_signal_handlers(self):
        """Set up graceful shutdown signal handlers."""

        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating shutdown...")
            self._shutdown_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    async def run_stdio(self):
        """Run in MCP stdio mode (for AI integrations)."""
        await self.setup()

        try:
            await self.server.run_stdio_async()
        finally:
            await self.shutdown()

    async def run_durable(self):
        """
        Run as a durable background process.

        This mode is for running the listener continuously
        (e.g., via systemd or pm2) with the MCP server available.
        """
        await self.setup()
        self.setup_signal_handlers()

        logger.info("Running in durable mode - waiting for shutdown signal")

        try:
            # Wait for shutdown signal
            await self._shutdown_event.wait()
        finally:
            await self.shutdown()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="AA Slack MCP Server - Proactive Slack Integration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment Variables:
  SLACK_XOXC_TOKEN      - Slack web client token (required)
  SLACK_D_COOKIE        - Slack session cookie (required)
  SLACK_POLL_INTERVAL   - Poll interval in seconds (default: 5)
  SLACK_WATCHED_CHANNELS - Comma-separated channel IDs to monitor
  SLACK_WATCHED_KEYWORDS - Comma-separated keywords to trigger on
  SLACK_SELF_USER_ID    - Your user ID (to ignore own messages)
  SLACK_STATE_DB_PATH   - Path to SQLite state file

Examples:
  # Run as MCP server (for Cursor integration)
  python -m src.server

  # Run with auto-start listener
  python -m src.server --auto-start

  # Run as durable background process
  python -m src.server --durable --auto-start
        """,
    )

    parser.add_argument(
        "--auto-start",
        action="store_true",
        help="Automatically start the background listener",
    )
    parser.add_argument(
        "--durable",
        action="store_true",
        help="Run as durable background process (for systemd/pm2)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    setup_logging(debug=args.debug)

    server = SlackMCPServer(
        auto_start_listener=args.auto_start,
    )

    try:
        if args.durable:
            asyncio.run(server.run_durable())
        else:
            asyncio.run(server.run_stdio())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
