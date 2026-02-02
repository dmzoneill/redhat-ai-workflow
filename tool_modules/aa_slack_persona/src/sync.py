"""Slack message sync for persona vector store.

Handles:
- Full sync of all messages within time window
- Incremental daily sync
- Thread reply fetching
- Rolling window pruning
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default paths
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "aa-workflow"
DEFAULT_VECTOR_DIR = DEFAULT_CONFIG_DIR / "vectors" / "slack-persona"
DEFAULT_METADATA_FILE = DEFAULT_CONFIG_DIR / "slack-persona-sync.json"


class SlackPersonaSync:
    """Sync Slack messages to persona vector store."""

    def __init__(
        self,
        vector_dir: Path | str | None = None,
        metadata_file: Path | str | None = None,
    ):
        """Initialize sync.

        Args:
            vector_dir: Path to vector database
            metadata_file: Path to sync metadata file
        """
        self.vector_dir = Path(vector_dir or DEFAULT_VECTOR_DIR)
        self.metadata_file = Path(metadata_file or DEFAULT_METADATA_FILE)

        self.vector_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file.parent.mkdir(parents=True, exist_ok=True)

        self._session = None
        self._vector_store = None
        self._my_user_id = None

    async def _get_session(self):
        """Get or create Slack session."""
        if self._session is None:
            import sys
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

    async def _fetch_channel_messages(
        self,
        channel_id: str,
        channel_type: str,
        channel_name: str,
        oldest_ts: str,
        include_threads: bool = True,
        request_delay: float = 1.5,
        vector_store=None,
        flush_threshold: int = 1000,
    ) -> list[dict[str, Any]]:
        """Fetch ALL messages from a channel within time window with CURSOR pagination.

        Uses the standard conversations.history API with cursor-based pagination
        to fetch the complete message history.

        Args:
            channel_id: Channel ID
            channel_type: Type (dm, group_dm, channel)
            channel_name: Channel name
            oldest_ts: Oldest timestamp to fetch (4 years ago)
            include_threads: Whether to fetch thread replies
            request_delay: Delay between API requests in seconds (default 1.5)
            vector_store: Optional vector store for mid-channel flushing
            flush_threshold: Flush to DB every N messages (default 1000)

        Returns:
            List of message dicts (unflushed remainder)
        """
        session = await self._get_session()
        messages = []

        # Track seen message IDs to avoid duplicates
        seen_ids = set()

        # Track thread fetches for progress
        thread_count = 0
        
        # Track date range for progress display
        oldest_date_seen = None
        newest_date_seen = None

        # Cursor-based pagination
        cursor = None
        page_count = 0

        # Display name for progress
        display_name = channel_name or channel_id

        try:
            while True:
                page_count += 1

                # Delay before request to avoid rate limits
                await asyncio.sleep(request_delay)

                # Fetch page of messages using cursor-based pagination
                result = await session.get_channel_history_with_cursor(
                    channel_id,
                    limit=200,
                    oldest=oldest_ts,
                    cursor=cursor,
                )

                # Progress output for each page (with date range)
                date_range = ""
                if oldest_date_seen and newest_date_seen:
                    date_range = f" [{oldest_date_seen.strftime('%Y-%m-%d')} → {newest_date_seen.strftime('%Y-%m-%d')}]"
                print(
                    f"\r    [{display_name}] page {page_count}: {len(messages)} msgs, {thread_count} threads{date_range}",
                    end="",
                    flush=True,
                )

                if not result.get("ok"):
                    logger.warning(f"API error for {channel_id}: {result.get('error')}")
                    break

                history = result.get("messages", [])

                if not history:
                    break

                new_messages_in_batch = 0

                # Process messages
                for msg in history:
                    ts = msg.get("ts", "")
                    msg_id = f"{channel_id}_{ts}"

                    # Skip if already seen (dedup)
                    if msg_id in seen_ids:
                        continue
                    seen_ids.add(msg_id)

                    text = msg.get("text", "")
                    if not text:
                        continue

                    user_id = msg.get("user", "")

                    # Convert timestamp to datetime
                    try:
                        dt = datetime.fromtimestamp(float(ts))
                        datetime_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                        # Track date range
                        if oldest_date_seen is None or dt < oldest_date_seen:
                            oldest_date_seen = dt
                        if newest_date_seen is None or dt > newest_date_seen:
                            newest_date_seen = dt
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
                    new_messages_in_batch += 1

                    # Fetch thread replies if this is a thread parent
                    if include_threads and msg.get("reply_count", 0) > 0:
                        thread_ts = msg.get("thread_ts") or ts
                        reply_count = msg.get("reply_count", 0)
                        try:
                            thread_count += 1
                            # Progress for thread fetch (with date range)
                            date_range = ""
                            if oldest_date_seen and newest_date_seen:
                                date_range = f" [{oldest_date_seen.strftime('%Y-%m-%d')} → {newest_date_seen.strftime('%Y-%m-%d')}]"
                            print(
                                f"\r    [{display_name}] page {page_count}: {len(messages)} msgs, thread {thread_count} ({reply_count} replies){date_range}",
                                end="",
                                flush=True,
                            )

                            # Delay before thread request
                            await asyncio.sleep(request_delay)
                            replies = await session.get_thread_replies(channel_id, thread_ts)
                            for reply in replies:
                                reply_ts = reply.get("ts", "")
                                reply_id = f"{channel_id}_{reply_ts}"

                                if reply_ts == thread_ts:
                                    continue  # Skip parent
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

                # Log progress for long channels (less frequent now since we have live output)
                if page_count % 25 == 0:
                    print()  # Newline before log
                    logger.info(
                        f"    {display_name}: {len(messages)} messages, {thread_count} threads (page {page_count})"
                    )

                # Mid-channel flush for large channels
                if vector_store and len(messages) >= flush_threshold:
                    print(f"\n  💾 Mid-channel flush: {len(messages)} messages to LanceDB...")
                    vector_store.add_messages(messages)
                    vs_stats = vector_store.get_stats()
                    print(
                        f"  💾 Total in DB: {vs_stats.get('total_messages', 0):,} messages ({vs_stats.get('db_size_mb', 0)} MB)"
                    )
                    messages = []  # Clear after flush

                # Check if there are more messages
                has_more = result.get("has_more", False)
                if not has_more:
                    break

                # Get next cursor from response_metadata
                cursor = result.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break

        except Exception as e:
            print()  # Newline before error
            logger.warning(f"Error fetching channel {channel_id}: {e}")

        print()  # Newline after progress
        logger.info(f"  ✓ {display_name}: {len(messages)} messages, {thread_count} threads (pages: {page_count})")
        return messages

    async def full_sync(
        self,
        months: int = 6,
        include_threads: bool = True,
        progress_callback: callable | None = None,
        resume: bool = False,
    ) -> dict[str, Any]:
        """Perform full sync of all messages within time window.

        Args:
            months: Number of months to sync
            include_threads: Whether to include thread replies
            progress_callback: Optional callback for progress updates
            resume: If True, continue from last synced channel instead of clearing

        Returns:
            Sync statistics
        """
        start_time = datetime.now()

        # Calculate cutoff
        cutoff = datetime.now() - timedelta(days=months * 30)
        oldest_ts = str(cutoff.timestamp())

        logger.info(f"Starting full sync for {months} months (since {cutoff.date()})")

        # Get all conversations
        conversations = await self._get_all_conversations()

        vector_store = self._get_vector_store()

        # Handle resume vs fresh start
        start_index = 0
        if resume:
            # Load metadata to find where we left off
            metadata = self._load_metadata()
            last_channel = metadata.get("last_synced_channel", "")
            if last_channel:
                # Find the index of the last synced channel
                for i, conv in enumerate(conversations):
                    if conv["id"] == last_channel:
                        start_index = i + 1  # Start from next channel
                        break
                logger.info(f"Resuming from channel {start_index + 1}/{len(conversations)}")
        else:
            # Clear existing data for fresh start
            vector_store.clear()

        # Fetch messages from each conversation
        total_messages = 0
        all_messages = []

        for i, conv in enumerate(conversations[start_index:], start=start_index):
            if progress_callback:
                progress_callback(i + 1, len(conversations), conv["id"])

            # Show which channel we're starting
            conv_name = conv["name"] or conv["id"]
            print(f"\n{'='*60}")
            print(f"[{i + 1}/{len(conversations)}] {conv['type'].upper()}: {conv_name}")
            print(f"{'='*60}")

            messages = await self._fetch_channel_messages(
                channel_id=conv["id"],
                channel_type=conv["type"],
                channel_name=conv["name"],
                oldest_ts=oldest_ts,
                include_threads=include_threads,
                vector_store=vector_store,
                flush_threshold=1000,
            )

            # messages now only contains unflushed remainder
            all_messages.extend(messages)
            total_messages += len(messages)

            # Batch insert every 1000 messages
            if len(all_messages) >= 1000:
                print(f"  💾 Flushing {len(all_messages)} messages to LanceDB...")
                vector_store.add_messages(all_messages)
                vs_stats = vector_store.get_stats()
                print(
                    f"  💾 Total in DB: {vs_stats.get('total_messages', 0):,} messages ({vs_stats.get('db_size_mb', 0)} MB)"
                )
                all_messages = []

            # Save progress after each channel
            self._save_metadata(
                {
                    "last_synced_channel": conv["id"],
                    "last_synced_index": i,
                    "months": months,
                    "include_threads": include_threads,
                    "sync_in_progress": True,
                }
            )

        # Insert remaining messages
        if all_messages:
            print(f"\n💾 Final flush: {len(all_messages)} messages to LanceDB...")
            vector_store.add_messages(all_messages)

        # Calculate conversation type breakdown
        channel_count = sum(1 for c in conversations if c["type"] == "channel")
        dm_count = sum(1 for c in conversations if c["type"] == "dm")
        group_dm_count = sum(1 for c in conversations if c["type"] == "group_dm")

        # Get vector store stats
        vs_stats = vector_store.get_stats()

        # Save final metadata
        metadata = {
            "last_full_sync": datetime.now().isoformat(),
            "last_sync_completed": datetime.now().isoformat(),
            "months": months,
            "total_messages": vs_stats.get("total_messages", 0),
            "conversations": len(conversations),
            "include_threads": include_threads,
            "sync_in_progress": False,
        }
        self._save_metadata(metadata)

        # Write detailed stats file for UI
        stats_file = self.vector_dir / "stats.json"
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
            "conversations": len(conversations),
            "months": months,
            "elapsed_seconds": round(elapsed, 1),
            "vector_stats": vector_store.get_stats(),
        }

    async def incremental_sync(
        self,
        days: int = 1,
        include_threads: bool = True,
    ) -> dict[str, Any]:
        """Perform incremental sync of recent messages.

        Args:
            days: Number of days to sync
            include_threads: Whether to include thread replies

        Returns:
            Sync statistics
        """
        start_time = datetime.now()

        # Load metadata to get window size
        metadata = self._load_metadata()
        months = metadata.get("months", 6)

        # Calculate cutoffs
        recent_cutoff = datetime.now() - timedelta(days=days)
        oldest_ts = str(recent_cutoff.timestamp())

        # Calculate prune cutoff
        prune_cutoff = datetime.now() - timedelta(days=months * 30)
        prune_ts = str(prune_cutoff.timestamp())

        logger.info(f"Starting incremental sync for {days} day(s)")

        # Get all conversations
        conversations = await self._get_all_conversations()

        vector_store = self._get_vector_store()

        # Prune old messages first
        deleted = vector_store.delete_older_than(prune_ts)
        logger.info(f"Pruned {deleted} old messages")

        # Fetch recent messages
        total_messages = 0
        all_messages = []

        for conv in conversations:
            messages = await self._fetch_channel_messages(
                channel_id=conv["id"],
                channel_type=conv["type"],
                channel_name=conv["name"],
                oldest_ts=oldest_ts,
                include_threads=include_threads,
            )

            all_messages.extend(messages)
            total_messages += len(messages)

        # Insert messages
        if all_messages:
            vector_store.add_messages(all_messages)

        # Update metadata
        metadata["last_incremental_sync"] = datetime.now().isoformat()
        metadata["last_incremental_messages"] = total_messages
        metadata["last_sync_completed"] = datetime.now().isoformat()
        self._save_metadata(metadata)

        # Update stats file for UI
        vs_stats = vector_store.get_stats()
        channel_count = sum(1 for c in conversations if c["type"] == "channel")
        dm_count = sum(1 for c in conversations if c["type"] == "dm")
        group_dm_count = sum(1 for c in conversations if c["type"] == "group_dm")

        stats_file = self.vector_dir / "stats.json"
        stats_data = {
            "total_messages": vs_stats.get("total_messages", 0),
            "channels": channel_count,
            "dms": dm_count,
            "group_dms": group_dm_count,
            "db_size_mb": vs_stats.get("db_size_mb", 0),
            "oldest_date": prune_cutoff.strftime("%Y-%m-%d"),
            "newest_date": datetime.now().strftime("%Y-%m-%d"),
            "last_updated": datetime.now().isoformat(),
        }
        with open(stats_file, "w") as f:
            json.dump(stats_data, f, indent=2)

        elapsed = (datetime.now() - start_time).total_seconds()

        return {
            "status": "success",
            "messages_synced": total_messages,
            "messages_pruned": deleted,
            "days": days,
            "elapsed_seconds": round(elapsed, 1),
            "vector_stats": vs_stats,
        }

    def search(
        self,
        query: str,
        limit: int = 5,
        channel_type: str | None = None,
        my_messages_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Search for similar messages.

        Args:
            query: Search query
            limit: Max results
            channel_type: Filter by type
            my_messages_only: Only return my messages

        Returns:
            List of matching messages
        """
        vector_store = self._get_vector_store()

        user_id = self._my_user_id if my_messages_only else None

        return vector_store.search(
            query=query,
            limit=limit,
            channel_type=channel_type,
            user_id=user_id,
        )

    def get_status(self) -> dict[str, Any]:
        """Get sync status."""
        metadata = self._load_metadata()
        vector_store = self._get_vector_store()

        return {
            "metadata": metadata,
            "vector_stats": vector_store.get_stats(),
        }
