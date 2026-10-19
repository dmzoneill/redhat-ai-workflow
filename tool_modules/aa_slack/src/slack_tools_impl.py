# pylint: disable=duplicate-code
"""Slack MCP Tools and Resources.

Provides MCP tools for Slack interaction:
- slack_send_message: Send a message (with threading support)
- slack_post_team: Post to the team channel
- slack_dm_gitlab_user: DM a user by GitLab username
- slack_get_user: Resolve user ID to name/info
- slack_list_channels: List available channels (direct API)
- slack_search_messages: Search Slack messages

Knowledge Cache Tools (work around enterprise_is_restricted):
- slack_find_channel: Search channels by name/purpose/topic
- slack_find_user: Search users by name/email/gitlab
- slack_list_my_channels: List channels bot is member of
- slack_resolve_target: Resolve #channel/@user/@group to ID
- slack_list_groups: List user groups for @team mentions
- slack_cache_stats: Get knowledge cache statistics

Also provides MCP resources for proactive updates.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import cast

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


async def _shared__send_via_dbus(
    channel_id: str,
    text: str,
    thread_ts: str = "",
    *,
    logger,  # pylint: disable=redefined-outer-name
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

        from services.slack.dbus import (  # pylint: disable=import-outside-toplevel
            SlackAgentClient,
        )  # pylint: disable=import-outside-toplevel

        client = SlackAgentClient()
        if await client.connect():
            # Use send_message_rich to properly format links like <url|text>
            result = await client.send_message_rich(channel_id, text, thread_ts)
            await client.disconnect()
            logger.debug(f"D-Bus send result: {result}")
            return result
        logger.debug("D-Bus connect failed")
        return None
    except Exception as e:  # pylint: disable=broad-exception-caught
        # D-Bus not available, will fall back to direct API
        logger.debug(f"D-Bus not available: {e}")
        return None


async def _send_via_dbus(
    channel_id: str, text: str, thread_ts: str = ""
) -> dict | None:
    return await _shared__send_via_dbus(channel_id, text, thread_ts, logger=logger)


_send_via_dbus.__doc__ = _shared__send_via_dbus.__doc__


# Global manager instance (initialized on first use)
_manager = None  # pylint: disable=invalid-name
_manager_lock = asyncio.Lock()


async def _shared_get_manager(*, logger):  # pylint: disable=redefined-outer-name
    """Get or create the SlackListenerManager singleton."""
    global _manager  # pylint: disable=global-statement
    async with _manager_lock:
        if _manager is None:
            # Use dynamic loading to avoid import issues when loaded via spec_from_file_location
            try:
                import importlib.util  # pylint: disable=import-outside-toplevel
                from pathlib import (  # pylint: disable=import-outside-toplevel,redefined-outer-name,reimported
                    Path,
                )  # pylint: disable=import-outside-toplevel,redefined-outer-name,reimported

                curr_dir = Path(__file__).parent.absolute()
                listener_file = curr_dir / "listener.py"

                spec = importlib.util.spec_from_file_location(
                    "slack_listener_dynamic", listener_file
                )
                mod = importlib.util.module_from_spec(spec)
                # Add to sys.modules to handle internal relative imports in listener.py if any
                sys.modules["slack_listener_dynamic"] = mod
                spec.loader.exec_module(mod)
                SlackListenerManager = (  # pylint: disable=invalid-name
                    mod.SlackListenerManager
                )  # pylint: disable=invalid-name
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error(f"Failed to load SlackListenerManager dynamically: {e}")
                # Fallback to standard imports
                try:
                    from listener import (  # pylint: disable=import-outside-toplevel
                        SlackListenerManager,
                    )  # pylint: disable=import-outside-toplevel
                except ImportError:
                    from .listener import (
                        SlackListenerManager,
                    )  # pylint: disable=import-outside-toplevel

            _manager = SlackListenerManager()
        return _manager


async def get_manager():
    "Get manager."
    return await _shared_get_manager(logger=logger)


get_manager.__doc__ = _shared_get_manager.__doc__


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

    except Exception as e:  # pylint: disable=broad-exception-caught
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

    except Exception as e:  # pylint: disable=broad-exception-caught
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

    except Exception as e:  # pylint: disable=broad-exception-caught
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
                    "channel_name": (
                        team_info.get("name", "team")
                        if isinstance(team_info, dict)
                        else "team"
                    ),
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
                "channel_name": (
                    team_info.get("name", "team")
                    if isinstance(team_info, dict)
                    else "team"
                ),
                "timestamp": result.get("ts", ""),
                "message": "Message posted to team channel (direct API)",
                "method": "direct",
            }
        )

    except Exception as e:  # pylint: disable=broad-exception-caught
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

    except Exception as e:  # pylint: disable=broad-exception-caught
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

        if target.startswith("@"):
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

    except Exception as e:  # pylint: disable=broad-exception-caught
        return json.dumps({"error": str(e), "success": False})


# ==================== KNOWLEDGE CACHE HELPERS ====================
