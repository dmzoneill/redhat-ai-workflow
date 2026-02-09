"""
Background Sync for Slack Cache

Slowly populates the Slack cache with:
- Channels from user's sidebar (via GetChannelSections API)
- Members from each channel (via ListChannelMembers API)
- User profile pictures (downloaded and cached locally)

Rate limiting:
- Max 1 API request per second (configurable)
- Stealth mode: random delays between 1-3 seconds
- Respects Slack rate limits (429 responses)

Usage:
    from background_sync import BackgroundSync

    sync = BackgroundSync(slack_client, state_db)
    await sync.start()  # Runs in background

    # Check status
    status = sync.get_status()

    # Stop gracefully
    await sync.stop()
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from .persistence import SlackStateDB
    from .slack_client import SlackSession

logger = logging.getLogger(__name__)

# Photo cache directory
PHOTO_CACHE_DIR = Path.home() / ".cache" / "aa-workflow" / "photos"


@dataclass
class SyncStats:
    """Statistics for background sync."""

    # Overall status
    is_running: bool = False
    started_at: float = 0.0
    last_activity: float = 0.0

    # Channel sync
    channels_discovered: int = 0
    channels_synced: int = 0
    channels_failed: int = 0

    # User sync
    users_discovered: int = 0
    users_synced: int = 0
    users_failed: int = 0

    # Photo sync
    photos_downloaded: int = 0
    photos_cached: int = 0  # Already had photo
    photos_failed: int = 0

    # Rate limiting
    requests_made: int = 0
    rate_limit_hits: int = 0
    last_request_time: float = 0.0

    # Current operation
    current_operation: str = ""
    current_channel: str = ""

    # Errors
    last_error: str = ""
    error_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "is_running": self.is_running,
            "started_at": self.started_at,
            "last_activity": self.last_activity,
            "uptime_seconds": time.time() - self.started_at if self.started_at else 0,
            "channels": {
                "discovered": self.channels_discovered,
                "synced": self.channels_synced,
                "failed": self.channels_failed,
                "progress": (
                    f"{self.channels_synced}/{self.channels_discovered}"
                    if self.channels_discovered
                    else "0/0"
                ),
            },
            "users": {
                "discovered": self.users_discovered,
                "synced": self.users_synced,
                "failed": self.users_failed,
                "progress": (
                    f"{self.users_synced}/{self.users_discovered}"
                    if self.users_discovered
                    else "0/0"
                ),
            },
            "photos": {
                "downloaded": self.photos_downloaded,
                "cached": self.photos_cached,
                "failed": self.photos_failed,
            },
            "rate_limiting": {
                "requests_made": self.requests_made,
                "rate_limit_hits": self.rate_limit_hits,
                "last_request_time": self.last_request_time,
            },
            "current": {
                "operation": self.current_operation,
                "channel": self.current_channel,
            },
            "errors": {
                "last_error": self.last_error,
                "error_count": self.error_count,
            },
        }


@dataclass
class SyncConfig:
    """Configuration for background sync."""

    # Rate limiting (requests per second)
    min_delay_seconds: float = 1.0  # Minimum delay between requests
    max_delay_seconds: float = 3.0  # Maximum delay (for stealth)

    # Retry settings
    max_retries: int = 3
    retry_delay_seconds: float = 5.0
    rate_limit_backoff_seconds: float = 60.0  # Wait time after 429

    # Sync intervals
    full_sync_interval_hours: float = 24.0  # Full resync every N hours
    incremental_sync_interval_minutes: float = 30.0  # Check for new channels

    # Photo settings
    photo_size: int = 512  # Size to download (192, 512, etc.)
    download_photos: bool = True  # Whether to download profile photos

    # Channel filtering
    skip_archived: bool = True
    skip_dm_channels: bool = True  # Skip D* channels (DMs)
    max_members_per_channel: int = 200  # Limit members to fetch per channel

    # Startup behavior
    delay_start_seconds: float = 30.0  # Wait before starting sync

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "rate_limiting": {
                "min_delay_seconds": self.min_delay_seconds,
                "max_delay_seconds": self.max_delay_seconds,
            },
            "retry": {
                "max_retries": self.max_retries,
                "retry_delay_seconds": self.retry_delay_seconds,
                "rate_limit_backoff_seconds": self.rate_limit_backoff_seconds,
            },
            "intervals": {
                "full_sync_hours": self.full_sync_interval_hours,
                "incremental_sync_minutes": self.incremental_sync_interval_minutes,
            },
            "photos": {
                "size": self.photo_size,
                "enabled": self.download_photos,
            },
            "channels": {
                "skip_archived": self.skip_archived,
                "skip_dm_channels": self.skip_dm_channels,
                "max_members_per_channel": self.max_members_per_channel,
            },
            "startup": {
                "delay_start_seconds": self.delay_start_seconds,
            },
        }


class BackgroundSync:
    """
    Background sync manager for Slack cache.

    Runs as an asyncio task, slowly populating the cache with
    channels, users, and profile photos.
    """

    def __init__(
        self,
        slack_client: "SlackSession",
        state_db: "SlackStateDB",
        config: SyncConfig | None = None,
    ):
        self.slack_client = slack_client
        self.state_db = state_db
        self.config = config or SyncConfig()

        self.stats = SyncStats()
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

        # Track what we've synced
        self._synced_channels: set[str] = set()
        self._synced_users: set[str] = set()

        # Ensure photo cache directory exists
        PHOTO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    async def start(self):
        """Start background sync task."""
        if self._task and not self._task.done():
            logger.warning("Background sync already running")
            return

        self._stop_event.clear()
        self.stats = SyncStats()
        self.stats.is_running = True
        self.stats.started_at = time.time()

        self._task = asyncio.create_task(self._sync_loop())
        logger.info("Background sync started")

    async def stop(self):
        """Stop background sync gracefully."""
        if not self._task:
            return

        logger.info("Stopping background sync...")
        self._stop_event.set()
        self.stats.is_running = False

        try:
            await asyncio.wait_for(self._task, timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("Background sync didn't stop gracefully, cancelling")
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._task = None
        logger.info("Background sync stopped")

    def get_status(self) -> dict[str, Any]:
        """Get current sync status."""
        return {
            "stats": self.stats.to_dict(),
            "config": self.config.to_dict(),
        }

    async def _rate_limit_delay(self):
        """Wait for rate limit delay with random jitter."""
        delay = random.uniform(
            self.config.min_delay_seconds,
            self.config.max_delay_seconds,
        )
        self.stats.last_request_time = time.time()
        await asyncio.sleep(delay)

    async def _sync_loop(self):
        """Main sync loop."""
        try:
            # Initial delay before starting
            logger.info(
                f"Background sync waiting {self.config.delay_start_seconds}s before starting..."
            )
            self.stats.current_operation = "startup_delay"

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.config.delay_start_seconds,
                )
                # Stop event was set during startup delay
                return
            except asyncio.TimeoutError:
                # Normal - delay completed
                pass

            while not self._stop_event.is_set():
                try:
                    # Run full sync
                    await self._full_sync()

                    # Wait for next sync interval
                    self.stats.current_operation = "waiting_for_next_sync"
                    wait_seconds = self.config.full_sync_interval_hours * 3600
                    logger.info(
                        f"Full sync complete. Next sync in {self.config.full_sync_interval_hours} hours"
                    )

                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(),
                            timeout=wait_seconds,
                        )
                        # Stop event was set
                        break
                    except asyncio.TimeoutError:
                        # Normal - time for next sync
                        pass

                except Exception as e:
                    self.stats.last_error = str(e)
                    self.stats.error_count += 1
                    logger.error(f"Sync loop error: {e}")

                    # Wait before retrying
                    await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info("Background sync cancelled")
            raise
        finally:
            self.stats.is_running = False
            self.stats.current_operation = "stopped"

    async def _full_sync(self):
        """Run a full sync of channels and users."""
        logger.info("Starting full sync...")
        self.stats.current_operation = "discovering_channels"
        self.stats.last_activity = time.time()

        # Step 1: Discover channels from sidebar
        channels = await self._discover_channels()
        if not channels:
            logger.warning("No channels discovered")
            return

        self.stats.channels_discovered = len(channels)
        logger.info(f"Discovered {len(channels)} channels")

        # Step 2: Sync each channel's members
        for channel_id, channel_name in channels:
            if self._stop_event.is_set():
                break

            # Skip if already synced recently
            if channel_id in self._synced_channels:
                continue

            # Skip DM channels if configured
            if self.config.skip_dm_channels and channel_id.startswith("D"):
                continue

            self.stats.current_operation = "syncing_channel_members"
            self.stats.current_channel = channel_name or channel_id
            self.stats.last_activity = time.time()

            try:
                await self._sync_channel_members(channel_id, channel_name)
                self._synced_channels.add(channel_id)
                self.stats.channels_synced += 1
            except Exception as e:
                logger.error(f"Failed to sync channel {channel_id}: {e}")
                self.stats.channels_failed += 1
                self.stats.last_error = f"Channel {channel_id}: {e}"

            # Rate limit
            await self._rate_limit_delay()

        # Step 3: Download photos for users without them
        if self.config.download_photos:
            await self._sync_photos()

        self.stats.current_operation = "sync_complete"
        self.stats.current_channel = ""
        logger.info(
            f"Full sync complete: {self.stats.channels_synced} channels, "
            f"{self.stats.users_synced} users, {self.stats.photos_downloaded} photos"
        )

    async def _discover_channels(self) -> list[tuple[str, str]]:
        """Discover channels from user's sidebar."""
        try:
            await self._rate_limit_delay()
            self.stats.requests_made += 1

            # Use the channel sections API
            result = await self.slack_client.get_channel_sections()

            if not result.get("ok"):
                logger.error(f"Channel sections API error: {result.get('error')}")
                return []

            # Get summary with all channel IDs
            summary = self.slack_client.get_channel_sections_summary(result)
            channel_ids = summary.get("all_channel_ids", [])

            # Build list of (channel_id, name) tuples
            # We don't have names from sections, so we'll get them from cache or leave empty
            channels = []
            for cid in channel_ids:
                # Try to get name from existing cache
                cached = await self.state_db.get_cached_channel(cid)
                name = cached.name if cached else ""
                channels.append((cid, name))

            return channels

        except Exception as e:
            logger.error(f"Failed to discover channels: {e}")
            self.stats.last_error = f"Channel discovery: {e}"
            return []

    async def _sync_channel_members(self, channel_id: str, channel_name: str):
        """Sync members for a single channel."""
        try:
            # If we don't have a channel name, try to fetch it first
            resolved_name = channel_name
            purpose = ""
            topic = ""

            if not channel_name or channel_name == channel_id:
                try:
                    await self._rate_limit_delay()
                    self.stats.requests_made += 1
                    channel_info = await self.slack_client.get_channel_info(channel_id)
                    if channel_info:
                        resolved_name = channel_info.get("name", channel_id)
                        purpose = channel_info.get("purpose", {}).get("value", "")
                        topic = channel_info.get("topic", {}).get("value", "")
                        logger.debug(
                            f"Resolved channel name: {channel_id} -> {resolved_name}"
                        )
                except Exception as e:
                    logger.debug(f"Could not fetch channel info for {channel_id}: {e}")

            await self._rate_limit_delay()
            self.stats.requests_made += 1

            # Use the list_channel_members_and_cache method
            result = await self.slack_client.list_channel_members_and_cache(
                channel_id,
                count=self.config.max_members_per_channel,
            )

            if not result.get("success"):
                error = result.get("error", "Unknown error")
                if "rate_limited" in error.lower() or "429" in error:
                    self.stats.rate_limit_hits += 1
                    logger.warning(
                        f"Rate limited, backing off for {self.config.rate_limit_backoff_seconds}s"
                    )
                    await asyncio.sleep(self.config.rate_limit_backoff_seconds)
                raise ValueError(error)

            users = result.get("users", [])
            self.stats.users_discovered += len(users)

            # Cache users to database
            from .persistence import CachedUser

            cached_users = []
            for u in users:
                user_id = u.get("user_id", "")
                if not user_id or user_id in self._synced_users:
                    continue

                cached_users.append(
                    CachedUser(
                        user_id=user_id,
                        user_name=u.get("user_name", ""),
                        display_name=u.get("display_name", ""),
                        real_name=u.get("real_name", ""),
                        email=u.get("email", ""),
                        gitlab_username="",  # Not available from this API
                        avatar_url=u.get("avatar_url", ""),
                    )
                )
                self._synced_users.add(user_id)

            if cached_users:
                await self.state_db.cache_users_bulk(cached_users)
                self.stats.users_synced += len(cached_users)
                logger.debug(
                    f"Cached {len(cached_users)} users from channel {resolved_name or channel_id}"
                )

            # Also update channel cache with member count and resolved name
            from .persistence import CachedChannel

            await self.state_db.cache_channel(
                CachedChannel(
                    channel_id=channel_id,
                    name=resolved_name or channel_id,
                    display_name=resolved_name or channel_id,
                    is_private=False,
                    is_member=True,
                    purpose=purpose,
                    topic=topic,
                    num_members=len(users),
                )
            )

        except Exception as e:
            logger.error(f"Failed to sync channel {channel_id} members: {e}")
            raise

    async def _sync_photos(self):
        """Download profile photos for users missing them."""
        self.stats.current_operation = "downloading_photos"

        # Get users without local photos
        all_users = await self.state_db.get_all_cached_users()

        for user_id, user_info in all_users.items():
            if self._stop_event.is_set():
                break

            avatar_url = user_info.get("avatar_url", "")
            if not avatar_url:
                continue

            # Check if we already have the photo cached locally
            photo_path = PHOTO_CACHE_DIR / f"{user_id}.jpg"
            if photo_path.exists():
                self.stats.photos_cached += 1
                continue

            # Download the photo
            self.stats.current_operation = f"downloading_photo_{user_id}"
            self.stats.last_activity = time.time()

            try:
                await self._download_photo(user_id, avatar_url, photo_path)
                self.stats.photos_downloaded += 1
            except Exception as e:
                logger.debug(f"Failed to download photo for {user_id}: {e}")
                self.stats.photos_failed += 1

            # Rate limit
            await self._rate_limit_delay()

    async def _download_photo(self, user_id: str, url: str, path: Path):
        """Download a single profile photo."""
        try:
            self.stats.requests_made += 1

            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=30.0)

                if response.status_code == 429:
                    self.stats.rate_limit_hits += 1
                    logger.warning("Photo download rate limited")
                    await asyncio.sleep(self.config.rate_limit_backoff_seconds)
                    raise ValueError("Rate limited")

                response.raise_for_status()

                # Save to cache
                path.write_bytes(response.content)
                logger.debug(f"Downloaded photo for {user_id}: {path}")

        except Exception as e:
            logger.debug(f"Photo download failed for {user_id}: {e}")
            raise

    async def trigger_sync(self, sync_type: str = "full") -> dict[str, Any]:
        """
        Manually trigger a sync.

        Args:
            sync_type: "full", "channels", "users", or "photos"

        Returns:
            Status dict
        """
        if not self.stats.is_running:
            return {"success": False, "error": "Background sync not running"}

        if self.stats.current_operation not in (
            "waiting_for_next_sync",
            "sync_complete",
        ):
            return {
                "success": False,
                "error": f"Sync already in progress: {self.stats.current_operation}",
            }

        # Reset synced tracking to force resync
        if sync_type in ("full", "channels"):
            self._synced_channels.clear()
        if sync_type in ("full", "users"):
            self._synced_users.clear()

        # The main loop will pick up the next sync
        # For immediate trigger, we'd need to implement a signal mechanism

        return {
            "success": True,
            "message": f"Sync type '{sync_type}' will run on next iteration",
            "current_operation": self.stats.current_operation,
        }


# Singleton instance for the daemon
_background_sync: BackgroundSync | None = None


def get_background_sync() -> BackgroundSync | None:
    """Get the singleton background sync instance."""
    return _background_sync


def set_background_sync(sync: BackgroundSync):
    """Set the singleton background sync instance."""
    global _background_sync
    _background_sync = sync
