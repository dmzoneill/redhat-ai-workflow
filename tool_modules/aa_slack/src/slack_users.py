"""Slack users mixin — profiles, search, membership."""

from __future__ import annotations

import json
import logging
import random
import time
import uuid
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SlackUsersMixin:
    """Mixin for user operations on SlackSession."""

    async def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Get information about a user."""
        result = await self._request("users.info", {"user": user_id})
        return result.get("user", {})

    async def get_users_list(self, limit: int = 200) -> list[dict[str, Any]]:
        """Get list of all users in workspace."""
        result = await self._request("users.list", {"limit": limit})
        return result.get("members", [])

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
