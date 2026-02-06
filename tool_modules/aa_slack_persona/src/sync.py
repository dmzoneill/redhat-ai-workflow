"""Slack message sync for persona vector store.

Handles:
- Parallel channel processing with configurable workers
- Per-channel day tracking to avoid re-syncing
- Backwards (today -> past) or forwards (past -> today) sync direction
- Thread reply fetching
- Clean tabular progress output
"""

import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default paths
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "aa-workflow"
DEFAULT_VECTOR_DIR = DEFAULT_CONFIG_DIR / "vectors" / "slack-persona"
DEFAULT_METADATA_FILE = DEFAULT_CONFIG_DIR / "slack-persona-sync.json"
DEFAULT_CHANNEL_STATE_FILE = DEFAULT_CONFIG_DIR / "slack-persona-channel-state.json"


class ProgressDisplay:
    """Tabular progress display for parallel sync."""

    # Column widths
    COL_WORKER = 3
    COL_CHANNEL = 25
    COL_TYPE = 8
    COL_DATE = 12
    COL_PAGE = 6
    COL_MSGS = 8
    COL_THREADS = 8
    COL_STATUS = 10

    def __init__(self, num_workers: int):
        self.num_workers = num_workers
        self.worker_states = {}
        self._lock = asyncio.Lock()
        self._header_printed = False

    def _truncate(self, text: str, width: int) -> str:
        """Truncate text to fit column width."""
        if len(text) <= width:
            return text.ljust(width)
        return text[: width - 2] + ".."

    def print_header(self):
        """Print table header."""
        if self._header_printed:
            return
        self._header_printed = True

        header = (
            f"{'W':>{self.COL_WORKER}}  "
            f"{'Channel':<{self.COL_CHANNEL}}  "
            f"{'Type':<{self.COL_TYPE}}  "
            f"{'Date':<{self.COL_DATE}}  "
            f"{'Page':>{self.COL_PAGE}}  "
            f"{'Msgs':>{self.COL_MSGS}}  "
            f"{'Threads':>{self.COL_THREADS}}  "
            f"{'Status':<{self.COL_STATUS}}"
        )
        separator = "-" * len(header)
        print(separator)
        print(header)
        print(separator)

    async def update_worker(
        self,
        worker_id: int,
        channel: str = "",
        channel_type: str = "",
        date: str = "",
        page: int = 0,
        msgs: int = 0,
        threads: int = 0,
        status: str = "",
        http_code: int = 0,
    ):
        """Update worker status and print row."""
        async with self._lock:
            self.print_header()

            # Format status with HTTP code if provided
            if http_code:
                status_str = f"{status} ({http_code})"
            else:
                status_str = status

            row = (
                f"{worker_id:>{self.COL_WORKER}}  "
                f"{self._truncate(channel, self.COL_CHANNEL)}  "
                f"{self._truncate(channel_type, self.COL_TYPE)}  "
                f"{self._truncate(date, self.COL_DATE)}  "
                f"{page:>{self.COL_PAGE}}  "
                f"{msgs:>{self.COL_MSGS}}  "
                f"{threads:>{self.COL_THREADS}}  "
                f"{self._truncate(status_str, self.COL_STATUS)}"
            )
            print(row)

    async def print_channel_complete(
        self,
        worker_id: int,
        channel: str,
        channel_type: str,
        total_msgs: int,
        total_threads: int,
        days_synced: int,
        days_skipped: int,
    ):
        """Print channel completion summary."""
        async with self._lock:
            summary = (
                f"{worker_id:>{self.COL_WORKER}}  "
                f"{self._truncate(channel, self.COL_CHANNEL)}  "
                f"{self._truncate(channel_type, self.COL_TYPE)}  "
                f"{'DONE':<{self.COL_DATE}}  "
                f"{days_synced:>{self.COL_PAGE}}d "
                f"{total_msgs:>{self.COL_MSGS}}  "
                f"{total_threads:>{self.COL_THREADS}}  "
                f"skip:{days_skipped}"
            )
            print(f"\033[92m{summary}\033[0m")  # Green for completion

    def print_separator(self):
        """Print a separator line."""
        width = (
            self.COL_WORKER
            + self.COL_CHANNEL
            + self.COL_TYPE
            + self.COL_DATE
            + self.COL_PAGE
            + self.COL_MSGS
            + self.COL_THREADS
            + self.COL_STATUS
            + 14  # spacing
        )
        print("-" * width)


class SlackPersonaSync:
    """Sync Slack messages to persona vector store."""

    def __init__(
        self,
        vector_dir: Path | str | None = None,
        metadata_file: Path | str | None = None,
        channel_state_file: Path | str | None = None,
    ):
        """Initialize sync.

        Args:
            vector_dir: Path to vector database
            metadata_file: Path to sync metadata file
            channel_state_file: Path to per-channel state file
        """
        self.vector_dir = Path(vector_dir or DEFAULT_VECTOR_DIR)
        self.metadata_file = Path(metadata_file or DEFAULT_METADATA_FILE)
        self.channel_state_file = Path(channel_state_file or DEFAULT_CHANNEL_STATE_FILE)

        self.vector_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file.parent.mkdir(parents=True, exist_ok=True)

        self._session = None
        self._vector_store = None
        self._my_user_id = None

    async def _get_session(self):
        """Get or create Slack session."""
        if self._session is None:
            from pathlib import Path

            # Add slack client to path
            project_root = Path(__file__).parent.parent.parent.parent
            slack_src = project_root / "aa_slack" / "src"
            if str(slack_src) not in sys.path:
                sys.path.insert(0, str(slack_src))

            from slack_client import SlackSession

            # Load config
            sys.path.insert(0, str(project_root.parent))
            from server.utils import load_config

            config = load_config()
            slack_config = config.get("slack", {})
            auth = slack_config.get("auth", {})

            self._session = SlackSession(
                xoxc_token=auth.get("xoxc_token", ""),
                d_cookie=auth.get("d_cookie", ""),
                workspace_id=auth.get("workspace_id", ""),
                enterprise_id=auth.get("enterprise_id", ""),
            )

            await self._session.validate_session()
            self._my_user_id = self._session.user_id
            logger.info(f"Slack session validated, user: {self._my_user_id}")

        return self._session

    def _get_vector_store(self):
        """Get or create vector store."""
        if self._vector_store is None:
            from tool_modules.aa_slack_persona.src.vector_store import SlackVectorStore

            self._vector_store = SlackVectorStore(self.vector_dir)
        return self._vector_store

    # -------------------------------------------------------------------------
    # Metadata management
    # -------------------------------------------------------------------------

    def _load_metadata(self) -> dict[str, Any]:
        """Load sync metadata."""
        if self.metadata_file.exists():
            with open(self.metadata_file) as f:
                return json.load(f)
        return {}

    def _save_metadata(self, metadata: dict[str, Any]) -> None:
        """Save sync metadata."""
        with open(self.metadata_file, "w") as f:
            json.dump(metadata, f, indent=2)

    # -------------------------------------------------------------------------
    # Per-channel day tracking
    # -------------------------------------------------------------------------

    def _load_channel_state(self) -> dict[str, Any]:
        """Load per-channel sync state."""
        if self.channel_state_file.exists():
            with open(self.channel_state_file) as f:
                return json.load(f)
        return {}

    def _save_channel_state(self, state: dict[str, Any]) -> None:
        """Save per-channel sync state."""
        with open(self.channel_state_file, "w") as f:
            json.dump(state, f, indent=2)

    def _is_day_synced(self, channel_state: dict, channel_id: str, date_str: str) -> bool:
        """Check if a day has been synced for a channel."""
        channel_data = channel_state.get(channel_id, {})
        synced_days = channel_data.get("synced_days", [])
        return date_str in synced_days

    def _mark_day_synced(self, channel_state: dict, channel_id: str, date_str: str) -> None:
        """Mark a day as synced for a channel."""
        if channel_id not in channel_state:
            channel_state[channel_id] = {"synced_days": [], "last_sync": None}

        if date_str not in channel_state[channel_id]["synced_days"]:
            channel_state[channel_id]["synced_days"].append(date_str)

        channel_state[channel_id]["last_sync"] = datetime.now().isoformat()

    # -------------------------------------------------------------------------
    # Conversation discovery
    # -------------------------------------------------------------------------

    async def _get_all_conversations(self) -> list[dict[str, Any]]:
        """Get all conversations (channels, DMs, group DMs)."""
        session = await self._get_session()

        # Use client.counts to get all conversations
        counts = await session.get_client_counts()

        conversations = []

        # Channels
        for ch in counts.get("channels", []):
            channel_id = ch.get("id", ch) if isinstance(ch, dict) else ch
            conversations.append(
                {
                    "id": channel_id,
                    "type": "channel",
                    "name": ch.get("name", "") if isinstance(ch, dict) else "",
                }
            )

        # DMs
        for im in counts.get("ims", []):
            channel_id = im.get("id", im) if isinstance(im, dict) else im
            conversations.append(
                {
                    "id": channel_id,
                    "type": "dm",
                    "name": "",
                }
            )

        # Group DMs
        for mpim in counts.get("mpims", []):
            channel_id = mpim.get("id", mpim) if isinstance(mpim, dict) else mpim
            conversations.append(
                {
                    "id": channel_id,
                    "type": "group_dm",
                    "name": "",
                }
            )

        logger.info(f"Found {len(conversations)} conversations")
        return conversations

    # -------------------------------------------------------------------------
    # Day-based message fetching
    # -------------------------------------------------------------------------

    async def _fetch_channel_day(
        self,
        channel_id: str,
        channel_type: str,
        channel_name: str,
        target_date: datetime,
        include_threads: bool,
        request_delay: float,
        worker_id: int,
        progress: ProgressDisplay,
    ) -> tuple[list[dict[str, Any]], int, int]:
        """Fetch messages for a single day from a channel.

        Args:
            channel_id: Channel ID
            channel_type: Type (dm, group_dm, channel)
            channel_name: Channel name
            target_date: The date to fetch
            include_threads: Whether to fetch thread replies
            request_delay: Delay between API requests
            worker_id: Worker ID for progress display
            progress: Progress display instance

        Returns:
            Tuple of (messages, thread_count, http_code)
        """
        session = await self._get_session()
        messages = []
        seen_ids = set()
        thread_count = 0
        last_http_code = 200

        # Calculate day bounds
        day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        oldest_ts = str(day_start.timestamp())
        latest_ts = str(day_end.timestamp())

        display_name = channel_name or channel_id[:12]
        date_str = target_date.strftime("%Y-%m-%d")

        cursor = None
        page_count = 0

        try:
            while True:
                page_count += 1
                await asyncio.sleep(request_delay)

                # Fetch page with cursor pagination
                result = await session.get_channel_history_with_cursor(
                    channel_id,
                    limit=200,
                    oldest=oldest_ts,
                    latest=latest_ts,
                    cursor=cursor,
                )

                # Extract HTTP status if available
                last_http_code = result.get("_http_status", 200)

                await progress.update_worker(
                    worker_id=worker_id,
                    channel=display_name,
                    channel_type=channel_type,
                    date=date_str,
                    page=page_count,
                    msgs=len(messages),
                    threads=thread_count,
                    status="fetching",
                    http_code=last_http_code,
                )

                if not result.get("ok"):
                    error = result.get("error", "unknown")
                    await progress.update_worker(
                        worker_id=worker_id,
                        channel=display_name,
                        channel_type=channel_type,
                        date=date_str,
                        page=page_count,
                        msgs=len(messages),
                        threads=thread_count,
                        status=f"ERR:{error}",
                    )
                    break

                history = result.get("messages", [])
                if not history:
                    break

                # Process messages
                for msg in history:
                    ts = msg.get("ts", "")
                    msg_id = f"{channel_id}_{ts}"

                    if msg_id in seen_ids:
                        continue
                    seen_ids.add(msg_id)

                    text = msg.get("text", "")
                    if not text:
                        continue

                    user_id = msg.get("user", "")

                    try:
                        dt = datetime.fromtimestamp(float(ts))
                        datetime_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        datetime_str = ""

                    messages.append(
                        {
                            "id": msg_id,
                            "text": text,
                            "user_id": user_id,
                            "user_name": msg.get("username", ""),
                            "channel_id": channel_id,
                            "channel_name": channel_name,
                            "channel_type": channel_type,
                            "ts": ts,
                            "thread_ts": msg.get("thread_ts"),
                            "is_thread_reply": False,
                            "datetime_str": datetime_str,
                        }
                    )

                    # Fetch thread replies
                    if include_threads and msg.get("reply_count", 0) > 0:
                        thread_ts = msg.get("thread_ts") or ts
                        try:
                            thread_count += 1
                            await asyncio.sleep(request_delay)
                            replies = await session.get_thread_replies(channel_id, thread_ts)

                            for reply in replies:
                                reply_ts = reply.get("ts", "")
                                reply_id = f"{channel_id}_{reply_ts}"

                                if reply_ts == thread_ts:
                                    continue
                                if reply_id in seen_ids:
                                    continue
                                seen_ids.add(reply_id)

                                reply_text = reply.get("text", "")
                                if not reply_text:
                                    continue

                                try:
                                    reply_dt = datetime.fromtimestamp(float(reply_ts))
                                    reply_datetime_str = reply_dt.strftime("%Y-%m-%d %H:%M:%S")
                                except Exception:
                                    reply_datetime_str = ""

                                messages.append(
                                    {
                                        "id": reply_id,
                                        "text": reply_text,
                                        "user_id": reply.get("user", ""),
                                        "user_name": reply.get("username", ""),
                                        "channel_id": channel_id,
                                        "channel_name": channel_name,
                                        "channel_type": channel_type,
                                        "ts": reply_ts,
                                        "thread_ts": thread_ts,
                                        "is_thread_reply": True,
                                        "datetime_str": reply_datetime_str,
                                    }
                                )
                        except Exception as e:
                            logger.debug(f"Error fetching thread {thread_ts}: {e}")

                # Check for more pages
                has_more = result.get("has_more", False)
                if not has_more:
                    break

                cursor = result.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break

        except Exception as e:
            await progress.update_worker(
                worker_id=worker_id,
                channel=display_name,
                channel_type=channel_type,
                date=date_str,
                page=page_count,
                msgs=len(messages),
                threads=thread_count,
                status=f"ERR:{str(e)[:10]}",
            )

        return messages, thread_count, last_http_code

    # -------------------------------------------------------------------------
    # Parallel sync worker
    # -------------------------------------------------------------------------

    async def _process_channel(
        self,
        worker_id: int,
        conv: dict[str, Any],
        days: int,
        direction: str,
        include_threads: bool,
        request_delay: float,
        channel_state: dict,
        state_lock: asyncio.Lock,
        progress: ProgressDisplay,
    ) -> tuple[list[dict[str, Any]], int, int]:
        """Process a single channel - fetch all days.

        Returns:
            Tuple of (all_messages, days_synced, days_skipped)
        """
        channel_id = conv["id"]
        channel_type = conv["type"]
        channel_name = conv["name"]
        display_name = channel_name or channel_id[:12]

        all_messages = []
        total_threads = 0
        days_synced = 0
        days_skipped = 0

        # Generate day list based on direction
        today = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)

        if direction == "backwards":
            # Today -> past
            day_offsets = range(0, days)
        else:
            # Past -> today (forwards)
            day_offsets = range(days - 1, -1, -1)

        for offset in day_offsets:
            target_date = today - timedelta(days=offset)
            date_str = target_date.strftime("%Y-%m-%d")

            # Check if already synced
            async with state_lock:
                if self._is_day_synced(channel_state, channel_id, date_str):
                    days_skipped += 1
                    continue

            # Fetch this day
            messages, thread_count, http_code = await self._fetch_channel_day(
                channel_id=channel_id,
                channel_type=channel_type,
                channel_name=channel_name,
                target_date=target_date,
                include_threads=include_threads,
                request_delay=request_delay,
                worker_id=worker_id,
                progress=progress,
            )

            all_messages.extend(messages)
            total_threads += thread_count
            days_synced += 1

            # Mark day as synced
            async with state_lock:
                self._mark_day_synced(channel_state, channel_id, date_str)

        # Print channel completion
        await progress.print_channel_complete(
            worker_id=worker_id,
            channel=display_name,
            channel_type=channel_type,
            total_msgs=len(all_messages),
            total_threads=total_threads,
            days_synced=days_synced,
            days_skipped=days_skipped,
        )

        return all_messages, days_synced, days_skipped

    # -------------------------------------------------------------------------
    # Main parallel sync
    # -------------------------------------------------------------------------

    async def full_sync_parallel(
        self,
        days: int = 90,
        include_threads: bool = True,
        resume: bool = False,
        reset_tracking: bool = False,
        workers: int = 3,
        request_delay: float = 1.5,
        direction: str = "backwards",
    ) -> dict[str, Any]:
        """Perform parallel full sync with day tracking.

        Args:
            days: Number of days to sync
            include_threads: Whether to include thread replies
            resume: If True, continue from channel state
            reset_tracking: If True, clear channel state and start fresh
            workers: Number of parallel workers
            request_delay: Delay between API requests per worker
            direction: "backwards" (today->past) or "forwards" (past->today)

        Returns:
            Sync statistics
        """
        start_time = datetime.now()

        # Load or reset channel state
        if reset_tracking:
            channel_state = {}
            logger.info("Reset channel tracking state")
        else:
            channel_state = self._load_channel_state()
            logger.info(f"Loaded state for {len(channel_state)} channels")

        # Get all conversations
        conversations = await self._get_all_conversations()

        vector_store = self._get_vector_store()

        # Clear vector store if not resuming and not just reset tracking
        if not resume and reset_tracking:
            vector_store.clear()
            logger.info("Cleared vector store")

        # Setup progress display
        progress = ProgressDisplay(workers)

        # Setup semaphore for parallel workers
        semaphore = asyncio.Semaphore(workers)
        state_lock = asyncio.Lock()

        # Track totals
        total_messages = 0
        total_days_synced = 0
        total_days_skipped = 0
        all_messages = []

        async def worker_task(worker_id: int, conv: dict) -> tuple[list, int, int]:
            async with semaphore:
                return await self._process_channel(
                    worker_id=worker_id,
                    conv=conv,
                    days=days,
                    direction=direction,
                    include_threads=include_threads,
                    request_delay=request_delay,
                    channel_state=channel_state,
                    state_lock=state_lock,
                    progress=progress,
                )

        # Create tasks for all channels
        tasks = []
        for i, conv in enumerate(conversations):
            worker_id = (i % workers) + 1
            tasks.append(worker_task(worker_id, conv))

        # Run all tasks (semaphore limits concurrency)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect results
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Worker error: {result}")
                continue
            messages, days_synced, days_skipped = result
            all_messages.extend(messages)
            total_messages += len(messages)
            total_days_synced += days_synced
            total_days_skipped += days_skipped

        progress.print_separator()

        # Save channel state
        self._save_channel_state(channel_state)
        logger.info(f"Saved state for {len(channel_state)} channels")

        # Insert all messages to vector store (single write, no race condition)
        if all_messages:
            print(f"\nIndexing {len(all_messages):,} messages to vector store...")
            vector_store.add_messages(all_messages)

        # Get final stats
        vs_stats = vector_store.get_stats()

        # Calculate conversation type breakdown
        channel_count = sum(1 for c in conversations if c["type"] == "channel")
        dm_count = sum(1 for c in conversations if c["type"] == "dm")
        group_dm_count = sum(1 for c in conversations if c["type"] == "group_dm")

        # Save metadata
        metadata = {
            "last_full_sync": datetime.now().isoformat(),
            "days": days,
            "direction": direction,
            "workers": workers,
            "total_messages": vs_stats.get("total_messages", 0),
            "conversations": len(conversations),
            "include_threads": include_threads,
        }
        self._save_metadata(metadata)

        # Write stats file for UI
        stats_file = self.vector_dir / "stats.json"
        cutoff = datetime.now() - timedelta(days=days)
        stats_data = {
            "total_messages": vs_stats.get("total_messages", 0),
            "channels": channel_count,
            "dms": dm_count,
            "group_dms": group_dm_count,
            "db_size_mb": vs_stats.get("db_size_mb", 0),
            "oldest_date": cutoff.strftime("%Y-%m-%d"),
            "newest_date": datetime.now().strftime("%Y-%m-%d"),
            "last_updated": datetime.now().isoformat(),
        }
        with open(stats_file, "w") as f:
            json.dump(stats_data, f, indent=2)

        elapsed = (datetime.now() - start_time).total_seconds()

        return {
            "status": "success",
            "messages_synced": total_messages,
            "days_synced": total_days_synced,
            "days_skipped": total_days_skipped,
            "conversations": len(conversations),
            "days": days,
            "direction": direction,
            "elapsed_seconds": round(elapsed, 1),
            "vector_stats": vs_stats,
        }

    # -------------------------------------------------------------------------
    # Legacy methods (kept for compatibility)
    # -------------------------------------------------------------------------

    async def full_sync(
        self,
        months: int = 6,
        include_threads: bool = True,
        progress_callback: callable | None = None,
        resume: bool = False,
    ) -> dict[str, Any]:
        """Legacy full sync - redirects to parallel sync."""
        days = months * 30
        return await self.full_sync_parallel(
            days=days,
            include_threads=include_threads,
            resume=resume,
            workers=1,  # Single worker for legacy behavior
            direction="forwards",
        )

    async def incremental_sync(
        self,
        days: int = 1,
        include_threads: bool = True,
    ) -> dict[str, Any]:
        """Perform incremental sync of recent messages."""
        start_time = datetime.now()

        # Load metadata to get window size
        metadata = self._load_metadata()
        total_days = metadata.get("days", 90)

        # Calculate prune cutoff
        prune_cutoff = datetime.now() - timedelta(days=total_days)
        prune_ts = str(prune_cutoff.timestamp())

        logger.info(f"Starting incremental sync for {days} day(s)")

        vector_store = self._get_vector_store()

        # Prune old messages first
        deleted = vector_store.delete_older_than(prune_ts)
        logger.info(f"Pruned {deleted} old messages")

        # Use parallel sync for the incremental days
        result = await self.full_sync_parallel(
            days=days,
            include_threads=include_threads,
            resume=True,  # Don't clear
            workers=3,
            direction="backwards",
        )

        # Update metadata
        metadata["last_incremental_sync"] = datetime.now().isoformat()
        metadata["last_incremental_messages"] = result["messages_synced"]
        self._save_metadata(metadata)

        elapsed = (datetime.now() - start_time).total_seconds()

        return {
            "status": "success",
            "messages_synced": result["messages_synced"],
            "messages_pruned": deleted,
            "days": days,
            "elapsed_seconds": round(elapsed, 1),
            "vector_stats": result["vector_stats"],
        }

    def search(
        self,
        query: str,
        limit: int = 5,
        channel_type: str | None = None,
        my_messages_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Search for similar messages."""
        vector_store = self._get_vector_store()
        user_id = self._my_user_id if my_messages_only else None
        return vector_store.search(
            query=query,
            limit=limit,
            channel_type=channel_type,
            user_id=user_id,
        )

    def get_status(self) -> dict[str, Any]:
        """Get sync status including per-channel state."""
        metadata = self._load_metadata()
        channel_state = self._load_channel_state()
        vector_store = self._get_vector_store()

        # Summarize channel state
        channel_summary = {}
        for channel_id, state in channel_state.items():
            synced_days = state.get("synced_days", [])
            channel_summary[channel_id] = {
                "days_synced": len(synced_days),
                "last_sync": state.get("last_sync"),
                "oldest_day": min(synced_days) if synced_days else None,
                "newest_day": max(synced_days) if synced_days else None,
            }

        return {
            "metadata": metadata,
            "vector_stats": vector_store.get_stats(),
            "channels_tracked": len(channel_state),
            "channel_summary": channel_summary,
        }
