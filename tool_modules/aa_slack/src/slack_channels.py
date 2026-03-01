"""Slack channels mixin — conversations, history, sections, app commands."""

from __future__ import annotations

import logging
import random
import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SlackChannelsMixin:
    """Mixin for channel/conversation operations on SlackSession."""

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
