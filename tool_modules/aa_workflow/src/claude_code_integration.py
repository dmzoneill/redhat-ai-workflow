"""
Claude Code Integration - Native UI prompts for skill error recovery.

This module detects if running in Claude Code and provides access to
the AskUserQuestion tool for native UI prompts.
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def is_claude_code_context() -> bool:
    """
    Detect if we're running in Claude Code context.

    Checks for:
    - CLAUDE_CODE environment variable
    - MCP server context markers
    - Tool availability

    Returns:
        True if running in Claude Code, False otherwise
    """
    import os

    # Check environment
    if os.getenv("CLAUDE_CODE"):
        return True

    # Check if we have access to Claude Code specific markers
    try:
        # Claude Code sets specific env vars
        if os.getenv("MCP_SERVER_NAME") == "claude-code":
            return True
        if os.getenv("CLAUDE_CLI_VERSION"):
            return True
    except Exception:
        pass

    return False


def create_ask_question_wrapper(server=None):
    """
    Create a wrapper function for AskUserQuestion tool.

    This function returns an async callable that can invoke
    Claude Code's AskUserQuestion tool if available.

    Args:
        server: The FastMCP server instance (may have access to tools)

    Returns:
        Async function or None if not available
    """
    # Strategy 1: Try to get tool from server registry
    if server:
        try:
            # Check if server has a way to call tools
            if hasattr(server, "call_tool"):

                async def ask_via_server(questions_data: dict) -> dict | None:
                    """Call AskUserQuestion via server."""
                    try:
                        result = await server.call_tool("AskUserQuestion", questions_data)
                        return result
                    except Exception as e:
                        logger.debug(f"Server tool call failed: {e}")
                        return None

                return ask_via_server

            # Check if server has tool registry we can query
            if hasattr(server, "list_tools"):
                tools = server.list_tools()
                tool_names = [t.name if hasattr(t, "name") else str(t) for t in tools]
                if "AskUserQuestion" in tool_names:
                    logger.info("AskUserQuestion found in server tools")
                    # Tool exists but we need server's call mechanism
        except Exception as e:
            logger.debug(f"Server tool check failed: {e}")

    # Strategy 2: Try to import from Claude Code's internal modules
    try:
        # This would work if Claude Code exposes its tools
        from claude_code import ask_user_question  # type: ignore

        async def ask_via_import(questions_data: dict) -> dict:
            """Call AskUserQuestion via direct import."""
            return await ask_user_question(questions_data)

        logger.info("Using imported AskUserQuestion from claude_code")
        return ask_via_import

    except ImportError:
        logger.debug("Could not import claude_code.ask_user_question")

    # Strategy 3: Try to use MCP client to call the tool
    try:
        # Check if we can create an MCP client to call tools
        mcp_socket = os.getenv("MCP_SOCKET")
        if mcp_socket:

            async def ask_via_mcp(questions_data: dict) -> dict | None:
                """Call AskUserQuestion via MCP client."""
                try:
                    # This would use MCP protocol to call the tool
                    # Implementation depends on MCP client library
                    from mcp import Client  # type: ignore

                    async with Client(mcp_socket) as client:
                        result = await client.call_tool("AskUserQuestion", questions_data)
                        return result
                except Exception as e:
                    logger.debug(f"MCP client call failed: {e}")
                    return None

            logger.info("Using MCP client for AskUserQuestion")
            return ask_via_mcp

    except Exception as e:
        logger.debug(f"MCP client strategy failed: {e}")

    # Strategy 4: Check if running as subprocess of Claude Code
    try:
        # Check parent process
        parent_pid = os.getppid()
        try:
            with open(f"/proc/{parent_pid}/cmdline", "r") as f:
                parent_cmd = f.read()
                if "claude" in parent_cmd.lower() or "code" in parent_cmd:
                    logger.info("Running as subprocess of Claude Code")
                    # We know we're in Claude Code but still need tool access
        except Exception:
            pass
    except Exception:
        pass

    # If all strategies fail, return None (will use CLI fallback)
    logger.info("AskUserQuestion not available - will use CLI fallback")
    return None


def get_claude_code_capabilities() -> dict[str, Any]:
    """
    Get information about Claude Code capabilities.

    Returns:
        Dict with:
            - is_claude_code: bool
            - has_ask_question: bool
            - has_native_ui: bool
            - version: str or None
    """
    import os

    is_cc = is_claude_code_context()

    capabilities = {
        "is_claude_code": is_cc,
        "has_ask_question": False,
        "has_native_ui": is_cc,
        "version": os.getenv("CLAUDE_CLI_VERSION"),
        "detection_method": None,
    }

    if is_cc:
        # Determine how we detected it
        if os.getenv("CLAUDE_CODE"):
            capabilities["detection_method"] = "CLAUDE_CODE env var"
        elif os.getenv("MCP_SERVER_NAME"):
            capabilities["detection_method"] = "MCP_SERVER_NAME"
        elif os.getenv("CLAUDE_CLI_VERSION"):
            capabilities["detection_method"] = "CLAUDE_CLI_VERSION"

    return capabilities


async def test_ask_question(ask_fn) -> bool:
    """
    Test if the ask question function works.

    Args:
        ask_fn: The async function to test

    Returns:
        True if working, False otherwise
    """
    if not ask_fn:
        return False

    try:
        result = await ask_fn(
            {
                "questions": [
                    {
                        "question": "Testing AskUserQuestion integration",
                        "header": "Test",
                        "options": [
                            {"label": "Yes", "description": "It works!"},
                            {"label": "No", "description": "Fallback to CLI"},
                        ],
                        "multiSelect": False,
                    }
                ]
            }
        )
        return result is not None and "answers" in result
    except Exception as e:
        logger.debug(f"AskUserQuestion test failed: {e}")
        return False
