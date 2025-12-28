#!/usr/bin/env python3
"""
Skill hooks - event-driven notifications during skill execution.

Sends terse DMs to PR authors and team channel updates.
Rate-limited to prevent spam.
"""

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class RateLimiter:
    """Track notifications per author to prevent spam."""

    window_seconds: int = 300
    max_per_author: int = 3
    _counts: dict = field(default_factory=lambda: defaultdict(list))

    def can_send(self, author_id: str) -> bool:
        """Check if we can send to this author."""
        now = time.time()
        # Clean old entries
        self._counts[author_id] = [ts for ts in self._counts[author_id] if now - ts < self.window_seconds]
        return len(self._counts[author_id]) < self.max_per_author

    def record(self, author_id: str):
        """Record a notification sent."""
        self._counts[author_id].append(time.time())


@dataclass
class PendingNotification:
    """A notification waiting to be sent."""

    event_type: str
    author_slack_id: Optional[str]
    channel_id: Optional[str]
    message: str
    context: dict
    timestamp: float = field(default_factory=time.time)


class SkillHooks:
    """
    Handle event notifications from skill execution.

    Usage:
        hooks = SkillHooks.from_config()
        await hooks.emit("review_approved", {
            "mr_id": "1449",
            "author": "daoneill",
            "target_branch": "main"
        })
    """

    def __init__(self, config: dict):
        self.config = config.get("skill_hooks", {})
        self.slack_config = config.get("slack", {})
        self.enabled = self.config.get("enabled", True)

        # Debug mode - redirect all messages to self
        debug_cfg = self.config.get("debug", {})
        self.debug_enabled = debug_cfg.get("enabled", False)
        self.debug_redirect_to_self = debug_cfg.get("redirect_all_to_self", False)
        self.debug_self_user_id = debug_cfg.get("self_user_id", "")

        # Rate limiting
        rate_cfg = self.config.get("rate_limiting", {})
        self.rate_limiter = RateLimiter(
            window_seconds=rate_cfg.get("batch_window_seconds", 300),
            max_per_author=rate_cfg.get("max_per_author", 3),
        )

        # Event configs
        self.events = self.config.get("events", {})
        self.channels = self.config.get("channels", {})
        self.user_mapping = self.config.get("user_mapping", {})

        # Slack auth
        auth = self.slack_config.get("auth", {})
        self.xoxc_token = auth.get("xoxc_token", "")
        self.d_cookie = auth.get("d_cookie", "")
        self.workspace_host = auth.get("host", "redhat.enterprise.slack.com")

        # Pending notifications for batching
        self._pending: list[PendingNotification] = []
        self._client: Optional[httpx.AsyncClient] = None

        if self.debug_enabled and self.debug_redirect_to_self:
            logger.info(f"🔧 DEBUG MODE: all messages will be sent to {self.debug_self_user_id}")

    @classmethod
    def from_config(cls, config_path: Optional[Path] = None) -> "SkillHooks":
        """Load from config.json."""
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config.json"

        with open(config_path) as f:
            config = json.load(f)

        return cls(config)

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self.xoxc_token}",
                    "Cookie": f"d={self.d_cookie}",
                    "Content-Type": "application/json; charset=utf-8",
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self):
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _resolve_author_slack_id(self, gitlab_username: str) -> Optional[str]:
        """Map GitLab username to Slack user ID."""
        # Direct mapping
        if gitlab_username in self.user_mapping:
            result = self.user_mapping[gitlab_username]
            return str(result) if result else None

        # Check if it's already a Slack ID
        if gitlab_username.startswith("U") and len(gitlab_username) == 11:
            return gitlab_username

        logger.warning(f"no slack mapping for gitlab user: {gitlab_username}")
        return None

    def _format_message(self, template: str, context: dict) -> str:
        """Format message template with context."""
        try:
            return template.format(**context)
        except KeyError as e:
            logger.warning(f"missing template var: {e}")
            return template

    async def emit(self, event_type: str, context: dict):
        """
        Emit an event notification.

        Args:
            event_type: One of the configured event types
            context: Dict with template variables (mr_id, author, target_branch, etc.)
        """
        if not self.enabled:
            return

        event_cfg = self.events.get(event_type)
        if not event_cfg:
            logger.debug(f"unknown event type: {event_type}")
            return

        template = event_cfg.get("template", event_type)
        message = self._format_message(template, context)

        # Debug mode: redirect all messages to self
        if self.debug_enabled and self.debug_redirect_to_self and self.debug_self_user_id:
            debug_prefix = f"[DEBUG {event_type}] "
            if event_cfg.get("notify_author"):
                debug_prefix += f"(would DM: {context.get('author', 'unknown')}) "
            if event_cfg.get("notify_channel"):
                debug_prefix += f"(would post to: {self.channels.get('team', 'unknown')}) "

            await self._send_dm(self.debug_self_user_id, debug_prefix + message)
            logger.info(f"debug: sent {event_type} to self instead of real recipients")
            return

        # Notify author?
        if event_cfg.get("notify_author") and context.get("author"):
            author_id = self._resolve_author_slack_id(context["author"])
            if author_id and self.rate_limiter.can_send(author_id):
                await self._send_dm(author_id, message)
                self.rate_limiter.record(author_id)

        # Notify team channel?
        if event_cfg.get("notify_channel"):
            channel_id = self.channels.get("team")
            if channel_id:
                await self._send_channel(channel_id, message)

    async def _send_dm(self, user_id: str, message: str):
        """Send a DM to a user."""
        # First open/get DM channel
        dm_channel = await self._open_dm(user_id)
        if dm_channel:
            await self._post_message(dm_channel, message)

    async def _open_dm(self, user_id: str) -> Optional[str]:
        """Open a DM channel with a user."""
        try:
            client = self._get_client()
            url = f"https://{self.workspace_host}/api/conversations.open"

            resp = await client.post(url, json={"users": user_id})
            data: Dict[str, Any] = resp.json()

            if data.get("ok"):
                channel = data.get("channel", {})
                channel_id = channel.get("id") if isinstance(channel, dict) else None
                return str(channel_id) if channel_id else None
            else:
                logger.error(f"failed to open dm: {data.get('error')}")
                return None
        except Exception as e:
            logger.error(f"error opening dm: {e}")
            return None

    async def _send_channel(self, channel_id: str, message: str):
        """Send to a channel."""
        await self._post_message(channel_id, message)

    async def _post_message(self, channel: str, text: str):
        """Post a message to Slack."""
        try:
            client = self._get_client()
            url = f"https://{self.workspace_host}/api/chat.postMessage"

            resp = await client.post(
                url,
                json={
                    "channel": channel,
                    "text": text,
                    "unfurl_links": False,
                    "unfurl_media": False,
                },
            )
            data = resp.json()

            if not data.get("ok"):
                logger.error(f"failed to post message: {data.get('error')}")
            else:
                logger.debug(f"sent to {channel}: {text[:50]}...")

        except Exception as e:
            logger.error(f"error posting message: {e}")


# Convenience function for use in skills
_hooks_instance: Optional[SkillHooks] = None


async def emit_event(event_type: str, context: dict):
    """
    Emit a skill event notification.

    Example:
        await emit_event("review_approved", {
            "mr_id": "1449",
            "author": "daoneill",
            "project": "automation-analytics-backend"
        })
    """
    global _hooks_instance
    if _hooks_instance is None:
        _hooks_instance = SkillHooks.from_config()

    await _hooks_instance.emit(event_type, context)


def emit_event_sync(event_type: str, context: dict):
    """
    Synchronous wrapper for emit_event.

    For use in YAML skill compute blocks.
    """
    asyncio.run(emit_event(event_type, context))


if __name__ == "__main__":
    # Quick test
    import sys

    logging.basicConfig(level=logging.DEBUG)

    async def test():
        hooks = SkillHooks.from_config()

        # Test event
        await hooks.emit("review_approved", {"mr_id": "1449", "author": "daoneill", "target_branch": "main"})

        await hooks.close()

    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        asyncio.run(test())
    else:
        print("skill_hooks.py - event notification handler")
        print("usage: python skill_hooks.py --test")
