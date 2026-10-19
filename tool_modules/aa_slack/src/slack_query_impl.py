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

import json
import sys

from fastmcp import FastMCP
from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry

# Setup project path for server imports FIRST
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization


from tool_modules.aa_slack.src.slack_tools_impl import (
    TOOL_MODULES_DIR,
    _get_slack_config,
    _slack_dm_gitlab_user_impl,
    _slack_get_user_impl,
    _slack_list_channels_impl,
    _slack_post_team_impl,
    _slack_search_messages_impl,
    _slack_send_message_impl,
    get_manager,
    logger,
)


async def _query_via_dbus(method_name: str, *args) -> dict | None:
    """
    Query the knowledge cache via D-Bus daemon.

    Returns the result dict if successful, None if D-Bus is not available.
    """
    try:
        scripts_dir = TOOL_MODULES_DIR.parent / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))

        from services.slack.dbus import (  # pylint: disable=import-outside-toplevel
            SlackAgentClient,
        )

        client = SlackAgentClient()
        if await client.connect():
            # Call the appropriate method
            if method_name == "find_channel":
                result = await client.find_channel(*args)
            elif method_name == "find_user":
                result = await client.find_user(*args)
            elif method_name == "get_my_channels":
                result = await client.get_my_channels()
            elif method_name == "get_user_groups":
                result = await client.get_user_groups()
            elif method_name == "resolve_target":
                result = await client.resolve_target(*args)
            elif method_name == "get_channel_cache_stats":
                result = await client.get_channel_cache_stats()
            elif method_name == "refresh_channel_cache":
                result = await client.refresh_channel_cache()
            else:
                result = None
            await client.disconnect()
            return result
        return None
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.debug("D-Bus query failed: %s", e)
        return None


async def _query_knowledge_cache(method_name: str, *args) -> dict:
    """
    Query the knowledge cache via D-Bus, falling back to config.json.

    The Slack daemon exposes all cache queries via D-Bus. If the daemon
    isn't running, we fall back to config.json for basic lookups.

    Returns the result dict with success status.
    """
    # Try D-Bus (primary method - Slack daemon must be running)
    result = await _query_via_dbus(method_name, *args)
    if result and result.get("success"):
        result["source"] = "dbus"
        return result

    # Fall back to config.json for some queries
    if method_name == "find_channel":
        return await _find_channel_from_config(args[0] if args else "")
    if method_name == "resolve_target":
        return await _resolve_target_from_config(args[0] if args else "")

    return {
        "success": False,
        "error": "Knowledge cache not available (Slack daemon not running)",
        "source": "none",
    }


async def _find_channel_from_config(query: str) -> dict:
    """Find channel from config.json as fallback."""
    config = _get_slack_config()
    channels_config = config.get("channels", {})

    matches = []
    query_lower = query.lower()

    for key, info in channels_config.items():
        if isinstance(info, dict):
            name = info.get("name", key)
            channel_id = info.get("id", "")
            purpose = str(info.get("purpose", info.get("description", "")) or "")
        else:
            name = key
            channel_id = info
            purpose = ""

        if (
            query_lower in name.lower()
            or query_lower in purpose.lower()
            or query_lower in key.lower()
        ):
            matches.append(
                {
                    "channel_id": channel_id,
                    "name": name,
                    "purpose": purpose,
                    "source": "config",
                }
            )

    return {
        "success": True,
        "query": query,
        "count": len(matches),
        "channels": matches,
        "source": "config",
        "note": "Results from config.json only. Start Slack daemon for full cache.",
    }


async def _resolve_target_from_config(  # pylint: disable=too-many-branches
    target: str,
) -> dict:  # pylint: disable=too-many-branches
    """Resolve target from config.json as fallback."""
    config = _get_slack_config()

    # Check if it's a raw ID
    if target.startswith(("C", "D", "U", "S")) and len(target) > 8:
        # Determine type from ID prefix
        if target.startswith("C"):
            target_type = "channel"
        elif target.startswith("D"):
            target_type = "dm"
        elif target.startswith("U"):
            target_type = "user"
        else:
            target_type = "group"

        return {
            "success": True,
            "type": target_type,
            "id": target,
            "name": target,
            "found": True,
            "source": "raw_id",
        }

    # Check channels
    if target.startswith("#"):
        target_name = target[1:]
    else:
        target_name = target

    channels_config = config.get("channels", {})
    for key, info in channels_config.items():
        if isinstance(info, dict):
            name = info.get("name", key)
            channel_id = info.get("id", "")
        else:
            name = key
            channel_id = info

        if name.lower() == target_name.lower() or key.lower() == target_name.lower():
            return {
                "success": True,
                "type": "channel",
                "id": channel_id,
                "name": name,
                "found": True,
                "source": "config",
            }

    # Check user mapping
    if target.startswith("@"):
        target_name = target[1:]

    user_mapping = config.get("user_mapping", {}).get("users", {})
    for username, info in user_mapping.items():
        if isinstance(info, dict):
            slack_id = info.get("slack_id", "")
            name = info.get("name", username)
        else:
            slack_id = info
            name = username

        if username.lower() == target_name.lower():
            return {
                "success": True,
                "type": "user",
                "id": slack_id,
                "name": name,
                "found": True,
                "source": "config",
            }

    return {
        "success": True,
        "type": "unknown",
        "id": None,
        "name": target,
        "found": False,
        "source": "config",
    }


# ==================== KNOWLEDGE CACHE TOOL IMPLEMENTATIONS ====================


async def _slack_find_channel_impl(query: str, member_only: bool) -> str:
    """Implementation of slack_find_channel tool."""
    try:
        result = await _query_knowledge_cache("find_channel", query)

        if not result.get("success"):
            return json.dumps(result)

        channels = result.get("channels", [])

        # Filter by member_only if requested and we have that info
        if member_only:
            channels = [c for c in channels if c.get("is_member", True)]

        return json.dumps(
            {
                "success": True,
                "query": query,
                "member_only": member_only,
                "count": len(channels),
                "channels": channels,
                "source": result.get("source", "unknown"),
            },
            indent=2,
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        return json.dumps({"success": False, "error": str(e)})


async def _slack_find_user_impl(query: str) -> str:
    """Implementation of slack_find_user tool."""
    try:
        result = await _query_knowledge_cache("find_user", query)

        if not result.get("success"):
            # Fall back to config.json user_mapping
            config = _get_slack_config()
            user_mapping = config.get("user_mapping", {}).get("users", {})

            matches = []
            query_lower = query.lower()

            for username, info in user_mapping.items():
                if isinstance(info, dict):
                    slack_id = info.get("slack_id", "")
                    name = info.get("name", username)
                else:
                    slack_id = info
                    name = username

                if query_lower in username.lower() or query_lower in name.lower():
                    matches.append(
                        {
                            "user_id": slack_id,
                            "user_name": username,
                            "display_name": name,
                            "gitlab_username": username,
                            "source": "config",
                        }
                    )

            return json.dumps(
                {
                    "success": True,
                    "query": query,
                    "count": len(matches),
                    "users": matches,
                    "source": "config",
                    "note": "Results from config.json only. Start Slack daemon for full cache.",
                },
                indent=2,
            )

        return json.dumps(
            {
                "success": True,
                "query": query,
                "count": result.get("count", len(result.get("users", []))),
                "users": result.get("users", []),
                "source": result.get("source", "unknown"),
            },
            indent=2,
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        return json.dumps({"success": False, "error": str(e)})


async def _slack_list_my_channels_impl() -> str:
    """Implementation of slack_list_my_channels tool."""
    try:
        result = await _query_knowledge_cache("get_my_channels")

        if not result.get("success"):
            # Fall back to config.json channels
            config = _get_slack_config()
            channels_config = config.get("channels", {})

            channels = []
            for key, info in channels_config.items():
                if isinstance(info, dict):
                    channels.append(
                        {
                            "channel_id": info.get("id", ""),
                            "name": info.get("name", key),
                            "purpose": info.get("purpose", info.get("description", "")),
                            "source": "config",
                        }
                    )

            return json.dumps(
                {
                    "success": True,
                    "count": len(channels),
                    "channels": channels,
                    "source": "config",
                    "note": "Results from config.json only. Start Slack daemon for full cache.",
                },
                indent=2,
            )

        return json.dumps(
            {
                "success": True,
                "count": result.get("count", len(result.get("channels", []))),
                "channels": result.get("channels", []),
                "source": result.get("source", "unknown"),
            },
            indent=2,
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        return json.dumps({"success": False, "error": str(e)})


async def _slack_resolve_target_impl(target: str) -> str:
    """Implementation of slack_resolve_target tool."""
    try:
        result = await _query_knowledge_cache("resolve_target", target)
        return json.dumps(result, indent=2)
    except Exception as e:  # pylint: disable=broad-exception-caught
        return json.dumps({"success": False, "error": str(e)})


async def _slack_list_groups_impl() -> str:
    """Implementation of slack_list_groups tool."""
    try:
        result = await _query_knowledge_cache("get_user_groups")

        if not result.get("success"):
            # Fall back to config.json groups
            config = _get_slack_config()
            groups_config = config.get("groups", {})

            groups = []
            for key, info in groups_config.items():
                if isinstance(info, dict):
                    groups.append(
                        {
                            "group_id": info.get("id", ""),
                            "handle": info.get("handle", key),
                            "name": info.get("name", key),
                            "members": info.get("members", []),
                            "source": "config",
                        }
                    )

            return json.dumps(
                {
                    "success": True,
                    "count": len(groups),
                    "groups": groups,
                    "source": "config",
                    "note": "Results from config.json only. Start Slack daemon for full cache.",
                },
                indent=2,
            )

        return json.dumps(
            {
                "success": True,
                "count": result.get("count", len(result.get("groups", []))),
                "groups": result.get("groups", []),
                "source": result.get("source", "unknown"),
            },
            indent=2,
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        return json.dumps({"success": False, "error": str(e)})


async def _slack_cache_stats_impl() -> str:
    """Implementation of slack_cache_stats tool."""
    try:
        result = await _query_knowledge_cache("get_channel_cache_stats")
        return json.dumps(result, indent=2)
    except Exception as e:  # pylint: disable=broad-exception-caught
        return json.dumps({"success": False, "error": str(e)})


def register_tools(server: FastMCP) -> int:  # pylint: disable=too-many-locals
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
        except Exception as e:  # pylint: disable=broad-exception-caught
            return json.dumps({"error": str(e)})

    @server.resource("slack://listener_status")
    async def listener_status_resource() -> str:
        """Current status of the Slack background listener."""
        try:
            manager = await get_manager()
            status = await manager.get_status()
            return json.dumps(status, indent=2)
        except Exception as e:  # pylint: disable=broad-exception-caught
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
        return await _slack_dm_gitlab_user_impl(
            gitlab_username, text, notification_type
        )

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

    # ==================== Knowledge Cache Tools ====================

    @auto_heal()
    @registry.tool()
    async def slack_find_channel(
        query: str,
        member_only: bool = False,
    ) -> str:
        """
        Find Slack channels by name, purpose, or topic.

        Searches the knowledge cache (populated by the Slack daemon) for channels
        matching the query. Falls back to config.json if the daemon is not running.

        This is the recommended way to discover channels - it works around
        enterprise_is_restricted errors by using cached data.

        Args:
            query: Search string to match against channel name/purpose/topic
            member_only: Only return channels the bot is a member of

        Returns:
            JSON with matching channels including id, name, purpose, etc.

        Example:
            slack_find_channel("analytics")  # Find channels with "analytics"
            slack_find_channel("alerts", member_only=True)  # Only joined channels
        """
        return await _slack_find_channel_impl(query, member_only)

    @auto_heal()
    @registry.tool()
    async def slack_find_user(query: str) -> str:
        """
        Find Slack users by name, email, or GitLab username.

        Searches the knowledge cache for users matching the query.
        Falls back to config.json user_mapping if the daemon is not running.

        Args:
            query: Search string to match against user fields

        Returns:
            JSON with matching users including id, name, email, gitlab_username.

        Example:
            slack_find_user("daoneill")  # Find user by username
            slack_find_user("analytics")  # Find users with "analytics" in name
        """
        return await _slack_find_user_impl(query)

    @auto_heal()
    @registry.tool()
    async def slack_list_my_channels() -> str:
        """
        List Slack channels the bot is a member of.

        Returns channels from the knowledge cache that the bot has joined.
        Falls back to config.json channels if the daemon is not running.

        Use this to discover which channels you can post to without errors.

        Returns:
            JSON with channels including id, name, purpose, member count.
        """
        return await _slack_list_my_channels_impl()

    @auto_heal()
    @registry.tool()
    async def slack_resolve_target(target: str) -> str:
        """
        Resolve a Slack target (#channel, @user, @group) to its ID.

        Takes a human-readable target and returns the Slack ID needed for API calls.
        Supports:
        - #channel-name -> channel ID (C...)
        - @username -> user ID (U...)
        - @group-handle -> group ID (S...)
        - Raw IDs are returned as-is

        Args:
            target: Target to resolve (e.g., "#aap-analytics", "@daoneill", "@team")

        Returns:
            JSON with type, id, name, and found status.

        Example:
            slack_resolve_target("#aap-analytics")  # Returns channel ID
            slack_resolve_target("@daoneill")  # Returns user ID
        """
        return await _slack_resolve_target_impl(target)

    @auto_heal()
    @registry.tool()
    async def slack_list_groups() -> str:
        """
        List Slack user groups (for @team mentions).

        Returns all cached user groups that can be used for @mentions.
        Falls back to config.json groups if the daemon is not running.

        Returns:
            JSON with groups including id, handle, name, and members.
        """
        return await _slack_list_groups_impl()

    @auto_heal()
    @registry.tool()
    async def slack_cache_stats() -> str:
        """
        Get statistics about the Slack knowledge cache.

        Shows cache health including:
        - Total channels cached
        - Channels bot is member of
        - Cache age
        - Last refresh time

        Returns:
            JSON with cache statistics.
        """
        return await _slack_cache_stats_impl()

    return registry.count
