# pylint: disable=duplicate-code
"""Query and profile methods for SlackSession.

Split out so the session module stays within the module line limit.
"""

import json
import logging
import random
import time
import uuid
from typing import Any

import httpx

from tool_modules.aa_slack.src.slack_message_builder import (
    _shared_get_app_commands_summary,
    extract_from_block_element,
)
from tool_modules.aa_slack.src.slack_message_builder import (
    get_channel_sections_summary as channel_sections_summary,
)
from tool_modules.aa_slack.src.slack_message_builder import (
    simplify_channel_history as simplified_channel_history,
)

logger = logging.getLogger("tool_modules.aa_slack.src.slack_session")


class SlackSessionQuery:  # pylint: disable=no-member
    """Slack search, membership, and profile methods."""

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
                "Edge API user search error: %s - %s",
                e.response.status_code,
                e.response.text[:200],
            )
            raise ValueError(f"User search failed: {e.response.status_code}") from e
        except Exception as e:
            logger.error("User search error: %s", e)
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
                logger.error("Channel members list error: %s", error)
                raise ValueError(f"Channel members list failed: {error}")

            return result.get("results", [])

        except httpx.HTTPStatusError as e:
            logger.error(
                "Edge API error: %s - %s", e.response.status_code, e.response.text[:200]
            )
            raise ValueError(
                f"Channel members list failed: {e.response.status_code}"
            ) from e
        except Exception as e:
            logger.error("Channel members list error: %s", e)
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
                logger.error("Channel membership check error: %s", error)
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
                "Edge API error: %s - %s", e.response.status_code, e.response.text[:200]
            )
            raise ValueError(
                f"Channel membership check failed: {e.response.status_code}"
            ) from e
        except Exception as e:
            logger.error("Channel membership check error: %s", e)
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
        except Exception as e:  # pylint: disable=broad-exception-caught
            return {
                "success": False,
                "error": str(e),
                "channel_id": channel_id,
                "users": [],
            }

    async def get_channel_sections(  # pylint: disable=too-many-locals
        self,
    ) -> dict[str, Any]:  # pylint: disable=too-many-locals
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
                logger.error("Channel sections error: %s", error)
                return {"ok": False, "error": error, "channel_sections": []}

            return {
                "ok": True,
                "channel_sections": data.get("channel_sections", []),
                "last_updated": data.get("last_updated", 0),
                "count": data.get("count", 0),
            }

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Channel sections request failed: %s", e)
            return {"ok": False, "error": str(e), "channel_sections": []}

    def get_channel_sections_summary(self, data):
        """Summarize channel sections."""
        return channel_sections_summary(data)

    async def get_channel_history_rich(  # pylint: disable=too-many-locals
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
                logger.error("Channel history error: %s", error)
                return {"ok": False, "error": error, "messages": []}

            return {
                "ok": True,
                "messages": data.get("messages", []),
                "has_more": data.get("has_more", False),
                "oldest": data.get("oldest", ""),
                "latest": data.get("latest", ""),
            }

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Channel history request failed: %s", e)
            return {"ok": False, "error": str(e), "messages": []}

    def simplify_channel_history(self, data):
        """Simplify channel history for AI processing."""
        return simplified_channel_history(data)

    def _extract_from_block_element(self, element, mentions, links):
        """Recursively extract mentions and links from block elements."""
        extract_from_block_element(element, mentions, links)

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
        except Exception as e:  # pylint: disable=broad-exception-caught
            return {
                "success": False,
                "error": str(e),
                "query": query,
                "users": [],
            }

    async def get_app_commands(  # pylint: disable=too-many-locals
        self,
    ) -> dict[str, Any]:  # pylint: disable=too-many-locals
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
                logger.error("App commands error: %s", error)
                return {"ok": False, "error": error, "app_actions": [], "commands": []}

            return {
                "ok": True,
                "app_actions": data.get("app_actions", []),
                "commands": data.get("commands", []),
                "cache_ts": data.get("cache_ts", ""),
            }

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("App commands request failed: %s", e)
            return {"ok": False, "error": str(e), "app_actions": [], "commands": []}

    def get_app_commands_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        "Get app commands summary."
        return _shared_get_app_commands_summary(data)

    get_app_commands_summary.__doc__ = _shared_get_app_commands_summary.__doc__

    async def get_user_profile_sections(  # pylint: disable=too-many-locals
        self, user_id: str
    ) -> dict[str, Any]:  # pylint: disable=too-many-locals
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
            logger.error("Profile API error: %s", e.response.status_code)
            raise ValueError(f"Profile fetch failed: {e.response.status_code}") from e
        except Exception as e:
            logger.error("Profile fetch error: %s", e)
            raise

    async def get_user_profile_details(  # pylint: disable=too-many-locals
        self, user_id: str
    ) -> dict[str, Any]:  # pylint: disable=too-many-locals
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

        except Exception as e:  # pylint: disable=broad-exception-caught
            return {
                "success": False,
                "user_id": user_id,
                "error": str(e),
                "profile": {},
            }
