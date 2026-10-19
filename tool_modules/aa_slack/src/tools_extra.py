# pylint: disable=duplicate-code
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

import json
import logging
import sys
from pathlib import Path
from typing import cast

from fastmcp import FastMCP
from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import load_config
from tool_modules.aa_slack.src.tools_basic import (
    _shared__send_via_dbus,
    _shared_get_manager,
)

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
    return await _shared__send_via_dbus(channel_id, text, thread_ts, logger=logger)


_send_via_dbus.__doc__ = _shared__send_via_dbus.__doc__


async def get_manager():
    "Get manager."
    return await _shared_get_manager(logger=logger)


get_manager.__doc__ = _shared_get_manager.__doc__


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

    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Tool boundary: return Slack failures to the MCP client as JSON.
        return json.dumps({"error": str(exc), "success": False})


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

    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Tool boundary: return config failures to the MCP client as JSON.
        return json.dumps({"error": str(exc)})


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
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    # Keep listing messages when one thread fetch fails.
                    logger.warning("Could not fetch thread: %s", exc)

        return json.dumps(
            {
                "channel_id": channel_id,
                "count": len(result),
                "messages": result,
            },
            indent=2,
        )

    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Tool boundary: return history failures to the MCP client as JSON.
        return json.dumps({"error": str(exc)})


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
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Resource boundary: return listener failures as JSON.
            return json.dumps({"error": str(exc)})

    @server.resource("slack://listener_status")
    async def listener_status_resource() -> str:
        """Current status of the Slack background listener."""
        try:
            manager = await get_manager()
            status = await manager.get_status()
            return json.dumps(status, indent=2)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Resource boundary: return listener status failures as JSON.
            return json.dumps({"error": str(exc), "status": "error"})

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
