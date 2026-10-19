# pylint: disable=duplicate-code
"""Slack Web Client Session Manager.

Manages authenticated sessions to Slack's internal web API using XOXC tokens
and session cookies. This bypasses the official API restrictions by using
the same authentication mechanism as the Slack web client.

IMPORTANT: This approach uses internal APIs and may violate Slack's ToS.
Use responsibly and at your own risk.
"""

import logging
import os
from dataclasses import dataclass
from typing import Any

from tool_modules.aa_slack.src.slack_api_client import RateLimitState, SlackApiClient
from tool_modules.aa_slack.src.slack_message_builder import (
    extract_from_element,
)
from tool_modules.aa_slack.src.slack_session_messaging import SlackSessionMessaging
from tool_modules.aa_slack.src.slack_session_query import SlackSessionQuery

logger = logging.getLogger(__name__)

__all__ = ["RateLimitState", "SlackSession"]


@dataclass
class SlackSession(SlackSessionMessaging, SlackSessionQuery, SlackApiClient):
    """
    Manages a persistent authenticated session to Slack's web API.

    Uses XOXC tokens (internal web tokens) and the d-cookie for authentication,
    mimicking the behavior of the official Slack web client.
    """

    _user_id: str = ""

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
        # Try to load from config.json via ConfigManager
        xoxc_token = ""
        d_cookie = ""
        workspace_id = ""
        enterprise_id = ""

        try:
            # isort: off
            from server.config_manager import (  # pylint: disable=import-outside-toplevel
                config as config_manager,
            )

            # isort: on

            slack_auth = (config_manager.get("slack") or {}).get("auth", {})
            xoxc_token = slack_auth.get("xoxc_token", "")
            d_cookie = slack_auth.get("d_cookie", "")
            workspace_id = slack_auth.get("workspace_id", "")
            enterprise_id = slack_auth.get("enterprise_id", "")
            if xoxc_token and d_cookie:
                logger.info("Loaded Slack credentials from ConfigManager")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.debug("Failed to load config from ConfigManager: %s", e)

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
                # pylint: disable-next=line-too-long
                "Slack xoxc_token not found. Run 'python scripts/get_slack_creds.py' to update config.json, "
                "or set SLACK_XOXC_TOKEN environment variable."
            )

        if not d_cookie:
            raise ValueError(
                # pylint: disable-next=line-too-long
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

    async def _request(self, method, data=None):
        """Authenticated Slack API request with rate-limit handling."""
        return await self.request(method, data)

    def _build_web_api_request(self, api_method, form_parts):
        """Build a web-client URL, multipart body, and headers."""
        url = self.build_web_api_url(api_method)
        parts = [("token", self.xoxc_token), *list(form_parts)]
        content_type, body = self.build_multipart_body(parts)
        headers = {
            "Content-Type": content_type,
            "Origin": "https://app.slack.com",
        }
        return url, body, headers

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
            raise ValueError(f"Session validation failed: {e}") from e

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

        Args:
            types: Comma-separated conversation types (im, mpim, public_channel, private_channel)
            limit: Max results per page (max 999, recommended 200)
            exclude_archived: Exclude archived conversations

        Returns:
            List of conversation objects
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

        Args:
            types: Comma-separated conversation types (im, mpim, public_channel, private_channel)
            limit: Max results

        Returns:
            List of conversation objects
        """
        url, body, headers = self._build_web_api_request(
            "users.conversations",
            [
                ("types", types),
                ("limit", str(limit)),
                ("exclude_archived", "true"),
                ("_x_reason", "conversations-list-fetch"),
                ("_x_mode", "online"),
                ("_x_sonic", "true"),
                ("_x_app_name", "client"),
            ],
        )

        client = await self.get_client()

        try:
            response = await client.post(url, content=body, headers=headers)
            response.raise_for_status()
            data = response.json()

            if not data.get("ok"):
                error = data.get("error", "Unknown error")
                logger.error("User conversations error: %s", error)
                return []

            return data.get("channels", [])

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("User conversations request failed: %s", e)
            return []

    async def get_client_counts(self) -> dict[str, Any]:
        """
        Get client counts including all DMs, MPDMs, and channels.

        This uses the client.counts API which returns unread counts and
        channel IDs for all conversations the user has access to.

        Returns:
            Dict with 'ims' (DMs), 'mpims' (group DMs), and 'channels' arrays
        """
        url, body, headers = self._build_web_api_request(
            "client.counts",
            [
                ("thread_counts_by_channel", "true"),
                ("org_wide_aware", "true"),
                ("include_file_channels", "true"),
                ("include_all_unreads", "true"),
                ("_x_reason", "fetchClientCounts"),
                ("_x_mode", "online"),
                ("_x_sonic", "true"),
                ("_x_app_name", "client"),
            ],
        )

        client = await self.get_client()

        try:
            response = await client.post(url, content=body, headers=headers)
            response.raise_for_status()
            data = response.json()

            if not data.get("ok"):
                error = data.get("error", "Unknown error")
                logger.error("Client counts error: %s", error)
                return {"ok": False, "error": error}

            return {
                "ok": True,
                "ims": data.get("ims", []),
                "mpims": data.get("mpims", []),
                "channels": data.get("channels", []),
            }

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Client counts request failed: %s", e)
            return {"ok": False, "error": str(e)}

    async def get_channel_history(
        self,
        channel_id: str,
        limit: int = 20,
        oldest: str | None = None,
        latest: str | None = None,
        inclusive: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Get message history for a channel.

        Args:
            channel_id: Channel ID (e.g., C12345678)
            limit: Number of messages to return
            oldest: Start of time range (Unix timestamp as string)
            latest: End of time range (Unix timestamp as string)
            inclusive: Include messages at boundary timestamps

        Returns:
            List of message objects
        """
        data = {"channel": channel_id, "limit": limit, "inclusive": inclusive}
        if oldest:
            data["oldest"] = oldest
        if latest:
            data["latest"] = latest

        result = await self._request("conversations.history", data)
        return result.get("messages", [])

    async def get_channel_history_with_cursor(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        channel_id: str,
        limit: int = 200,
        oldest: str | None = None,
        latest: str | None = None,
        cursor: str | None = None,
        inclusive: bool = True,
    ) -> dict[str, Any]:
        """
        Get message history for a channel with cursor-based pagination.

        This method returns the full API response including pagination metadata,
        allowing proper iteration through all messages in a channel.

        Args:
            channel_id: Channel ID (e.g., C12345678)
            limit: Number of messages to return (max 200)
            oldest: Start of time range (Unix timestamp as string)
            latest: End of time range (Unix timestamp as string)
            cursor: Pagination cursor from previous response
            inclusive: Include messages at boundary timestamps

        Returns:
            Full API response dict with:
            - ok: bool
            - messages: list of message objects
            - has_more: bool indicating if more messages exist
            - response_metadata: dict with next_cursor for pagination
        """
        data = {"channel": channel_id, "limit": min(limit, 200), "inclusive": inclusive}
        if oldest:
            data["oldest"] = oldest
        if latest:
            data["latest"] = latest
        if cursor:
            data["cursor"] = cursor

        return await self._request("conversations.history", data)

    async def get_channel_info(self, channel_id: str) -> dict[str, Any] | None:
        """
        Get information about a channel.

        Args:
            channel_id: Channel ID (e.g., C12345678)

        Returns:
            Channel info dict with id, name, purpose, topic, etc.
            Returns None if channel not found or API error.
        """
        try:
            result = await self._request("conversations.info", {"channel": channel_id})
            return result.get("channel")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.debug("Could not get channel info for %s: %s", channel_id, e)
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

        This uses the same multipart/form-data format as the Slack web client,
        which provides more detailed information including:
        - Full message blocks with rich text formatting
        - Reactions with user lists
        - Edit history
        - Proper pagination with cursors

        Args:
            channel_id: Channel containing the thread
            thread_ts: Thread parent timestamp
            limit: Maximum replies to fetch (default 50)
            latest: Latest timestamp to fetch up to (for pagination)
            inclusive: Include the parent message

        Returns:
            Dict with messages, has_more, pagination info, etc.
        """
        form_parts = [
            ("channel", channel_id),
            ("ts", thread_ts),
            ("inclusive", "true" if inclusive else "false"),
            ("limit", str(limit)),
        ]

        if latest:
            form_parts.append(("latest", latest))

        form_parts.extend(
            [
                ("_x_reason", "history-api/fetchReplies"),
                ("_x_mode", "online"),
                ("_x_sonic", "true"),
                ("_x_app_name", "client"),
            ]
        )

        url, body, headers = self._build_web_api_request(
            "conversations.replies", form_parts
        )

        client = await self.get_client()

        try:
            response = await client.post(url, content=body, headers=headers)
            response.raise_for_status()
            data = response.json()

            if not data.get("ok"):
                error = data.get("error", "Unknown error")
                logger.error("Thread replies error: %s", error)
                return {"ok": False, "error": error, "messages": []}

            return {
                "ok": True,
                "messages": data.get("messages", []),
                "has_more": data.get("has_more", False),
                "response_metadata": data.get("response_metadata", {}),
            }

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Thread replies request failed: %s", e)
            return {"ok": False, "error": str(e), "messages": []}

    async def get_thread_context(  # pylint: disable=too-many-locals
        self,
        channel_id: str,
        thread_ts: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        Get thread context in a simplified format for AI processing.

        Extracts key information from a thread:
        - Parent message with author
        - All replies with authors
        - Mentioned users
        - Links (URLs, MRs, Jira issues)
        - Code blocks
        - Reactions summary

        Args:
            channel_id: Channel containing the thread
            thread_ts: Thread parent timestamp
            limit: Maximum replies to fetch

        Returns:
            Simplified thread context dict
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
        participants = set()
        mentioned_users = set()
        links = []
        code_blocks = []
        reactions_summary = {}

        for msg in messages:
            # Track participants
            if msg.get("user"):
                participants.add(msg["user"])

            # Extract mentions from blocks
            for block in msg.get("blocks", []):
                for element in block.get("elements", []):
                    if isinstance(element, dict):
                        self._extract_from_element(
                            element, mentioned_users, links, code_blocks
                        )

            # Collect reactions
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
            "code_blocks": code_blocks[:5],  # Limit code blocks
            "reactions_summary": reactions_summary,
            "messages": simplified_messages,
            "has_more": result.get("has_more", False),
        }

    def _extract_from_element(self, element, mentioned_users, links, code_blocks):
        """Recursively extract mentions, links, and code from rich text."""
        extract_from_element(element, mentioned_users, links, code_blocks)

    # ==================== Message Methods ====================
