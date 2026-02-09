"""Slack API Client — low-level HTTP, rate limiting, and session management.

Extracted from SlackSession to isolate network transport concerns.  All HTTP
request methods, cookie handling, multipart body construction, and retry /
back-off logic live here.
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
class SlackApiClient:
    """Low-level HTTP transport for the Slack web API.

    Manages:
    - httpx.AsyncClient lifecycle
    - XOXC token / d-cookie authentication
    - Rate-limit retry with exponential back-off
    - Enterprise multipart / edge-API request helpers
    """

    xoxc_token: str
    d_cookie: str
    workspace_id: str = ""
    enterprise_id: str = ""

    # Rate limiting configuration
    max_retries: int = 5
    base_backoff: float = 1.0

    # Internal state
    _client: httpx.AsyncClient | None = field(default=None, repr=False)
    _rate_limit: RateLimitState = field(default_factory=RateLimitState)

    # High-fidelity spoofing headers
    USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/143.0.0.0 Safari/537.36"
    )

    # Enterprise Slack URLs
    SLACK_HOST = os.getenv("SLACK_HOST", "redhat.enterprise.slack.com")
    REFERER = f"https://{SLACK_HOST}/"
    BASE_URL = "https://slack.com/api"

    def __post_init__(self):
        """Initialize internal state."""
        self._client = None
        self._rate_limit = RateLimitState()

    # ------------------------------------------------------------------
    # Client lifecycle
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Core authenticated request
    # ------------------------------------------------------------------

    async def request(
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
                        await asyncio.sleep(self.base_backoff * (2**attempt))
                        continue
                    else:
                        raise ValueError(f"Slack API error: {error}")

                return result

            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500 and attempt < self.max_retries - 1:
                    await asyncio.sleep(self.base_backoff * (2**attempt))
                    continue
                raise

        raise ValueError(f"Max retries ({self.max_retries}) exceeded for {method}")

    # ------------------------------------------------------------------
    # Enterprise / web-client multipart helpers
    # ------------------------------------------------------------------

    def get_enterprise_id(self) -> str:
        """Return the best available enterprise / workspace ID."""
        return self.enterprise_id or self.workspace_id or self._extract_enterprise_id()

    def _extract_enterprise_id(self) -> str:
        """Try to extract enterprise ID from environment."""
        return os.getenv("SLACK_ENTERPRISE_ID", "")

    def build_web_api_url(self, api_method: str) -> str:
        """Build a web-client-style URL with routing parameters.

        Args:
            api_method: Slack API method name (e.g., "conversations.history")

        Returns:
            Fully-qualified URL string
        """
        eid = self.get_enterprise_id()
        x_id = f"{uuid.uuid4().hex[:8]}-{int(time.time())}.{random.randint(100, 999)}"

        return (
            f"https://{self.SLACK_HOST}/api/{api_method}"
            f"?_x_id={x_id}"
            f"&slack_route={eid}%3A{eid}"
            "&_x_gantry=true"
            "&fp=14"
            "&_x_num_retries=0"
        )

    @staticmethod
    def build_multipart_body(parts: list[tuple[str, str]]) -> tuple[str, str]:
        """Build a multipart/form-data body from name/value pairs.

        Args:
            parts: List of (field_name, value) tuples

        Returns:
            (content_type_header, body_string)
        """
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"

        body_parts: list[str] = []
        for name, value in parts:
            body_parts.append(f"--{boundary}")
            body_parts.append(f'Content-Disposition: form-data; name="{name}"')
            body_parts.append("")
            body_parts.append(value)
        body_parts.append(f"--{boundary}--")
        body_parts.append("")

        body = "\r\n".join(body_parts)
        content_type = f"multipart/form-data; boundary={boundary}"
        return content_type, body

    async def web_api_request(
        self,
        api_method: str,
        parts: list[tuple[str, str]],
        x_reason: str = "",
    ) -> dict[str, Any]:
        """Make a web-client-style multipart request.

        This is the shared implementation behind many enterprise web-API
        methods that all follow the same URL-building + multipart-body
        pattern.

        Args:
            api_method: Slack API method (e.g., "conversations.history")
            parts: Extra form-data fields (token is prepended automatically)
            x_reason: Value for the ``_x_reason`` field

        Returns:
            Parsed JSON response dict
        """
        url = self.build_web_api_url(api_method)

        all_parts: list[tuple[str, str]] = [("token", self.xoxc_token)]
        all_parts.extend(parts)

        if x_reason:
            all_parts.append(("_x_reason", x_reason))
        all_parts.extend(
            [
                ("_x_mode", "online"),
                ("_x_sonic", "true"),
                ("_x_app_name", "client"),
            ]
        )

        content_type, body = self.build_multipart_body(all_parts)

        headers = {
            "Content-Type": content_type,
            "Origin": "https://app.slack.com",
        }

        client = await self.get_client()
        response = await client.post(url, content=body, headers=headers)
        response.raise_for_status()
        return response.json()

    async def edge_api_request(
        self,
        edge_path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Make a request to the Slack Edge API.

        Edge API endpoints use JSON body with ``text/plain`` content type
        and a different header set from the standard web-client API.

        Args:
            edge_path: Path under ``https://edgeapi.slack.com/cache/{eid}/``
                       e.g. ``"channels/search"`` or ``"users/list"``
            payload: JSON body (token is injected automatically)

        Returns:
            Parsed JSON response dict

        Raises:
            ValueError: If enterprise ID is unavailable or the API returns an error
        """
        eid = self.get_enterprise_id()

        if not eid:
            raise ValueError(
                "Enterprise ID not available. Set enterprise_id in config.json slack.auth section, "
                "or set SLACK_ENTERPRISE_ID environment variable."
            )

        edge_url = f"https://edgeapi.slack.com/cache/{eid}/{edge_path}"

        payload["token"] = self.xoxc_token
        payload["enterprise_token"] = self.xoxc_token

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

        client = await self.get_client()

        try:
            response = await client.post(
                edge_url,
                content=json.dumps(payload),
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Edge API error: {e.response.status_code} - {e.response.text[:200]}"
            )
            raise ValueError(
                f"Edge API request to {edge_path} failed: {e.response.status_code}"
            ) from e
