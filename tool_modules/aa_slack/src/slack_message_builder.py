"""Slack Message Builder — formatting, rich blocks, and data extraction.

Extracted from SlackSession to separate message construction and parsing
from HTTP transport concerns. All methods are pure functions or lightweight
data transformers that operate on dicts — they need no network access.
"""

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# Emoji shortcode → Unicode map used by rich text block builder
EMOJI_MAP: dict[str, str] = {
    ":wrench:": "\U0001f527",
    ":hammer:": "\U0001f528",
    ":gear:": "\u2699\ufe0f",
    ":rocket:": "\U0001f680",
    ":warning:": "\u26a0\ufe0f",
    ":x:": "\u274c",
    ":white_check_mark:": "\u2705",
    ":heavy_check_mark:": "\u2714\ufe0f",
    ":information_source:": "\u2139\ufe0f",
    ":bulb:": "\U0001f4a1",
    ":memo:": "\U0001f4dd",
    ":package:": "\U0001f4e6",
    ":fire:": "\U0001f525",
    ":bug:": "\U0001f41b",
    ":zap:": "\u26a1",
    ":star:": "\u2b50",
    ":tada:": "\U0001f389",
    ":eyes:": "\U0001f440",
    ":thumbsup:": "\U0001f44d",
    ":thumbsdown:": "\U0001f44e",
    ":rotating_light:": "\U0001f6a8",
    ":lock:": "\U0001f512",
    ":key:": "\U0001f511",
    ":link:": "\U0001f517",
    ":clipboard:": "\U0001f4cb",
    ":calendar:": "\U0001f4c5",
    ":clock:": "\U0001f550",
    ":hourglass:": "\u23f3",
    ":mag:": "\U0001f50d",
    ":chart_with_upwards_trend:": "\U0001f4c8",
    ":chart_with_downwards_trend:": "\U0001f4c9",
    ":construction:": "\U0001f6a7",
    ":hammer_and_wrench:": "\U0001f6e0\ufe0f",
    ":test_tube:": "\U0001f9ea",
    ":microscope:": "\U0001f52c",
    ":speech_balloon:": "\U0001f4ac",
    ":thought_balloon:": "\U0001f4ad",
    ":bell:": "\U0001f514",
    ":no_bell:": "\U0001f515",
    ":loudspeaker:": "\U0001f4e2",
    ":mega:": "\U0001f4e3",
}


# ---------------------------------------------------------------------------
# Rich text block building
# ---------------------------------------------------------------------------


def text_to_rich_blocks(text: str) -> list[dict[str, Any]]:
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
    text = text.replace("\\n", "\n")

    # Convert common emoji shortcodes to Unicode
    for shortcode, unicode_emoji in EMOJI_MAP.items():
        text = text.replace(shortcode, unicode_emoji)

    elements: list[dict[str, Any]] = []
    current_text = ""

    # Split by code blocks first
    code_block_pattern = r"```([^`]*?)```"
    parts = re.split(code_block_pattern, text, flags=re.DOTALL)

    for i, part in enumerate(parts):
        if i % 2 == 1:
            # This is a code block
            if current_text:
                elements.extend(parse_inline_elements(current_text))
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
        elements.extend(parse_inline_elements(current_text))

    # Wrap in rich_text block
    if not elements:
        elements = [
            {"type": "rich_text_section", "elements": [{"type": "text", "text": text}]}
        ]

    return [{"type": "rich_text", "elements": elements}]


def parse_inline_elements(text: str) -> list[dict[str, Any]]:
    """Parse inline elements (mentions, links, inline code, bold, italic) from text."""
    if not text.strip():
        return []

    elements: list[dict[str, Any]] = []
    section_elements: list[dict[str, Any]] = []

    # Pattern for user mentions, channel mentions, links, inline code, bold, and italic
    pattern = r"(<@U[A-Z0-9]+>|<#C[A-Z0-9]+(?:\|[^>]*)?>|<https?://[^|>]+(?:\|[^>]*)?>|`[^`]+`|\*[^*\n]+\*|_[^_\n]+_)"

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


# ---------------------------------------------------------------------------
# Data extraction helpers
# ---------------------------------------------------------------------------


def extract_from_element(
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
                extract_from_element(sub, mentioned_users, links, code_blocks)


def extract_from_block_element(
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
    elif elem_type in ("rich_text_section", "rich_text_preformatted", "rich_text_list"):
        for sub in element.get("elements", []):
            extract_from_block_element(sub, mentions, links)


# ---------------------------------------------------------------------------
# History / response simplification
# ---------------------------------------------------------------------------


def simplify_channel_history(data: dict[str, Any]) -> dict[str, Any]:
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
        text = msg.get("text", "")

        # Get thread info
        thread_ts = msg.get("thread_ts", "")
        is_thread_parent = thread_ts == msg.get("ts", "")
        reply_count = msg.get("reply_count", 0) if is_thread_parent else 0

        # Extract mentions from blocks
        mentions: list[str] = []
        links: list[str] = []
        for block in msg.get("blocks", []):
            for element in block.get("elements", []):
                extract_from_block_element(element, mentions, links)

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


def get_channel_sections_summary(data: dict[str, Any]) -> dict[str, Any]:
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
    all_channel_ids: list[str] = []

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


def get_app_commands_summary(data: dict[str, Any]) -> dict[str, Any]:
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


# ---------------------------------------------------------------------------
# Avatar helpers
# ---------------------------------------------------------------------------


def get_avatar_url(
    user_id: str,
    avatar_hash: str,
    size: int = 512,
    enterprise_id: str = "",
    workspace_id: str = "",
) -> str:
    """
    Construct a Slack avatar URL from user ID and avatar hash.

    Avatar URLs follow the pattern:
    https://ca.slack-edge.com/{enterprise_id}-{user_id}-{avatar_hash}-{size}

    Args:
        user_id: Slack user ID (e.g., U04RA3VE2RZ)
        avatar_hash: Avatar hash from profile (e.g., 4d88f1ddb848)
        size: Image size in pixels (512, 192, 72, 48, 32)
        enterprise_id: Enterprise ID for URL construction
        workspace_id: Fallback workspace ID

    Returns:
        Full avatar URL or empty string if hash is missing
    """
    if not avatar_hash:
        return ""

    eid = enterprise_id or workspace_id or os.getenv("SLACK_ENTERPRISE_ID", "")
    if not eid:
        return ""

    return f"https://ca.slack-edge.com/{eid}-{user_id}-{avatar_hash}-{size}"


def extract_avatar_hash(profile: dict[str, Any]) -> str:
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
            parts = url.split("/")
            if parts:
                last_part = parts[-1]
                if "-" in last_part and not last_part.endswith(".jpg"):
                    segments = last_part.split("-")
                    if len(segments) >= 3:
                        return segments[-2]
                elif "_" in last_part:
                    segments = (
                        last_part.replace(".jpg", "").replace(".png", "").split("_")
                    )
                    if len(segments) >= 2:
                        return segments[1]

    return ""
