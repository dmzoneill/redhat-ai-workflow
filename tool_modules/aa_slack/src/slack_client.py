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
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from .slack_channels import SlackChannelsMixin
from .slack_messages import SlackMessagesMixin
from .slack_users import SlackUsersMixin

logger = logging.getLogger(__name__)


@dataclass
class RateLimitState:
    """Tracks rate limit backoff state."""

    retry_count: int = 0
    last_429_time: float = 0
    backoff_until: float = 0


@dataclass
class SlackSession(SlackMessagesMixin, SlackChannelsMixin, SlackUsersMixin):
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


from .slack_channels import SlackChannelsMixin  # noqa: F401, E402

# Re-export mixins for backward compatibility
from .slack_messages import SlackMessagesMixin  # noqa: F401, E402
from .slack_users import SlackUsersMixin  # noqa: F401, E402
