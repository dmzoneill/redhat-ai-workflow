"""Slack Web Client Session Manager.

Manages authenticated sessions to Slack's internal web API using XOXC tokens
and session cookies. This bypasses the official API restrictions by using
the same authentication mechanism as the Slack web client.

IMPORTANT: This approach uses internal APIs and may violate Slack's ToS.
Use responsibly and at your own risk.
"""

import asyncio
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

try:
    from . import slack_message_builder as mb
    from .slack_api_client import (  # noqa: F401 — re-export
        RateLimitState,
        SlackApiClient,
    )
except (ImportError, SystemError, TypeError):
    import slack_message_builder as mb  # type: ignore[no-redef]
    from slack_api_client import (  # type: ignore[no-redef]  # noqa: F401
        RateLimitState,
        SlackApiClient,
    )

logger = logging.getLogger(__name__)


@dataclass
class SlackSession:
    """
    Manages a persistent authenticated session to Slack's web API.

    Uses XOXC tokens (internal web tokens) and the d-cookie for authentication,
    mimicking the behavior of the official Slack web client.

    HTTP transport is delegated to :class:`SlackApiClient`; message formatting
    helpers live in :mod:`slack_message_builder`.
    """

    xoxc_token: str
    d_cookie: str
    workspace_id: str = ""
    enterprise_id: str = ""  # Enterprise ID for edge API (e.g., E030G10V24F)

    # Rate limiting configuration
    max_retries: int = 5
    base_backoff: float = 1.0

    # Internal state
    _api: SlackApiClient | None = field(default=None, repr=False)
    _user_id: str = ""

    # Re-export constants so existing callers still work
    USER_AGENT = SlackApiClient.USER_AGENT
    SLACK_HOST = SlackApiClient.SLACK_HOST
    REFERER = SlackApiClient.REFERER
    BASE_URL = SlackApiClient.BASE_URL

    def __post_init__(self):
        """Initialize the API client."""
        self._api = SlackApiClient(
            xoxc_token=self.xoxc_token,
            d_cookie=self.d_cookie,
            workspace_id=self.workspace_id,
            enterprise_id=self.enterprise_id,
            max_retries=self.max_retries,
            base_backoff=self.base_backoff,
        )

    # ------------------------------------------------------------------
    # Lazy-forward properties so callers can reach the underlying client
    # ------------------------------------------------------------------

    @property
    def _rate_limit(self) -> RateLimitState:
        return self._api._rate_limit

    @property
    def _client(self) -> httpx.AsyncClient | None:
        return self._api._client

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "SlackSession":
        """Create session from environment variables."""
        xoxc_token = os.getenv("SLACK_XOXC_TOKEN", "")
        d_cookie = os.getenv("SLACK_D_COOKIE", "")
        workspace_id = os.getenv("SLACK_WORKSPACE_ID", "")
        max_retries = int(os.getenv("SLACK_MAX_RETRIES", "5"))
        base_backoff = float(os.getenv("SLACK_BASE_BACKOFF", "1.0"))

        if not xoxc_token:
            raise ValueError(
                "SLACK_XOXC_TOKEN environment variable is required. "
                "Obtain from browser dev tools while logged into Slack web."
            )

        if not d_cookie:
            raise ValueError(
                "SLACK_D_COOKIE environment variable is required. "
                "Obtain from browser dev tools (Cookie header, 'd' value)."
            )

        return cls(
            xoxc_token=xoxc_token,
            d_cookie=d_cookie,
            workspace_id=workspace_id,
            max_retries=max_retries,
            base_backoff=base_backoff,
        )

    @classmethod
    def from_config(cls) -> "SlackSession":
        """Create session from config.json (preferred) or fall back to environment variables."""
        import json
        from pathlib import Path

        # Try to load from config.json first
        config_paths = [
            Path(__file__).parent.parent.parent.parent.parent
            / "config.json",  # tool_modules/aa_slack/src -> project root
            Path.cwd() / "config.json",
            Path.home() / "src" / "redhat-ai-workflow" / "config.json",
        ]

        xoxc_token = ""
        d_cookie = ""
        workspace_id = ""
        enterprise_id = ""

        for config_path in config_paths:
            if config_path.exists():
                try:
                    with open(config_path) as f:
                        config = json.load(f)
                    slack_auth = config.get("slack", {}).get("auth", {})
                    xoxc_token = slack_auth.get("xoxc_token", "")
                    d_cookie = slack_auth.get("d_cookie", "")
                    workspace_id = slack_auth.get("workspace_id", "")
                    enterprise_id = slack_auth.get("enterprise_id", "")
                    if xoxc_token and d_cookie:
                        logger.info(f"Loaded Slack credentials from {config_path}")
                        break
                except Exception as e:
                    logger.debug(f"Failed to load config from {config_path}: {e}")

        # Fall back to environment variables if config.json doesn't have tokens
        if not xoxc_token:
            xoxc_token = os.getenv("SLACK_XOXC_TOKEN", "")
        if not d_cookie:
            d_cookie = os.getenv("SLACK_D_COOKIE", "")
        if not workspace_id:
            workspace_id = os.getenv("SLACK_WORKSPACE_ID", "")
        if not enterprise_id:
            enterprise_id = os.getenv("SLACK_ENTERPRISE_ID", "")

        if not xoxc_token:
            raise ValueError(
                "Slack xoxc_token not found. Run 'python scripts/get_slack_creds.py' to update config.json, "
                "or set SLACK_XOXC_TOKEN environment variable."
            )

        if not d_cookie:
            raise ValueError(
                "Slack d_cookie not found. Run 'python scripts/get_slack_creds.py' to update config.json, "
                "or set SLACK_D_COOKIE environment variable."
            )

        max_retries = int(os.getenv("SLACK_MAX_RETRIES", "5"))
        base_backoff = float(os.getenv("SLACK_BASE_BACKOFF", "1.0"))

        return cls(
            xoxc_token=xoxc_token,
            d_cookie=d_cookie,
            workspace_id=workspace_id,
            enterprise_id=enterprise_id,
            max_retries=max_retries,
            base_backoff=base_backoff,
        )

    # ------------------------------------------------------------------
    # Client lifecycle (delegated)
    # ------------------------------------------------------------------

    async def get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        return await self._api.get_client()

    async def close(self):
        """Close the HTTP client."""
        await self._api.close()

    async def _request(
        self,
        method: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated request to the Slack API with rate limit handling."""
        return await self._api.request(method, data)

    # ------------------------------------------------------------------
    # Session validation
    # ------------------------------------------------------------------

    async def validate_session(self) -> dict[str, Any]:
        """
        Validate the current session by calling auth.test.

        Returns:
            User info including user_id, team_id, etc.

        Raises:
            ValueError: If session is invalid or expired
        """
        try:
            result = await self._request("auth.test")
            self._user_id = result.get("user_id", "")
            return result
        except Exception as e:
            raise ValueError(f"Session validation failed: {e}")

    @property
    def user_id(self) -> str:
        """Get the authenticated user's ID."""
        return self._user_id

    # ==================== Channel/Conversation Methods ====================

    async def get_conversations_list(
        self,
        types: str = "public_channel,private_channel,mpim,im",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get list of conversations (channels, DMs, etc.)."""
        result = await self._request(
            "conversations.list", {"types": types, "limit": limit}
        )
        return result.get("channels", [])

    async def get_user_conversations(
        self,
        types: str = "im,mpim",
        limit: int = 200,
        exclude_archived: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Get list of conversations the user is a member of.

        This uses users.conversations which may work when conversations.list is blocked.
        """
        data = {
            "types": types,
            "limit": limit,
            "exclude_archived": exclude_archived,
        }
        result = await self._request("users.conversations", data)
        return result.get("channels", [])

    async def get_user_conversations_web(
        self,
        types: str = "im,mpim",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """
        Get list of conversations using web client API format.

        This uses the same multipart form-data format as the web client,
        which may bypass enterprise restrictions.
        """
        parts = [
            ("types", types),
            ("limit", str(limit)),
            ("exclude_archived", "true"),
        ]

        try:
            data = await self._api.web_api_request(
                "users.conversations", parts, x_reason="conversations-list-fetch"
            )

            if not data.get("ok"):
                error = data.get("error", "Unknown error")
                logger.error(f"User conversations error: {error}")
                return []

            return data.get("channels", [])

        except Exception as e:
            logger.error(f"User conversations request failed: {e}")
            return []

    async def get_client_counts(self) -> dict[str, Any]:
        """
        Get client counts including all DMs, MPDMs, and channels.

        Returns:
            Dict with 'ims' (DMs), 'mpims' (group DMs), and 'channels' arrays
        """
        parts = [
            ("thread_counts_by_channel", "true"),
            ("org_wide_aware", "true"),
            ("include_file_channels", "true"),
            ("include_all_unreads", "true"),
        ]

        try:
            data = await self._api.web_api_request(
                "client.counts", parts, x_reason="fetchClientCounts"
            )

            if not data.get("ok"):
                error = data.get("error", "Unknown error")
                logger.error(f"Client counts error: {error}")
                return {"ok": False, "error": error}

            return {
                "ok": True,
                "ims": data.get("ims", []),
                "mpims": data.get("mpims", []),
                "channels": data.get("channels", []),
            }

        except Exception as e:
            logger.error(f"Client counts request failed: {e}")
            return {"ok": False, "error": str(e)}

    async def get_channel_history(
        self,
        channel_id: str,
        limit: int = 20,
        oldest: str | None = None,
        latest: str | None = None,
        inclusive: bool = True,
    ) -> list[dict[str, Any]]:
        """Get message history for a channel."""
        data: dict[str, Any] = {
            "channel": channel_id,
            "limit": limit,
            "inclusive": inclusive,
        }
        if oldest:
            data["oldest"] = oldest
        if latest:
            data["latest"] = latest

        result = await self._request("conversations.history", data)
        return result.get("messages", [])

    async def get_channel_history_with_cursor(
        self,
        channel_id: str,
        limit: int = 200,
        oldest: str | None = None,
        latest: str | None = None,
        cursor: str | None = None,
        inclusive: bool = True,
    ) -> dict[str, Any]:
        """Get message history for a channel with cursor-based pagination."""
        data: dict[str, Any] = {
            "channel": channel_id,
            "limit": min(limit, 200),
            "inclusive": inclusive,
        }
        if oldest:
            data["oldest"] = oldest
        if latest:
            data["latest"] = latest
        if cursor:
            data["cursor"] = cursor

        return await self._request("conversations.history", data)

    async def get_channel_info(self, channel_id: str) -> dict[str, Any] | None:
        """Get information about a channel."""
        try:
            result = await self._request("conversations.info", {"channel": channel_id})
            return result.get("channel")
        except Exception as e:
            logger.debug(f"Could not get channel info for {channel_id}: {e}")
            return None

    async def get_thread_replies(
        self,
        channel_id: str,
        thread_ts: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get replies in a thread (basic API)."""
        result = await self._request(
            "conversations.replies",
            {"channel": channel_id, "ts": thread_ts, "limit": limit},
        )
        return result.get("messages", [])

    async def get_thread_replies_full(
        self,
        channel_id: str,
        thread_ts: str,
        limit: int = 50,
        latest: str | None = None,
        inclusive: bool = True,
    ) -> dict[str, Any]:
        """
        Get thread replies using the web client API format.

        Provides full message blocks with rich text formatting, reactions,
        edit history, and proper pagination with cursors.
        """
        parts = [
            ("channel", channel_id),
            ("ts", thread_ts),
            ("inclusive", "true" if inclusive else "false"),
            ("limit", str(limit)),
        ]

        if latest:
            parts.append(("latest", latest))

        try:
            data = await self._api.web_api_request(
                "conversations.replies", parts, x_reason="history-api/fetchReplies"
            )

            if not data.get("ok"):
                error = data.get("error", "Unknown error")
                logger.error(f"Thread replies error: {error}")
                return {"ok": False, "error": error, "messages": []}

            return {
                "ok": True,
                "messages": data.get("messages", []),
                "has_more": data.get("has_more", False),
                "response_metadata": data.get("response_metadata", {}),
            }

        except Exception as e:
            logger.error(f"Thread replies request failed: {e}")
            return {"ok": False, "error": str(e), "messages": []}

    async def get_thread_context(
        self,
        channel_id: str,
        thread_ts: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        Get thread context in a simplified format for AI processing.

        Extracts key information from a thread including participants,
        mentioned users, links, code blocks, and reactions.
        """
        result = await self.get_thread_replies_full(channel_id, thread_ts, limit)

        if not result.get("ok") or not result.get("messages"):
            return {
                "ok": False,
                "error": result.get("error", "No messages"),
                "thread_ts": thread_ts,
                "channel_id": channel_id,
            }

        messages = result["messages"]
        parent = messages[0] if messages else {}
        replies = messages[1:] if len(messages) > 1 else []

        # Extract participants
        participants: set[str] = set()
        mentioned_users: set[str] = set()
        links: list[str] = []
        code_blocks: list[str] = []
        reactions_summary: dict[str, int] = {}

        for msg in messages:
            if msg.get("user"):
                participants.add(msg["user"])

            for block in msg.get("blocks", []):
                for element in block.get("elements", []):
                    if isinstance(element, dict):
                        mb.extract_from_element(
                            element, mentioned_users, links, code_blocks
                        )

            for reaction in msg.get("reactions", []):
                name = reaction.get("name", "")
                count = reaction.get("count", 0)
                if name in reactions_summary:
                    reactions_summary[name] += count
                else:
                    reactions_summary[name] = count

        # Build simplified messages
        simplified_messages = []
        for msg in messages:
            simplified_messages.append(
                {
                    "user": msg.get("user", ""),
                    "text": msg.get("text", ""),
                    "ts": msg.get("ts", ""),
                    "is_parent": msg.get("ts") == thread_ts,
                    "edited": bool(msg.get("edited")),
                    "reactions": [r.get("name") for r in msg.get("reactions", [])],
                }
            )

        return {
            "ok": True,
            "thread_ts": thread_ts,
            "channel_id": channel_id,
            "reply_count": parent.get("reply_count", len(replies)),
            "participants": list(participants),
            "mentioned_users": list(mentioned_users),
            "links": links,
            "code_blocks": code_blocks[:5],
            "reactions_summary": reactions_summary,
            "messages": simplified_messages,
            "has_more": result.get("has_more", False),
        }

    def _extract_from_element(
        self,
        element: dict,
        mentioned_users: set,
        links: list,
        code_blocks: list,
    ) -> None:
        """Recursively extract data from rich text elements."""
        mb.extract_from_element(element, mentioned_users, links, code_blocks)

    # ==================== Message Methods ====================

    async def send_message(
        self,
        channel_id: str,
        text: str,
        thread_ts: str | None = None,
        typing_delay: bool = True,
    ) -> dict[str, Any]:
        """Send a message to a channel."""
        if typing_delay:
            delay = random.uniform(0.5, 2.5)
            logger.debug(f"Adding natural typing delay: {delay:.2f}s")
            await asyncio.sleep(delay)

        data: dict[str, Any] = {"channel": channel_id, "text": text}
        if thread_ts:
            data["thread_ts"] = thread_ts

        result = await self._request("chat.postMessage", data)
        return result

    async def send_message_rich(
        self,
        channel_id: str,
        text: str,
        thread_ts: str | None = None,
        reply_broadcast: bool = False,
        typing_delay: bool = True,
    ) -> dict[str, Any]:
        """
        Send a message using the web client API format with rich text blocks.
        """
        if typing_delay:
            delay = random.uniform(0.5, 2.5)
            logger.debug(f"Adding natural typing delay: {delay:.2f}s")
            await asyncio.sleep(delay)

        import uuid

        # Generate unique IDs
        client_msg_id = str(uuid.uuid4())
        draft_id = str(uuid.uuid4())
        msg_ts = f"{int(time.time())}.{random.randint(100000, 999999)}"

        # Build rich text blocks from plain text
        blocks = mb.text_to_rich_blocks(text)

        parts = [
            ("channel", channel_id),
            ("ts", msg_ts),
            ("type", "message"),
            ("xArgs", json.dumps({"draft_id": draft_id})),
            ("reply_broadcast", "true" if reply_broadcast else "false"),
        ]

        if thread_ts:
            parts.append(("thread_ts", thread_ts))

        parts.extend(
            [
                ("unfurl", "[]"),
                ("blocks", json.dumps(blocks)),
                ("draft_id", draft_id),
                ("include_channel_perm_error", "true"),
                ("client_msg_id", client_msg_id),
            ]
        )

        try:
            data = await self._api.web_api_request(
                "chat.postMessage", parts, x_reason="webapp_message_send"
            )

            if not data.get("ok"):
                error = data.get("error", "Unknown error")
                logger.error(f"Send message error: {error}")
                return {"ok": False, "error": error}

            return {
                "ok": True,
                "channel": data.get("channel", channel_id),
                "ts": data.get("ts", ""),
                "message": data.get("message", {}),
            }

        except Exception as e:
            logger.error(f"Send message request failed: {e}")
            return {"ok": False, "error": str(e)}

    def _text_to_rich_blocks(self, text: str) -> list[dict[str, Any]]:
        """Convert plain text to Slack rich text blocks."""
        return mb.text_to_rich_blocks(text)

    def _parse_inline_elements(self, text: str) -> list[dict[str, Any]]:
        """Parse inline elements from text."""
        return mb.parse_inline_elements(text)

    async def add_reaction(
        self,
        channel_id: str,
        timestamp: str,
        emoji: str,
    ) -> dict[str, Any]:
        """Add a reaction to a message."""
        return await self._request(
            "reactions.add",
            {"channel": channel_id, "timestamp": timestamp, "name": emoji},
        )

    # ==================== DM Methods ====================

    async def open_dm(self, user_id: str) -> str:
        """Open a DM channel with a user."""
        result = await self._request("conversations.open", {"users": user_id})
        channel = result.get("channel", {})
        return channel.get("id", "")

    async def send_dm(
        self,
        user_id: str,
        text: str,
        typing_delay: bool = True,
    ) -> dict[str, Any]:
        """Send a direct message to a user."""
        dm_channel = await self.open_dm(user_id)
        if not dm_channel:
            raise ValueError(f"Could not open DM with user {user_id}")

        return await self.send_message(
            channel_id=dm_channel,
            text=text,
            typing_delay=typing_delay,
        )

    # ==================== User Methods ====================

    async def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Get information about a user."""
        result = await self._request("users.info", {"user": user_id})
        return result.get("user", {})

    async def get_users_list(self, limit: int = 200) -> list[dict[str, Any]]:
        """Get list of all users in workspace."""
        result = await self._request("users.list", {"limit": limit})
        return result.get("members", [])

    # ==================== Search Methods ====================

    async def search_messages(
        self,
        query: str,
        count: int = 20,
        sort: str = "timestamp",
        sort_dir: str = "desc",
    ) -> list[dict[str, Any]]:
        """Search for messages."""
        result = await self._request(
            "search.messages",
            {"query": query, "count": count, "sort": sort, "sort_dir": sort_dir},
        )
        return result.get("messages", {}).get("matches", [])

    async def search_channels(
        self,
        query: str,
        count: int = 30,
        include_archived: bool = False,
        check_membership: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Search for channels using Slack's edge API.
        """
        payload = {
            "query": query,
            "count": count,
            "fuzz": 1,
            "uax29_tokenizer": False,
            "include_record_channels": True,
            "check_membership": check_membership,
        }

        try:
            result = await self._api.edge_api_request("channels/search", payload)
            channels = result.get("results", [])

            if not include_archived:
                channels = [c for c in channels if not c.get("is_archived", False)]

            return channels
        except Exception as e:
            logger.error(f"Channel search error: {e}")
            raise

    def _extract_enterprise_id(self) -> str:
        """Try to extract enterprise ID from the xoxc token or other sources."""
        return self._api._extract_enterprise_id()

    def get_avatar_url(self, user_id: str, avatar_hash: str, size: int = 512) -> str:
        """Construct a Slack avatar URL from user ID and avatar hash."""
        return mb.get_avatar_url(
            user_id,
            avatar_hash,
            size,
            enterprise_id=self.enterprise_id,
            workspace_id=self.workspace_id,
        )

    def extract_avatar_hash(self, profile: dict[str, Any]) -> str:
        """Extract avatar hash from a user profile."""
        return mb.extract_avatar_hash(profile)

    async def search_channels_and_cache(
        self,
        query: str,
        count: int = 30,
    ) -> dict[str, Any]:
        """Search for channels and return results in a format suitable for caching."""
        try:
            channels = await self.search_channels(query, count)

            results = []
            for ch in channels:
                results.append(
                    {
                        "channel_id": ch.get("id", ""),
                        "name": ch.get("name", ""),
                        "display_name": ch.get("name_normalized", ch.get("name", "")),
                        "is_private": ch.get("is_private", False),
                        "is_archived": ch.get("is_archived", False),
                        "is_member": ch.get("is_member", False),
                        "purpose": ch.get("purpose", {}).get("value", ""),
                        "topic": ch.get("topic", {}).get("value", ""),
                        "num_members": ch.get("num_members", 0),
                        "created": ch.get("created", 0),
                    }
                )

            return {
                "success": True,
                "query": query,
                "count": len(results),
                "channels": results,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "query": query,
                "channels": [],
            }

    async def search_users(
        self,
        query: str,
        count: int = 30,
        include_deactivated: bool = False,
    ) -> list[dict[str, Any]]:
        """Search for users using Slack's edge API."""
        user_filter = "" if include_deactivated else "NOT deactivated"

        payload = {
            "query": query,
            "count": count,
            "fuzz": 1,
            "uax29_tokenizer": False,
            "include_profile_only_users": True,
            "enable_workspace_ranking": True,
            "filter": user_filter,
        }

        try:
            result = await self._api.edge_api_request("users/search", payload)
            return result.get("results", [])
        except Exception as e:
            logger.error(f"User search error: {e}")
            raise

    async def list_channel_members(
        self,
        channel_id: str,
        count: int = 100,
        include_bots: bool = False,
        present_first: bool = True,
    ) -> list[dict[str, Any]]:
        """List members of a specific channel using the Edge API."""
        if include_bots:
            user_filter = "everyone"
        else:
            user_filter = "everyone AND NOT bots AND NOT apps"

        payload = {
            "channels": [channel_id],
            "present_first": present_first,
            "filter": user_filter,
            "count": count,
        }

        try:
            result = await self._api.edge_api_request("users/list", payload)

            if not result.get("ok"):
                error = result.get("error", "Unknown error")
                logger.error(f"Channel members list error: {error}")
                raise ValueError(f"Channel members list failed: {error}")

            return result.get("results", [])
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Channel members list error: {e}")
            raise

    async def check_channel_membership(
        self,
        channel_id: str,
        user_ids: list[str],
    ) -> dict[str, Any]:
        """Check which users from a list are members of a channel."""
        payload = {
            "channel": channel_id,
            "users": user_ids,
            "as_admin": False,
        }

        try:
            result = await self._api.edge_api_request("channels/membership", payload)

            if not result.get("ok"):
                error = result.get("error", "Unknown error")
                logger.error(f"Channel membership check error: {error}")
                return {"ok": False, "error": error, "members": []}

            return {
                "ok": True,
                "channel": result.get("channel", channel_id),
                "members": result.get("members", []),
                "checked_count": len(user_ids),
                "member_count": len(result.get("members", [])),
            }
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Channel membership check error: {e}")
            raise

    async def list_channel_members_and_cache(
        self,
        channel_id: str,
        count: int = 100,
    ) -> dict[str, Any]:
        """List channel members and return in a format suitable for caching."""
        try:
            users = await self.list_channel_members(channel_id, count)

            results = []
            for u in users:
                user_id = u.get("id", "")
                profile = u.get("profile", {})

                avatar_hash = self.extract_avatar_hash(profile)
                if avatar_hash and user_id:
                    avatar_url = self.get_avatar_url(user_id, avatar_hash, 512)
                else:
                    avatar_url = profile.get(
                        "image_original", profile.get("image_72", "")
                    )

                results.append(
                    {
                        "user_id": user_id,
                        "user_name": u.get("name", ""),
                        "display_name": profile.get("display_name", ""),
                        "real_name": profile.get("real_name", ""),
                        "email": profile.get("email", ""),
                        "title": profile.get("title", ""),
                        "avatar_url": avatar_url,
                        "avatar_hash": avatar_hash,
                        "pronouns": profile.get("pronouns", ""),
                        "status_text": profile.get("status_text", ""),
                        "status_emoji": profile.get("status_emoji", ""),
                        "is_bot": u.get("is_bot", False),
                        "is_admin": u.get("is_admin", False),
                        "deleted": u.get("deleted", False),
                        "tz": u.get("tz", ""),
                        "tz_label": u.get("tz_label", ""),
                    }
                )

            return {
                "success": True,
                "channel_id": channel_id,
                "count": len(results),
                "users": results,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "channel_id": channel_id,
                "users": [],
            }

    async def get_channel_sections(self) -> dict[str, Any]:
        """Get the user's sidebar channel sections/folders."""
        try:
            data = await self._api.web_api_request(
                "users.channelSections.list", [], x_reason="conditional-fetch-manager"
            )

            if not data.get("ok"):
                error = data.get("error", "Unknown error")
                logger.error(f"Channel sections error: {error}")
                return {"ok": False, "error": error, "channel_sections": []}

            return {
                "ok": True,
                "channel_sections": data.get("channel_sections", []),
                "last_updated": data.get("last_updated", 0),
                "count": data.get("count", 0),
            }

        except Exception as e:
            logger.error(f"Channel sections request failed: {e}")
            return {"ok": False, "error": str(e), "channel_sections": []}

    def get_channel_sections_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        """Summarize channel sections into a more usable format."""
        return mb.get_channel_sections_summary(data)

    async def get_channel_history_rich(
        self,
        channel_id: str,
        limit: int = 50,
        oldest: str = "",
        latest: str = "",
        ignore_replies: bool = True,
    ) -> dict[str, Any]:
        """Get message history for a channel with rich data (web API version)."""
        limit = max(1, min(limit, 100))

        parts = [
            ("channel", channel_id),
            ("limit", str(limit)),
            ("ignore_replies", "true" if ignore_replies else "false"),
            ("include_pin_count", "false"),
            ("inclusive", "true"),
            ("no_user_profile", "true"),
            ("include_stories", "true"),
        ]

        if oldest:
            parts.append(("oldest", oldest))
        if latest:
            parts.append(("latest", latest))

        try:
            data = await self._api.web_api_request(
                "conversations.history", parts, x_reason="channel-history-fetch"
            )

            if not data.get("ok"):
                error = data.get("error", "Unknown error")
                logger.error(f"Channel history error: {error}")
                return {"ok": False, "error": error, "messages": []}

            return {
                "ok": True,
                "messages": data.get("messages", []),
                "has_more": data.get("has_more", False),
                "oldest": data.get("oldest", ""),
                "latest": data.get("latest", ""),
            }

        except Exception as e:
            logger.error(f"Channel history request failed: {e}")
            return {"ok": False, "error": str(e), "messages": []}

    def simplify_channel_history(self, data: dict[str, Any]) -> dict[str, Any]:
        """Simplify channel history into a more usable format."""
        return mb.simplify_channel_history(data)

    def _extract_from_block_element(
        self,
        element: dict[str, Any],
        mentions: list[str],
        links: list[str],
    ) -> None:
        """Recursively extract mentions and links from block elements."""
        mb.extract_from_block_element(element, mentions, links)

    async def search_users_and_cache(
        self,
        query: str,
        count: int = 30,
    ) -> dict[str, Any]:
        """Search for users and return results in a format suitable for caching."""
        try:
            users = await self.search_users(query, count)

            results = []
            for u in users:
                user_id = u.get("id", "")
                profile = u.get("profile", {})

                avatar_hash = self.extract_avatar_hash(profile)
                if avatar_hash and user_id:
                    avatar_url = self.get_avatar_url(user_id, avatar_hash, 512)
                else:
                    avatar_url = profile.get(
                        "image_original", profile.get("image_72", "")
                    )

                results.append(
                    {
                        "user_id": user_id,
                        "user_name": u.get("name", ""),
                        "display_name": profile.get("display_name", ""),
                        "real_name": profile.get("real_name", ""),
                        "email": profile.get("email", ""),
                        "title": profile.get("title", ""),
                        "avatar_url": avatar_url,
                        "avatar_hash": avatar_hash,
                        "pronouns": profile.get("pronouns", ""),
                        "is_bot": u.get("is_bot", False),
                        "is_admin": u.get("is_admin", False),
                        "deleted": u.get("deleted", False),
                        "tz": u.get("tz", ""),
                    }
                )

            return {
                "success": True,
                "query": query,
                "count": len(results),
                "users": results,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "query": query,
                "users": [],
            }

    async def get_app_commands(self) -> dict[str, Any]:
        """Get all available slash commands and app actions in the workspace."""
        try:
            data = await self._api.web_api_request(
                "client.appCommands", [], x_reason="set-model-data"
            )

            if not data.get("ok"):
                error = data.get("error", "Unknown error")
                logger.error(f"App commands error: {error}")
                return {"ok": False, "error": error, "app_actions": [], "commands": []}

            return {
                "ok": True,
                "app_actions": data.get("app_actions", []),
                "commands": data.get("commands", []),
                "cache_ts": data.get("cache_ts", ""),
            }

        except Exception as e:
            logger.error(f"App commands request failed: {e}")
            return {"ok": False, "error": str(e), "app_actions": [], "commands": []}

    def get_app_commands_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        """Summarize app commands data into a more usable format."""
        return mb.get_app_commands_summary(data)

    async def get_user_profile_sections(self, user_id: str) -> dict[str, Any]:
        """Get detailed user profile with sections (contact info, about me, etc.)."""
        parts = [
            ("user", user_id),
        ]

        try:
            result = await self._api.web_api_request(
                "users.profile.getSections", parts, x_reason="profiles"
            )

            if not result.get("ok"):
                error = result.get("error", "unknown_error")
                raise ValueError(f"Profile API error: {error}")

            return result

        except httpx.HTTPStatusError as e:
            logger.error(f"Profile API error: {e.response.status_code}")
            raise ValueError(f"Profile fetch failed: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Profile fetch error: {e}")
            raise

    async def get_user_profile_details(self, user_id: str) -> dict[str, Any]:
        """Get user profile details in a simplified format."""
        try:
            result = await self.get_user_profile_sections(user_id)

            data = result.get("result", {}).get("data", {})
            user_data = data.get("user", {})
            sections = user_data.get("profileSections", [])

            profile: dict[str, Any] = {
                "user_id": user_id,
                "sections": {},
            }

            for section in sections:
                section_type = section.get("type", "")
                section_label = section.get("label", "")
                elements = section.get("profileElements", [])

                section_data: dict[str, Any] = {
                    "label": section_label,
                    "fields": {},
                }

                for elem in elements:
                    key = elem.get("elementKey", elem.get("label", "unknown"))
                    label = elem.get("label", key)

                    if elem.get("type") == "TEXT":
                        value = elem.get("text", "")
                    elif elem.get("type") == "RICH_TEXT":
                        value = elem.get("richText", {}).get("text", "")
                    else:
                        value = elem.get("text", elem.get("value", ""))

                    if value:
                        section_data["fields"][key] = {
                            "label": label,
                            "value": value,
                        }

                if section_data["fields"]:
                    profile["sections"][section_type] = section_data

            contact = profile["sections"].get("CONTACT", {}).get("fields", {})
            header = profile["sections"].get("HEADER", {}).get("fields", {})

            profile["email"] = contact.get("email", {}).get("value", "")
            profile["phone"] = contact.get("phone", {}).get("value", "")
            profile["title"] = header.get("title", {}).get("value", "")

            return {
                "success": True,
                "user_id": user_id,
                "profile": profile,
            }

        except Exception as e:
            return {
                "success": False,
                "user_id": user_id,
                "error": str(e),
                "profile": {},
            }
