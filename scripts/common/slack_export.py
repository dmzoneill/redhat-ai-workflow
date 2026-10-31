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

import asyncio
import importlib
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from server import utils as server_utils

logger = logging.getLogger(__name__)

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
MEMORY_DIR = PROJECT_ROOT / "memory"
STYLE_DIR = MEMORY_DIR / "style"

# Ensure slack module is importable
_slack_path = PROJECT_ROOT / "tool_modules" / "aa_slack" / "src"
if str(_slack_path) not in sys.path:
    sys.path.insert(0, str(_slack_path))

# Errors the Slack session raises for API/transport failures
_SLACK_ERRORS = (ValueError, KeyError, httpx.HTTPError)

# Keys in a client.counts response and the flag each conversation type gets
_COUNTS_KINDS = (("ims", "is_im"), ("mpims", "is_mpim"), ("channels", "is_channel"))


@dataclass
class _ExportStats:
    """Running totals for an export."""

    message_count: int = 0
    conversation_count: int = 0
    skipped_conversations: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Return the stats in the historical dict shape."""
        return {
            "message_count": self.message_count,
            "conversation_count": self.conversation_count,
            "skipped_conversations": self.skipped_conversations,
            "errors": self.errors,
        }


def get_slack_config() -> dict[str, Any]:
    """Get Slack configuration from config.json.

    Returns:
        Slack config dict with auth credentials, or empty dict if not found
    """
    try:
        slack: dict[str, Any] = server_utils.load_config().get("slack", {})
    except (OSError, ValueError):
        logger.exception("Failed to load Slack config")
        return {}
    return slack


async def create_slack_session(validate: bool = True) -> Any | None:
    """Create and optionally validate a Slack session.

    Args:
        validate: If True, validate the session after creation

    Returns:
        SlackSession instance if successful, None if credentials missing or validation fails
    """
    slack_session_cls = importlib.import_module("slack_client").SlackSession

    slack_config = get_slack_config()
    auth = slack_config.get("auth", {})

    if not auth.get("xoxc_token"):
        logger.error("No Slack credentials found in config.json")
        return None

    session = slack_session_cls(
        xoxc_token=auth.get("xoxc_token", ""),
        d_cookie=auth.get("d_cookie", ""),
        workspace_id=auth.get("workspace_id", ""),
        enterprise_id=auth.get("enterprise_id", ""),
    )

    if validate:
        try:
            await session.validate_session()
            logger.info("Slack session validated, user_id: %s", session.user_id)
        except _SLACK_ERRORS:
            logger.exception("Slack session validation failed")
            return None

    return session


def _conversations_from_counts(counts: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a conversation list from a client.counts API response."""
    conversations: list[dict[str, Any]] = []
    for key, flag in _COUNTS_KINDS:
        for entry in counts.get(key, []):
            conv_id = entry.get("id") if isinstance(entry, dict) else entry
            conversations.append({"id": conv_id, flag: True})
    return conversations


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
    # Try users.conversations first
    try:
        conversations: list[dict[str, Any]] = await session.get_user_conversations(types=types, limit=limit)
        logger.info("Found %d conversations via users.conversations", len(conversations))
        return conversations
    except _SLACK_ERRORS as e:
        if "enterprise_is_restricted" not in str(e):
            logger.warning("users.conversations failed: %s", e)
            # Don't fall back for non-enterprise errors
            raise

    # Fall back to client.counts API for enterprise workspaces
    logger.info("Enterprise restricted, trying client.counts API...")
    try:
        counts = await session.get_client_counts()
    except _SLACK_ERRORS:
        logger.exception("client.counts API also failed")
        return []

    if not counts.get("ok"):
        return []
    conversations = _conversations_from_counts(counts)
    logger.info("Found %d conversations via client.counts", len(conversations))
    return conversations


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Write records to a JSON-lines file (run via asyncio.to_thread)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(record) + "\n" for record in records)


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
    oldest_ts = str((datetime.now().astimezone() - timedelta(days=months * 30)).timestamp())

    stats = _ExportStats()
    exported: list[dict[str, Any]] = []

    for conv in conversations:
        conv_id = conv.get("id")
        if not conv_id:
            continue

        try:
            messages = await session.get_conversation_history(channel=conv_id, oldest=oldest_ts, limit=1000)
        except _SLACK_ERRORS as e:
            logger.debug("Error fetching %s", conv_id, exc_info=True)
            stats.errors.append(f"Error fetching {conv_id}: {e}")
            stats.skipped_conversations += 1
            continue

        # Filter to user's messages
        user_messages = [m for m in messages if m.get("user") == user_id]
        if user_messages:
            stats.conversation_count += 1
            stats.message_count += len(user_messages)
            exported.extend(user_messages)
        else:
            stats.skipped_conversations += 1

    await asyncio.to_thread(_write_jsonl, output_file, exported)

    logger.info(
        "Exported %d messages from %d conversations to %s",
        stats.message_count,
        stats.conversation_count,
        output_file,
    )

    return stats.as_dict()
