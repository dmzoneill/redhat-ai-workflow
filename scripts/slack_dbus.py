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
"""

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path

# Check for dbus availability
try:
    from dbus_next.aio import MessageBus
    from dbus_next.constants import PropertyAccess
    from dbus_next.service import ServiceInterface, dbus_property, method
    from dbus_next.service import signal as dbus_signal

    DBUS_AVAILABLE = True
except ImportError:
    DBUS_AVAILABLE = False
    print("Warning: dbus-next not installed. Install with: pip install dbus-next")

PROJECT_ROOT = Path(__file__).parent.parent

logger = logging.getLogger(__name__)

# D-Bus configuration
DBUS_SERVICE_NAME = "com.aiworkflow.BotSlack"
DBUS_OBJECT_PATH = "/com/aiworkflow/BotSlack"
DBUS_INTERFACE_NAME = "com.aiworkflow.BotSlack"


@dataclass
class MessageRecord:
    """Record of a processed message."""

    id: str
    timestamp: str
    channel_id: str
    channel_name: str
    user_id: str
    user_name: str
    text: str
    intent: str
    classification: str
    response: str
    status: str  # pending, approved, rejected, sent, skipped
    created_at: float
    processed_at: float | None = None
    thread_ts: str | None = None  # Thread timestamp for replies

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class MessageHistory:
    """Stores message history for querying."""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.messages: list[MessageRecord] = []
        self.pending_approvals: dict[str, MessageRecord] = {}

    def add(self, record: MessageRecord):
        """Add a message record."""
        self.messages.append(record)
        if len(self.messages) > self.max_size:
            self.messages.pop(0)

        if record.status == "pending":
            self.pending_approvals[record.id] = record

    def get_pending(self) -> list[MessageRecord]:
        """Get messages pending approval."""
        return list(self.pending_approvals.values())

    def approve(self, message_id: str) -> MessageRecord | None:
        """Approve a pending message."""
        if message_id in self.pending_approvals:
            record = self.pending_approvals.pop(message_id)
            record.status = "approved"
            record.processed_at = time.time()
            return record
        return None

    def reject(self, message_id: str) -> MessageRecord | None:
        """Reject a pending message."""
        if message_id in self.pending_approvals:
            record = self.pending_approvals.pop(message_id)
            record.status = "rejected"
            record.processed_at = time.time()
            return record
        return None

    def get_history(
        self,
        limit: int = 50,
        channel_id: str = "",
        user_id: str = "",
        status: str = "",
    ) -> list[MessageRecord]:
        """Get message history with optional filters."""
        result = self.messages.copy()

        if channel_id:
            result = [m for m in result if m.channel_id == channel_id]
        if user_id:
            result = [m for m in result if m.user_id == user_id]
        if status:
            result = [m for m in result if m.status == status]

        return result[-limit:]

    def get_stats(self) -> dict:
        """Get message statistics."""
        total = len(self.messages)
        by_status = {}
        by_classification = {}
        by_intent = {}

        for m in self.messages:
            by_status[m.status] = by_status.get(m.status, 0) + 1
            by_classification[m.classification] = by_classification.get(m.classification, 0) + 1
            by_intent[m.intent] = by_intent.get(m.intent, 0) + 1

        return {
            "total": total,
            "pending_approvals": len(self.pending_approvals),
            "by_status": by_status,
            "by_classification": by_classification,
            "by_intent": by_intent,
        }


if DBUS_AVAILABLE:

    class SlackPersonaDBusInterface(ServiceInterface):
        """D-Bus interface for the Slack Persona daemon."""

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
            # Get listener stats if available (includes polls, errors, etc.)
            listener_stats = {}
            if hasattr(self.daemon, "listener") and self.daemon.listener:
                listener_stats = getattr(self.daemon.listener, "stats", {})

            stats = {
                "running": self.daemon.is_running,
                "uptime": (time.time() - self.daemon.start_time if self.daemon.start_time else 0),
                "messages_processed": self.daemon.messages_processed,
                "messages_responded": self.daemon.messages_responded,
                "pending_approvals": len(self.daemon.history.pending_approvals),
                # Add listener stats for VSCode extension
                "polls": listener_stats.get("polls", 0),
                "errors": listener_stats.get("errors", 0),
                "consecutive_errors": listener_stats.get("consecutive_errors", 0),
                "messages_seen": listener_stats.get("messages_seen", 0),
            }
            return json.dumps(stats)

        # ==================== Methods ====================

        @method()
        def GetStatus(self) -> "s":
            """Get daemon status as JSON."""
            return self.Stats

        @method()
        def GetPending(self) -> "s":
            """Get pending approval messages as JSON array."""
            pending = self.daemon.history.get_pending()
            return json.dumps([m.to_dict() for m in pending])

        @method()
        def ApproveMessage(self, message_id: "s") -> "s":
            """Approve a pending message and send it."""
            loop = self.daemon._event_loop
            future = asyncio.run_coroutine_threadsafe(self.daemon.approve_message(message_id), loop)
            result = future.result(timeout=30)
            return json.dumps(result)

        @method()
        def RejectMessage(self, message_id: "s") -> "s":
            """Reject a pending message."""
            record = self.daemon.history.reject(message_id)
            if record:
                return json.dumps({"success": True, "message_id": message_id})
            return json.dumps({"success": False, "error": "Message not found"})

        @method()
        def ApproveAll(self) -> "s":
            """Approve all pending messages."""
            loop = self.daemon._event_loop
            future = asyncio.run_coroutine_threadsafe(self.daemon.approve_all_pending(), loop)
            result = future.result(timeout=60)
            return json.dumps(result)

        @method()
        def GetHistory(self, limit: "i", channel_id: "s", user_id: "s", status: "s") -> "s":
            """Get message history with optional filters."""
            history = self.daemon.history.get_history(
                limit=limit,
                channel_id=channel_id,
                user_id=user_id,
                status=status,
            )
            return json.dumps([m.to_dict() for m in history])

        @method()
        def SendMessage(self, channel_id: "s", text: "s", thread_ts: "s") -> "s":
            """Send a message to Slack.

            Note: This method schedules the send and returns immediately.
            The actual send happens asynchronously.
            """
            # Schedule the coroutine on the event loop (non-blocking)
            loop = self.daemon._event_loop
            if not loop or not self.daemon.session:
                return json.dumps({"success": False, "error": "Session not available"})

            # Create a task to run the send (fire-and-forget for now)
            # We return success immediately since we can't block here
            async def do_send():
                try:
                    result = await self.daemon.session.send_message(
                        channel_id=channel_id,
                        text=text,
                        thread_ts=thread_ts if thread_ts else None,
                        typing_delay=True,
                    )
                    logger.info(f"D-Bus SendMessage completed: ts={result.get('ts', 'unknown')}")
                    return result
                except Exception as e:
                    logger.error(f"D-Bus SendMessage failed: {e}")
                    return {"success": False, "error": str(e)}

            # Schedule the task
            asyncio.run_coroutine_threadsafe(do_send(), loop)

            # Return immediately - the message will be sent asynchronously
            return json.dumps({"success": True, "message": "Message send scheduled", "async": True})

        @method()
        async def SendMessageRich(self, channel_id: "s", text: "s", thread_ts: "s", reply_broadcast: "b") -> "s":
            """
            Send a message using the web client API format with rich text blocks.

            This uses the same multipart/form-data format as the Slack web client,
            which provides:
            - Rich text formatting (bold, italic, code, etc.)
            - Proper thread replies
            - Reply broadcast option (also send to channel)
            - Client message ID tracking

            Args:
                channel_id: Target channel ID
                text: Message text (supports Slack markdown, code blocks, mentions)
                thread_ts: Thread timestamp for threaded reply (empty string for no thread)
                reply_broadcast: Also send reply to channel (not just thread)

            Returns:
                JSON with success status, channel, timestamp, and message details
            """
            if not self.daemon.session:
                return json.dumps({"success": False, "error": "Session not available"})

            try:
                result = await self.daemon.session.send_message_rich(
                    channel_id=channel_id,
                    text=text,
                    thread_ts=thread_ts if thread_ts else None,
                    reply_broadcast=reply_broadcast,
                    typing_delay=True,
                )

                if result.get("ok"):
                    return json.dumps(
                        {
                            "success": True,
                            "channel": result.get("channel", channel_id),
                            "ts": result.get("ts", ""),
                            "message": result.get("message", {}),
                        }
                    )
                else:
                    return json.dumps(
                        {
                            "success": False,
                            "error": result.get("error", "Unknown error"),
                        }
                    )
            except Exception as e:
                logger.error(f"SendMessageRich error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        def ReloadConfig(self) -> "s":
            """Reload configuration from config.json."""
            self.daemon.reload_config()
            return json.dumps({"success": True, "message": "Config reloaded"})

        @method()
        def Shutdown(self) -> "s":
            """Gracefully shutdown the daemon."""
            self.daemon._event_loop.call_soon(self.daemon.request_shutdown)
            return json.dumps({"success": True, "message": "Shutdown initiated"})

        @method()
        def HealthCheck(self) -> "s":
            """Perform a comprehensive health check."""
            try:
                # Use synchronous health check to avoid event loop issues
                result = self.daemon.health_check_sync()
                return json.dumps(result)
            except Exception as e:
                return json.dumps(
                    {
                        "healthy": False,
                        "checks": {"health_check_execution": False},
                        "message": f"Health check failed: {e}",
                        "timestamp": time.time(),
                    }
                )

        # ==================== Knowledge Cache Methods ====================

        @method()
        async def FindChannel(self, query: "s") -> "s":
            """
            Find channels by name, purpose, or topic.

            Args:
                query: Search string to match against channel name/purpose/topic

            Returns:
                JSON array of matching channels with id, name, purpose, etc.
            """
            if not self.daemon.state_db:
                return json.dumps({"success": False, "error": "State DB not available", "channels": []})

            try:
                channels = await self.daemon.state_db.find_channels(query=query, limit=500)
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
            """
            Search for channels using Slack's edge API.

            This uses the internal edgeapi endpoint which works even when the
            regular conversations.list API is blocked by enterprise restrictions.

            Unlike FindChannel (which searches the local cache), this searches
            Slack directly and can find channels you're not a member of.

            Args:
                query: Search query string (e.g., "ansible", "analytics")
                count: Maximum number of results (default 30, max 100)

            Returns:
                JSON with search results including channel id, name, purpose, etc.
            """
            if not self.daemon.session:
                return json.dumps({"success": False, "error": "Session not available", "channels": []})

            # Cap count at 100 for safety
            count = min(max(count, 1), 100) if count > 0 else 30

            try:
                result = await self.daemon.session.search_channels_and_cache(query, count)
                return json.dumps(result)
            except Exception as e:
                logger.error(f"SearchChannels error: {e}")
                return json.dumps({"success": False, "error": str(e), "channels": []})

        @method()
        async def SearchAndCacheChannels(self, query: "s", count: "i") -> "s":
            """
            Search for channels and add results to the local cache.

            This combines SearchChannels with caching - useful for discovering
            new channels and adding them to the bot's knowledge base.

            Args:
                query: Search query string
                count: Maximum number of results

            Returns:
                JSON with search results and cache update status
            """
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
                # Search channels
                result = await self.daemon.session.search_channels_and_cache(query, count)

                if not result.get("success"):
                    return json.dumps(result)

                # Import to cache
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
            """
            Find users by name, email, or GitLab username.

            Args:
                query: Search string to match against user fields

            Returns:
                JSON array of matching users with id, name, email, etc.
            """
            if not self.daemon.state_db:
                return json.dumps({"success": False, "error": "State DB not available", "users": []})

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
            """
            Search for users using Slack's edge API.

            This uses the internal edgeapi endpoint which works even when the
            regular users.list API is blocked by enterprise restrictions.

            Unlike FindUser (which searches the local cache), this searches
            Slack directly and can find any user in the enterprise.

            Args:
                query: Search query string (name, email, title, etc.)
                count: Maximum number of results (default 30, max 100)

            Returns:
                JSON with search results including user id, name, email, title, etc.
            """
            if not self.daemon.session:
                return json.dumps({"success": False, "error": "Session not available", "users": []})

            # Cap count at 100 for safety
            count = min(max(count, 1), 100) if count > 0 else 30

            try:
                result = await self.daemon.session.search_users_and_cache(query, count)
                return json.dumps(result)
            except Exception as e:
                logger.error(f"SearchUsers error: {e}")
                return json.dumps({"success": False, "error": str(e), "users": []})

        @method()
        async def SearchAndCacheUsers(self, query: "s", count: "i") -> "s":
            """
            Search for users and add results to the local cache.

            This combines SearchUsers with caching - useful for discovering
            new users and adding them to the bot's knowledge base.

            Args:
                query: Search query string
                count: Maximum number of results

            Returns:
                JSON with search results and cache update status
            """
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
                # Search users
                result = await self.daemon.session.search_users_and_cache(query, count)

                if not result.get("success"):
                    return json.dumps(result)

                # Import to cache
                from tool_modules.aa_slack.src.persistence import CachedUser

                users_to_cache = []
                for u in result.get("users", []):
                    if u.get("user_id") and not u.get("is_bot") and not u.get("deleted"):
                        users_to_cache.append(
                            CachedUser(
                                user_id=u["user_id"],
                                user_name=u.get("user_name", ""),
                                display_name=u.get("display_name", ""),
                                real_name=u.get("real_name", ""),
                                email=u.get("email", ""),
                                gitlab_username="",  # Not available from Slack
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
            """
            Get detailed user profile with sections (contact info, about me, etc.).

            This uses the users.profile.getSections API which returns structured
            profile data including custom fields, contact information, and more.

            Args:
                user_id: Slack user ID (e.g., U04RA3VE2RZ)

            Returns:
                JSON with profile sections and extracted fields (email, title, etc.)
            """
            if not self.daemon.session:
                return json.dumps({"success": False, "error": "Session not available", "profile": {}})

            try:
                result = await self.daemon.session.get_user_profile_details(user_id)
                return json.dumps(result)
            except Exception as e:
                logger.error(f"GetUserProfile error: {e}")
                return json.dumps({"success": False, "error": str(e), "profile": {}})

        @method()
        def GetAvatarUrl(self, user_id: "s", avatar_hash: "s", size: "i") -> "s":
            """
            Construct a Slack avatar URL from user ID and avatar hash.

            Avatar URLs follow the pattern:
            https://ca.slack-edge.com/{enterprise_id}-{user_id}-{avatar_hash}-{size}

            Args:
                user_id: Slack user ID (e.g., U04RA3VE2RZ)
                avatar_hash: Avatar hash from profile (e.g., 4d88f1ddb848)
                size: Image size in pixels (512, 192, 72, 48, 32)

            Returns:
                JSON with the constructed avatar URL
            """
            if not self.daemon.session:
                return json.dumps({"success": False, "error": "Session not available", "url": ""})

            try:
                # Default size to 512 if not specified
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
            """
            Get channels the bot is a member of.

            Returns:
                JSON array of channels with id, name, purpose, etc.
            """
            if not self.daemon.state_db:
                return json.dumps({"success": False, "error": "State DB not available", "channels": []})

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
            """
            Get all cached user groups (for @team mentions).

            Returns:
                JSON array of groups with id, handle, name, members.
            """
            if not self.daemon.state_db:
                return json.dumps({"success": False, "error": "State DB not available", "groups": []})

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
            """
            Find a Slack user by their email address.

            Args:
                email: Email address to search for (case-insensitive)

            Returns:
                JSON with user info including user_id, name, and photo_path
            """
            if not self.daemon.state_db:
                return json.dumps({"success": False, "error": "State DB not available"})

            try:
                user = await self.daemon.state_db.find_user_by_email(email)
                if user:
                    # Check for cached photo
                    from pathlib import Path

                    photo_dir = Path.home() / ".cache" / "aa-workflow" / "photos"
                    photo_path = photo_dir / f"{user['user_id']}.jpg"

                    return json.dumps(
                        {
                            "success": True,
                            "found": True,
                            "user_id": user["user_id"],
                            "user_name": user["user_name"],
                            "display_name": user["display_name"],
                            "real_name": user["real_name"],
                            "email": user["email"],
                            "avatar_url": user["avatar_url"],
                            "photo_path": str(photo_path) if photo_path.exists() else "",
                        }
                    )
                else:
                    return json.dumps(
                        {
                            "success": True,
                            "found": False,
                            "email": email,
                        }
                    )
            except Exception as e:
                logger.error(f"LookupUserByEmail error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        async def LookupUserByName(self, name: "s", threshold: "d") -> "s":
            """
            Find Slack users by fuzzy name matching.

            Compares the input name against real_name, display_name, and user_name
            using fuzzy string matching.

            Args:
                name: Name to search for (e.g., "John Smith")
                threshold: Minimum similarity ratio (0-1, default 0.7 if 0 passed)

            Returns:
                JSON with list of matching users sorted by match score
            """
            if not self.daemon.state_db:
                return json.dumps({"success": False, "error": "State DB not available", "users": []})

            try:
                # Default threshold if not specified
                if threshold <= 0:
                    threshold = 0.7

                users = await self.daemon.state_db.find_user_by_name_fuzzy(name, threshold=threshold, limit=5)

                # Add photo paths
                from pathlib import Path

                photo_dir = Path.home() / ".cache" / "aa-workflow" / "photos"

                results = []
                for user in users:
                    photo_path = photo_dir / f"{user['user_id']}.jpg"
                    results.append(
                        {
                            "user_id": user["user_id"],
                            "user_name": user["user_name"],
                            "display_name": user["display_name"],
                            "real_name": user["real_name"],
                            "email": user["email"],
                            "avatar_url": user["avatar_url"],
                            "photo_path": str(photo_path) if photo_path.exists() else "",
                            "match_score": user.get("match_score", 0),
                        }
                    )

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
            """
            Get the local file path to a cached Slack user's profile photo.

            Photos are cached to ~/.cache/aa-workflow/photos/{user_id}.jpg

            Args:
                user_id: Slack user ID (e.g., U04RA3VE2RZ)

            Returns:
                JSON with photo_path (empty string if not cached)
            """
            from pathlib import Path

            try:
                photo_dir = Path.home() / ".cache" / "aa-workflow" / "photos"
                photo_path = photo_dir / f"{user_id}.jpg"

                return json.dumps(
                    {
                        "success": True,
                        "user_id": user_id,
                        "photo_path": str(photo_path) if photo_path.exists() else "",
                        "exists": photo_path.exists(),
                    }
                )
            except Exception as e:
                logger.error(f"GetUserPhotoPath error: {e}")
                return json.dumps({"success": False, "error": str(e), "photo_path": ""})

        @method()
        async def ResolveTarget(self, target: "s") -> "s":
            """
            Resolve a Slack target to its ID.

            Args:
                target: Can be #channel, @user, @group, or raw ID

            Returns:
                JSON with type, id, name, and found status.
            """
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
            """
            Get statistics about the knowledge cache.

            Returns:
                JSON with cache stats (total channels, member channels, age, etc.)
            """
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
            """
            Trigger a refresh of the channel cache from Slack API.

            Returns:
                JSON with refresh status and count of channels cached.
            """
            if not self.daemon.session or not self.daemon.state_db:
                return json.dumps({"success": False, "error": "Session or State DB not available"})

            try:
                # Import here to avoid circular imports
                from tool_modules.aa_slack.src.persistence import CachedChannel

                # Fetch channels from Slack API
                channels_data = await self.daemon.session.get_conversations_list(
                    types="public_channel,private_channel",
                    limit=1000,
                )

                # Convert to CachedChannel objects
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

                # Bulk cache
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
            """
            Import channels from a Slack sidebar HTML file.

            This is a fallback for when the Slack API's conversations.list is
            blocked by enterprise restrictions. Users can:
            1. Open Slack in a browser
            2. Right-click on the sidebar
            3. Select "Inspect Element"
            4. Copy the outer HTML of the sidebar div
            5. Save to a file
            6. Call this method with the file path

            Args:
                file_path: Path to the HTML file (e.g., ~/Downloads/sidebar.txt)

            Returns:
                JSON with import stats (channels_imported, dms_found, etc.)
            """
            if not self.daemon.state_db:
                return json.dumps({"success": False, "error": "State DB not available"})

            try:
                # Expand ~ in path
                import os

                expanded_path = os.path.expanduser(file_path)

                result = await self.daemon.state_db.import_channels_from_sidebar(expanded_path)
                return json.dumps(result)
            except Exception as e:
                logger.error(f"ImportSidebarChannels error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        async def GetSidebarDMs(self) -> "s":
            """
            Get DMs that were imported from the sidebar.

            Returns:
                JSON array of DM info (channel_id, name, display_name, type)
            """
            if not self.daemon.state_db:
                return json.dumps({"success": False, "error": "State DB not available", "dms": []})

            try:
                dms = await self.daemon.state_db.get_sidebar_dms()
                return json.dumps({"success": True, "dms": dms, "count": len(dms)})
            except Exception as e:
                logger.error(f"GetSidebarDMs error: {e}")
                return json.dumps({"success": False, "error": str(e), "dms": []})

        @method()
        async def RefreshUserCache(self) -> "s":
            """
            Trigger a refresh of the user cache from Slack API.

            This is rate-limited to prevent abuse. Only refreshes if cache
            is older than 1 hour or empty.

            Returns:
                JSON with refresh status and count of users cached.
            """
            if not self.daemon.session or not self.daemon.state_db:
                return json.dumps({"success": False, "error": "Session or State DB not available"})

            try:
                # Import here to avoid circular imports
                from tool_modules.aa_slack.src.persistence import CachedUser

                # Check if cache is recent (rate limiting)
                stats = await self.daemon.state_db.get_user_cache_stats()
                cache_age = stats.get("cache_age_seconds")
                if cache_age is not None and cache_age < 3600:  # 1 hour
                    return json.dumps(
                        {
                            "success": True,
                            "message": "User cache is recent, skipping refresh",
                            "cache_age_seconds": cache_age,
                            "users_cached": stats.get("total_users", 0),
                            "skipped": True,
                        }
                    )

                # Fetch users from Slack API
                users_data = await self.daemon.session.get_users_list(limit=1000)

                # Convert to CachedUser objects
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
                                gitlab_username="",  # Not available from Slack
                                avatar_url=profile.get("image_72", profile.get("image_48", "")),
                            )
                        )

                # Bulk cache
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
            """
            Get statistics about the user cache.

            Returns:
                JSON with cache stats (total users, with avatar, with email, age, etc.)
            """
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
        async def SearchMessages(self, query: "s", max_results: "i") -> "s":
            """
            Search Slack messages with rate limiting.

            This method is rate-limited to prevent abuse:
            - Max 1 search per 5 seconds
            - Max 20 searches per day
            - Max 50 results per search

            Args:
                query: Search query string
                max_results: Maximum results to return (capped at 50)

            Returns:
                JSON with search results or rate limit error.
            """
            if not self.daemon.session:
                return json.dumps({"success": False, "error": "Session not available", "messages": []})

            # Cap max_results at 50 for safety
            max_results = min(max_results, 50) if max_results > 0 else 20

            try:
                # Check rate limits
                now = time.time()

                # Initialize rate limit tracking if needed
                if not hasattr(self.daemon, "_search_rate_limit"):
                    self.daemon._search_rate_limit = {
                        "last_search": 0,
                        "daily_count": 0,
                        "daily_reset": now,
                    }

                rl = self.daemon._search_rate_limit

                # Reset daily count if it's a new day
                if now - rl["daily_reset"] > 86400:  # 24 hours
                    rl["daily_count"] = 0
                    rl["daily_reset"] = now

                # Check per-search rate limit (5 seconds)
                if now - rl["last_search"] < 5:
                    wait_time = 5 - (now - rl["last_search"])
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"Rate limited. Please wait {wait_time:.1f} seconds.",
                            "rate_limited": True,
                            "wait_seconds": wait_time,
                            "messages": [],
                        }
                    )

                # Check daily limit (20 searches)
                if rl["daily_count"] >= 20:
                    return json.dumps(
                        {
                            "success": False,
                            "error": "Daily search limit (20) reached. Try again tomorrow.",
                            "rate_limited": True,
                            "daily_limit_reached": True,
                            "messages": [],
                        }
                    )

                # Update rate limit tracking
                rl["last_search"] = now
                rl["daily_count"] += 1

                # Perform the search
                results = await self.daemon.session.search_messages(
                    query=query,
                    count=max_results,
                )

                messages = results.get("messages", {}).get("matches", [])

                return json.dumps(
                    {
                        "success": True,
                        "query": query,
                        "count": len(messages),
                        "total": results.get("messages", {}).get("total", 0),
                        "messages": [
                            {
                                "text": m.get("text", ""),
                                "user": m.get("user", ""),
                                "username": m.get("username", ""),
                                "channel_id": m.get("channel", {}).get("id", ""),
                                "channel_name": m.get("channel", {}).get("name", ""),
                                "ts": m.get("ts", ""),
                                "permalink": m.get("permalink", ""),
                            }
                            for m in messages
                        ],
                        "searches_remaining_today": 20 - rl["daily_count"],
                    }
                )
            except Exception as e:
                logger.error(f"SearchMessages error: {e}")
                return json.dumps({"success": False, "error": str(e), "messages": []})

        @method()
        async def GetThreadReplies(self, channel_id: "s", thread_ts: "s", limit: "i") -> "s":
            """
            Get thread replies using the enhanced web client API.

            Returns full message data including:
            - Rich text blocks with formatting
            - Reactions with user lists
            - Edit history
            - Proper pagination

            Args:
                channel_id: Channel containing the thread
                thread_ts: Thread parent timestamp
                limit: Maximum replies to fetch (default 50, max 100)

            Returns:
                JSON with messages array and pagination info
            """
            if not self.daemon.session:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Session not available",
                        "messages": [],
                    }
                )

            try:
                limit = min(max(limit, 1), 100)  # Clamp to 1-100
                result = await self.daemon.session.get_thread_replies_full(channel_id, thread_ts, limit)

                if not result.get("ok"):
                    return json.dumps(
                        {
                            "success": False,
                            "error": result.get("error", "Unknown error"),
                            "messages": [],
                        }
                    )

                return json.dumps(
                    {
                        "success": True,
                        "channel_id": channel_id,
                        "thread_ts": thread_ts,
                        "count": len(result.get("messages", [])),
                        "has_more": result.get("has_more", False),
                        "messages": result.get("messages", []),
                    }
                )
            except Exception as e:
                logger.error(f"GetThreadReplies error: {e}")
                return json.dumps(
                    {
                        "success": False,
                        "error": str(e),
                        "messages": [],
                    }
                )

        @method()
        async def GetThreadContext(self, channel_id: "s", thread_ts: "s") -> "s":
            """
            Get thread context in a simplified format for AI processing.

            Extracts key information from a thread:
            - Parent message with author
            - All replies with authors
            - Mentioned users
            - Links (URLs, MRs, Jira issues)
            - Code blocks
            - Reactions summary

            This is optimized for use with @me commands that need
            to understand thread context (e.g., @me jira, @me cursor).

            Args:
                channel_id: Channel containing the thread
                thread_ts: Thread parent timestamp

            Returns:
                JSON with simplified thread context
            """
            if not self.daemon.session:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Session not available",
                    }
                )

            try:
                result = await self.daemon.session.get_thread_context(channel_id, thread_ts)

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
                        **result,
                    }
                )
            except Exception as e:
                logger.error(f"GetThreadContext error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        async def GetAppCommands(self, summarize: "b") -> "s":
            """
            Get all available slash commands and app actions in the workspace.

            This returns information about:
            - Core Slack commands (/remind, /status, /dnd, etc.)
            - App commands (/jira, /github, /gcal, etc.)
            - App actions (message actions, global shortcuts)

            Useful for discovering what integrations are available and
            what commands can be used.

            Args:
                summarize: If true, return a categorized summary.
                          If false, return the raw API response.

            Returns:
                JSON with commands and actions data
            """
            if not self.daemon.session:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Session not available",
                    }
                )

            try:
                result = await self.daemon.session.get_app_commands()

                if not result.get("ok"):
                    return json.dumps(
                        {
                            "success": False,
                            "error": result.get("error", "Unknown error"),
                        }
                    )

                if summarize:
                    summary = self.daemon.session.get_app_commands_summary(result)
                    return json.dumps(
                        {
                            "success": True,
                            **summary,
                        }
                    )
                else:
                    return json.dumps(
                        {
                            "success": True,
                            "app_actions": result.get("app_actions", []),
                            "commands": result.get("commands", []),
                        }
                    )
            except Exception as e:
                logger.error(f"GetAppCommands error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        async def ListChannelMembers(self, channel_id: "s", count: "i") -> "s":
            """
            List members of a specific channel.

            This uses the Edge API to bypass enterprise restrictions on
            users.list by scoping the request to a specific channel.

            Returns full user profiles including:
            - Name, display name, email, title
            - Avatar URL and hash
            - Status (text and emoji)
            - Timezone
            - Admin/bot flags

            Args:
                channel_id: Channel ID (e.g., C089F16L30T)
                count: Maximum number of members (default 100, max 500)

            Returns:
                JSON with list of channel members
            """
            if not self.daemon.session:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Session not available",
                    }
                )

            try:
                # Clamp count to reasonable limits
                count = max(1, min(count, 500))

                result = await self.daemon.session.list_channel_members_and_cache(channel_id, count)
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
        async def CheckChannelMembership(self, channel_id: "s", user_ids_json: "s") -> "s":
            """
            Check which users from a list are members of a channel.

            This is useful for:
            - Verifying if specific users are in a channel
            - Filtering a user list to only channel members
            - Checking membership before sending targeted messages

            Args:
                channel_id: Channel ID to check membership for
                user_ids_json: JSON array of user IDs to check, e.g. '["U123", "U456"]'

            Returns:
                JSON with channel, members list (only those who are actually members)
            """
            if not self.daemon.session:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Session not available",
                    }
                )

            try:
                # Parse user IDs from JSON
                user_ids = json.loads(user_ids_json)
                if not isinstance(user_ids, list):
                    return json.dumps(
                        {
                            "success": False,
                            "error": "user_ids_json must be a JSON array",
                        }
                    )

                result = await self.daemon.session.check_channel_membership(channel_id, user_ids)

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
                    {
                        "success": False,
                        "error": f"Invalid JSON for user_ids: {e}",
                    }
                )
            except Exception as e:
                logger.error(f"CheckChannelMembership error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        async def GetChannelSections(self, summarize: "b") -> "s":
            """
            Get the user's sidebar channel sections/folders.

            This returns the user's organized sidebar structure including:
            - Custom sections (folders) they've created
            - Channel IDs in each section
            - Section types (standard, stars, direct_messages, etc.)

            This is the proper API alternative to scraping the sidebar HTML
            and provides a complete list of all channels the user has organized.

            Args:
                summarize: If true, return a simplified summary with all channel IDs.
                          If false, return the raw API response.

            Returns:
                JSON with channel sections and channel IDs
            """
            if not self.daemon.session:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Session not available",
                    }
                )

            try:
                result = await self.daemon.session.get_channel_sections()

                if not result.get("ok"):
                    return json.dumps(
                        {
                            "success": False,
                            "error": result.get("error", "Unknown error"),
                        }
                    )

                if summarize:
                    summary = self.daemon.session.get_channel_sections_summary(result)
                    return json.dumps(
                        {
                            "success": True,
                            **summary,
                        }
                    )
                else:
                    return json.dumps(
                        {
                            "success": True,
                            "channel_sections": result.get("channel_sections", []),
                            "last_updated": result.get("last_updated", 0),
                        }
                    )
            except Exception as e:
                logger.error(f"GetChannelSections error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        async def GetChannelHistory(
            self,
            channel_id: "s",
            limit: "i",
            oldest: "s",
            latest: "s",
            simplify: "b",
        ) -> "s":
            """
            Get message history for a channel.

            Fetches messages with full rich text blocks, attachments,
            and thread metadata.

            Args:
                channel_id: Channel ID to fetch history for
                limit: Maximum number of messages (1-100, default 50)
                oldest: Start timestamp - fetch messages after this (empty for no limit)
                latest: End timestamp - fetch messages before this (empty for no limit)
                simplify: If true, return simplified format for AI processing

            Returns:
                JSON with messages list and pagination info
            """
            if not self.daemon.session:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Session not available",
                    }
                )

            try:
                # Clamp limit
                limit = max(1, min(limit or 50, 100))

                result = await self.daemon.session.get_channel_history_rich(
                    channel_id=channel_id,
                    limit=limit,
                    oldest=oldest or "",
                    latest=latest or "",
                )

                if not result.get("ok"):
                    return json.dumps(
                        {
                            "success": False,
                            "error": result.get("error", "Unknown error"),
                        }
                    )

                if simplify:
                    simplified = self.daemon.session.simplify_channel_history(result)
                    return json.dumps(
                        {
                            "success": True,
                            **simplified,
                        }
                    )
                else:
                    return json.dumps(
                        {
                            "success": True,
                            "messages": result.get("messages", []),
                            "has_more": result.get("has_more", False),
                        }
                    )
            except Exception as e:
                logger.error(f"GetChannelHistory error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        def GetCommandList(self) -> "s":
            """Get list of available @me commands with descriptions."""
            try:
                from scripts.common.command_registry import get_registry

                registry = get_registry()
                commands = registry.list_commands()

                result = []
                for cmd in commands:
                    result.append(
                        {
                            "name": cmd.name,
                            "description": cmd.description,
                            "type": cmd.command_type.value,
                            "category": cmd.category,
                            "contextual": cmd.contextual,
                            "examples": cmd.examples[:3] if cmd.examples else [],
                            "inputs": cmd.inputs[:5] if cmd.inputs else [],
                        }
                    )

                return json.dumps({"success": True, "commands": result})
            except Exception as e:
                logger.error(f"GetCommandList error: {e}")
                return json.dumps({"success": False, "error": str(e), "commands": []})

        @method()
        def GetConfig(self) -> "s":
            """Get current Slack daemon configuration."""
            try:
                from scripts.common.config_loader import load_config

                config = load_config()
                slack_config = config.get("slack", {})

                # Extract relevant config sections
                result = {
                    "listener": slack_config.get("listener", {}),
                    "watched_channels": slack_config.get("listener", {}).get("watched_channels", []),
                    "alert_channels": slack_config.get("listener", {}).get("alert_channels", {}),
                    "user_classification": slack_config.get("user_classification", {}),
                    "commands": slack_config.get("commands", {}),
                    "research": slack_config.get("research", {}),
                    "debug_mode": slack_config.get("debug_mode", False),
                }

                return json.dumps({"success": True, "config": result})
            except Exception as e:
                logger.error(f"GetConfig error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        def SetDebugMode(self, enabled: "b") -> "s":
            """Enable or disable debug mode."""
            try:
                if self.daemon:
                    # Update daemon state
                    self.daemon._debug_mode = enabled
                    return json.dumps(
                        {
                            "success": True,
                            "debug_mode": enabled,
                            "message": f"Debug mode {'enabled' if enabled else 'disabled'}",
                        }
                    )
                return json.dumps({"success": False, "error": "Daemon not available"})
            except Exception as e:
                logger.error(f"SetDebugMode error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        # ==================== Background Sync ====================

        @method()
        def GetSyncStatus(self) -> "s":
            """
            Get the status of the background sync process.

            Returns stats on:
            - Channels discovered/synced
            - Users discovered/synced
            - Photos downloaded/cached
            - Rate limiting info
            - Current operation
            """
            try:
                from src.background_sync import get_background_sync

                sync = get_background_sync()
                if not sync:
                    return json.dumps(
                        {
                            "success": False,
                            "error": "Background sync not initialized",
                            "is_running": False,
                        }
                    )

                status = sync.get_status()
                return json.dumps(
                    {
                        "success": True,
                        **status,
                    }
                )
            except ImportError:
                return json.dumps(
                    {
                        "success": False,
                        "error": "Background sync module not available",
                        "is_running": False,
                    }
                )
            except Exception as e:
                logger.error(f"GetSyncStatus error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        async def StartSync(self) -> "s":
            """
            Start the background sync process.

            The sync slowly populates the cache with:
            - Channels from user's sidebar
            - Members from each channel
            - User profile pictures

            Rate limited to ~1 request/second to avoid detection.
            """
            try:
                from src.background_sync import BackgroundSync, SyncConfig, get_background_sync, set_background_sync

                existing = get_background_sync()
                if existing and existing.stats.is_running:
                    return json.dumps(
                        {
                            "success": False,
                            "error": "Background sync already running",
                            "status": existing.get_status(),
                        }
                    )

                if not self.daemon.session or not self.daemon.state_db:
                    return json.dumps(
                        {
                            "success": False,
                            "error": "Slack session or database not available",
                        }
                    )

                # Create and start sync
                config = SyncConfig(
                    min_delay_seconds=1.0,
                    max_delay_seconds=3.0,
                    delay_start_seconds=5.0,  # Short delay for manual start
                )
                sync = BackgroundSync(
                    slack_client=self.daemon.session,
                    state_db=self.daemon.state_db,
                    config=config,
                )
                set_background_sync(sync)
                await sync.start()

                return json.dumps(
                    {
                        "success": True,
                        "message": "Background sync started",
                        "status": sync.get_status(),
                    }
                )
            except Exception as e:
                logger.error(f"StartSync error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        async def StopSync(self) -> "s":
            """Stop the background sync process."""
            try:
                from src.background_sync import get_background_sync

                sync = get_background_sync()
                if not sync:
                    return json.dumps(
                        {
                            "success": False,
                            "error": "Background sync not initialized",
                        }
                    )

                if not sync.stats.is_running:
                    return json.dumps(
                        {
                            "success": False,
                            "error": "Background sync not running",
                        }
                    )

                await sync.stop()

                return json.dumps(
                    {
                        "success": True,
                        "message": "Background sync stopped",
                        "final_stats": sync.stats.to_dict(),
                    }
                )
            except Exception as e:
                logger.error(f"StopSync error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        async def TriggerSync(self, sync_type: "s") -> "s":
            """
            Manually trigger a sync operation.

            Args:
                sync_type: Type of sync - "full", "channels", "users", or "photos"

            Returns:
                Status of the trigger request
            """
            try:
                from src.background_sync import get_background_sync

                sync = get_background_sync()
                if not sync:
                    return json.dumps(
                        {
                            "success": False,
                            "error": "Background sync not initialized",
                        }
                    )

                result = await sync.trigger_sync(sync_type)
                return json.dumps(result)
            except Exception as e:
                logger.error(f"TriggerSync error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        def GetSyncConfig(self) -> "s":
            """Get the background sync configuration."""
            try:
                from src.background_sync import get_background_sync

                sync = get_background_sync()
                if sync:
                    return json.dumps(
                        {
                            "success": True,
                            "config": sync.config.to_dict(),
                        }
                    )

                # Return default config if sync not started
                from src.background_sync import SyncConfig

                default_config = SyncConfig()
                return json.dumps(
                    {
                        "success": True,
                        "config": default_config.to_dict(),
                        "note": "Using default config (sync not started)",
                    }
                )
            except Exception as e:
                logger.error(f"GetSyncConfig error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        def SetSyncConfig(self, config_json: "s") -> "s":
            """
            Update background sync configuration.

            Args:
                config_json: JSON object with config keys to update:
                    - min_delay_seconds: Minimum delay between requests (default 1.0)
                    - max_delay_seconds: Maximum delay for stealth (default 3.0)
                    - download_photos: Whether to download profile photos (default true)
                    - max_members_per_channel: Max members to fetch per channel (default 200)

            Returns:
                Updated configuration
            """
            try:
                from src.background_sync import get_background_sync

                sync = get_background_sync()
                if not sync:
                    return json.dumps(
                        {
                            "success": False,
                            "error": "Background sync not initialized. Start sync first.",
                        }
                    )

                updates = json.loads(config_json)

                # Apply updates to config
                if "min_delay_seconds" in updates:
                    sync.config.min_delay_seconds = float(updates["min_delay_seconds"])
                if "max_delay_seconds" in updates:
                    sync.config.max_delay_seconds = float(updates["max_delay_seconds"])
                if "download_photos" in updates:
                    sync.config.download_photos = bool(updates["download_photos"])
                if "max_members_per_channel" in updates:
                    sync.config.max_members_per_channel = int(updates["max_members_per_channel"])

                return json.dumps(
                    {
                        "success": True,
                        "config": sync.config.to_dict(),
                    }
                )
            except json.JSONDecodeError as e:
                return json.dumps({"success": False, "error": f"Invalid JSON: {e}"})
            except Exception as e:
                logger.error(f"SetSyncConfig error: {e}")
                return json.dumps({"success": False, "error": str(e)})

        @method()
        def GetPhotoPath(self, user_id: "s") -> "s":
            """
            Get the local cached photo path for a user.

            Args:
                user_id: Slack user ID

            Returns:
                Path to cached photo if it exists, or empty string
            """
            try:
                from pathlib import Path

                photo_dir = Path.home() / ".cache" / "aa-workflow" / "photos"
                photo_path = photo_dir / f"{user_id}.jpg"

                if photo_path.exists():
                    return json.dumps(
                        {
                            "success": True,
                            "user_id": user_id,
                            "photo_path": str(photo_path),
                            "exists": True,
                        }
                    )
                else:
                    return json.dumps(
                        {
                            "success": True,
                            "user_id": user_id,
                            "photo_path": "",
                            "exists": False,
                        }
                    )
            except Exception as e:
                logger.error(f"GetPhotoPath error: {e}")
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
            introspection = await self._bus.introspect(DBUS_SERVICE_NAME, DBUS_OBJECT_PATH)
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

    async def send_message(self, channel_id: str, text: str, thread_ts: str = "") -> dict:
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

    async def get_avatar_url(self, user_id: str, avatar_hash: str, size: int = 512) -> dict:
        """Construct a Slack avatar URL from user ID and avatar hash."""
        interface = self._get_interface()
        result = await interface.call_get_avatar_url(user_id, avatar_hash, size)
        return json.loads(result)

    async def get_thread_replies(self, channel_id: str, thread_ts: str, limit: int = 50) -> dict:
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
        result = await interface.call_send_message_rich(channel_id, text, thread_ts, reply_broadcast)
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
        result = await interface.call_get_channel_history(channel_id, limit, oldest, latest, simplify)
        return json.loads(result)

    async def check_channel_membership(
        self,
        channel_id: str,
        user_ids: list[str],
    ) -> dict:
        """Check which users from a list are members of a channel."""
        interface = self._get_interface()
        user_ids_json = json.dumps(user_ids)
        result = await interface.call_check_channel_membership(channel_id, user_ids_json)
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
