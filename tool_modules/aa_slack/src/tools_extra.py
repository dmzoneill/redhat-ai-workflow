"""Slack MCP Tools and Resources.

Provides MCP tools for Slack interaction:
- slack_list_messages: Get recent messages from a channel
- slack_send_message: Send a message (with threading support)
- slack_get_user: Resolve user ID to name/info
- slack_get_pending: Get messages waiting for agent processing
- slack_mark_processed: Mark a message as handled
- slack_listener_status: Get listener status and stats
- slack_listener_control: Start/stop the listener

Also provides MCP resources for proactive updates.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import cast

from fastmcp import FastMCP

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import load_config

# Setup project path for server imports FIRST
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization


logger = logging.getLogger(__name__)

# Add current directory to sys.path to support both relative and absolute imports
# when loaded via spec_from_file_location
_TOOLS_DIR = Path(__file__).parent.absolute()
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

TOOL_MODULES_DIR = _TOOLS_DIR.parent.parent  # tool_modules/


def _get_slack_config() -> dict:
    """Get Slack configuration from config.json."""
    config = load_config()
    return cast(dict, config.get("slack", {}))


async def _send_via_dbus(
    channel_id: str, text: str, thread_ts: str = ""
) -> dict | None:
    """
    Try to send a message via the D-Bus daemon.

    Uses send_message_rich to properly format Slack links and markdown.

    Returns the result dict if successful, None if D-Bus is not available.
    """
    try:
        # Import D-Bus client
        scripts_dir = TOOL_MODULES_DIR.parent / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))

        from services.slack.dbus import SlackAgentClient

        client = SlackAgentClient()
        if await client.connect():
            # Use send_message_rich to properly format links like <url|text>
            result = await client.send_message_rich(channel_id, text, thread_ts)
            await client.disconnect()
            logger.debug(f"D-Bus send result: {result}")
            return result
        else:
            logger.debug("D-Bus connect failed")
            return None
    except Exception as e:
        # D-Bus not available, will fall back to direct API
        logger.debug(f"D-Bus not available: {e}")
        return None


# Global manager instance (initialized on first use)
_manager = None
_manager_lock = asyncio.Lock()


async def get_manager():
    """Get or create the SlackListenerManager singleton."""
    global _manager
    async with _manager_lock:
        if _manager is None:
            # Use dynamic loading to avoid import issues when loaded via spec_from_file_location
            try:
                import importlib.util
                from pathlib import Path

                curr_dir = Path(__file__).parent.absolute()
                listener_file = curr_dir / "listener.py"

                spec = importlib.util.spec_from_file_location(
                    "slack_listener_dynamic", listener_file
                )
                mod = importlib.util.module_from_spec(spec)
                # Add to sys.modules to handle internal relative imports in listener.py if any
                sys.modules["slack_listener_dynamic"] = mod
                spec.loader.exec_module(mod)
                SlackListenerManager = mod.SlackListenerManager
            except Exception as e:
                logger.error(f"Failed to load SlackListenerManager dynamically: {e}")
                # Fallback to standard imports
                try:
                    from listener import SlackListenerManager
                except ImportError:
                    from .listener import SlackListenerManager

            _manager = SlackListenerManager()
        return _manager


async def _slack_add_reaction_impl(channel_id: str, timestamp: str, emoji: str) -> str:
    """Implementation of slack_add_reaction tool."""
    try:
        manager = await get_manager()
        await manager.initialize()

        await manager.session.add_reaction(channel_id, timestamp, emoji)

        return json.dumps(
            {
                "success": True,
                "message": f"Added :{emoji}: reaction",
            }
        )

    except Exception as e:
        return json.dumps({"error": str(e), "success": False})


async def _slack_get_channels_impl() -> str:
    """Implementation of slack_get_channels tool."""
    try:
        config = _get_slack_config()

        # Get named channels
        channels_config = config.get("channels", {})
        channels = {}
        for name, info in channels_config.items():
            if isinstance(info, dict):
                channels[name] = {
                    "id": info.get("id", ""),
                    "name": info.get("name", name),
                    "description": info.get("description", ""),
                }
            elif isinstance(info, str):
                # Legacy format: just channel ID
                channels[name] = {"id": info, "name": name, "description": ""}

        # Get alert channels
        listener_config = config.get("listener", {})
        alert_channels = listener_config.get("alert_channels", {})
        alerts = {}
        for channel_id, info in alert_channels.items():
            alerts[info.get("name", channel_id)] = {
                "id": channel_id,
                "environment": info.get("environment", ""),
                "severity": info.get("severity", ""),
                "auto_investigate": info.get("auto_investigate", False),
            }

        # Get watched channels
        watched = listener_config.get("watched_channels", [])

        return json.dumps(
            {
                "channels": channels,
                "alert_channels": alerts,
                "watched_channels": watched,
                "team_channel_id": channels.get("team", {}).get("id", ""),
            },
            indent=2,
        )

    except Exception as e:
        return json.dumps({"error": str(e)})


async def _slack_list_messages_impl(
    channel_id: str, limit: int, include_threads: bool
) -> str:
    """Implementation of slack_list_messages tool."""
    try:
        manager = await get_manager()
        await manager.initialize()

        messages = await manager.session.get_channel_history(
            channel_id=channel_id,
            limit=min(limit, 100),
        )

        result = []
        for msg in messages:
            user_id = msg.get("user", "")
            user_name = await manager.state_db.get_user_name(user_id) or user_id

            result.append(
                {
                    "ts": msg.get("ts", ""),
                    "user": user_name,
                    "text": msg.get("text", ""),
                    "thread_ts": msg.get("thread_ts"),
                    "reply_count": msg.get("reply_count", 0),
                }
            )

            # Optionally fetch thread replies
            if include_threads and msg.get("reply_count", 0) > 0:
                try:
                    thread_ts = msg.get("thread_ts") or msg.get("ts")
                    replies = await manager.session.get_thread_replies(
                        channel_id, thread_ts
                    )
                    for reply in replies[1:]:  # Skip first (parent)
                        reply_user = reply.get("user", "")
                        reply_name = (
                            await manager.state_db.get_user_name(reply_user)
                            or reply_user
                        )
                        result.append(
                            {
                                "ts": reply.get("ts", ""),
                                "user": reply_name,
                                "text": reply.get("text", ""),
                                "thread_ts": thread_ts,
                                "is_reply": True,
                            }
                        )
                except Exception as e:
                    logger.warning(f"Could not fetch thread: {e}")

        return json.dumps(
            {
                "channel_id": channel_id,
                "count": len(result),
                "messages": result,
            },
            indent=2,
        )

    except Exception as e:
        return json.dumps({"error": str(e)})


def register_tools(server: FastMCP) -> int:
    """
    Register Slack MCP tools with the server.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    registry = ToolRegistry(server)

    # ==================== MCP Resources ====================
    @server.resource("slack://pending_messages")
    async def pending_messages_resource() -> str:
        """
        Pending Slack messages waiting for agent processing.

        This resource updates automatically as new messages are detected.
        Poll this resource or use notifications to stay updated.
        """
        try:
            manager = await get_manager()
            messages = await manager.get_pending_messages(limit=20)

            if not messages:
                return json.dumps(
                    {
                        "count": 0,
                        "messages": [],
                        "hint": "No pending messages. The listener may not be running.",
                    }
                )

            return json.dumps(
                {
                    "count": len(messages),
                    "messages": [
                        {
                            "id": m.id,
                            "channel": m.channel_name,
                            "user": m.user_name,
                            "text": m.text[:500],
                            "is_mention": m.is_mention,
                            "keywords": m.matched_keywords,
                            "timestamp": m.timestamp,
                        }
                        for m in messages
                    ],
                },
                indent=2,
            )
        except Exception as e:
            return json.dumps({"error": str(e)})

    @server.resource("slack://listener_status")
    async def listener_status_resource() -> str:
        """Current status of the Slack background listener."""
        try:
            manager = await get_manager()
            status = await manager.get_status()
            return json.dumps(status, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e), "status": "error"})

    # ==================== Message Tools ====================
    # ==================== TOOLS NOT USED IN SKILLS ====================
    @auto_heal()
    @registry.tool()
    async def slack_add_reaction(
        channel_id: str,
        timestamp: str,
        emoji: str,
    ) -> str:
        """
        Add a reaction to a message.

        Args:
            channel_id: Channel containing the message
            timestamp: Message timestamp (ts)
            emoji: Emoji name without colons (e.g., "thumbsup")

        Returns:
            Confirmation
        """
        return await _slack_add_reaction_impl(channel_id, timestamp, emoji)

    @auto_heal()
    @registry.tool()
    async def slack_get_channels() -> str:
        """
        Get configured Slack channels from config.json.

        Returns channel IDs for:
        - team: Main team channel for notifications
        - standup: Channel for standup summaries
        - alert channels: Stage/prod alert channels

        Use the returned channel IDs with slack_send_message to post to these channels.

        Returns:
            JSON with configured channels and their IDs
        """
        return await _slack_get_channels_impl()

    @auto_heal()
    @registry.tool()
    async def slack_list_messages(
        channel_id: str,
        limit: int = 20,
        include_threads: bool = False,
    ) -> str:
        """
        Get recent messages from a Slack channel.

        Args:
            channel_id: Channel ID (e.g., C12345678)
            limit: Number of messages to return (max 100)
            include_threads: Include thread replies

        Returns:
            Recent messages with sender, text, and timestamp
        """
        return await _slack_list_messages_impl(channel_id, limit, include_threads)

    return registry.count
