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

from mcp.server.fastmcp import FastMCP

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


async def _send_via_dbus(channel_id: str, text: str, thread_ts: str = "") -> dict | None:
    """
    Try to send a message via the D-Bus daemon.

    Returns the result dict if successful, None if D-Bus is not available.
    """
    try:
        # Import D-Bus client
        scripts_dir = TOOL_MODULES_DIR.parent / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))

        from slack_dbus import SlackAgentClient

        client = SlackAgentClient()
        if await client.connect():
            result = await client.send_message(channel_id, text, thread_ts)
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

                spec = importlib.util.spec_from_file_location("slack_listener_dynamic", listener_file)
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


# ==================== TOOL IMPLEMENTATIONS ====================


async def _slack_dm_gitlab_user_impl(
    gitlab_username: str,
    text: str,
    notification_type: str,
) -> str:
    """Implementation of slack_dm_gitlab_user tool."""
    try:
        config = _get_slack_config()

        # Get user mapping
        user_mapping = config.get("user_mapping", {}).get("users", {})

        if gitlab_username not in user_mapping:
            return json.dumps(
                {
                    "success": False,
                    "error": f"GitLab user '{gitlab_username}' not found in user_mapping",
                    "hint": "Add this user to config.json: slack.user_mapping.users",
                    "known_users": list(user_mapping.keys()),
                }
            )

        user_info = user_mapping[gitlab_username]
        slack_id = user_info.get("slack_id")

        if not slack_id:
            return json.dumps(
                {
                    "success": False,
                    "error": f"No slack_id configured for '{gitlab_username}'",
                }
            )

        # Add emoji prefix based on notification type
        prefix = ""
        if notification_type == "feedback":
            prefix = "💬 "
        elif notification_type == "approval":
            prefix = "✅ "
        elif notification_type == "info":
            prefix = "ℹ️ "

        formatted_text = prefix + text

        manager = await get_manager()
        await manager.initialize()

        result = await manager.session.send_dm(
            user_id=slack_id,
            text=formatted_text,
            typing_delay=True,
        )

        return json.dumps(
            {
                "success": True,
                "gitlab_user": gitlab_username,
                "slack_user": user_info.get("name", gitlab_username),
                "slack_id": slack_id,
                "channel": result.get("channel", ""),
                "timestamp": result.get("ts", ""),
                "message": f"DM sent to {user_info.get('name', gitlab_username)}",
            }
        )

    except Exception as e:
        return json.dumps({"error": str(e), "success": False})


async def _slack_get_user_impl(user_id: str) -> str:
    """Implementation of slack_get_user tool."""
    try:
        manager = await get_manager()
        await manager.initialize()

        user_info = await manager.session.get_user_info(user_id)

        profile = user_info.get("profile", {})

        return json.dumps(
            {
                "id": user_id,
                "name": user_info.get("name", ""),
                "real_name": user_info.get("real_name", ""),
                "display_name": profile.get("display_name", ""),
                "title": profile.get("title", ""),
                "email": profile.get("email", ""),
                "is_bot": user_info.get("is_bot", False),
                "timezone": user_info.get("tz", ""),
            },
            indent=2,
        )

    except Exception as e:
        return json.dumps({"error": str(e)})


async def _slack_list_channels_impl(types: str, limit: int) -> str:
    """Implementation of slack_list_channels tool."""
    try:
        manager = await get_manager()
        await manager.initialize()

        channels = await manager.session.get_conversations_list(
            types=types,
            limit=limit,
        )

        return json.dumps(
            {
                "count": len(channels),
                "channels": [
                    {
                        "id": c.get("id", ""),
                        "name": c.get("name", ""),
                        "is_private": c.get("is_private", False),
                        "is_member": c.get("is_member", False),
                        "num_members": c.get("num_members", 0),
                        "topic": c.get("topic", {}).get("value", "")[:100],
                    }
                    for c in channels
                ],
            },
            indent=2,
        )

    except Exception as e:
        return json.dumps({"error": str(e)})


async def _slack_post_team_impl(text: str, thread_ts: str) -> str:
    """Implementation of slack_post_team tool."""
    try:
        config = _get_slack_config()
        channels_config = config.get("channels", {})

        # Get team channel ID
        team_info = channels_config.get("team", {})
        if isinstance(team_info, dict):
            team_channel = team_info.get("id", "")
        else:
            team_channel = team_info  # Legacy string format

        if not team_channel:
            return json.dumps(
                {
                    "error": "Team channel not configured in config.json under slack.channels.team",
                    "success": False,
                }
            )

        # Try D-Bus daemon first (if running with --dbus)
        dbus_result = await _send_via_dbus(team_channel, text, thread_ts or "")
        if dbus_result and dbus_result.get("success"):
            return json.dumps(
                {
                    "success": True,
                    "channel": team_channel,
                    "channel_name": (team_info.get("name", "team") if isinstance(team_info, dict) else "team"),
                    "timestamp": dbus_result.get("ts", ""),
                    "message": "Message posted to team channel (via D-Bus)",
                    "method": "dbus",
                }
            )

        # Fall back to direct API
        manager = await get_manager()
        await manager.initialize()

        result = await manager.session.send_message(
            channel_id=team_channel,
            text=text,
            thread_ts=thread_ts if thread_ts else None,
            typing_delay=True,
        )

        return json.dumps(
            {
                "success": True,
                "channel": team_channel,
                "channel_name": (team_info.get("name", "team") if isinstance(team_info, dict) else "team"),
                "timestamp": result.get("ts", ""),
                "message": "Message posted to team channel (direct API)",
                "method": "direct",
            }
        )

    except Exception as e:
        return json.dumps({"error": str(e), "success": False})


async def _slack_search_messages_impl(query: str, count: int) -> str:
    """Implementation of slack_search_messages tool."""
    try:
        manager = await get_manager()
        await manager.initialize()

        results = await manager.session.search_messages(
            query=query,
            count=min(count, 100),
        )

        return json.dumps(
            {
                "query": query,
                "count": len(results),
                "matches": [
                    {
                        "channel": m.get("channel", {}).get("name", ""),
                        "user": m.get("username", ""),
                        "text": m.get("text", "")[:300],
                        "timestamp": m.get("ts", ""),
                        "permalink": m.get("permalink", ""),
                    }
                    for m in results
                ],
            },
            indent=2,
        )

    except Exception as e:
        return json.dumps({"error": str(e)})


async def _slack_send_message_impl(
    target: str,
    text: str,
    thread_ts: str,
    typing_delay: bool,
) -> str:
    """Implementation of slack_send_message tool."""
    try:
        manager = await get_manager()
        await manager.initialize()

        # Determine target type and get channel ID
        target = target.strip()

        if target.startswith("U"):
            # User ID - open DM first
            result = await manager.session.send_dm(
                user_id=target,
                text=text,
                typing_delay=typing_delay,
            )
            return json.dumps(
                {
                    "success": True,
                    "type": "dm",
                    "user": target,
                    "channel": result.get("channel", ""),
                    "timestamp": result.get("ts", ""),
                    "message": f"DM sent to {target}",
                }
            )

        elif target.startswith("@"):
            # @username - need to resolve to user ID first
            username = target[1:]  # Remove @
            users = await manager.session.get_users_list()
            user = next((u for u in users if u.get("name") == username), None)
            if not user:
                return json.dumps(
                    {
                        "error": f"User @{username} not found",
                        "success": False,
                    }
                )

            result = await manager.session.send_dm(
                user_id=user["id"],
                text=text,
                typing_delay=typing_delay,
            )
            return json.dumps(
                {
                    "success": True,
                    "type": "dm",
                    "user": f"@{username}",
                    "user_id": user["id"],
                    "channel": result.get("channel", ""),
                    "timestamp": result.get("ts", ""),
                    "message": f"DM sent to @{username}",
                }
            )

        else:
            # Channel ID (C...) or DM ID (D...) - try D-Bus first, then direct
            msg_type = "dm" if target.startswith("D") else "channel"

            # Try D-Bus daemon first (if running with --dbus)
            dbus_result = await _send_via_dbus(target, text, thread_ts or "")
            if dbus_result and dbus_result.get("success"):
                return json.dumps(
                    {
                        "success": True,
                        "type": msg_type,
                        "channel": dbus_result.get("channel", target),
                        "timestamp": dbus_result.get("ts", ""),
                        "message": "Message sent successfully (via D-Bus)",
                        "method": "dbus",
                    }
                )

            # Fall back to direct API
            result = await manager.session.send_message(
                channel_id=target,
                text=text,
                thread_ts=thread_ts if thread_ts else None,
                typing_delay=typing_delay,
            )

            return json.dumps(
                {
                    "success": True,
                    "type": msg_type,
                    "channel": result.get("channel", target),
                    "timestamp": result.get("ts", ""),
                    "message": "Message sent successfully (direct API)",
                    "method": "direct",
                }
            )

    except Exception as e:
        return json.dumps({"error": str(e), "success": False})


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
    # ==================== TOOLS USED IN SKILLS ====================
    @auto_heal()
    @registry.tool()
    async def slack_dm_gitlab_user(
        gitlab_username: str,
        text: str,
        notification_type: str = "info",
    ) -> str:
        """
        Send a Slack DM to a user based on their GitLab username.

        Uses the user_mapping in config.json to resolve GitLab usernames
        to Slack user IDs. Perfect for notifying PR authors about feedback.

        Args:
            gitlab_username: GitLab username (e.g., 'bthomass', 'akarve')
            text: Message text (supports Slack markdown)
            notification_type: Type of notification for styling (info, feedback, approval)

        Returns:
            Confirmation with message timestamp or error if user not found.
        """
        return await _slack_dm_gitlab_user_impl(gitlab_username, text, notification_type)

    @auto_heal()
    @registry.tool()
    async def slack_get_user(user_id: str) -> str:
        """
        Get information about a Slack user.

        Args:
            user_id: Slack user ID (e.g., U12345678)

        Returns:
            User profile with name, display name, title, etc.
        """
        return await _slack_get_user_impl(user_id)

    @auto_heal()
    @registry.tool()
    async def slack_list_channels(
        types: str = "public_channel,private_channel",
        limit: int = 100,
    ) -> str:
        """
        List available Slack channels.

        Args:
            types: Channel types (public_channel, private_channel, mpim, im)
            limit: Maximum channels to return

        Returns:
            List of channels with IDs and names
        """
        return await _slack_list_channels_impl(types, limit)

    @auto_heal()
    @registry.tool()
    async def slack_post_team(
        text: str,
        thread_ts: str = "",
    ) -> str:
        """
        Post a message to the team channel.

        Convenience wrapper that automatically uses the team channel from config.
        Use this for team notifications, updates, and announcements.

        Tries D-Bus daemon first (if running), falls back to direct API.

        Args:
            text: Message text (supports Slack markdown)
            thread_ts: Optional thread timestamp to reply in a thread

        Returns:
            JSON with success status and message timestamp
        """
        return await _slack_post_team_impl(text, thread_ts)

    @auto_heal()
    @registry.tool()
    async def slack_search_messages(
        query: str,
        count: int = 10,
    ) -> str:
        """
        Search Slack messages.

        Args:
            query: Search query (supports Slack search syntax)
            count: Number of results (max 100)

        Returns:
            Matching messages with context
        """
        return await _slack_search_messages_impl(query, count)

    @auto_heal()
    @registry.tool()
    async def slack_send_message(
        target: str,
        text: str,
        thread_ts: str = "",
        typing_delay: bool = True,
    ) -> str:
        """
        Send a message to a Slack channel or user.
        """
        return await _slack_send_message_impl(target, text, thread_ts, typing_delay)

    return registry.count
