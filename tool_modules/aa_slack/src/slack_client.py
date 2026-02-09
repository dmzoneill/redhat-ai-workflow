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
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class RateLimitState:
    """Tracks rate limit backoff state."""

    retry_count: int = 0
    last_429_time: float = 0
    backoff_until: float = 0


@dataclass
class SlackSession:
    """
    Manages a persistent authenticated session to Slack's web API.

    Uses XOXC tokens (internal web tokens) and the d-cookie for authentication,
    mimicking the behavior of the official Slack web client.
    """

    xoxc_token: str
    d_cookie: str
    workspace_id: str = ""
    enterprise_id: str = ""  # Enterprise ID for edge API (e.g., E030G10V24F)

    # Rate limiting configuration
    max_retries: int = 5
    base_backoff: float = 1.0

    # Internal state
    _client: httpx.AsyncClient | None = field(default=None, repr=False)
    _rate_limit: RateLimitState = field(default_factory=RateLimitState)
    _user_id: str = ""

    # High-fidelity spoofing headers - updated to match current Chrome
    USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/143.0.0.0 Safari/537.36"
    )

    # Enterprise Slack URLs - configurable via environment
    SLACK_HOST = os.getenv("SLACK_HOST", "redhat.enterprise.slack.com")
    REFERER = f"https://{SLACK_HOST}/"

    # API endpoint - enterprise still uses slack.com/api
    BASE_URL = "https://slack.com/api"

    def __post_init__(self):
        """Initialize the HTTP client."""
        self._client = None
        self._rate_limit = RateLimitState()

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
            from server.config_manager import config as config_manager

            slack_auth = (config_manager.get("slack") or {}).get("auth", {})
            xoxc_token = slack_auth.get("xoxc_token", "")
            d_cookie = slack_auth.get("d_cookie", "")
            workspace_id = slack_auth.get("workspace_id", "")
            enterprise_id = slack_auth.get("enterprise_id", "")
            if xoxc_token and d_cookie:
                logger.info("Loaded Slack credentials from ConfigManager")
        except Exception as e:
            logger.debug(f"Failed to load config from ConfigManager: {e}")

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

    async def get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": self.USER_AGENT,
                    "Referer": self.REFERER,
                    "Accept": "application/json",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": f"https://{self.SLACK_HOST}",
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-site",
                },
                cookies={"d": self.d_cookie},
                timeout=30.0,
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Make an authenticated request to the Slack API with rate limit handling.

        Args:
            method: Slack API method name (e.g., "conversations.history")
            data: Request payload

        Returns:
            API response as dict

        Raises:
            httpx.HTTPStatusError: On HTTP errors
            ValueError: On Slack API errors
        """
        # Check if we're in backoff
        if time.time() < self._rate_limit.backoff_until:
            wait_time = self._rate_limit.backoff_until - time.time()
            logger.warning(f"Rate limited, waiting {wait_time:.1f}s before retry")
            await asyncio.sleep(wait_time)

        url = f"{self.BASE_URL}/{method}"
        payload = data or {}
        payload["token"] = self.xoxc_token

        client = await self.get_client()

        for attempt in range(self.max_retries):
            try:
                response = await client.post(url, data=payload)

                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    self._rate_limit.retry_count += 1

                    # Exponential backoff with jitter
                    backoff = min(
                        retry_after,
                        self.base_backoff * (2**attempt) + random.uniform(0, 1),
                    )
                    self._rate_limit.backoff_until = time.time() + backoff

                    logger.warning(
                        f"Rate limited (429). Attempt {attempt + 1}/{self.max_retries}. "
                        f"Backing off {backoff:.1f}s"
                    )

                    await asyncio.sleep(backoff)
                    continue

                response.raise_for_status()
                result = response.json()

                # Reset rate limit state on success
                self._rate_limit.retry_count = 0

                # Check Slack-level errors
                if not result.get("ok", False):
                    error = result.get("error", "unknown_error")

                    # Handle specific errors
                    if error == "invalid_auth":
                        raise ValueError(
                            "Invalid authentication. XOXC_TOKEN or D_COOKIE may be expired. "
                            "Re-obtain from browser dev tools."
                        )
                    elif error == "token_revoked":
                        raise ValueError(
                            "Token has been revoked. Re-authenticate via browser."
                        )
                    elif error == "ratelimited":
                        # Slack-level rate limiting
                        await asyncio.sleep(self.base_backoff * (2**attempt))
                        continue
                    else:
                        raise ValueError(f"Slack API error: {error}")

                return result

            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500 and attempt < self.max_retries - 1:
                    # Server error, retry with backoff
                    await asyncio.sleep(self.base_backoff * (2**attempt))
                    continue
                raise

        raise ValueError(f"Max retries ({self.max_retries}) exceeded for {method}")

    def _build_web_api_request(
        self,
        api_method: str,
        form_parts: list[tuple[str, str]],
    ) -> tuple[str, str, dict[str, str]]:
        """Build a web-client-style API request with multipart form data.

        Many internal Slack APIs require the same URL format and multipart
        encoding. This helper constructs all three components.

        Args:
            api_method: Slack API method (e.g. "users.conversations")
            form_parts: List of (name, value) tuples for the form body.
                        The token is prepended automatically.

        Returns:
            (url, body, headers) tuple ready for client.post().
        """
        eid = self.enterprise_id or self.workspace_id or self._extract_enterprise_id()
        x_id = f"{uuid.uuid4().hex[:8]}-{int(time.time())}.{random.randint(100, 999)}"

        url = (
            f"https://{self.SLACK_HOST}/api/{api_method}"
            f"?_x_id={x_id}"
            f"&slack_route={eid}%3A{eid}"
            "&_x_gantry=true"
            "&fp=14"
            "&_x_num_retries=0"
        )

        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"
        all_parts = [("token", self.xoxc_token)] + form_parts

        body_lines: list[str] = []
        for name, value in all_parts:
            body_lines.append(f"--{boundary}")
            body_lines.append(f'Content-Disposition: form-data; name="{name}"')
            body_lines.append("")
            body_lines.append(value)
        body_lines.append(f"--{boundary}--")
        body_lines.append("")

        body = "\r\n".join(body_lines)
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
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
                logger.error(f"User conversations error: {error}")
                return []

            return data.get("channels", [])

        except Exception as e:
            logger.error(f"User conversations request failed: {e}")
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

    async def get_channel_history_with_cursor(
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

    def _extract_from_element(
        self,
        element: dict,
        mentioned_users: set,
        links: list,
        code_blocks: list,
    ) -> None:
        """Recursively extract data from rich text elements."""
        elem_type = element.get("type", "")

        if elem_type == "user":
            mentioned_users.add(element.get("user_id", ""))

        elif elem_type == "link":
            url = element.get("url", "")
            if url:
                links.append(url)

        elif elem_type == "rich_text_preformatted":
            # Code block
            code_text = ""
            for sub in element.get("elements", []):
                if sub.get("type") == "text":
                    code_text += sub.get("text", "")
            if code_text:
                code_blocks.append(code_text[:500])  # Limit size

        elif elem_type in ("rich_text_section", "rich_text_quote"):
            # Recurse into nested elements
            for sub in element.get("elements", []):
                if isinstance(sub, dict):
                    self._extract_from_element(sub, mentioned_users, links, code_blocks)

    # ==================== Message Methods ====================

    async def send_message(
        self,
        channel_id: str,
        text: str,
        thread_ts: str | None = None,
        typing_delay: bool = True,
    ) -> dict[str, Any]:
        """
        Send a message to a channel.

        Args:
            channel_id: Target channel ID
            text: Message text (supports Slack markdown)
            thread_ts: Thread timestamp for threaded reply
            typing_delay: Add natural typing delay (0.5-2.5s)

        Returns:
            Message response with ts (timestamp), channel, etc.
        """
        if typing_delay:
            # Natural typing delay to avoid bot-like behavior
            delay = random.uniform(0.5, 2.5)
            logger.debug(f"Adding natural typing delay: {delay:.2f}s")
            await asyncio.sleep(delay)

        data = {"channel": channel_id, "text": text}
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

        This uses the same multipart/form-data format as the Slack web client,
        which provides:
        - Rich text formatting (bold, italic, code, etc.)
        - Proper thread replies
        - Reply broadcast option (also send to channel)
        - Client message ID tracking

        Args:
            channel_id: Target channel ID
            text: Message text (supports Slack markdown)
            thread_ts: Thread timestamp for threaded reply
            reply_broadcast: Also send reply to channel (not just thread)
            typing_delay: Add natural typing delay (0.5-2.5s)

        Returns:
            Message response with ts, channel, message details, etc.
        """
        if typing_delay:
            delay = random.uniform(0.5, 2.5)
            logger.debug(f"Adding natural typing delay: {delay:.2f}s")
            await asyncio.sleep(delay)

        # Get enterprise ID for routing
        eid = self.enterprise_id or self.workspace_id or self._extract_enterprise_id()

        # Build URL with query params
        x_id = f"{uuid.uuid4().hex[:8]}-{int(time.time())}.{random.randint(100, 999)}"

        url = (
            f"https://{self.SLACK_HOST}/api/chat.postMessage"
            f"?_x_id={x_id}"
            f"&slack_route={eid}%3A{eid}"
            "&_x_gantry=true"
            "&fp=14"
            "&_x_num_retries=0"
        )

        # Build multipart form data
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"

        # Generate unique IDs
        client_msg_id = str(uuid.uuid4())
        draft_id = str(uuid.uuid4())
        msg_ts = f"{int(time.time())}.{random.randint(100000, 999999)}"

        # Build rich text blocks from plain text
        blocks = self._text_to_rich_blocks(text)

        parts = [
            ("token", self.xoxc_token),
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
                ("_x_reason", "webapp_message_send"),
                ("_x_mode", "online"),
                ("_x_sonic", "true"),
                ("_x_app_name", "client"),
            ]
        )

        # Build the multipart body
        body_parts = []
        for name, value in parts:
            body_parts.append(f"--{boundary}")
            body_parts.append(f'Content-Disposition: form-data; name="{name}"')
            body_parts.append("")
            body_parts.append(value)
        body_parts.append(f"--{boundary}--")
        body_parts.append("")

        body = "\r\n".join(body_parts)

        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Origin": "https://app.slack.com",
        }

        client = await self.get_client()

        try:
            response = await client.post(url, content=body, headers=headers)
            response.raise_for_status()
            data = response.json()

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
        """
        Convert plain text to Slack rich text blocks.

        Handles:
        - Plain text
        - Code blocks (```)
        - Inline code (`)
        - User mentions (<@U...>)
        - Channel mentions (<#C...>)
        - Links (<url|text> or <url>)
        - Newlines (both actual and escaped \\n)
        - Emoji shortcodes (:emoji_name:)

        Args:
            text: Plain text with optional Slack markdown

        Returns:
            List of rich text block dicts
        """
        import re

        # Convert escaped newlines to actual newlines
        # This handles cases where text was passed with literal \n strings
        text = text.replace("\\n", "\n")

        # Convert common emoji shortcodes to Unicode
        # Slack rich_text blocks don't auto-convert shortcodes
        emoji_map = {
            ":wrench:": "🔧",
            ":hammer:": "🔨",
            ":gear:": "⚙️",
            ":rocket:": "🚀",
            ":warning:": "⚠️",
            ":x:": "❌",
            ":white_check_mark:": "✅",
            ":heavy_check_mark:": "✔️",
            ":information_source:": "ℹ️",
            ":bulb:": "💡",
            ":memo:": "📝",
            ":package:": "📦",
            ":fire:": "🔥",
            ":bug:": "🐛",
            ":zap:": "⚡",
            ":star:": "⭐",
            ":tada:": "🎉",
            ":eyes:": "👀",
            ":thumbsup:": "👍",
            ":thumbsdown:": "👎",
            ":rotating_light:": "🚨",
            ":lock:": "🔒",
            ":key:": "🔑",
            ":link:": "🔗",
            ":clipboard:": "📋",
            ":calendar:": "📅",
            ":clock:": "🕐",
            ":hourglass:": "⏳",
            ":mag:": "🔍",
            ":chart_with_upwards_trend:": "📈",
            ":chart_with_downwards_trend:": "📉",
            ":construction:": "🚧",
            ":hammer_and_wrench:": "🛠️",
            ":test_tube:": "🧪",
            ":microscope:": "🔬",
            ":speech_balloon:": "💬",
            ":thought_balloon:": "💭",
            ":bell:": "🔔",
            ":no_bell:": "🔕",
            ":loudspeaker:": "📢",
            ":mega:": "📣",
        }
        for shortcode, unicode_emoji in emoji_map.items():
            text = text.replace(shortcode, unicode_emoji)

        elements = []
        current_text = ""

        # Split by code blocks first
        code_block_pattern = r"```([^`]*?)```"
        parts = re.split(code_block_pattern, text, flags=re.DOTALL)

        for i, part in enumerate(parts):
            if i % 2 == 1:
                # This is a code block
                if current_text:
                    elements.extend(self._parse_inline_elements(current_text))
                    current_text = ""
                elements.append(
                    {
                        "type": "rich_text_preformatted",
                        "elements": [{"type": "text", "text": part}],
                        "border": 0,
                    }
                )
            else:
                current_text += part

        # Process remaining text
        if current_text:
            elements.extend(self._parse_inline_elements(current_text))

        # Wrap in rich_text block
        if not elements:
            elements = [
                {
                    "type": "rich_text_section",
                    "elements": [{"type": "text", "text": text}],
                }
            ]

        return [{"type": "rich_text", "elements": elements}]

    def _parse_inline_elements(self, text: str) -> list[dict[str, Any]]:
        """Parse inline elements (mentions, links, inline code, bold, italic) from text."""
        import re

        if not text.strip():
            return []

        elements = []
        section_elements = []

        # Pattern for user mentions, channel mentions, links, inline code, bold, and italic
        # Order matters: check longer patterns first, and be careful with * and _
        # Bold: *text* (but not ** or *text *text*)
        # Italic: _text_ (but not __ or _text _text_)
        # Inline code: `code`
        pattern = r"(<@U[A-Z0-9]+>|<#C[A-Z0-9]+(?:\|[^>]*)?>|<https?://[^|>]+(?:\|[^>]*)?>|`[^`]+`|\*[^*\n]+\*|_[^_\n]+_)"  # noqa: E501

        parts = re.split(pattern, text)

        for part in parts:
            if not part:
                continue

            if part.startswith("<@U"):
                # User mention
                user_id = part[2:-1]
                section_elements.append({"type": "user", "user_id": user_id})

            elif part.startswith("<#C"):
                # Channel mention
                match = re.match(r"<#(C[A-Z0-9]+)(?:\|([^>]*))?>", part)
                if match:
                    channel_id = match.group(1)
                    section_elements.append(
                        {
                            "type": "channel",
                            "channel_id": channel_id,
                        }
                    )

            elif part.startswith("<http"):
                # Link
                match = re.match(r"<(https?://[^|>]+)(?:\|([^>]*))?>", part)
                if match:
                    url = match.group(1)
                    link_text = match.group(2) if match.group(2) else url
                    section_elements.append(
                        {
                            "type": "link",
                            "url": url,
                            "text": link_text,
                        }
                    )

            elif part.startswith("`") and part.endswith("`") and len(part) > 2:
                # Inline code
                code = part[1:-1]
                section_elements.append(
                    {
                        "type": "text",
                        "text": code,
                        "style": {"code": True},
                    }
                )

            elif part.startswith("*") and part.endswith("*") and len(part) > 2:
                # Bold text
                bold_text = part[1:-1]
                section_elements.append(
                    {
                        "type": "text",
                        "text": bold_text,
                        "style": {"bold": True},
                    }
                )

            elif part.startswith("_") and part.endswith("_") and len(part) > 2:
                # Italic text
                italic_text = part[1:-1]
                section_elements.append(
                    {
                        "type": "text",
                        "text": italic_text,
                        "style": {"italic": True},
                    }
                )

            else:
                # Plain text
                section_elements.append({"type": "text", "text": part})

        if section_elements:
            elements.append(
                {
                    "type": "rich_text_section",
                    "elements": section_elements,
                }
            )

        return elements

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
        """
        Open a DM channel with a user.

        Args:
            user_id: User ID (e.g., U123456)

        Returns:
            DM channel ID (e.g., D123456)
        """
        result = await self._request("conversations.open", {"users": user_id})
        channel = result.get("channel", {})
        return channel.get("id", "")

    async def send_dm(
        self,
        user_id: str,
        text: str,
        typing_delay: bool = True,
    ) -> dict[str, Any]:
        """
        Send a direct message to a user.

        Args:
            user_id: Target user ID (e.g., U123456)
            text: Message text
            typing_delay: Add natural typing delay

        Returns:
            Message response
        """
        # First open a DM channel with the user
        dm_channel = await self.open_dm(user_id)
        if not dm_channel:
            raise ValueError(f"Could not open DM with user {user_id}")

        # Then send the message
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

        This uses the internal edgeapi endpoint which works even when the
        regular conversations.list API is blocked by enterprise restrictions.

        Args:
            query: Search query string
            count: Maximum number of results (default 30)
            include_archived: Include archived channels in results
            check_membership: Check if user is a member of each channel

        Returns:
            List of channel dicts with id, name, purpose, topic, etc.
        """
        # Get enterprise ID - prefer explicit enterprise_id, fall back to workspace_id
        eid = self.enterprise_id or self.workspace_id or self._extract_enterprise_id()

        if not eid:
            raise ValueError(
                "Enterprise ID not available. Set enterprise_id in config.json slack.auth section, "
                "or set SLACK_ENTERPRISE_ID environment variable."
            )

        # Edge API URL for channel search
        edge_url = f"https://edgeapi.slack.com/cache/{eid}/channels/search"

        # Build request payload
        payload = {
            "token": self.xoxc_token,
            "query": query,
            "count": count,
            "fuzz": 1,  # Enable fuzzy matching
            "uax29_tokenizer": False,
            "include_record_channels": True,
            "check_membership": check_membership,
            "enterprise_token": self.xoxc_token,
        }

        client = await self.get_client()

        try:
            # Edge API uses different headers
            headers = {
                "User-Agent": self.USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": "en-IE,en-US;q=0.9,en-GB;q=0.8,en;q=0.7",
                "Content-Type": "text/plain;charset=UTF-8",
                "Origin": "https://app.slack.com",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
            }

            response = await client.post(
                edge_url,
                content=json.dumps(payload),
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()

            channels = result.get("results", [])

            # Filter out archived if requested
            if not include_archived:
                channels = [c for c in channels if not c.get("is_archived", False)]

            return channels

        except httpx.HTTPStatusError as e:
            logger.error(
                f"Edge API error: {e.response.status_code} - {e.response.text[:200]}"
            )
            raise ValueError(f"Channel search failed: {e.response.status_code}") from e
        except Exception as e:
            logger.error(f"Channel search error: {e}")
            raise

    def _extract_enterprise_id(self) -> str:
        """
        Try to extract enterprise ID from the xoxc token or other sources.

        The enterprise ID is typically in the format E030G10V24F.
        """
        # Try to get from environment
        enterprise_id = os.getenv("SLACK_ENTERPRISE_ID", "")
        if enterprise_id:
            return enterprise_id

        # The enterprise ID might be embedded in certain API responses
        # For now, return empty and require explicit configuration
        return ""

    def get_avatar_url(self, user_id: str, avatar_hash: str, size: int = 512) -> str:
        """
        Construct a Slack avatar URL from user ID and avatar hash.

        Avatar URLs follow the pattern:
        https://ca.slack-edge.com/{enterprise_id}-{user_id}-{avatar_hash}-{size}

        Args:
            user_id: Slack user ID (e.g., U04RA3VE2RZ)
            avatar_hash: Avatar hash from profile (e.g., 4d88f1ddb848)
            size: Image size in pixels (512, 192, 72, 48, 32)

        Returns:
            Full avatar URL or empty string if hash is missing
        """
        if not avatar_hash:
            return ""

        eid = self.enterprise_id or self.workspace_id or self._extract_enterprise_id()
        if not eid:
            # Fall back to just using the hash-based URL without enterprise ID
            return ""

        return f"https://ca.slack-edge.com/{eid}-{user_id}-{avatar_hash}-{size}"

    def extract_avatar_hash(self, profile: dict[str, Any]) -> str:
        """
        Extract avatar hash from a user profile.

        The hash can be found in:
        - profile.avatar_hash (direct field)
        - Extracted from image URLs like image_72, image_192, etc.

        Args:
            profile: User profile dict from Slack API

        Returns:
            Avatar hash string or empty string if not found
        """
        # Try direct avatar_hash field first
        avatar_hash = profile.get("avatar_hash", "")
        if avatar_hash:
            return avatar_hash

        # Try to extract from image URLs
        for key in ["image_original", "image_512", "image_192", "image_72", "image_48"]:
            url = profile.get(key, "")
            if url and "slack-edge.com" in url:
                # URL format: https://ca.slack-edge.com/E030G10V24F-U04RA3VE2RZ-4d88f1ddb848-512
                # or: https://avatars.slack-edge.com/2022-01-12/2965715167392_15b10eb54da5b144a96b_original.jpg
                parts = url.split("/")
                if parts:
                    last_part = parts[-1]
                    # Check for the enterprise format (contains dashes)
                    if "-" in last_part and not last_part.endswith(".jpg"):
                        # Format: E030G10V24F-U04RA3VE2RZ-4d88f1ddb848-512
                        segments = last_part.split("-")
                        if len(segments) >= 3:
                            return segments[-2]  # The hash is second to last
                    # Check for the avatars format
                    elif "_" in last_part:
                        # Format: 2965715167392_15b10eb54da5b144a96b_original.jpg
                        segments = (
                            last_part.replace(".jpg", "").replace(".png", "").split("_")
                        )
                        if len(segments) >= 2:
                            return segments[1]  # The hash is the second part

        return ""

    async def search_channels_and_cache(
        self,
        query: str,
        count: int = 30,
    ) -> dict[str, Any]:
        """
        Search for channels and return results in a format suitable for caching.

        Args:
            query: Search query string
            count: Maximum number of results

        Returns:
            Dict with success status and list of channel info
        """
        try:
            channels = await self.search_channels(query, count)

            # Convert to a simpler format for caching
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
        """
        Search for users using Slack's edge API.

        This uses the internal edgeapi endpoint which works even when the
        regular users.list API is blocked by enterprise restrictions.

        Args:
            query: Search query string (name, email, etc.)
            count: Maximum number of results (default 30)
            include_deactivated: Include deactivated users in results

        Returns:
            List of user dicts with id, name, profile, etc.
        """
        # Get enterprise ID
        eid = self.enterprise_id or self.workspace_id or self._extract_enterprise_id()

        if not eid:
            raise ValueError(
                "Enterprise ID not available. Set enterprise_id in config.json slack.auth section, "
                "or set SLACK_ENTERPRISE_ID environment variable."
            )

        # Edge API URL for user search
        edge_url = f"https://edgeapi.slack.com/cache/{eid}/users/search"

        # Build filter - exclude deactivated by default
        user_filter = "" if include_deactivated else "NOT deactivated"

        # Build request payload
        payload = {
            "token": self.xoxc_token,
            "query": query,
            "count": count,
            "fuzz": 1,  # Enable fuzzy matching
            "uax29_tokenizer": False,
            "include_profile_only_users": True,
            "enable_workspace_ranking": True,
            "filter": user_filter,
            "enterprise_token": self.xoxc_token,
        }

        client = await self.get_client()

        try:
            # Edge API uses different headers
            headers = {
                "User-Agent": self.USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": "en-IE,en-US;q=0.9,en-GB;q=0.8,en;q=0.7",
                "Content-Type": "text/plain;charset=UTF-8",
                "Origin": "https://app.slack.com",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
            }

            response = await client.post(
                edge_url,
                content=json.dumps(payload),
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()

            users = result.get("results", [])
            return users

        except httpx.HTTPStatusError as e:
            logger.error(
                f"Edge API user search error: {e.response.status_code} - {e.response.text[:200]}"
            )
            raise ValueError(f"User search failed: {e.response.status_code}") from e
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
        """
        List members of a specific channel using the Edge API.

        This bypasses enterprise restrictions on users.list by scoping
        the request to a specific channel.

        Args:
            channel_id: Channel ID to list members for (e.g., C089F16L30T)
            count: Maximum number of members to return (default 100)
            include_bots: Include bot users in results (default False)
            present_first: Show active/present users first (default True)

        Returns:
            List of user dicts with full profile information
        """
        # Get enterprise ID
        eid = self.enterprise_id or self.workspace_id or self._extract_enterprise_id()

        if not eid:
            raise ValueError(
                "Enterprise ID not available. Set enterprise_id in config.json slack.auth section."
            )

        # Edge API URL for users list
        edge_url = f"https://edgeapi.slack.com/cache/{eid}/users/list"

        # Build filter
        if include_bots:
            user_filter = "everyone"
        else:
            user_filter = "everyone AND NOT bots AND NOT apps"

        # Build request payload
        payload = {
            "token": self.xoxc_token,
            "channels": [channel_id],
            "present_first": present_first,
            "filter": user_filter,
            "count": count,
            "enterprise_token": self.xoxc_token,
        }

        client = await self.get_client()

        try:
            headers = {
                "User-Agent": self.USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": "en-IE,en-US;q=0.9,en-GB;q=0.8,en;q=0.7",
                "Content-Type": "text/plain;charset=UTF-8",
                "Origin": "https://app.slack.com",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
            }

            response = await client.post(
                edge_url,
                content=json.dumps(payload),
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()

            if not result.get("ok"):
                error = result.get("error", "Unknown error")
                logger.error(f"Channel members list error: {error}")
                raise ValueError(f"Channel members list failed: {error}")

            return result.get("results", [])

        except httpx.HTTPStatusError as e:
            logger.error(
                f"Edge API error: {e.response.status_code} - {e.response.text[:200]}"
            )
            raise ValueError(
                f"Channel members list failed: {e.response.status_code}"
            ) from e
        except Exception as e:
            logger.error(f"Channel members list error: {e}")
            raise

    async def check_channel_membership(
        self,
        channel_id: str,
        user_ids: list[str],
    ) -> dict[str, Any]:
        """
        Check which users from a list are members of a channel.

        This uses the Edge API channels/membership endpoint to verify
        membership for a known list of user IDs. Useful for:
        - Verifying if specific users are in a channel
        - Filtering a user list to only channel members
        - Checking membership before sending targeted messages

        Args:
            channel_id: Channel ID to check membership for
            user_ids: List of user IDs to check

        Returns:
            Dict with channel, members list (filtered to actual members), and ok status
        """
        # Get enterprise ID
        eid = self.enterprise_id or self.workspace_id or self._extract_enterprise_id()

        if not eid:
            raise ValueError(
                "Enterprise ID not available. Set enterprise_id in config.json slack.auth section."
            )

        # Edge API URL for membership check
        edge_url = f"https://edgeapi.slack.com/cache/{eid}/channels/membership"

        # Build request payload
        payload = {
            "token": self.xoxc_token,
            "channel": channel_id,
            "users": user_ids,
            "as_admin": False,
            "enterprise_token": self.xoxc_token,
        }

        client = await self.get_client()

        try:
            headers = {
                "User-Agent": self.USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": "en-IE,en-US;q=0.9,en-GB;q=0.8,en;q=0.7",
                "Content-Type": "text/plain;charset=UTF-8",
                "Origin": "https://app.slack.com",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
            }

            response = await client.post(
                edge_url,
                content=json.dumps(payload),
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()

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

        except httpx.HTTPStatusError as e:
            logger.error(
                f"Edge API error: {e.response.status_code} - {e.response.text[:200]}"
            )
            raise ValueError(
                f"Channel membership check failed: {e.response.status_code}"
            ) from e
        except Exception as e:
            logger.error(f"Channel membership check error: {e}")
            raise

    async def list_channel_members_and_cache(
        self,
        channel_id: str,
        count: int = 100,
    ) -> dict[str, Any]:
        """
        List channel members and return in a format suitable for caching.

        Args:
            channel_id: Channel ID to list members for
            count: Maximum number of members

        Returns:
            Dict with success status and list of user info
        """
        try:
            users = await self.list_channel_members(channel_id, count)

            # Convert to a simpler format for caching
            results = []
            for u in users:
                user_id = u.get("id", "")
                profile = u.get("profile", {})

                # Get avatar URL
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
        """
        Get the user's sidebar channel sections/folders.

        This returns the user's organized sidebar structure including:
        - Custom sections (folders) they've created
        - Channel IDs in each section
        - Section types (standard, stars, direct_messages, etc.)

        This is the proper API alternative to scraping the sidebar HTML.

        Returns:
            Dict with channel_sections list and metadata
        """
        # Get enterprise ID for routing
        eid = self.enterprise_id or self.workspace_id or self._extract_enterprise_id()

        # Build URL with query params
        x_id = f"{uuid.uuid4().hex[:8]}-{int(time.time())}.{random.randint(100, 999)}"

        url = (
            f"https://{self.SLACK_HOST}/api/users.channelSections.list"
            f"?_x_id={x_id}"
            f"&slack_route={eid}%3A{eid}"
            "&_x_gantry=true"
            "&fp=14"
            "&_x_num_retries=0"
        )

        # Build multipart form data
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"

        parts = [
            ("token", self.xoxc_token),
            ("_x_reason", "conditional-fetch-manager"),
            ("_x_mode", "online"),
            ("_x_sonic", "true"),
            ("_x_app_name", "client"),
        ]

        # Build the multipart body
        body_parts = []
        for name, value in parts:
            body_parts.append(f"--{boundary}")
            body_parts.append(f'Content-Disposition: form-data; name="{name}"')
            body_parts.append("")
            body_parts.append(value)
        body_parts.append(f"--{boundary}--")
        body_parts.append("")

        body = "\r\n".join(body_parts)

        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Origin": "https://app.slack.com",
        }

        client = await self.get_client()

        try:
            response = await client.post(url, content=body, headers=headers)
            response.raise_for_status()
            data = response.json()

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
        """
        Summarize channel sections into a more usable format.

        Args:
            data: Raw channel sections response from get_channel_sections()

        Returns:
            Summarized dict with sections and all channel IDs
        """
        if not data.get("ok"):
            return data

        sections = []
        all_channel_ids = []

        for section in data.get("channel_sections", []):
            section_type = section.get("type", "")
            channel_ids = section.get("channel_ids_page", {}).get("channel_ids", [])

            sections.append(
                {
                    "id": section.get("channel_section_id", ""),
                    "name": section.get("name", "")
                    or section_type.replace("_", " ").title(),
                    "type": section_type,
                    "emoji": section.get("emoji", ""),
                    "channel_count": len(channel_ids),
                    "channel_ids": channel_ids,
                }
            )

            # Collect all channel IDs (skip DMs and special sections)
            if section_type == "standard":
                all_channel_ids.extend(channel_ids)

        return {
            "ok": True,
            "sections": sections,
            "total_sections": len(sections),
            "total_channels": len(all_channel_ids),
            "all_channel_ids": all_channel_ids,
        }

    async def get_channel_history_rich(
        self,
        channel_id: str,
        limit: int = 50,
        oldest: str = "",
        latest: str = "",
        ignore_replies: bool = True,
    ) -> dict[str, Any]:
        """
        Get message history for a channel with rich data (Edge API version).

        This uses the conversations.history API via multipart/form-data to fetch
        messages with full rich text blocks, attachments, and thread metadata.

        Note: For simple polling, use get_channel_history() which returns a list.
        This method returns a dict with additional metadata.

        Args:
            channel_id: Channel ID to fetch history for
            limit: Maximum number of messages (default 50, max 100)
            oldest: Start timestamp (exclusive) - fetch messages after this
            latest: End timestamp (inclusive) - fetch messages before this
            ignore_replies: If true, don't include thread replies in results

        Returns:
            Dict with messages list and pagination info
        """
        # Get enterprise ID for routing
        eid = self.enterprise_id or self.workspace_id or self._extract_enterprise_id()

        # Build URL with query params
        x_id = f"{uuid.uuid4().hex[:8]}-{int(time.time())}.{random.randint(100, 999)}"

        url = (
            f"https://{self.SLACK_HOST}/api/conversations.history"
            f"?_x_id={x_id}"
            f"&slack_route={eid}%3A{eid}"
            "&_x_gantry=true"
            "&fp=14"
            "&_x_num_retries=0"
        )

        # Build multipart form data
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"

        # Clamp limit
        limit = max(1, min(limit, 100))

        parts = [
            ("token", self.xoxc_token),
            ("channel", channel_id),
            ("limit", str(limit)),
            ("ignore_replies", "true" if ignore_replies else "false"),
            ("include_pin_count", "false"),
            ("inclusive", "true"),
            ("no_user_profile", "true"),
            ("include_stories", "true"),
            ("_x_reason", "channel-history-fetch"),
            ("_x_mode", "online"),
            ("_x_sonic", "true"),
            ("_x_app_name", "client"),
        ]

        # Add optional time range
        if oldest:
            parts.append(("oldest", oldest))
        if latest:
            parts.append(("latest", latest))

        # Build the multipart body
        body_parts = []
        for name, value in parts:
            body_parts.append(f"--{boundary}")
            body_parts.append(f'Content-Disposition: form-data; name="{name}"')
            body_parts.append("")
            body_parts.append(value)
        body_parts.append(f"--{boundary}--")
        body_parts.append("")

        body = "\r\n".join(body_parts)

        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Origin": "https://app.slack.com",
        }

        client = await self.get_client()

        try:
            response = await client.post(url, content=body, headers=headers)
            response.raise_for_status()
            data = response.json()

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
        """
        Simplify channel history into a more usable format.

        Extracts key information from messages for AI processing.

        Args:
            data: Raw channel history response

        Returns:
            Simplified dict with messages
        """
        if not data.get("ok"):
            return data

        messages = []
        for msg in data.get("messages", []):
            # Extract text content
            text = msg.get("text", "")

            # Get thread info
            thread_ts = msg.get("thread_ts", "")
            is_thread_parent = thread_ts == msg.get("ts", "")
            reply_count = msg.get("reply_count", 0) if is_thread_parent else 0

            # Extract mentions from blocks
            mentions = []
            links = []
            for block in msg.get("blocks", []):
                for element in block.get("elements", []):
                    self._extract_from_block_element(element, mentions, links)

            messages.append(
                {
                    "ts": msg.get("ts", ""),
                    "user": msg.get("user", ""),
                    "text": text,
                    "thread_ts": thread_ts,
                    "is_thread_parent": is_thread_parent,
                    "reply_count": reply_count,
                    "reply_users": msg.get("reply_users", []),
                    "mentions": list(set(mentions)),
                    "links": links[:10],  # Limit links
                    "has_attachments": len(msg.get("attachments", [])) > 0,
                    "edited": msg.get("edited") is not None,
                }
            )

        return {
            "ok": True,
            "messages": messages,
            "count": len(messages),
            "has_more": data.get("has_more", False),
        }

    def _extract_from_block_element(
        self,
        element: dict[str, Any],
        mentions: list[str],
        links: list[str],
    ) -> None:
        """Recursively extract mentions and links from block elements."""
        elem_type = element.get("type", "")

        if elem_type == "user":
            mentions.append(element.get("user_id", ""))
        elif elem_type == "link":
            url = element.get("url", "")
            if url:
                links.append(url)
        elif elem_type in (
            "rich_text_section",
            "rich_text_preformatted",
            "rich_text_list",
        ):
            for sub in element.get("elements", []):
                self._extract_from_block_element(sub, mentions, links)

    async def search_users_and_cache(
        self,
        query: str,
        count: int = 30,
    ) -> dict[str, Any]:
        """
        Search for users and return results in a format suitable for caching.

        Args:
            query: Search query string
            count: Maximum number of results

        Returns:
            Dict with success status and list of user info
        """
        try:
            users = await self.search_users(query, count)

            # Convert to a simpler format for caching
            results = []
            for u in users:
                user_id = u.get("id", "")
                profile = u.get("profile", {})

                # Get avatar URL - prefer constructed URL, fall back to profile URLs
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
        """
        Get all available slash commands and app actions in the workspace.

        This uses the client.appCommands API which returns:
        - app_actions: Actions from installed apps (Jira, GitHub, etc.)
        - commands: Slash commands (both core and app-specific)

        Returns:
            Dict with app_actions and commands lists
        """
        # Get enterprise ID for routing
        eid = self.enterprise_id or self.workspace_id or self._extract_enterprise_id()

        # Build URL with query params
        x_id = f"{uuid.uuid4().hex[:8]}-{int(time.time())}.{random.randint(100, 999)}"

        url = (
            f"https://{self.SLACK_HOST}/api/client.appCommands"
            f"?_x_id={x_id}"
            f"&slack_route={eid}%3A{eid}"
            "&_x_gantry=true"
            "&fp=14"
            "&_x_num_retries=0"
        )

        # Build multipart form data
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"

        parts = [
            ("token", self.xoxc_token),
            ("_x_reason", "set-model-data"),
            ("_x_mode", "online"),
            ("_x_sonic", "true"),
            ("_x_app_name", "client"),
        ]

        # Build the multipart body
        body_parts = []
        for name, value in parts:
            body_parts.append(f"--{boundary}")
            body_parts.append(f'Content-Disposition: form-data; name="{name}"')
            body_parts.append("")
            body_parts.append(value)
        body_parts.append(f"--{boundary}--")
        body_parts.append("")

        body = "\r\n".join(body_parts)

        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Origin": "https://app.slack.com",
        }

        client = await self.get_client()

        try:
            response = await client.post(url, content=body, headers=headers)
            response.raise_for_status()
            data = response.json()

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
        """
        Summarize app commands data into a more usable format.

        Args:
            data: Raw app commands response from get_app_commands()

        Returns:
            Summarized dict with categorized commands and actions
        """
        if not data.get("ok"):
            return data

        # Categorize commands
        core_commands = []
        app_commands = []
        service_commands = []

        for cmd in data.get("commands", []):
            cmd_type = cmd.get("type", "")
            cmd_info = {
                "name": cmd.get("name", ""),
                "desc": cmd.get("desc", ""),
                "usage": cmd.get("usage", ""),
                "app_name": cmd.get("app_name", ""),
            }

            if cmd_type == "core":
                core_commands.append(cmd_info)
            elif cmd_type == "app":
                app_commands.append(cmd_info)
            elif cmd_type == "service":
                service_commands.append(cmd_info)

        # Categorize app actions by type
        global_actions = []
        message_actions = []

        for app in data.get("app_actions", []):
            app_name = app.get("app_name", "")
            app_id = app.get("app_id", "")

            for action in app.get("actions", []):
                action_info = {
                    "name": action.get("name", ""),
                    "desc": action.get("desc", ""),
                    "app_name": app_name,
                    "app_id": app_id,
                    "action_id": action.get("action_id", ""),
                    "callback_id": action.get("callback_id", ""),
                }

                if action.get("type") == "global_action":
                    global_actions.append(action_info)
                elif action.get("type") == "message_action":
                    message_actions.append(action_info)

        return {
            "ok": True,
            "core_commands": core_commands,
            "app_commands": app_commands,
            "service_commands": service_commands,
            "global_actions": global_actions,
            "message_actions": message_actions,
            "total_commands": len(core_commands)
            + len(app_commands)
            + len(service_commands),
            "total_actions": len(global_actions) + len(message_actions),
        }

    async def get_user_profile_sections(self, user_id: str) -> dict[str, Any]:
        """
        Get detailed user profile with sections (contact info, about me, etc.).

        This uses the users.profile.getSections API which returns structured
        profile data including custom fields, contact information, and more.

        Args:
            user_id: Slack user ID (e.g., U04RA3VE2RZ)

        Returns:
            Dict with profile sections and elements
        """
        # Get enterprise ID for routing
        eid = self.enterprise_id or self.workspace_id or self._extract_enterprise_id()

        # Build URL with query params
        x_id = f"{uuid.uuid4().hex[:8]}-{int(time.time() * 1000)}.{random.randint(100, 999)}"

        url = (
            f"https://{self.SLACK_HOST}/api/users.profile.getSections"
            f"?_x_id={x_id}"
            f"&slack_route={eid}%3A{eid}"
            "&_x_gantry=true"
            "&fp=14"
            "&_x_num_retries=0"
        )

        client = await self.get_client()

        try:
            # Build multipart form data
            boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"

            form_parts = [
                ("token", self.xoxc_token),
                ("user", user_id),
                ("_x_reason", "profiles"),
                ("_x_mode", "online"),
                ("_x_sonic", "true"),
                ("_x_app_name", "client"),
            ]

            body_parts = []
            for name, value in form_parts:
                body_parts.append(f"--{boundary}")
                body_parts.append(f'Content-Disposition: form-data; name="{name}"')
                body_parts.append("")
                body_parts.append(value)

            body_parts.append(f"--{boundary}--")
            body_parts.append("")

            body = "\r\n".join(body_parts)

            headers = {
                "User-Agent": self.USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": "en-IE,en-US;q=0.9,en-GB;q=0.8,en;q=0.7",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Origin": "https://app.slack.com",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
            }

            response = await client.post(url, content=body, headers=headers)
            response.raise_for_status()
            result = response.json()

            if not result.get("ok"):
                error = result.get("error", "unknown_error")
                raise ValueError(f"Profile API error: {error}")

            return result

        except httpx.HTTPStatusError as e:
            logger.error(f"Profile API error: {e.response.status_code}")
            raise ValueError(f"Profile fetch failed: {e.response.status_code}") from e
        except Exception as e:
            logger.error(f"Profile fetch error: {e}")
            raise

    async def get_user_profile_details(self, user_id: str) -> dict[str, Any]:
        """
        Get user profile details in a simplified format.

        Extracts key information from the profile sections API response.

        Args:
            user_id: Slack user ID

        Returns:
            Dict with extracted profile fields (email, title, about, etc.)
        """
        try:
            result = await self.get_user_profile_sections(user_id)

            # Extract data from the nested structure
            data = result.get("result", {}).get("data", {})
            user_data = data.get("user", {})
            sections = user_data.get("profileSections", [])

            profile = {
                "user_id": user_id,
                "sections": {},
            }

            # Parse each section
            for section in sections:
                section_type = section.get("type", "")
                section_label = section.get("label", "")
                elements = section.get("profileElements", [])

                section_data = {
                    "label": section_label,
                    "fields": {},
                }

                for elem in elements:
                    key = elem.get("elementKey", elem.get("label", "unknown"))
                    label = elem.get("label", key)

                    # Get value based on element type
                    if elem.get("type") == "TEXT":
                        value = elem.get("text", "")
                    elif elem.get("type") == "RICH_TEXT":
                        value = elem.get("richText", {}).get("text", "")
                    else:
                        value = elem.get("text", elem.get("value", ""))

                    if value:  # Only include non-empty values
                        section_data["fields"][key] = {
                            "label": label,
                            "value": value,
                        }

                if section_data["fields"]:  # Only include sections with data
                    profile["sections"][section_type] = section_data

            # Extract common fields for convenience
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
