#!/usr/bin/env python3
"""Slack Persona Sync Script.

Standalone script for syncing Slack messages to persona vector store.
Can be run manually or via cron daemon.

Usage:
    # Full sync (90 days default, 3 parallel workers, backwards from today)
    python scripts/slack_persona_sync.py --full

    # Full sync with custom options
    python scripts/slack_persona_sync.py --full --days 180 --workers 5 --delay 1.0

    # Sync forwards from oldest
    python scripts/slack_persona_sync.py --full --days 30 --direction forwards

    # Resume interrupted sync
    python scripts/slack_persona_sync.py --full --resume

    # Reset tracking and start fresh
    python scripts/slack_persona_sync.py --full --reset-tracking

    # Incremental sync (1 day default)
    python scripts/slack_persona_sync.py --incremental

    # Check status
    python scripts/slack_persona_sync.py --status

    # Search
    python scripts/slack_persona_sync.py --search "CVE release"
"""

import argparse
import asyncio
import fcntl
import logging
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tool_modules" / "aa_slack" / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "tool_modules" / "aa_slack_persona" / "src"))

# Configure logging - reduce noise from httpx
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
# Suppress verbose HTTP logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

LOCK_FILE = Path("/tmp/slack_persona_sync.lock")


class SingleInstance:
    """Ensures only one instance of the sync runs at a time."""

    def __init__(self):
        self._lock_file = None
        self._acquired = False

    def acquire(self) -> bool:
        """Try to acquire the lock. Returns True if successful."""
        try:
            self._lock_file = open(LOCK_FILE, "w")
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_file.write(str(os.getpid()))
            self._lock_file.flush()
            self._acquired = True
            return True
        except OSError:
            return False

    def release(self):
        """Release the lock."""
        if self._lock_file:
            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
            except Exception as e:
                logger.debug(f"Suppressed error in SyncLock.release: {e}")
        if LOCK_FILE.exists():
            try:
                LOCK_FILE.unlink()
            except Exception as e:
                logger.debug(f"Suppressed error in SyncLock.release unlink: {e}")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.release()


async def run_full_sync(
    days: int,
    include_threads: bool,
    resume: bool = False,
    reset_tracking: bool = False,
    workers: int = 3,
    delay: float = 1.5,
    direction: str = "backwards",
):
    """Run full sync with parallel processing."""
    from tool_modules.aa_slack_persona.src.sync import SlackPersonaSync

    print("=" * 70)
    print(f"Slack Persona Full Sync - {days} days ({direction})")
    print(
        f"Workers: {workers}  |  Delay: {delay}s  |  Threads: {'Yes' if include_threads else 'No'}"
    )
    if resume:
        print("Mode: RESUMING from last sync")
    if reset_tracking:
        print("Mode: RESET TRACKING (fresh start)")
    print("=" * 70)
    print()

    sync = SlackPersonaSync()

    result = await sync.full_sync_parallel(
        days=days,
        include_threads=include_threads,
        resume=resume,
        reset_tracking=reset_tracking,
        workers=workers,
        request_delay=delay,
        direction=direction,
    )

    print()
    print("=" * 70)
    print("Results")
    print("=" * 70)
    print(f"Status:           {result['status']}")
    print(f"Messages synced:  {result['messages_synced']:,}")
    print(f"Days skipped:     {result.get('days_skipped', 0):,} (already synced)")
    print(f"Conversations:    {result['conversations']}")
    print(f"Time window:      {result['days']} days")
    print(f"Elapsed:          {result['elapsed_seconds']}s")
    print()
    print("Vector Store:")
    print(f"  Total messages: {result['vector_stats']['total_messages']:,}")
    print(f"  Database size:  {result['vector_stats']['db_size_mb']} MB")
    print(f"  Path:           {result['vector_stats']['db_path']}")


async def run_incremental_sync(days: int, include_threads: bool):
    """Run incremental sync."""
    from tool_modules.aa_slack_persona.src.sync import SlackPersonaSync

    print("=" * 60)
    print(f"Slack Persona Incremental Sync - {days} day(s)")
    print("=" * 60)
    print()

    sync = SlackPersonaSync()

    result = await sync.incremental_sync(
        days=days,
        include_threads=include_threads,
    )

    print()
    print("Results")
    print("-" * 40)
    print(f"Status: {result['status']}")
    print(f"Messages synced: {result['messages_synced']:,}")
    print(f"Messages pruned: {result.get('messages_pruned', 0):,}")
    print(f"Days: {result['days']}")
    print(f"Elapsed: {result['elapsed_seconds']}s")
    print()
    print("Vector Store:")
    print(f"  Total messages: {result['vector_stats']['total_messages']:,}")
    print(f"  Database size: {result['vector_stats']['db_size_mb']} MB")


async def show_status():
    """Show sync status with per-channel tracking."""
    from tool_modules.aa_slack_persona.src.sync import SlackPersonaSync

    sync = SlackPersonaSync()
    status = sync.get_status()

    metadata = status.get("metadata", {})
    stats = status.get("vector_stats", {})
    channel_summary = status.get("channel_summary", {})

    print("=" * 70)
    print("Slack Persona Sync Status")
    print("=" * 70)
    print()

    print("Sync Configuration:")
    if metadata:
        print(f"  Last full sync:   {metadata.get('last_full_sync', 'Never')}")
        print(f"  Days window:      {metadata.get('days', 'N/A')}")
        print(f"  Direction:        {metadata.get('direction', 'N/A')}")
        print(f"  Workers:          {metadata.get('workers', 'N/A')}")
        print(f"  Total messages:   {metadata.get('total_messages', 0):,}")
        print(f"  Conversations:    {metadata.get('conversations', 0)}")
        print(f"  Include threads:  {metadata.get('include_threads', True)}")
        print(f"  Last incremental: {metadata.get('last_incremental_sync', 'Never')}")
    else:
        print("  No sync metadata found. Run a full sync first.")

    print()
    print("Vector Store:")
    print(f"  Messages indexed: {stats.get('total_messages', 0):,}")
    print(f"  Database size:    {stats.get('db_size_mb', 0)} MB")
    print(f"  Path:             {stats.get('db_path', 'N/A')}")

    print()
    print(f"Channel Tracking: {status.get('channels_tracked', 0)} channels")

    if channel_summary:
        # Show top 10 channels by days synced
        sorted_channels = sorted(
            channel_summary.items(),
            key=lambda x: x[1].get("days_synced", 0),
            reverse=True,
        )[:10]

        if sorted_channels:
            print()
            print(f"  {'Channel ID':<15}  {'Days':>6}  {'Oldest':<12}  {'Newest':<12}")
            print(f"  {'-'*15}  {'-'*6}  {'-'*12}  {'-'*12}")
            for channel_id, info in sorted_channels:
                days = info.get("days_synced", 0)
                oldest = info.get("oldest_day", "N/A") or "N/A"
                newest = info.get("newest_day", "N/A") or "N/A"
                print(f"  {channel_id:<15}  {days:>6}  {oldest:<12}  {newest:<12}")

            if len(channel_summary) > 10:
                print(f"  ... and {len(channel_summary) - 10} more channels")


async def run_search(query: str, limit: int, my_only: bool):
    """Run search."""
    from tool_modules.aa_slack_persona.src.sync import SlackPersonaSync

    sync = SlackPersonaSync()

    results = sync.search(
        query=query,
        limit=limit,
        my_messages_only=my_only,
    )

    print("=" * 60)
    print(f"Search: {query}")
    print("=" * 60)
    print()

    if not results:
        print("No matching messages found.")
        return

    print(f"Found {len(results)} results:")
    print()

    for i, msg in enumerate(results, 1):
        score = 1 - msg.get("score", 0)
        print(f"{i}. [{msg['channel_type']}] {msg['datetime_str']}")
        print(f"   User: {msg['user_name'] or msg['user_id']}")
        print(f"   Relevance: {score:.2%}")
        print(f"   > {msg['text'][:200]}{'...' if len(msg['text']) > 200 else ''}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Slack Persona Sync - Parallel channel sync with day tracking",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --full                          # 90 days, 3 workers, backwards
  %(prog)s --full --days 30 --workers 5    # 30 days, 5 parallel workers
  %(prog)s --full --direction forwards     # Start from oldest, work forward
  %(prog)s --full --reset-tracking         # Clear day tracking, fresh start
  %(prog)s --status                        # Show sync status per channel
  %(prog)s --search "deployment issue"     # Search messages
        """,
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--full", action="store_true", help="Run full parallel sync"
    )
    mode_group.add_argument(
        "--incremental", action="store_true", help="Run incremental sync"
    )
    mode_group.add_argument("--status", action="store_true", help="Show sync status")
    mode_group.add_argument(
        "--search", type=str, metavar="QUERY", help="Search for messages"
    )

    # Sync parameters
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Days to sync (default: 90). Common values: 30, 60, 90, 180, 365",
    )
    parser.add_argument(
        "--direction",
        choices=["backwards", "forwards"],
        default="backwards",
        help="Sync direction: backwards from today (default) or forwards from oldest",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Parallel channel workers (default: 3). Higher = faster but more API load",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="Seconds between API requests per worker (default: 1.5)",
    )

    # Sync control
    parser.add_argument(
        "--no-threads", action="store_true", help="Exclude thread replies"
    )
    parser.add_argument("--resume", action="store_true", help="Resume interrupted sync")
    parser.add_argument(
        "--reset-tracking",
        action="store_true",
        help="Clear per-channel day tracking and start fresh",
    )

    # Search options
    parser.add_argument(
        "--limit", type=int, default=5, help="Search result limit (default: 5)"
    )
    parser.add_argument(
        "--my-only", action="store_true", help="Search only my messages"
    )

    args = parser.parse_args()

    include_threads = not args.no_threads

    # Status and search don't need lock
    if args.status:
        asyncio.run(show_status())
        return
    elif args.search:
        asyncio.run(run_search(args.search, args.limit, args.my_only))
        return

    # Sync operations need single instance lock
    if args.full or args.incremental:
        lock = SingleInstance()
        if not lock.acquire():
            print("Another sync is already running!")
            print("   Check with: ps aux | grep slack_persona_sync")
            print("   Or remove lock: rm /tmp/slack_persona_sync.lock")
            sys.exit(1)

        try:
            if args.full:
                asyncio.run(
                    run_full_sync(
                        days=args.days,
                        include_threads=include_threads,
                        resume=args.resume,
                        reset_tracking=args.reset_tracking,
                        workers=args.workers,
                        delay=args.delay,
                        direction=args.direction,
                    )
                )
            elif args.incremental:
                asyncio.run(run_incremental_sync(args.days, include_threads))
        finally:
            lock.release()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
