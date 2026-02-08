#!/usr/bin/env python3
# flake8: noqa: F821
# Note: F821 disabled because D-Bus type annotations like "s", "i", "b"
# are valid dbus-next signatures but flake8 misinterprets them as undefined names.
"""
D-Bus Interface for Slack Daemon

Provides IPC communication with the Slack daemon via D-Bus:
- Start/stop/status control
- Send messages
- Approve/reject queued messages
- Query message history
- Real-time notifications

D-Bus Service: com.aiworkflow.BotSlack
D-Bus Path: /com/aiworkflow/BotSlack

Business logic is delegated to handler modules:
- dbus_message_handlers: messaging, approval, search, threads, history
- dbus_config_handlers: config, admin, sync, persona tests
- dbus_formatters: pure formatting helpers
- dbus_history: message records and history tracking
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from services.slack.dbus_config_handlers import (
    handle_get_app_commands,
    handle_get_channel_sections,
    handle_get_command_list,
    handle_get_config,
    handle_get_sync_config,
    handle_get_sync_status,
    handle_health_check,
    handle_reload_config,
    handle_run_persona_test,
    handle_set_debug_mode,
    handle_set_sync_config,
    handle_shutdown,
    handle_start_sync,
    handle_stop_sync,
    handle_trigger_sync,
)
from services.slack.dbus_formatters import (
    format_email_lookup_found,
    format_email_lookup_not_found,
    format_photo_path_response,
    format_user_match_with_photo,
)
from services.slack.dbus_history import MessageHistory, MessageRecord
from services.slack.dbus_message_handlers import (
    handle_approve_all,
    handle_approve_message,
    handle_get_channel_history,
    handle_get_history,
    handle_get_pending,
    handle_get_status,
    handle_get_thread_context,
    handle_get_thread_replies,
    handle_reject_message,
    handle_search_messages,
    handle_send_message,
    handle_send_message_rich,
)

# Check for dbus availability
try:
    from dbus_next.aio import MessageBus
    from dbus_next.constants import PropertyAccess
    from dbus_next.service import ServiceInterface, dbus_property, method
    from dbus_next.service import signal as dbus_signal

    DBUS_AVAILABLE = True
except ImportError:
    DBUS_AVAILABLE = False
    print("Warning: dbus-next not installed. Install with: uv add dbus-next")

PROJECT_ROOT = Path(__file__).parent.parent.parent

logger = logging.getLogger(__name__)

# D-Bus configuration
DBUS_SERVICE_NAME = "com.aiworkflow.BotSlack"
DBUS_OBJECT_PATH = "/com/aiworkflow/BotSlack"
DBUS_INTERFACE_NAME = "com.aiworkflow.BotSlack"


# MessageRecord and MessageHistory are imported from dbus_history.py
# They are re-exported here to maintain backward compatibility for
# external imports like: from services.slack.dbus import MessageRecord
__all__ = [
    "MessageRecord",
    "MessageHistory",
    "SlackPersonaDBusInterface",
    "SlackDaemonWithDBus",
    "SlackAgentClient",
    "DBUS_SERVICE_NAME",
    "DBUS_OBJECT_PATH",
    "DBUS_INTERFACE_NAME",
    "DBUS_AVAILABLE",
]


if DBUS_AVAILABLE:

    class SlackPersonaDBusInterface(ServiceInterface):
        """D-Bus interface for the Slack Persona daemon.

        Thin routing layer: each @method() delegates to handler functions in
        dbus_message_handlers or dbus_config_handlers.
        """

        def __init__(self, daemon: "SlackDaemonWithDBus"):
            super().__init__(DBUS_INTERFACE_NAME)
            self.daemon = daemon

        # ==================== Properties ====================

        @dbus_property(access=PropertyAccess.READ)
        def Running(self) -> "b":
            """Whether the daemon is running."""
            return self.daemon.is_running

        @dbus_property(access=PropertyAccess.READ)
        def PendingCount(self) -> "i":
            """Number of messages pending approval."""
            return len(self.daemon.history.pending_approvals)

        @dbus_property(access=PropertyAccess.READ)
        def Stats(self) -> "s":
            """JSON stats about the daemon."""
            return json.dumps(handle_get_status(self.daemon))

        # ==================== Message / Approval Methods ====================

        @method()
        def GetStatus(self) -> "s":
            """Get daemon status as JSON."""
            return self.Stats

        @method()
        def GetPending(self) -> "s":
            """Get pending approval messages as JSON array."""
            return json.dumps(handle_get_pending(self.daemon))

        @method()
        def ApproveMessage(self, message_id: "s") -> "s":
            """Approve a pending message and send it."""
            return json.dumps(handle_approve_message(self.daemon, message_id))

        @method()
        def RejectMessage(self, message_id: "s") -> "s":
            """Reject a pending message."""
            return json.dumps(handle_reject_message(self.daemon, message_id))

        @method()
        def ApproveAll(self) -> "s":
            """Approve all pending messages."""
            return json.dumps(handle_approve_all(self.daemon))

        @method()
        def GetHistory(
            self, limit: "i", channel_id: "s", user_id: "s", status: "s"
        ) -> "s":
            """Get message history with optional filters."""
            return json.dumps(
                handle_get_history(self.daemon, limit, channel_id, user_id, status)
            )

        @method()
        def SendMessage(self, channel_id: "s", text: "s", thread_ts: "s") -> "s":
            """Send a message to Slack (fire-and-forget)."""
            return json.dumps(
                handle_send_message(self.daemon, channel_id, text, thread_ts)
            )

        @method()
        async def SendMessageRich(
            self, channel_id: "s", text: "s", thread_ts: "s", reply_broadcast: "b"
        ) -> "s":
            """Send a message using the web client API format with rich text blocks."""
            result = await handle_send_message_rich(
                self.daemon, channel_id, text, thread_ts, reply_broadcast
            )
            return json.dumps(result)

        @method()
        async def SearchMessages(self, query: "s", max_results: "i") -> "s":
            """Search Slack messages with rate limiting."""
            result = await handle_search_messages(self.daemon, query, max_results)
            return json.dumps(result)

        @method()
        async def GetThreadReplies(
            self, channel_id: "s", thread_ts: "s", limit: "i"
        ) -> "s":
            """Get thread replies using the enhanced web client API."""
            result = await handle_get_thread_replies(
                self.daemon, channel_id, thread_ts, limit
            )
            return json.dumps(result)

        @method()
        async def GetThreadContext(self, channel_id: "s", thread_ts: "s") -> "s":
            """Get thread context in a simplified format for AI processing."""
            result = await handle_get_thread_context(self.daemon, channel_id, thread_ts)
            return json.dumps(result)

        @method()
        async def GetChannelHistory(
            self,
            channel_id: "s",
            limit: "i",
            oldest: "s",
            latest: "s",
            simplify: "b",
        ) -> "s":
            """Get message history for a channel."""
            result = await handle_get_channel_history(
                self.daemon, channel_id, limit, oldest, latest, simplify
            )
            return json.dumps(result)

        # ==================== Config / Admin Methods ====================

        @method()
        def ReloadConfig(self) -> "s":
            """Reload configuration from config.json."""
            return json.dumps(handle_reload_config(self.daemon))

        @method()
        def Shutdown(self) -> "s":
            """Gracefully shutdown the daemon."""
            return json.dumps(handle_shutdown(self.daemon))

        @method()
        def HealthCheck(self) -> "s":
            """Perform a comprehensive health check."""
            return json.dumps(handle_health_check(self.daemon))

        @method()
        def GetCommandList(self) -> "s":
            """Get list of available @me commands with descriptions."""
            return json.dumps(handle_get_command_list())

        @method()
        def GetConfig(self) -> "s":
            """Get current Slack daemon configuration."""
            return json.dumps(handle_get_config())

        @method()
        def SetDebugMode(self, enabled: "b") -> "s":
            """Enable or disable debug mode."""
            return json.dumps(handle_set_debug_mode(self.daemon, enabled))

        @method()
        def RunPersonaTest(self, query: "s", persona: "s") -> "s":
            """Run a context gathering test for the Slack persona."""
            return json.dumps(handle_run_persona_test(query))

        @method()
        async def GetAppCommands(self, summarize: "b") -> "s":
            """Get all available slash commands and app actions."""
            result = await handle_get_app_commands(self.daemon, summarize)
            return json.dumps(result)

        @method()
        async def GetChannelSections(self, summarize: "b") -> "s":
            """Get the user's sidebar channel sections/folders."""
            result = await handle_get_channel_sections(self.daemon, summarize)
            return json.dumps(result)

        # ==================== Background Sync Methods ====================

        @method()
        def GetSyncStatus(self) -> "s":
            """Get the status of the background sync process."""
            return json.dumps(handle_get_sync_status())

        @method()
        async def StartSync(self) -> "s":
            """Start the background sync process."""
            result = await handle_start_sync(self.daemon)
            return json.dumps(result)

        @method()
        async def StopSync(self) -> "s":
            """Stop the background sync process."""
            result = await handle_stop_sync()
            return json.dumps(result)

        @method()
        async def TriggerSync(self, sync_type: "s") -> "s":
            """Manually trigger a sync operation."""
            result = await handle_trigger_sync(sync_type)
            return json.dumps(result)

        @method()
        def GetSyncConfig(self) -> "s":
            """Get the background sync configuration."""
            return json.dumps(handle_get_sync_config())

        @method()
        def SetSyncConfig(self, config_json: "s") -> "s":
            """Update background sync configuration."""
            return json.dumps(handle_set_sync_config(config_json))

        @method()
        def GetPhotoPath(self, user_id: "s") -> "s":
            """Get the local cached photo path for a user."""
            try:
                return json.dumps(format_photo_path_response(user_id))
            except Exception as e:
                logger.error(f"GetPhotoPath error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        # ==================== Knowledge Cache Methods ====================

        @method()
        async def FindChannel(self, query: "s") -> "s":
            """Find channels by name, purpose, or topic."""
            if not self.daemon.state_db:
                return json.dumps(
                    {
                        "success": False,
                        "error": "State DB not available",
                        "channels": [],
                    }
                )

            try:
                channels = await self.daemon.state_db.find_channels(
                    query=query, limit=500
                )
                return json.dumps(
                    {
                        "success": True,
                        "query": query,
                        "count": len(channels),
                        "channels": [c.to_dict() for c in channels],
                    }
                )
            except Exception as e:
                logger.error(f"FindChannel error: {e}")
                return json.dumps({"success": False, "error": str(e), "channels": []})

        @method()
        async def SearchChannels(self, query: "s", count: "i") -> "s":
            """Search for channels using Slack's edge API."""
            if not self.daemon.session:
                return json.dumps(
                    {"success": False, "error": "Session not available", "channels": []}
                )

            count = min(max(count, 1), 100) if count > 0 else 30

            try:
                result = await self.daemon.session.search_channels_and_cache(
                    query, count
                )
                return json.dumps(result)
            except Exception as e:
                logger.error(f"SearchChannels error: {e}")
                return json.dumps({"success": False, "error": str(e), "channels": []})

        @method()
        async def SearchAndCacheChannels(self, query: "s", count: "i") -> "s":
            """Search for channels and add results to the local cache."""
            if not self.daemon.session or not self.daemon.state_db:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Session or State DB not available",
                        "channels": [],
                    }
                )

            count = min(max(count, 1), 100) if count > 0 else 30

            try:
                result = await self.daemon.session.search_channels_and_cache(
                    query, count
                )

                if not result.get("success"):
                    return json.dumps(result)

                from tool_modules.aa_slack.src.persistence import CachedChannel

                channels_to_cache = []
                for ch in result.get("channels", []):
                    if ch.get("channel_id"):
                        channels_to_cache.append(
                            CachedChannel(
                                channel_id=ch["channel_id"],
                                name=ch.get("name", ""),
                                display_name=ch.get("display_name", ""),
                                is_private=ch.get("is_private", False),
                                is_member=ch.get("is_member", False),
                                purpose=ch.get("purpose", ""),
                                topic=ch.get("topic", ""),
                                num_members=ch.get("num_members", 0),
                            )
                        )

                if channels_to_cache:
                    await self.daemon.state_db.cache_channels_bulk(channels_to_cache)

                result["cached"] = len(channels_to_cache)
                return json.dumps(result)

            except Exception as e:
                logger.error(f"SearchAndCacheChannels error: {e}")
                return json.dumps({"success": False, "error": str(e), "channels": []})

        @method()
        async def FindUser(self, query: "s") -> "s":
            """Find users by name, email, or GitLab username."""
            if not self.daemon.state_db:
                return json.dumps(
                    {"success": False, "error": "State DB not available", "users": []}
                )

            try:
                users = await self.daemon.state_db.find_users(query=query, limit=500)
                return json.dumps(
                    {
                        "success": True,
                        "query": query,
                        "count": len(users),
                        "users": users,
                    }
                )
            except Exception as e:
                logger.error(f"FindUser error: {e}")
                return json.dumps({"success": False, "error": str(e), "users": []})

        @method()
        async def SearchUsers(self, query: "s", count: "i") -> "s":
            """Search for users using Slack's edge API."""
            if not self.daemon.session:
                return json.dumps(
                    {"success": False, "error": "Session not available", "users": []}
                )

            count = min(max(count, 1), 100) if count > 0 else 30

            try:
                result = await self.daemon.session.search_users_and_cache(query, count)
                return json.dumps(result)
            except Exception as e:
                logger.error(f"SearchUsers error: {e}")
                return json.dumps({"success": False, "error": str(e), "users": []})

        @method()
        async def SearchAndCacheUsers(self, query: "s", count: "i") -> "s":
            """Search for users and add results to the local cache."""
            if not self.daemon.session or not self.daemon.state_db:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Session or State DB not available",
                        "users": [],
                    }
                )

            count = min(max(count, 1), 100) if count > 0 else 30

            try:
                result = await self.daemon.session.search_users_and_cache(query, count)

                if not result.get("success"):
                    return json.dumps(result)

                from tool_modules.aa_slack.src.persistence import CachedUser

                users_to_cache = []
                for u in result.get("users", []):
                    if (
                        u.get("user_id")
                        and not u.get("is_bot")
                        and not u.get("deleted")
                    ):
                        users_to_cache.append(
                            CachedUser(
                                user_id=u["user_id"],
                                user_name=u.get("user_name", ""),
                                display_name=u.get("display_name", ""),
                                real_name=u.get("real_name", ""),
                                email=u.get("email", ""),
                                gitlab_username="",
                                avatar_url=u.get("avatar_url", ""),
                            )
                        )

                if users_to_cache:
                    await self.daemon.state_db.cache_users_bulk(users_to_cache)

                result["cached"] = len(users_to_cache)
                return json.dumps(result)

            except Exception as e:
                logger.error(f"SearchAndCacheUsers error: {e}")
                return json.dumps({"success": False, "error": str(e), "users": []})

        @method()
        async def GetUserProfile(self, user_id: "s") -> "s":
            """Get detailed user profile with sections."""
            if not self.daemon.session:
                return json.dumps(
                    {"success": False, "error": "Session not available", "profile": {}}
                )

            try:
                result = await self.daemon.session.get_user_profile_details(user_id)
                return json.dumps(result)
            except Exception as e:
                logger.error(f"GetUserProfile error: {e}")
                return json.dumps({"success": False, "error": str(e), "profile": {}})

        @method()
        def GetAvatarUrl(self, user_id: "s", avatar_hash: "s", size: "i") -> "s":
            """Construct a Slack avatar URL from user ID and avatar hash."""
            if not self.daemon.session:
                return json.dumps(
                    {"success": False, "error": "Session not available", "url": ""}
                )

            try:
                size = size if size > 0 else 512
                url = self.daemon.session.get_avatar_url(user_id, avatar_hash, size)
                return json.dumps(
                    {
                        "success": True,
                        "user_id": user_id,
                        "avatar_hash": avatar_hash,
                        "size": size,
                        "url": url,
                    }
                )
            except Exception as e:
                logger.error(f"GetAvatarUrl error: {e}")
                return json.dumps({"success": False, "error": str(e), "url": ""})

        @method()
        async def GetMyChannels(self) -> "s":
            """Get channels the bot is a member of."""
            if not self.daemon.state_db:
                return json.dumps(
                    {
                        "success": False,
                        "error": "State DB not available",
                        "channels": [],
                    }
                )

            try:
                channels = await self.daemon.state_db.get_my_channels(limit=100)
                return json.dumps(
                    {
                        "success": True,
                        "count": len(channels),
                        "channels": [c.to_dict() for c in channels],
                    }
                )
            except Exception as e:
                logger.error(f"GetMyChannels error: {e}")
                return json.dumps({"success": False, "error": str(e), "channels": []})

        @method()
        async def GetUserGroups(self) -> "s":
            """Get all cached user groups (for @team mentions)."""
            if not self.daemon.state_db:
                return json.dumps(
                    {"success": False, "error": "State DB not available", "groups": []}
                )

            try:
                groups = await self.daemon.state_db.get_all_groups()
                return json.dumps(
                    {
                        "success": True,
                        "count": len(groups),
                        "groups": [g.to_dict() for g in groups],
                    }
                )
            except Exception as e:
                logger.error(f"GetUserGroups error: {e}")
                return json.dumps({"success": False, "error": str(e), "groups": []})

        # ==================== User Lookup Methods ====================

        @method()
        async def LookupUserByEmail(self, email: "s") -> "s":
            """Find a Slack user by their email address."""
            if not self.daemon.state_db:
                return json.dumps({"success": False, "error": "State DB not available"})

            try:
                user = await self.daemon.state_db.find_user_by_email(email)
                if user:
                    return json.dumps(format_email_lookup_found(user))
                else:
                    return json.dumps(format_email_lookup_not_found(email))
            except Exception as e:
                logger.error(f"LookupUserByEmail error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        async def LookupUserByName(self, name: "s", threshold: "d") -> "s":
            """Find Slack users by fuzzy name matching."""
            if not self.daemon.state_db:
                return json.dumps(
                    {"success": False, "error": "State DB not available", "users": []}
                )

            try:
                if threshold <= 0:
                    threshold = 0.7

                users = await self.daemon.state_db.find_user_by_name_fuzzy(
                    name, threshold=threshold, limit=5
                )

                results = [format_user_match_with_photo(u) for u in users]

                return json.dumps(
                    {
                        "success": True,
                        "query": name,
                        "threshold": threshold,
                        "count": len(results),
                        "users": results,
                    }
                )
            except Exception as e:
                logger.error(f"LookupUserByName error: {e}")
                return json.dumps({"success": False, "error": str(e), "users": []})

        @method()
        def GetUserPhotoPath(self, user_id: "s") -> "s":
            """Get the local file path to a cached Slack user's profile photo."""
            try:
                return json.dumps(format_photo_path_response(user_id))
            except Exception as e:
                logger.error(f"GetUserPhotoPath error: {e}")
                return json.dumps({"success": False, "error": str(e), "photo_path": ""})

        @method()
        async def ResolveTarget(self, target: "s") -> "s":
            """Resolve a Slack target (#channel, @user, @group) to its ID."""
            if not self.daemon.state_db:
                return json.dumps(
                    {
                        "success": False,
                        "error": "State DB not available",
                        "type": "unknown",
                        "id": None,
                        "name": target,
                        "found": False,
                    }
                )

            try:
                result = await self.daemon.state_db.resolve_target(target)
                result["success"] = True
                return json.dumps(result)
            except Exception as e:
                logger.error(f"ResolveTarget error: {e}")
                return json.dumps(
                    {
                        "success": False,
                        "error": str(e),
                        "type": "unknown",
                        "id": None,
                        "name": target,
                        "found": False,
                    }
                )

        @method()
        async def GetChannelCacheStats(self) -> "s":
            """Get statistics about the knowledge cache."""
            if not self.daemon.state_db:
                return json.dumps({"success": False, "error": "State DB not available"})

            try:
                stats = await self.daemon.state_db.get_channel_cache_stats()
                stats["success"] = True
                return json.dumps(stats)
            except Exception as e:
                logger.error(f"GetChannelCacheStats error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        async def RefreshChannelCache(self) -> "s":
            """Trigger a refresh of the channel cache from Slack API."""
            if not self.daemon.session or not self.daemon.state_db:
                return json.dumps(
                    {"success": False, "error": "Session or State DB not available"}
                )

            try:
                from tool_modules.aa_slack.src.persistence import CachedChannel

                channels_data = await self.daemon.session.get_conversations_list(
                    types="public_channel,private_channel",
                    limit=1000,
                )

                channels = [
                    CachedChannel(
                        channel_id=c.get("id", ""),
                        name=c.get("name", ""),
                        display_name=c.get("name_normalized", c.get("name", "")),
                        is_private=c.get("is_private", False),
                        is_member=c.get("is_member", False),
                        purpose=c.get("purpose", {}).get("value", ""),
                        topic=c.get("topic", {}).get("value", ""),
                        num_members=c.get("num_members", 0),
                    )
                    for c in channels_data
                    if c.get("id")
                ]

                await self.daemon.state_db.cache_channels_bulk(channels)

                return json.dumps(
                    {
                        "success": True,
                        "message": "Channel cache refreshed",
                        "channels_cached": len(channels),
                    }
                )
            except Exception as e:
                logger.error(f"RefreshChannelCache error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        async def ImportSidebarChannels(self, file_path: "s") -> "s":
            """Import channels from a Slack sidebar HTML file."""
            if not self.daemon.state_db:
                return json.dumps({"success": False, "error": "State DB not available"})

            try:
                expanded_path = os.path.expanduser(file_path)
                result = await self.daemon.state_db.import_channels_from_sidebar(
                    expanded_path
                )
                return json.dumps(result)
            except Exception as e:
                logger.error(f"ImportSidebarChannels error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        async def GetSidebarDMs(self) -> "s":
            """Get DMs that were imported from the sidebar."""
            if not self.daemon.state_db:
                return json.dumps(
                    {"success": False, "error": "State DB not available", "dms": []}
                )

            try:
                dms = await self.daemon.state_db.get_sidebar_dms()
                return json.dumps({"success": True, "dms": dms, "count": len(dms)})
            except Exception as e:
                logger.error(f"GetSidebarDMs error: {e}")
                return json.dumps({"success": False, "error": str(e), "dms": []})

        @method()
        async def RefreshUserCache(self) -> "s":
            """Trigger a refresh of the user cache from Slack API."""
            if not self.daemon.session or not self.daemon.state_db:
                return json.dumps(
                    {"success": False, "error": "Session or State DB not available"}
                )

            try:
                from tool_modules.aa_slack.src.persistence import CachedUser

                stats = await self.daemon.state_db.get_user_cache_stats()
                cache_age = stats.get("cache_age_seconds")
                if cache_age is not None and cache_age < 3600:
                    return json.dumps(
                        {
                            "success": True,
                            "message": "User cache is recent, skipping refresh",
                            "cache_age_seconds": cache_age,
                            "users_cached": stats.get("total_users", 0),
                            "skipped": True,
                        }
                    )

                users_data = await self.daemon.session.get_users_list(limit=1000)

                users = []
                for u in users_data:
                    if u.get("id") and not u.get("is_bot") and not u.get("deleted"):
                        profile = u.get("profile", {})
                        users.append(
                            CachedUser(
                                user_id=u.get("id", ""),
                                user_name=u.get("name", ""),
                                display_name=profile.get("display_name", ""),
                                real_name=profile.get("real_name", ""),
                                email=profile.get("email", ""),
                                gitlab_username="",
                                avatar_url=profile.get(
                                    "image_72", profile.get("image_48", "")
                                ),
                            )
                        )

                await self.daemon.state_db.cache_users_bulk(users)

                return json.dumps(
                    {
                        "success": True,
                        "message": "User cache refreshed",
                        "users_cached": len(users),
                    }
                )
            except Exception as e:
                logger.error(f"RefreshUserCache error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        async def GetUserCacheStats(self) -> "s":
            """Get statistics about the user cache."""
            if not self.daemon.state_db:
                return json.dumps({"success": False, "error": "State DB not available"})

            try:
                stats = await self.daemon.state_db.get_user_cache_stats()
                stats["success"] = True
                return json.dumps(stats)
            except Exception as e:
                logger.error(f"GetUserCacheStats error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        async def ListChannelMembers(self, channel_id: "s", count: "i") -> "s":
            """List members of a specific channel."""
            if not self.daemon.session:
                return json.dumps({"success": False, "error": "Session not available"})

            try:
                count = max(1, min(count, 500))
                result = await self.daemon.session.list_channel_members_and_cache(
                    channel_id, count
                )
                return json.dumps(result)
            except Exception as e:
                logger.error(f"ListChannelMembers error: {e}")
                return json.dumps(
                    {
                        "success": False,
                        "error": str(e),
                        "channel_id": channel_id,
                        "users": [],
                    }
                )

        @method()
        async def CheckChannelMembership(
            self, channel_id: "s", user_ids_json: "s"
        ) -> "s":
            """Check which users from a list are members of a channel."""
            if not self.daemon.session:
                return json.dumps({"success": False, "error": "Session not available"})

            try:
                user_ids = json.loads(user_ids_json)
                if not isinstance(user_ids, list):
                    return json.dumps(
                        {
                            "success": False,
                            "error": "user_ids_json must be a JSON array",
                        }
                    )

                result = await self.daemon.session.check_channel_membership(
                    channel_id, user_ids
                )

                if not result.get("ok"):
                    return json.dumps(
                        {
                            "success": False,
                            "error": result.get("error", "Unknown error"),
                        }
                    )

                return json.dumps(
                    {
                        "success": True,
                        "channel": result.get("channel", channel_id),
                        "members": result.get("members", []),
                        "checked_count": result.get("checked_count", 0),
                        "member_count": result.get("member_count", 0),
                    }
                )
            except json.JSONDecodeError as e:
                return json.dumps(
                    {"success": False, "error": f"Invalid JSON for user_ids: {e}"}
                )
            except Exception as e:
                logger.error(f"CheckChannelMembership error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        # ==================== Signals ====================

        @dbus_signal()
        def MessageReceived(self, message_json: "s") -> None:
            """Emitted when a new message is received."""
            pass

        @dbus_signal()
        def MessageProcessed(self, message_id: "s", status: "s") -> None:
            """Emitted when a message is processed."""
            pass

        @dbus_signal()
        def PendingApproval(self, message_json: "s") -> None:
            """Emitted when a message needs approval."""
            pass


class SlackDaemonWithDBus:
    """
    Extended Slack daemon with D-Bus IPC support.

    Inherits behavior from the base daemon but adds:
    - D-Bus interface for external control
    - Message history tracking
    - Approval queue management
    - Health checking
    """

    def __init__(self):
        self.is_running = False
        self.start_time: float | None = None
        self.messages_processed = 0
        self.messages_responded = 0
        self.history = MessageHistory()

        self._bus: MessageBus | None = None
        self._dbus_interface: SlackPersonaDBusInterface | None = None
        self._shutdown_requested = False

        # Health tracking
        self._last_successful_poll: float = 0
        self._last_successful_api_call: float = 0
        self._consecutive_api_failures: int = 0
        self._last_health_check: float = 0

        # Will be set when daemon starts
        self.session = None
        self.state_db = None
        self.listener = None
        self.user_classifier = None
        self.channel_permissions = None
        self.response_generator = None
        self._event_loop = None  # Set when D-Bus starts

    async def start_dbus(self):
        """Start the D-Bus service."""
        if not DBUS_AVAILABLE:
            logger.warning("D-Bus not available, IPC disabled")
            return

        try:
            # Store the running event loop for D-Bus method handlers
            self._event_loop = asyncio.get_running_loop()

            self._bus = await MessageBus().connect()
            self._dbus_interface = SlackPersonaDBusInterface(self)

            self._bus.export(DBUS_OBJECT_PATH, self._dbus_interface)
            await self._bus.request_name(DBUS_SERVICE_NAME)

            logger.info(f"D-Bus service started: {DBUS_SERVICE_NAME}")
        except Exception as e:
            logger.error(f"Failed to start D-Bus: {e}")

    async def stop_dbus(self):
        """Stop the D-Bus service."""
        if self._bus:
            self._bus.disconnect()
            self._bus = None

    def emit_message_received(self, record: MessageRecord):
        """Emit D-Bus signal for new message."""
        if self._dbus_interface:
            self._dbus_interface.MessageReceived(record.to_json())

    def emit_message_processed(self, message_id: str, status: str):
        """Emit D-Bus signal for processed message."""
        if self._dbus_interface:
            self._dbus_interface.MessageProcessed(message_id, status)

    def emit_pending_approval(self, record: MessageRecord):
        """Emit D-Bus signal for pending approval."""
        if self._dbus_interface:
            self._dbus_interface.PendingApproval(record.to_json())

    async def approve_message(self, message_id: str) -> dict:
        """Approve and send a pending message."""
        record = self.history.approve(message_id)
        if not record:
            return {"success": False, "error": "Message not found"}

        # Send the response
        try:
            if self.session:
                await self.session.send_message(
                    channel_id=record.channel_id,
                    text=record.response,
                    thread_ts=record.thread_ts,
                    typing_delay=True,
                )
                self.messages_responded += 1
                self.emit_message_processed(message_id, "sent")
                return {"success": True, "message_id": message_id, "status": "sent"}
        except Exception as e:
            return {"success": False, "error": str(e)}

        return {"success": False, "error": "Session not available"}

    async def approve_all_pending(self) -> dict:
        """Approve all pending messages."""
        pending = list(self.history.pending_approvals.keys())
        results = []

        for msg_id in pending:
            result = await self.approve_message(msg_id)
            results.append(result)

        return {
            "total": len(pending),
            "approved": sum(1 for r in results if r.get("success")),
            "failed": sum(1 for r in results if not r.get("success")),
            "results": results,
        }

    async def send_direct_message(
        self,
        channel_id: str,
        text: str,
        thread_ts: str = "",
    ) -> dict:
        """Send a message directly (bypassing intent detection)."""
        if not self.session:
            return {"success": False, "error": "Session not available"}

        try:
            result = await self.session.send_message(
                channel_id=channel_id,
                text=text,
                thread_ts=thread_ts if thread_ts else None,
                typing_delay=True,
            )
            return {"success": True, "ts": result.get("ts", "")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def reload_config(self):
        """Reload configuration from config.json."""
        if self.user_classifier:
            self.user_classifier.reload()
        if self.channel_permissions:
            self.channel_permissions.reload()

    def request_shutdown(self):
        """Request graceful shutdown."""
        self._shutdown_requested = True

    def record_successful_poll(self):
        """Record a successful poll (for health tracking)."""
        self._last_successful_poll = time.time()
        self._consecutive_api_failures = 0

    def record_successful_api_call(self):
        """Record a successful API call (for health tracking)."""
        self._last_successful_api_call = time.time()
        self._consecutive_api_failures = 0

    def record_api_failure(self):
        """Record an API failure (for health tracking)."""
        self._consecutive_api_failures += 1

    def health_check_sync(self) -> dict:
        """
        Perform a synchronous health check on the Slack daemon.

        This is a lightweight check that doesn't make API calls.
        For API reachability, rely on the listener's polling stats.

        Checks:
        - Service is running
        - Listener is active and polling
        - No excessive consecutive failures
        """
        self._last_health_check = time.time()
        now = time.time()

        # Core checks (required for health)
        checks = {
            "running": self.is_running,
            "session_valid": self.session is not None,
            "listener_active": self.listener is not None,
        }

        # Check if polling is happening (should poll at least every 60s)
        if self._last_successful_poll > 0:
            poll_age = now - self._last_successful_poll
            checks["polling_recent"] = poll_age < 120  # Last poll within 2 minutes
        else:
            # If we just started, don't fail this check
            if self.start_time and (now - self.start_time) < 60:
                checks["polling_recent"] = True  # Grace period
            else:
                checks["polling_recent"] = False

        # Check consecutive failures
        checks["no_excessive_failures"] = self._consecutive_api_failures < 10

        # Check uptime (at least 10 seconds)
        if self.start_time:
            checks["uptime_ok"] = (now - self.start_time) > 10
        else:
            checks["uptime_ok"] = False

        # Get listener stats for additional info
        listener_stats = {}
        if self.listener:
            listener_stats = getattr(self.listener, "stats", {})

        # Overall health based on core checks only
        healthy = all(checks.values())

        # Build message
        if healthy:
            message = "Slack daemon is healthy"
        else:
            failed = [k for k, v in checks.items() if not v]
            message = f"Unhealthy: {', '.join(failed)}"

        return {
            "healthy": healthy,
            "checks": checks,
            "message": message,
            "timestamp": self._last_health_check,
            "consecutive_failures": self._consecutive_api_failures,
            "last_successful_poll": self._last_successful_poll,
            "last_successful_api_call": self._last_successful_api_call,
            "polls": listener_stats.get("polls", 0),
            "errors": listener_stats.get("errors", 0),
        }

    async def health_check(self) -> dict:
        """Async wrapper for health_check_sync (for compatibility)."""
        return self.health_check_sync()


# =============================================================================
# D-Bus CLIENT
# =============================================================================


class SlackAgentClient:
    """Client for communicating with the Slack daemon via D-Bus."""

    def __init__(self):
        self._bus: MessageBus | None = None
        self._proxy = None

    async def connect(self) -> bool:
        """Connect to the D-Bus service."""
        if not DBUS_AVAILABLE:
            print("Error: dbus-next not installed")
            return False

        try:
            self._bus = await MessageBus().connect()
            introspection = await self._bus.introspect(
                DBUS_SERVICE_NAME, DBUS_OBJECT_PATH
            )
            self._proxy = self._bus.get_proxy_object(
                DBUS_SERVICE_NAME,
                DBUS_OBJECT_PATH,
                introspection,
            )
            return True
        except Exception as e:
            print(f"Failed to connect to Slack daemon: {e}")
            print("Is the daemon running? Start with: make slack-daemon-bg")
            return False

    async def disconnect(self):
        """Disconnect from D-Bus."""
        if self._bus:
            self._bus.disconnect()

    def _get_interface(self):
        """Get the D-Bus interface."""
        if not self._proxy:
            raise RuntimeError("Not connected")
        return self._proxy.get_interface(DBUS_INTERFACE_NAME)

    async def get_status(self) -> dict:
        """Get daemon status."""
        interface = self._get_interface()
        result = await interface.call_get_status()
        return json.loads(result)

    async def get_pending(self) -> list:
        """Get pending approval messages."""
        interface = self._get_interface()
        result = await interface.call_get_pending()
        return json.loads(result)

    async def approve(self, message_id: str) -> dict:
        """Approve a pending message."""
        interface = self._get_interface()
        result = await interface.call_approve_message(message_id)
        return json.loads(result)

    async def reject(self, message_id: str) -> dict:
        """Reject a pending message."""
        interface = self._get_interface()
        result = await interface.call_reject_message(message_id)
        return json.loads(result)

    async def approve_all(self) -> dict:
        """Approve all pending messages."""
        interface = self._get_interface()
        result = await interface.call_approve_all()
        return json.loads(result)

    async def get_history(
        self,
        limit: int = 50,
        channel_id: str = "",
        user_id: str = "",
        status: str = "",
    ) -> list:
        """Get message history."""
        interface = self._get_interface()
        result = await interface.call_get_history(limit, channel_id, user_id, status)
        return json.loads(result)

    async def send_message(
        self, channel_id: str, text: str, thread_ts: str = ""
    ) -> dict:
        """Send a message to Slack."""
        interface = self._get_interface()
        result = await interface.call_send_message(channel_id, text, thread_ts)
        return json.loads(result)

    async def reload_config(self) -> dict:
        """Reload daemon configuration."""
        interface = self._get_interface()
        result = await interface.call_reload_config()
        return json.loads(result)

    async def shutdown(self) -> dict:
        """Shutdown the daemon."""
        interface = self._get_interface()
        result = await interface.call_shutdown()
        return json.loads(result)

    async def health_check(self) -> dict:
        """Perform a comprehensive health check."""
        interface = self._get_interface()
        result = await interface.call_health_check()
        return json.loads(result)

    # ==================== Knowledge Cache Methods ====================

    async def find_channel(self, query: str) -> dict:
        """Find channels by name, purpose, or topic."""
        interface = self._get_interface()
        result = await interface.call_find_channel(query)
        return json.loads(result)

    async def find_user(self, query: str) -> dict:
        """Find users by name, email, or GitLab username."""
        interface = self._get_interface()
        result = await interface.call_find_user(query)
        return json.loads(result)

    async def get_my_channels(self) -> dict:
        """Get channels the bot is a member of."""
        interface = self._get_interface()
        result = await interface.call_get_my_channels()
        return json.loads(result)

    async def get_user_groups(self) -> dict:
        """Get all cached user groups."""
        interface = self._get_interface()
        result = await interface.call_get_user_groups()
        return json.loads(result)

    async def resolve_target(self, target: str) -> dict:
        """Resolve #channel, @user, or @group to ID."""
        interface = self._get_interface()
        result = await interface.call_resolve_target(target)
        return json.loads(result)

    async def get_channel_cache_stats(self) -> dict:
        """Get knowledge cache statistics."""
        interface = self._get_interface()
        result = await interface.call_get_channel_cache_stats()
        return json.loads(result)

    async def refresh_channel_cache(self) -> dict:
        """Trigger a refresh of the channel cache."""
        interface = self._get_interface()
        result = await interface.call_refresh_channel_cache()
        return json.loads(result)

    async def refresh_user_cache(self) -> dict:
        """Trigger a refresh of the user cache."""
        interface = self._get_interface()
        result = await interface.call_refresh_user_cache()
        return json.loads(result)

    async def get_user_cache_stats(self) -> dict:
        """Get user cache statistics."""
        interface = self._get_interface()
        result = await interface.call_get_user_cache_stats()
        return json.loads(result)

    async def search_messages(self, query: str, max_results: int = 20) -> dict:
        """Search Slack messages (rate-limited)."""
        interface = self._get_interface()
        result = await interface.call_search_messages(query, max_results)
        return json.loads(result)

    async def get_command_list(self) -> dict:
        """Get list of available @me commands."""
        interface = self._get_interface()
        result = await interface.call_get_command_list()
        return json.loads(result)

    async def get_config(self) -> dict:
        """Get current Slack daemon configuration."""
        interface = self._get_interface()
        result = await interface.call_get_config()
        return json.loads(result)

    async def set_debug_mode(self, enabled: bool) -> dict:
        """Enable or disable debug mode."""
        interface = self._get_interface()
        result = await interface.call_set_debug_mode(enabled)
        return json.loads(result)

    async def import_sidebar_channels(self, file_path: str) -> dict:
        """Import channels from a Slack sidebar HTML file."""
        interface = self._get_interface()
        result = await interface.call_import_sidebar_channels(file_path)
        return json.loads(result)

    async def get_sidebar_dms(self) -> dict:
        """Get DMs that were imported from the sidebar."""
        interface = self._get_interface()
        result = await interface.call_get_sidebar_d_ms()
        return json.loads(result)

    async def search_channels(self, query: str, count: int = 30) -> dict:
        """Search for channels using Slack's edge API."""
        interface = self._get_interface()
        result = await interface.call_search_channels(query, count)
        return json.loads(result)

    async def search_and_cache_channels(self, query: str, count: int = 30) -> dict:
        """Search for channels and add results to the local cache."""
        interface = self._get_interface()
        result = await interface.call_search_and_cache_channels(query, count)
        return json.loads(result)

    async def search_users(self, query: str, count: int = 30) -> dict:
        """Search for users using Slack's edge API."""
        interface = self._get_interface()
        result = await interface.call_search_users(query, count)
        return json.loads(result)

    async def search_and_cache_users(self, query: str, count: int = 30) -> dict:
        """Search for users and add results to the local cache."""
        interface = self._get_interface()
        result = await interface.call_search_and_cache_users(query, count)
        return json.loads(result)

    async def get_user_profile(self, user_id: str) -> dict:
        """Get detailed user profile with sections."""
        interface = self._get_interface()
        result = await interface.call_get_user_profile(user_id)
        return json.loads(result)

    async def get_avatar_url(
        self, user_id: str, avatar_hash: str, size: int = 512
    ) -> dict:
        """Construct a Slack avatar URL from user ID and avatar hash."""
        interface = self._get_interface()
        result = await interface.call_get_avatar_url(user_id, avatar_hash, size)
        return json.loads(result)

    async def get_thread_replies(
        self, channel_id: str, thread_ts: str, limit: int = 50
    ) -> dict:
        """Get thread replies with full message data."""
        interface = self._get_interface()
        result = await interface.call_get_thread_replies(channel_id, thread_ts, limit)
        return json.loads(result)

    async def get_thread_context(self, channel_id: str, thread_ts: str) -> dict:
        """Get simplified thread context for AI processing."""
        interface = self._get_interface()
        result = await interface.call_get_thread_context(channel_id, thread_ts)
        return json.loads(result)

    async def send_message_rich(
        self,
        channel_id: str,
        text: str,
        thread_ts: str = "",
        reply_broadcast: bool = False,
    ) -> dict:
        """Send a message using the web client API format with rich text blocks."""
        interface = self._get_interface()
        result = await interface.call_send_message_rich(
            channel_id, text, thread_ts, reply_broadcast
        )
        return json.loads(result)

    async def get_app_commands(self, summarize: bool = True) -> dict:
        """Get all available slash commands and app actions in the workspace."""
        interface = self._get_interface()
        result = await interface.call_get_app_commands(summarize)
        return json.loads(result)

    async def list_channel_members(self, channel_id: str, count: int = 100) -> dict:
        """List members of a specific channel with full profile info."""
        interface = self._get_interface()
        result = await interface.call_list_channel_members(channel_id, count)
        return json.loads(result)

    async def get_channel_sections(self, summarize: bool = True) -> dict:
        """Get the user's sidebar channel sections/folders with channel IDs."""
        interface = self._get_interface()
        result = await interface.call_get_channel_sections(summarize)
        return json.loads(result)

    async def get_channel_history(
        self,
        channel_id: str,
        limit: int = 50,
        oldest: str = "",
        latest: str = "",
        simplify: bool = True,
    ) -> dict:
        """Get message history for a channel with optional time range."""
        interface = self._get_interface()
        result = await interface.call_get_channel_history(
            channel_id, limit, oldest, latest, simplify
        )
        return json.loads(result)

    async def check_channel_membership(
        self,
        channel_id: str,
        user_ids: list[str],
    ) -> dict:
        """Check which users from a list are members of a channel."""
        interface = self._get_interface()
        user_ids_json = json.dumps(user_ids)
        result = await interface.call_check_channel_membership(
            channel_id, user_ids_json
        )
        return json.loads(result)

    # ==================== User Lookup ====================

    async def lookup_user_by_email(self, email: str) -> dict:
        """
        Find a Slack user by their email address.

        Args:
            email: Email address to search for

        Returns:
            Dict with user info including user_id, name, and photo_path
        """
        interface = self._get_interface()
        result = await interface.call_lookup_user_by_email(email)
        return json.loads(result)

    async def lookup_user_by_name(self, name: str, threshold: float = 0.7) -> dict:
        """
        Find Slack users by fuzzy name matching.

        Args:
            name: Name to search for (e.g., "John Smith")
            threshold: Minimum similarity ratio (0-1, default 0.7)

        Returns:
            Dict with list of matching users sorted by match score
        """
        interface = self._get_interface()
        result = await interface.call_lookup_user_by_name(name, threshold)
        return json.loads(result)

    def get_user_photo_path(self, user_id: str) -> dict:
        """
        Get the local file path to a cached Slack user's profile photo.

        Args:
            user_id: Slack user ID (e.g., U04RA3VE2RZ)

        Returns:
            Dict with photo_path (empty string if not cached)
        """
        interface = self._get_interface()
        result = interface.call_get_user_photo_path(user_id)
        return json.loads(result)

    # ==================== Background Sync ====================

    def get_sync_status(self) -> dict:
        """Get the status of the background sync process."""
        interface = self._get_interface()
        result = interface.call_get_sync_status()
        return json.loads(result)

    async def start_sync(self) -> dict:
        """Start the background sync process."""
        interface = self._get_interface()
        result = await interface.call_start_sync()
        return json.loads(result)

    async def stop_sync(self) -> dict:
        """Stop the background sync process."""
        interface = self._get_interface()
        result = await interface.call_stop_sync()
        return json.loads(result)

    async def trigger_sync(self, sync_type: str = "full") -> dict:
        """Manually trigger a sync operation."""
        interface = self._get_interface()
        result = await interface.call_trigger_sync(sync_type)
        return json.loads(result)

    def get_sync_config(self) -> dict:
        """Get the background sync configuration."""
        interface = self._get_interface()
        result = interface.call_get_sync_config()
        return json.loads(result)

    def set_sync_config(self, config: dict) -> dict:
        """Update background sync configuration."""
        interface = self._get_interface()
        result = interface.call_set_sync_config(json.dumps(config))
        return json.loads(result)

    def get_photo_path(self, user_id: str) -> dict:
        """Get the local cached photo path for a user."""
        interface = self._get_interface()
        result = interface.call_get_photo_path(user_id)
        return json.loads(result)
