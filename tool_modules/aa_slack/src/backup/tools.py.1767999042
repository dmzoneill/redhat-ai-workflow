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

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

from typing import cast

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import load_config

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT, setup_path  # noqa: F401 - side effect: adds to sys.path

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
                        replies = await manager.session.get_thread_replies(channel_id, thread_ts)
                        for reply in replies[1:]:  # Skip first (parent)
                            reply_user = reply.get("user", "")
                            reply_name = await manager.state_db.get_user_name(reply_user) or reply_user
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

    # REMOVED: Pending Message Tools (slack_get_pending, slack_mark_processed)
    # These are internal daemon tools, not workflow tools

    # REMOVED: slack_respond_and_mark - internal daemon tool

    # REMOVED: Listener Control Tools (slack_listener_status, slack_listener_start, slack_listener_stop)
    # These are daemon control tools, not workflow tools

    # ==================== Utility Tools ====================

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

    # REMOVED: slack_validate_session - internal check, not workflow tool

    return registry.count
