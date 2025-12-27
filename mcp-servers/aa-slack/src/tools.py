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
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Add aa-common to path for shared utilities
# Handle both MCP server context (aa-common in path) and standalone script context
SERVERS_DIR = Path(__file__).parent.parent.parent
_common_path = str(SERVERS_DIR / "aa-common")
if _common_path not in sys.path:
    sys.path.insert(0, _common_path)

try:
    # When running as MCP server, src.utils resolves to aa-common/src/utils
    from src.utils import load_config
except (ImportError, ModuleNotFoundError):
    # When running from slack_daemon.py where aa-slack/src shadows aa-common/src,
    # import directly from aa-common/src
    _common_src = str(SERVERS_DIR / "aa-common" / "src")
    if _common_src not in sys.path:
        sys.path.insert(0, _common_src)
    from utils import load_config

logger = logging.getLogger(__name__)


def _get_slack_config() -> dict:
    """Get Slack configuration from config.json."""
    config = load_config()
    return config.get("slack", {})


# Global manager instance (initialized on first use)
_manager = None
_manager_lock = asyncio.Lock()


async def get_manager():
    """Get or create the SlackListenerManager singleton."""
    global _manager
    async with _manager_lock:
        if _manager is None:
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

    @server.tool()
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
                            reply_name = (
                                await manager.state_db.get_user_name(reply_user) or reply_user
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

    @server.tool()
    async def slack_send_message(
        target: str,
        text: str,
        thread_ts: str = "",
        typing_delay: bool = True,
    ) -> str:
        """
        Send a message to a Slack channel or user.

        Supports:
        - Channels: C12345678 (public/private channels)
        - DMs: D12345678 (direct message channels)
        - Users: U12345678 (will open DM automatically)
        - @username: Will resolve to user ID and open DM

        Args:
            target: Channel ID (C...), DM ID (D...), User ID (U...), or @username
            text: Message text (supports Slack markdown)
            thread_ts: Thread timestamp to reply in (optional)
            typing_delay: Add natural typing delay (0.5-2.5s)

        Returns:
            Confirmation with message timestamp
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
                # Channel ID (C...) or DM ID (D...) - send directly
                result = await manager.session.send_message(
                    channel_id=target,
                    text=text,
                    thread_ts=thread_ts if thread_ts else None,
                    typing_delay=typing_delay,
                )

                msg_type = "dm" if target.startswith("D") else "channel"
                return json.dumps(
                    {
                        "success": True,
                        "type": msg_type,
                        "channel": result.get("channel", target),
                        "timestamp": result.get("ts", ""),
                        "message": "Message sent successfully",
                    }
                )

        except Exception as e:
            return json.dumps({"error": str(e), "success": False})

    @server.tool()
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

    @server.tool()
    async def slack_post_team(
        text: str,
        thread_ts: str = "",
    ) -> str:
        """
        Post a message to the team channel.

        Convenience wrapper that automatically uses the team channel from config.
        Use this for team notifications, updates, and announcements.

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

            # Use the send_message function
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
                    "channel_name": (
                        team_info.get("name", "team") if isinstance(team_info, dict) else "team"
                    ),
                    "timestamp": result.get("ts", ""),
                    "message": "Message posted to team channel",
                }
            )

        except Exception as e:
            return json.dumps({"error": str(e), "success": False})

    @server.tool()
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

    @server.tool()
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

    @server.tool()
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

    @server.tool()
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

    # ==================== Pending Message Tools ====================

    @server.tool()
    async def slack_get_pending(
        limit: int = 20,
        channel_id: str = "",
    ) -> str:
        """
        Get pending messages waiting for agent processing.

        These are messages that matched your watched keywords/mentions
        and haven't been processed yet.

        Args:
            limit: Maximum messages to return
            channel_id: Filter by channel (optional)

        Returns:
            Pending messages with full context
        """
        try:
            manager = await get_manager()
            await manager.initialize()

            messages = await manager.get_pending_messages(
                limit=limit,
                channel_id=channel_id if channel_id else None,
            )

            if not messages:
                return json.dumps(
                    {
                        "count": 0,
                        "messages": [],
                        "hint": "No pending messages",
                    }
                )

            return json.dumps(
                {
                    "count": len(messages),
                    "messages": [
                        {
                            "id": m.id,
                            "channel_id": m.channel_id,
                            "channel_name": m.channel_name,
                            "user_id": m.user_id,
                            "user_name": m.user_name,
                            "text": m.text,
                            "timestamp": m.timestamp,
                            "thread_ts": m.thread_ts,
                            "is_mention": m.is_mention,
                            "is_dm": m.is_dm,
                            "matched_keywords": m.matched_keywords,
                            "age_seconds": time.time() - m.created_at,
                        }
                        for m in messages
                    ],
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps({"error": str(e)})

    @server.tool()
    async def slack_mark_processed(message_id: str) -> str:
        """
        Mark a pending message as processed.

        Call this after you've responded to or handled a message.

        Args:
            message_id: Message ID from slack_get_pending

        Returns:
            Confirmation
        """
        try:
            manager = await get_manager()
            await manager.mark_processed(message_id)

            return json.dumps(
                {
                    "success": True,
                    "message_id": message_id,
                    "message": "Message marked as processed",
                }
            )

        except Exception as e:
            return json.dumps({"error": str(e), "success": False})

    @server.tool()
    async def slack_respond_and_mark(
        message_id: str,
        response_text: str,
        as_thread: bool = True,
    ) -> str:
        """
        Respond to a pending message and mark it as processed.

        Convenience tool that sends a response and marks the message handled.

        Args:
            message_id: Message ID from slack_get_pending
            response_text: Your response text
            as_thread: Reply in thread (recommended)

        Returns:
            Confirmation with response details
        """
        try:
            manager = await get_manager()
            await manager.initialize()

            # Get the pending message
            messages = await manager.get_pending_messages(limit=100)
            pending = None
            for m in messages:
                if m.id == message_id:
                    pending = m
                    break

            if not pending:
                return json.dumps(
                    {
                        "error": f"Message {message_id} not found in pending queue",
                        "success": False,
                    }
                )

            # Send response
            thread_ts = pending.thread_ts or pending.timestamp if as_thread else None

            result = await manager.session.send_message(
                channel_id=pending.channel_id,
                text=response_text,
                thread_ts=thread_ts,
                typing_delay=True,
            )

            # Mark as processed
            await manager.mark_processed(message_id)

            return json.dumps(
                {
                    "success": True,
                    "message_id": message_id,
                    "response_ts": result.get("ts", ""),
                    "channel": pending.channel_name,
                    "in_thread": bool(thread_ts),
                    "message": f"Responded to {pending.user_name} and marked processed",
                }
            )

        except Exception as e:
            return json.dumps({"error": str(e), "success": False})

    # ==================== Listener Control Tools ====================

    @server.tool()
    async def slack_listener_status() -> str:
        """
        Get the status of the Slack background listener.

        Returns:
            Listener status including running state, stats, and config
        """
        try:
            manager = await get_manager()
            status = await manager.get_status()
            return json.dumps(status, indent=2)

        except Exception as e:
            return json.dumps({"error": str(e), "status": "error"})

    @server.tool()
    async def slack_listener_start() -> str:
        """
        Start the Slack background listener.

        The listener polls watched channels and queues relevant messages.

        Returns:
            Confirmation with listener config
        """
        try:
            manager = await get_manager()
            await manager.start()

            status = await manager.get_status()
            return json.dumps(
                {
                    "success": True,
                    "message": "Listener started",
                    **status,
                }
            )

        except Exception as e:
            return json.dumps({"error": str(e), "success": False})

    @server.tool()
    async def slack_listener_stop() -> str:
        """
        Stop the Slack background listener.

        Returns:
            Confirmation
        """
        try:
            manager = await get_manager()
            await manager.stop()

            return json.dumps(
                {
                    "success": True,
                    "message": "Listener stopped",
                }
            )

        except Exception as e:
            return json.dumps({"error": str(e), "success": False})

    # ==================== Utility Tools ====================

    @server.tool()
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

    @server.tool()
    async def slack_validate_session() -> str:
        """
        Validate the Slack session credentials.

        Use this to check if your XOXC_TOKEN and D_COOKIE are valid.

        Returns:
            Session info if valid, error if expired
        """
        try:
            manager = await get_manager()
            await manager.initialize()

            auth_info = await manager.session.validate_session()

            return json.dumps(
                {
                    "valid": True,
                    "user_id": auth_info.get("user_id", ""),
                    "user": auth_info.get("user", ""),
                    "team_id": auth_info.get("team_id", ""),
                    "team": auth_info.get("team", ""),
                    "message": "Session is valid",
                }
            )

        except Exception as e:
            return json.dumps(
                {
                    "valid": False,
                    "error": str(e),
                    "hint": "Re-obtain XOXC_TOKEN and D_COOKIE from browser dev tools",
                }
            )

    # Return count of registered tools
    return 16  # +1 for slack_dm_gitlab_user
