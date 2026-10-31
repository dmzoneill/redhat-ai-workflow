# pylint: disable=duplicate-code
"""Messaging helpers for SlackSession."""

import asyncio
import json
import logging
import secrets
import time
import uuid
from typing import Any

import httpx

from tool_modules.aa_slack.src.slack_message_builder import extract_avatar_hash as avatar_hash_from_profile
from tool_modules.aa_slack.src.slack_message_builder import get_avatar_url as avatar_url_for
from tool_modules.aa_slack.src.slack_message_builder import parse_inline_elements, text_to_rich_blocks

# Non-cryptographic jitter/variety; SystemRandom avoids the predictable Mersenne Twister flagged by scanners
_RNG = secrets.SystemRandom()

logger = logging.getLogger("tool_modules.aa_slack.src.slack_session")


class SlackSessionMessaging:  # pylint: disable=no-member
    """Send, react, and search helpers for a Slack web session."""

    # Declared for mixins that read sibling state.
    SLACK_HOST: Any
    _extract_enterprise_id: Any
    _request: Any
    enterprise_id: Any
    get_client: Any
    workspace_id: Any
    xoxc_token: Any

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
            delay = _RNG.uniform(0.5, 2.5)
            logger.debug("Adding natural typing delay: %ss", format(delay, ".2f"))
            await asyncio.sleep(delay)

        data = {"channel": channel_id, "text": text}
        if thread_ts:
            data["thread_ts"] = thread_ts

        result: dict[str, Any] = await self._request("chat.postMessage", data)
        return result

    async def send_message_rich(  # pylint: disable=too-many-locals
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
            delay = _RNG.uniform(0.5, 2.5)
            logger.debug("Adding natural typing delay: %ss", format(delay, ".2f"))
            await asyncio.sleep(delay)

        # Get enterprise ID for routing
        eid = self.enterprise_id or self.workspace_id or self._extract_enterprise_id()

        # Build URL with query params
        x_id = f"{uuid.uuid4().hex[:8]}-{int(time.time())}.{_RNG.randint(100, 999)}"

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
        msg_ts = f"{int(time.time())}.{_RNG.randint(100000, 999999)}"

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
                logger.error("Send message error: %s", error)
                return {"ok": False, "error": error}

            return {
                "ok": True,
                "channel": data.get("channel", channel_id),
                "ts": data.get("ts", ""),
                "message": data.get("message", {}),
            }

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.exception("Send message request failed")
            return {"ok": False, "error": str(e)}

    def _text_to_rich_blocks(self, text):
        """Convert plain text to Slack rich text blocks."""
        return text_to_rich_blocks(text)

    def _parse_inline_elements(self, text):
        """Parse inline mentions, links, and styles."""
        return parse_inline_elements(text)

    async def add_reaction(
        self,
        channel_id: str,
        timestamp: str,
        emoji: str,
    ) -> dict[str, Any]:
        """Add a reaction to a message."""
        result: dict[str, Any] = await self._request(
            "reactions.add",
            {"channel": channel_id, "timestamp": timestamp, "name": emoji},
        )
        return result

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
        return str(channel.get("id", ""))

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
        user: dict[str, Any] = result.get("user", {})
        return user

    async def get_users_list(self, limit: int = 200) -> list[dict[str, Any]]:
        """Get list of all users in workspace."""
        result = await self._request("users.list", {"limit": limit})
        members: list[dict[str, Any]] = result.get("members", [])
        return members

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
        matches: list[dict[str, Any]] = result.get("messages", {}).get("matches", [])
        return matches

    async def search_channels(
        self,
        query,
        count=30,
        include_archived=False,
        check_membership=True,
    ):
        """Search for channels using Slack's edge API."""
        payload = {
            "query": query,
            "count": count,
            "fuzz": 1,
            "uax29_tokenizer": False,
            "include_record_channels": True,
            "check_membership": check_membership,
        }
        try:
            result = await self.edge_api_request("channels/search", payload)
        except ValueError as exc:
            message = str(exc)
            prefix = "Edge API request to channels/search failed:"
            if message.startswith(prefix):
                code = message[len(prefix) :].strip()
                raise ValueError(f"Channel search failed: {code}") from exc
            logger.error("Channel search error: %s", exc)
            raise
        except httpx.HTTPError as exc:
            logger.error("Channel search error: %s", exc)
            raise
        channels = result.get("results", [])
        if not include_archived:
            channels = [item for item in channels if not item.get("is_archived", False)]
        return channels

    def get_avatar_url(self, user_id, avatar_hash, size=512):
        """Construct a Slack avatar URL."""
        return avatar_url_for(
            user_id,
            avatar_hash,
            size,
            enterprise_id=self.enterprise_id,
            workspace_id=self.workspace_id,
        )

    def extract_avatar_hash(self, profile):
        """Extract an avatar hash from a user profile."""
        return avatar_hash_from_profile(profile)

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
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.debug("Channel search failed", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "query": query,
                "channels": [],
            }
