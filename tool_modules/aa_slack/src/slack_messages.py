"""Slack messages mixin — send/receive/format messages."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SlackMessagesMixin:
    """Mixin for message operations on SlackSession."""

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
