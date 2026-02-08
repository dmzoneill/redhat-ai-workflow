"""
Message-related D-Bus handler logic for Slack daemon.

Extracted from dbus.py to reduce class size. Contains business logic
for message sending, approval, history, search, and thread operations.

All functions take the daemon as first argument and return JSON-serializable
dicts. The D-Bus @method() wrappers in dbus.py delegate here.
"""

import asyncio
import logging
import time

from services.slack.dbus_formatters import (
    check_search_rate_limit,
    format_search_results,
    record_search,
)

logger = logging.getLogger(__name__)


# ==================== Status / Approval ====================


def handle_get_status(daemon) -> dict:
    """Get daemon status as JSON dict."""
    listener_stats = {}
    if hasattr(daemon, "listener") and daemon.listener:
        listener_stats = getattr(daemon.listener, "stats", {})

    return {
        "running": daemon.is_running,
        "uptime": (time.time() - daemon.start_time if daemon.start_time else 0),
        "messages_processed": daemon.messages_processed,
        "messages_responded": daemon.messages_responded,
        "pending_approvals": len(daemon.history.pending_approvals),
        "polls": listener_stats.get("polls", 0),
        "errors": listener_stats.get("errors", 0),
        "consecutive_errors": listener_stats.get("consecutive_errors", 0),
        "messages_seen": listener_stats.get("messages_seen", 0),
    }


def handle_get_pending(daemon) -> list[dict]:
    """Get pending approval messages."""
    pending = daemon.history.get_pending()
    return [m.to_dict() for m in pending]


def handle_approve_message(daemon, message_id: str) -> dict:
    """Approve a pending message and send it (sync, blocks D-Bus thread)."""
    loop = daemon._event_loop
    future = asyncio.run_coroutine_threadsafe(daemon.approve_message(message_id), loop)
    try:
        result = future.result(timeout=30)
    except TimeoutError:
        logger.error(f"ApproveMessage timed out after 30s for message_id={message_id}")
        return {"success": False, "error": "Approval timed out after 30 seconds"}
    except Exception as e:
        logger.error(f"ApproveMessage failed for message_id={message_id}: {e}")
        return {"success": False, "error": str(e)}
    return result


def handle_reject_message(daemon, message_id: str) -> dict:
    """Reject a pending message."""
    record = daemon.history.reject(message_id)
    if record:
        return {"success": True, "message_id": message_id}
    return {"success": False, "error": "Message not found"}


def handle_approve_all(daemon) -> dict:
    """Approve all pending messages (sync, blocks D-Bus thread)."""
    loop = daemon._event_loop
    future = asyncio.run_coroutine_threadsafe(daemon.approve_all_pending(), loop)
    try:
        result = future.result(timeout=60)
    except TimeoutError:
        logger.error("ApproveAll timed out after 60s")
        return {"success": False, "error": "Approval timed out after 60 seconds"}
    except Exception as e:
        logger.error(f"ApproveAll failed: {e}")
        return {"success": False, "error": str(e)}
    return result


# ==================== Message History ====================


def handle_get_history(
    daemon, limit: int, channel_id: str, user_id: str, status: str
) -> list[dict]:
    """Get message history with optional filters."""
    history = daemon.history.get_history(
        limit=limit,
        channel_id=channel_id,
        user_id=user_id,
        status=status,
    )
    return [m.to_dict() for m in history]


# ==================== Message Sending ====================


def handle_send_message(daemon, channel_id: str, text: str, thread_ts: str) -> dict:
    """Send a message to Slack (fire-and-forget)."""
    loop = daemon._event_loop
    if not loop or not daemon.session:
        return {"success": False, "error": "Session not available"}

    async def do_send():
        try:
            result = await daemon.session.send_message(
                channel_id=channel_id,
                text=text,
                thread_ts=thread_ts if thread_ts else None,
                typing_delay=True,
            )
            logger.info(
                f"D-Bus SendMessage completed: ts={result.get('ts', 'unknown')}"
            )
            return result
        except Exception as e:
            logger.error(f"D-Bus SendMessage failed: {e}")
            return {"success": False, "error": str(e)}

    future = asyncio.run_coroutine_threadsafe(do_send(), loop)

    def _on_send_done(fut):
        exc = fut.exception()
        if exc is not None:
            logger.error(f"D-Bus SendMessage background task failed: {exc}")

    future.add_done_callback(_on_send_done)

    return {"success": True, "message": "Message send scheduled", "async": True}


async def handle_send_message_rich(
    daemon, channel_id: str, text: str, thread_ts: str, reply_broadcast: bool
) -> dict:
    """Send a message using the web client API format with rich text blocks."""
    if not daemon.session:
        return {"success": False, "error": "Session not available"}

    try:
        result = await daemon.session.send_message_rich(
            channel_id=channel_id,
            text=text,
            thread_ts=thread_ts if thread_ts else None,
            reply_broadcast=reply_broadcast,
            typing_delay=True,
        )

        if result.get("ok"):
            return {
                "success": True,
                "channel": result.get("channel", channel_id),
                "ts": result.get("ts", ""),
                "message": result.get("message", {}),
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
            }
    except Exception as e:
        logger.error(f"SendMessageRich error: {e}")
        return {"success": False, "error": str(e)}


# ==================== Search ====================


async def handle_search_messages(daemon, query: str, max_results: int) -> dict:
    """Search Slack messages with rate limiting."""
    if not daemon.session:
        return {"success": False, "error": "Session not available", "messages": []}

    max_results = min(max_results, 50) if max_results > 0 else 20

    try:
        if not hasattr(daemon, "_search_rate_limit"):
            daemon._search_rate_limit = {
                "last_search": 0,
                "daily_count": 0,
                "daily_reset": time.time(),
            }

        rl = daemon._search_rate_limit

        rate_limit_error = check_search_rate_limit(rl)
        if rate_limit_error:
            return rate_limit_error

        record_search(rl)

        results = await daemon.session.search_messages(
            query=query,
            count=max_results,
        )

        return format_search_results(query, results, rl["daily_count"])
    except Exception as e:
        logger.error(f"SearchMessages error: {e}")
        return {"success": False, "error": str(e), "messages": []}


# ==================== Thread Operations ====================


async def handle_get_thread_replies(
    daemon, channel_id: str, thread_ts: str, limit: int
) -> dict:
    """Get thread replies using the enhanced web client API."""
    if not daemon.session:
        return {"success": False, "error": "Session not available", "messages": []}

    try:
        limit = min(max(limit, 1), 100)
        result = await daemon.session.get_thread_replies_full(
            channel_id, thread_ts, limit
        )

        if not result.get("ok"):
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
                "messages": [],
            }

        return {
            "success": True,
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "count": len(result.get("messages", [])),
            "has_more": result.get("has_more", False),
            "messages": result.get("messages", []),
        }
    except Exception as e:
        logger.error(f"GetThreadReplies error: {e}")
        return {"success": False, "error": str(e), "messages": []}


async def handle_get_thread_context(daemon, channel_id: str, thread_ts: str) -> dict:
    """Get thread context in a simplified format for AI processing."""
    if not daemon.session:
        return {"success": False, "error": "Session not available"}

    try:
        result = await daemon.session.get_thread_context(channel_id, thread_ts)

        if not result.get("ok"):
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
            }

        return {"success": True, **result}
    except Exception as e:
        logger.error(f"GetThreadContext error: {e}")
        return {"success": False, "error": str(e)}


# ==================== Channel History ====================


async def handle_get_channel_history(
    daemon,
    channel_id: str,
    limit: int,
    oldest: str,
    latest: str,
    simplify: bool,
) -> dict:
    """Get message history for a channel."""
    if not daemon.session:
        return {"success": False, "error": "Session not available"}

    try:
        limit = max(1, min(limit or 50, 100))

        result = await daemon.session.get_channel_history_rich(
            channel_id=channel_id,
            limit=limit,
            oldest=oldest or "",
            latest=latest or "",
        )

        if not result.get("ok"):
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
            }

        if simplify:
            simplified = daemon.session.simplify_channel_history(result)
            return {"success": True, **simplified}
        else:
            return {
                "success": True,
                "messages": result.get("messages", []),
                "has_more": result.get("has_more", False),
            }
    except Exception as e:
        logger.error(f"GetChannelHistory error: {e}")
        return {"success": False, "error": str(e)}
