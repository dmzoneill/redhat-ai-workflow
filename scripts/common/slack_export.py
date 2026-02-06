"""Shared Slack export utilities.

This module provides common functionality for Slack message export scripts,
reducing duplication between run_slack_export.py and test scripts.

Usage:
    from scripts.common.slack_export import (
        create_slack_session,
        get_conversations_with_fallback,
        export_messages_to_jsonl,
    )

    # Create and validate session
    session = await create_slack_session()
    if not session:
        return

    # Get conversations (handles enterprise restrictions)
    conversations = await get_conversations_with_fallback(session)

    # Export messages
    await export_messages_to_jsonl(session, conversations, output_file)
"""

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass  # SlackSession imported dynamically

logger = logging.getLogger(__name__)

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
MEMORY_DIR = PROJECT_ROOT / "memory"
STYLE_DIR = MEMORY_DIR / "style"

# Ensure slack module is importable
_slack_path = PROJECT_ROOT / "tool_modules" / "aa_slack" / "src"
if str(_slack_path) not in sys.path:
    sys.path.insert(0, str(_slack_path))


def get_slack_config() -> dict[str, Any]:
    """Get Slack configuration from config.json.

    Returns:
        Slack config dict with auth credentials, or empty dict if not found
    """
    try:
        from server.utils import load_config

        config = load_config()
        return config.get("slack", {})
    except Exception as e:
        logger.error(f"Failed to load Slack config: {e}")
        return {}


async def create_slack_session(validate: bool = True) -> Any | None:
    """Create and optionally validate a Slack session.

    Args:
        validate: If True, validate the session after creation

    Returns:
        SlackSession instance if successful, None if credentials missing or validation fails
    """
    from slack_client import SlackSession

    slack_config = get_slack_config()
    auth = slack_config.get("auth", {})

    if not auth.get("xoxc_token"):
        logger.error("No Slack credentials found in config.json")
        return None

    session = SlackSession(
        xoxc_token=auth.get("xoxc_token", ""),
        d_cookie=auth.get("d_cookie", ""),
        workspace_id=auth.get("workspace_id", ""),
        enterprise_id=auth.get("enterprise_id", ""),
    )

    if validate:
        try:
            await session.validate_session()
            logger.info(f"Slack session validated, user_id: {session.user_id}")
        except Exception as e:
            logger.error(f"Slack session validation failed: {e}")
            return None

    return session


async def get_conversations_with_fallback(
    session: Any,
    types: str = "im,mpim,public_channel,private_channel",
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Get conversations, with fallback for enterprise restrictions.

    Enterprise Slack workspaces often restrict the users.conversations API.
    This function tries that first, then falls back to client.counts API.

    Args:
        session: SlackSession instance
        types: Comma-separated conversation types
        limit: Maximum conversations to fetch

    Returns:
        List of conversation dicts with at least 'id' key
    """
    conversations: list[dict[str, Any]] = []

    # Try users.conversations first
    try:
        conversations = await session.get_user_conversations(types=types, limit=limit)
        logger.info(f"Found {len(conversations)} conversations via users.conversations")
        return conversations
    except Exception as e:
        if "enterprise_is_restricted" not in str(e):
            logger.warning(f"users.conversations failed: {e}")
            # Don't fall back for non-enterprise errors
            raise

    # Fall back to client.counts API for enterprise workspaces
    logger.info("Enterprise restricted, trying client.counts API...")
    try:
        counts = await session.get_client_counts()

        if counts.get("ok"):
            # Build conversation list from counts
            for im in counts.get("ims", []):
                if isinstance(im, dict):
                    conversations.append({"id": im.get("id"), "is_im": True})
                else:
                    conversations.append({"id": im, "is_im": True})

            for mpim in counts.get("mpims", []):
                if isinstance(mpim, dict):
                    conversations.append({"id": mpim.get("id"), "is_mpim": True})
                else:
                    conversations.append({"id": mpim, "is_mpim": True})

            for channel in counts.get("channels", []):
                if isinstance(channel, dict):
                    conversations.append({"id": channel.get("id"), "is_channel": True})
                else:
                    conversations.append({"id": channel, "is_channel": True})

            logger.info(f"Found {len(conversations)} conversations via client.counts")

    except Exception as e:
        logger.error(f"client.counts API also failed: {e}")

    return conversations


async def export_messages_to_jsonl(
    session: Any,
    conversations: list[dict[str, Any]],
    output_file: Path,
    months: int = 1,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Export messages from conversations to a JSONL file.

    Args:
        session: SlackSession instance
        conversations: List of conversation dicts
        output_file: Path to output JSONL file
        months: Number of months of history to export
        user_id: User ID to filter messages (defaults to session user)

    Returns:
        Stats dict with message_count, conversation_count, etc.
    """
    if user_id is None:
        user_id = session.user_id

    # Calculate time range
    now = datetime.now()
    oldest_date = now - timedelta(days=months * 30)
    oldest_ts = str(oldest_date.timestamp())

    stats = {
        "message_count": 0,
        "conversation_count": 0,
        "skipped_conversations": 0,
        "errors": [],
    }

    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w") as f:
        for conv in conversations:
            conv_id = conv.get("id")
            if not conv_id:
                continue

            try:
                messages = await session.get_conversation_history(
                    channel=conv_id,
                    oldest=oldest_ts,
                    limit=1000,
                )

                # Filter to user's messages
                user_messages = [m for m in messages if m.get("user") == user_id]

                if user_messages:
                    stats["conversation_count"] += 1
                    for msg in user_messages:
                        f.write(json.dumps(msg) + "\n")
                        stats["message_count"] += 1
                else:
                    stats["skipped_conversations"] += 1

            except Exception as e:
                error_msg = f"Error fetching {conv_id}: {e}"
                logger.debug(error_msg)
                stats["errors"].append(error_msg)
                stats["skipped_conversations"] += 1

    logger.info(
        f"Exported {stats['message_count']} messages from "
        f"{stats['conversation_count']} conversations to {output_file}"
    )

    return stats
