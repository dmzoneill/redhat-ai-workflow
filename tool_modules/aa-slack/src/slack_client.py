"""Slack Web Client Session Manager.

Manages authenticated sessions to Slack's internal web API using XOXC tokens
and session cookies. This bypasses the official API restrictions by using
the same authentication mechanism as the Slack web client.

IMPORTANT: This approach uses internal APIs and may violate Slack's ToS.
Use responsibly and at your own risk.
"""

import asyncio
import logging
import os
import random
import time
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

    # Rate limiting configuration
    max_retries: int = 5
    base_backoff: float = 1.0

    # Internal state
    _client: httpx.AsyncClient | None = field(default=None, repr=False)
    _rate_limit: RateLimitState = field(default_factory=RateLimitState)
    _user_id: str = ""

    # High-fidelity spoofing headers - updated to match current Chrome
    USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) " "AppleWebKit/537.36 (KHTML, like Gecko) " "Chrome/143.0.0.0 Safari/537.36"
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
        import json
        from pathlib import Path

        # Try to load from config.json first
        config_paths = [
            Path(__file__).parent.parent.parent.parent.parent
            / "config.json",  # tool_modules/aa-slack/src -> project root
            Path.cwd() / "config.json",
            Path.home() / "src" / "redhat-ai-workflow" / "config.json",
        ]

        xoxc_token = ""
        d_cookie = ""
        workspace_id = ""

        for config_path in config_paths:
            if config_path.exists():
                try:
                    with open(config_path) as f:
                        config = json.load(f)
                    slack_auth = config.get("slack", {}).get("auth", {})
                    xoxc_token = slack_auth.get("xoxc_token", "")
                    d_cookie = slack_auth.get("d_cookie", "")
                    workspace_id = slack_auth.get("workspace_id", "")
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
                    backoff = min(retry_after, self.base_backoff * (2**attempt) + random.uniform(0, 1))
                    self._rate_limit.backoff_until = time.time() + backoff

                    logger.warning(
                        f"Rate limited (429). Attempt {attempt + 1}/{self.max_retries}. " f"Backing off {backoff:.1f}s"
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
                        raise ValueError("Token has been revoked. Re-authenticate via browser.")
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
        result = await self._request("conversations.list", {"types": types, "limit": limit})
        return result.get("channels", [])

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

    async def get_thread_replies(
        self,
        channel_id: str,
        thread_ts: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get replies in a thread."""
        result = await self._request("conversations.replies", {"channel": channel_id, "ts": thread_ts, "limit": limit})
        return result.get("messages", [])

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

    async def add_reaction(
        self,
        channel_id: str,
        timestamp: str,
        emoji: str,
    ) -> dict[str, Any]:
        """Add a reaction to a message."""
        return await self._request("reactions.add", {"channel": channel_id, "timestamp": timestamp, "name": emoji})

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
            "search.messages", {"query": query, "count": count, "sort": sort, "sort_dir": sort_dir}
        )
        return result.get("messages", {}).get("matches", [])
