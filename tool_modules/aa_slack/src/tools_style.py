"""Slack Style Export Tools.

Provides MCP tools for exporting Slack messages for style analysis:
- slack_export_my_messages: Export your messages for persona training
- slack_export_status: Check export progress
- slack_export_cancel: Cancel an in-progress export
"""

import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import load_config

# Setup project path for server imports FIRST
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization

logger = logging.getLogger(__name__)

# Add current directory to sys.path
_TOOLS_DIR = Path(__file__).parent.absolute()
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

TOOL_MODULES_DIR = _TOOLS_DIR.parent.parent  # tool_modules/
MEMORY_DIR = PROJECT_ROOT / "memory"
STYLE_DIR = MEMORY_DIR / "style"


def _get_slack_config() -> dict:
    """Get Slack configuration from config.json."""
    config = load_config()
    return config.get("slack", {})


async def _get_slack_session():
    """Get or create a Slack session."""
    from slack_client import SlackSession

    config = _get_slack_config()
    auth = config.get("auth", {})

    return SlackSession(
        xoxc_token=auth.get("xoxc_token", ""),
        d_cookie=auth.get("d_cookie", ""),
        workspace_id=auth.get("workspace_id", ""),
        enterprise_id=auth.get("enterprise_id", ""),
    )


# Export state tracking
_export_state: dict[str, Any] = {
    "running": False,
    "cancelled": False,
    "progress": {},
    "start_time": None,
    "task": None,
}


def register_tools(server: FastMCP) -> int:  # noqa: C901
    """
    Register Slack style export tools with the MCP server.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    registry = ToolRegistry(server)
    mcp = server  # Alias for compatibility

    @mcp.tool()
    @auto_heal()
    async def slack_export_my_messages(
        months: int = 6,
        include_dms: bool = True,
        include_channels: bool = True,
        include_groups: bool = True,
        include_threads: bool = True,
        output_format: str = "jsonl",
    ) -> str:
        """
        Export your Slack messages for style analysis and persona training.

        This tool fetches your message history from Slack and saves it for
        analysis. The export respects rate limits and can be resumed if
        interrupted.

        Args:
            months: Number of months of history to export (default: 6)
            include_dms: Include direct messages (default: True)
            include_channels: Include public/private channels (default: True)
            include_groups: Include group DMs/MPIMs (default: True)
            include_threads: Include thread replies (default: True)
            output_format: Output format - "jsonl" or "yaml" (default: jsonl)

        Returns:
            Status message with export results or progress
        """
        global _export_state

        if _export_state["running"]:
            progress = _export_state["progress"]
            return (
                "⏳ Export already in progress\n"
                f"Started: {_export_state['start_time']}\n"
                f"Channels processed: {progress.get('channels_done', 0)}/{progress.get('channels_total', '?')}\n"
                f"Messages exported: {progress.get('messages', 0)}\n"
                "Use `slack_export_status` for detailed progress or `slack_export_cancel` to stop."
            )

        # Initialize export state
        _export_state = {
            "running": True,
            "cancelled": False,
            "progress": {
                "channels_done": 0,
                "channels_total": 0,
                "messages": 0,
                "my_messages": 0,
                "errors": [],
                "current_channel": "",
            },
            "start_time": datetime.now().isoformat(),
            "task": None,
        }

        try:
            # Ensure style directory exists
            STYLE_DIR.mkdir(parents=True, exist_ok=True)

            # Get Slack session
            session = await _get_slack_session()
            await session.validate_session()
            my_user_id = session.user_id

            if not my_user_id:
                _export_state["running"] = False
                return (
                    "❌ Could not determine your Slack user ID. Check authentication."
                )

            # Calculate time range
            now = datetime.now()
            oldest_date = now - timedelta(days=months * 30)
            oldest_ts = str(oldest_date.timestamp())

            # Output file
            output_file = STYLE_DIR / f"slack_corpus.{output_format}"
            context_file = STYLE_DIR / "slack_corpus_context.jsonl"

            # Get conversations to export
            conversations = []

            # Build conversation type filter
            conv_types = []
            if include_dms:
                conv_types.append("im")
            if include_groups:
                conv_types.append("mpim")
            if include_channels:
                conv_types.extend(["public_channel", "private_channel"])

            if not conv_types:
                _export_state["running"] = False
                return "❌ No conversation types selected. Enable at least one of: DMs, channels, groups."

            # Try to get conversations using client.counts (works around enterprise_is_restricted)
            try:
                logger.info("Fetching conversations via client.counts API...")
                counts = await session.get_client_counts()

                if counts.get("ok"):
                    # Build conversation list from counts
                    if include_dms:
                        for im in counts.get("ims", []):
                            if isinstance(im, dict):
                                conversations.append(
                                    {"id": im.get("id"), "is_im": True}
                                )
                            else:
                                conversations.append({"id": im, "is_im": True})

                    if include_groups:
                        for mpim in counts.get("mpims", []):
                            if isinstance(mpim, dict):
                                conversations.append(
                                    {"id": mpim.get("id"), "is_mpim": True}
                                )
                            else:
                                conversations.append({"id": mpim, "is_mpim": True})

                    if include_channels:
                        for channel in counts.get("channels", []):
                            if isinstance(channel, dict):
                                conversations.append(
                                    {"id": channel.get("id"), "is_channel": True}
                                )
                            else:
                                conversations.append(
                                    {"id": channel, "is_channel": True}
                                )

                    logger.info(
                        f"Found {len(conversations)} conversations via client.counts"
                    )
                else:
                    logger.warning(f"client.counts failed: {counts.get('error')}")
            except Exception as e:
                logger.warning(f"client.counts failed: {e}")

            # Fallback to standard APIs if client.counts didn't work
            if not conversations:
                logger.info("Trying standard conversation APIs...")
                types_str = ",".join(conv_types)
                try:
                    conversations = await session.get_user_conversations(
                        types=types_str, limit=500
                    )
                except Exception as e:
                    logger.warning(
                        f"get_user_conversations failed: {e}, trying web API"
                    )
                    try:
                        conversations = await session.get_user_conversations_web(
                            types=types_str, limit=500
                        )
                    except Exception as e2:
                        logger.warning(f"get_user_conversations_web failed: {e2}")

            if not conversations:
                _export_state["running"] = False
                return "❌ Could not fetch conversation list. Check Slack permissions."

            _export_state["progress"]["channels_total"] = len(conversations)

            # Export messages
            total_messages = 0
            my_messages = 0

            with (
                open(output_file, "w", encoding="utf-8") as f_out,
                open(context_file, "w", encoding="utf-8") as f_ctx,
            ):
                for conv in conversations:
                    if _export_state["cancelled"]:
                        break

                    channel_id = conv.get("id", "")
                    channel_name = conv.get("name", conv.get("user", channel_id))
                    channel_type = _get_channel_type(conv)

                    _export_state["progress"]["current_channel"] = channel_name

                    try:
                        # Fetch messages with pagination
                        channel_messages = []

                        while True:
                            if _export_state["cancelled"]:
                                break

                            # Fetch batch
                            messages = await session.get_channel_history(
                                channel_id=channel_id,
                                limit=100,
                                oldest=oldest_ts,
                            )

                            if not messages:
                                break

                            channel_messages.extend(messages)
                            total_messages += len(messages)
                            _export_state["progress"]["messages"] = total_messages

                            # Check if we have more (pagination)
                            # The API returns messages newest-first, so if we got fewer than limit, we're done
                            if len(messages) < 100:
                                break

                            # Get oldest message timestamp for next batch
                            oldest_msg_ts = messages[-1].get("ts", "")
                            if oldest_msg_ts:
                                # Fetch older messages
                                messages = await session.get_channel_history(
                                    channel_id=channel_id,
                                    limit=100,
                                    latest=oldest_msg_ts,
                                    oldest=oldest_ts,
                                    inclusive=False,
                                )
                                if not messages:
                                    break
                                channel_messages.extend(messages)
                                total_messages += len(messages)
                            else:
                                break

                            # Rate limit protection
                            await asyncio.sleep(0.5)

                        # Process messages - filter to my messages
                        for msg in channel_messages:
                            msg_user = msg.get("user", "")
                            msg_text = msg.get("text", "")
                            msg_ts = msg.get("ts", "")
                            thread_ts = msg.get("thread_ts", "")

                            if msg_user == my_user_id and msg_text:
                                # This is my message
                                my_messages += 1
                                _export_state["progress"]["my_messages"] = my_messages

                                # Find context (what I was replying to)
                                reply_to = None
                                if thread_ts and thread_ts != msg_ts:
                                    # This is a thread reply - find parent
                                    for parent_msg in channel_messages:
                                        if parent_msg.get("ts") == thread_ts:
                                            reply_to = {
                                                "user": parent_msg.get("user", ""),
                                                "text": parent_msg.get("text", "")[
                                                    :500
                                                ],
                                            }
                                            break

                                # Build export record
                                record = {
                                    "text": msg_text,
                                    "ts": msg_ts,
                                    "channel_type": channel_type,
                                    "channel_id": channel_id,
                                    "is_thread_reply": bool(
                                        thread_ts and thread_ts != msg_ts
                                    ),
                                    "reply_to": reply_to,
                                    "reactions": msg.get("reactions", []),
                                    "has_attachments": bool(
                                        msg.get("files") or msg.get("attachments")
                                    ),
                                }

                                if output_format == "jsonl":
                                    f_out.write(json.dumps(record) + "\n")
                                else:
                                    # YAML format - one doc per message
                                    import yaml

                                    f_out.write("---\n")
                                    yaml.dump(record, f_out, default_flow_style=False)

                            elif msg_text:
                                # Context message (not mine) - save for context analysis
                                ctx_record = {
                                    "user": msg_user,
                                    "text": msg_text[:500],
                                    "ts": msg_ts,
                                    "channel_id": channel_id,
                                }
                                f_ctx.write(json.dumps(ctx_record) + "\n")

                        # Fetch thread replies if enabled
                        if include_threads:
                            for msg in channel_messages:
                                if _export_state["cancelled"]:
                                    break

                                thread_ts = msg.get("thread_ts", msg.get("ts"))
                                reply_count = msg.get("reply_count", 0)

                                if reply_count > 0 and thread_ts:
                                    try:
                                        replies = await session.get_thread_replies(
                                            channel_id=channel_id,
                                            thread_ts=thread_ts,
                                            limit=100,
                                        )

                                        for reply in replies:
                                            if reply.get(
                                                "user"
                                            ) == my_user_id and reply.get("text"):
                                                my_messages += 1
                                                _export_state["progress"][
                                                    "my_messages"
                                                ] = my_messages

                                                record = {
                                                    "text": reply.get("text", ""),
                                                    "ts": reply.get("ts", ""),
                                                    "channel_type": channel_type,
                                                    "channel_id": channel_id,
                                                    "is_thread_reply": True,
                                                    "thread_ts": thread_ts,
                                                    "reply_to": {
                                                        "user": msg.get("user", ""),
                                                        "text": msg.get("text", "")[
                                                            :500
                                                        ],
                                                    },
                                                    "reactions": reply.get(
                                                        "reactions", []
                                                    ),
                                                    "has_attachments": bool(
                                                        reply.get("files")
                                                        or reply.get("attachments")
                                                    ),
                                                }

                                                if output_format == "jsonl":
                                                    f_out.write(
                                                        json.dumps(record) + "\n"
                                                    )
                                                else:
                                                    import yaml

                                                    f_out.write("---\n")
                                                    yaml.dump(
                                                        record,
                                                        f_out,
                                                        default_flow_style=False,
                                                    )

                                        await asyncio.sleep(0.3)  # Rate limit
                                    except Exception as e:
                                        logger.debug(
                                            f"Could not fetch thread {thread_ts}: {e}"
                                        )

                    except Exception as e:
                        error_msg = f"Error processing {channel_name}: {e}"
                        logger.warning(error_msg)
                        _export_state["progress"]["errors"].append(error_msg)

                    _export_state["progress"]["channels_done"] += 1

                    # Rate limit between channels
                    await asyncio.sleep(0.5)

            # Calculate duration
            start_time = datetime.fromisoformat(_export_state["start_time"])
            duration = datetime.now() - start_time
            duration_str = str(duration).split(".")[0]  # Remove microseconds

            # Write metadata
            metadata = {
                "export_date": datetime.now().isoformat(),
                "months_exported": months,
                "total_messages_scanned": total_messages,
                "my_messages_exported": my_messages,
                "channels_processed": _export_state["progress"]["channels_done"],
                "duration": duration_str,
                "user_id": my_user_id,
                "include_dms": include_dms,
                "include_channels": include_channels,
                "include_groups": include_groups,
                "include_threads": include_threads,
                "errors": _export_state["progress"]["errors"],
            }

            metadata_file = STYLE_DIR / "export_metadata.json"
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)

            _export_state["running"] = False

            cancelled_note = " (cancelled early)" if _export_state["cancelled"] else ""

            return (
                f"✅ Export complete{cancelled_note}\n\n"
                "**Results:**\n"
                f"- Your messages: {my_messages:,}\n"
                f"- Total scanned: {total_messages:,}\n"
                f"- Channels: {_export_state['progress']['channels_done']}\n"
                f"- Duration: {duration_str}\n"
                f"- Errors: {len(_export_state['progress']['errors'])}\n\n"
                "**Files:**\n"
                f"- Corpus: `{output_file}`\n"
                f"- Context: `{context_file}`\n"
                f"- Metadata: `{metadata_file}`\n\n"
                "Next step: Run `style_analyze` to analyze your writing patterns."
            )

        except Exception as e:
            _export_state["running"] = False
            logger.exception("Export failed")
            return f"❌ Export failed: {e}"

    @mcp.tool()
    @auto_heal()
    async def slack_export_status() -> str:
        """
        Check the status of an in-progress Slack message export.

        Returns:
            Current export status and progress
        """
        if not _export_state["running"]:
            # Check if we have previous export data
            metadata_file = STYLE_DIR / "export_metadata.json"
            if metadata_file.exists():
                with open(metadata_file, encoding="utf-8") as f:
                    metadata = json.load(f)
                return (
                    "No export in progress.\n\n"
                    "**Last export:**\n"
                    f"- Date: {metadata.get('export_date', 'unknown')}\n"
                    f"- Messages: {metadata.get('my_messages_exported', 0):,}\n"
                    f"- Duration: {metadata.get('duration', 'unknown')}\n"
                )
            return "No export in progress and no previous export found."

        progress = _export_state["progress"]
        start_time = datetime.fromisoformat(_export_state["start_time"])
        elapsed = datetime.now() - start_time
        elapsed_str = str(elapsed).split(".")[0]

        # Estimate remaining time
        channels_done = progress.get("channels_done", 0)
        channels_total = progress.get("channels_total", 1)
        if channels_done > 0:
            avg_per_channel = elapsed.total_seconds() / channels_done
            remaining_channels = channels_total - channels_done
            est_remaining = timedelta(seconds=avg_per_channel * remaining_channels)
            est_str = str(est_remaining).split(".")[0]
        else:
            est_str = "calculating..."

        return (
            "📊 Export in progress\n\n"
            "**Progress:**\n"
            f"- Channels: {channels_done}/{channels_total}\n"
            f"- Current: {progress.get('current_channel', 'starting...')}\n"
            f"- Messages scanned: {progress.get('messages', 0):,}\n"
            f"- Your messages: {progress.get('my_messages', 0):,}\n"
            f"- Errors: {len(progress.get('errors', []))}\n\n"
            "**Time:**\n"
            f"- Elapsed: {elapsed_str}\n"
            f"- Est. remaining: {est_str}\n"
        )

    @mcp.tool()
    @auto_heal()
    async def slack_export_cancel() -> str:
        """
        Cancel an in-progress Slack message export.

        The export will stop after the current channel completes and save
        whatever has been exported so far.

        Returns:
            Confirmation message
        """
        if not _export_state["running"]:
            return "No export in progress to cancel."

        _export_state["cancelled"] = True
        return (
            "🛑 Export cancellation requested.\n"
            "The export will stop after the current channel completes.\n"
            "Partial results will be saved."
        )

    return registry.count


def _get_channel_type(conv: dict) -> str:
    """Determine the channel type from conversation object."""
    if conv.get("is_im"):
        return "dm"
    elif conv.get("is_mpim"):
        return "group_dm"
    elif conv.get("is_channel"):
        return "channel"
    elif conv.get("is_private"):
        return "private_channel"
    else:
        return "public_channel"
