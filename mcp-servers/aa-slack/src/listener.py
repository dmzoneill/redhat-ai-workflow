"""Background Slack Listener with Continuous Polling.

Implements the "Active Listener" pattern:
- Polls Slack channels at configurable intervals
- Filters messages by mentions, keywords, and watched users
- Queues relevant messages for LLM processing
- Survives restarts via persistent state

This runs as a background asyncio task alongside the MCP server.
"""

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .persistence import PendingMessage, SlackStateDB
from .slack_client import SlackSession

logger = logging.getLogger(__name__)


@dataclass
class ListenerConfig:
    """Configuration for the Slack listener."""
    
    # Polling interval in seconds
    poll_interval: float = 5.0
    
    # Channels to monitor (list of channel IDs)
    watched_channels: list[str] = field(default_factory=list)
    
    # Keywords that trigger the agent (case-insensitive)
    watched_keywords: list[str] = field(default_factory=list)
    
    # User IDs whose messages always trigger
    watched_users: list[str] = field(default_factory=list)
    
    # Our own user ID (to ignore our messages)
    self_user_id: str = ""
    
    # Enable debug logging
    debug: bool = False
    
    @classmethod
    def from_env(cls) -> "ListenerConfig":
        """Create configuration from environment variables."""
        return cls(
            poll_interval=float(os.getenv("SLACK_POLL_INTERVAL", "5")),
            watched_channels=[
                c.strip() for c in os.getenv("SLACK_WATCHED_CHANNELS", "").split(",")
                if c.strip()
            ],
            watched_keywords=[
                k.strip().lower() for k in os.getenv("SLACK_WATCHED_KEYWORDS", "").split(",")
                if k.strip()
            ],
            watched_users=[
                u.strip() for u in os.getenv("SLACK_WATCHED_USERS", "").split(",")
                if u.strip()
            ],
            self_user_id=os.getenv("SLACK_SELF_USER_ID", ""),
            debug=os.getenv("SLACK_DEBUG", "").lower() in ("true", "1", "yes"),
        )


# Type alias for notification callbacks
NotificationCallback = Callable[[PendingMessage], None]


class SlackListener:
    """
    Background Slack message listener.
    
    Continuously polls configured channels and triggers callbacks
    when relevant messages are detected.
    """
    
    def __init__(
        self,
        session: SlackSession,
        state_db: SlackStateDB,
        config: ListenerConfig | None = None,
    ):
        """
        Initialize the listener.
        
        Args:
            session: Authenticated Slack session
            state_db: Persistence layer for state
            config: Listener configuration (or load from env)
        """
        self.session = session
        self.state_db = state_db
        self.config = config or ListenerConfig.from_env()
        
        # Notification callbacks
        self._callbacks: list[NotificationCallback] = []
        
        # Background task handle
        self._task: asyncio.Task | None = None
        self._running = False
        
        # Channel name cache
        self._channel_names: dict[str, str] = {}
        
        # Stats
        self._stats = {
            "polls": 0,
            "messages_seen": 0,
            "messages_queued": 0,
            "errors": 0,
            "started_at": 0.0,
        }
    
    def add_callback(self, callback: NotificationCallback):
        """Add a callback to be called when relevant messages are detected."""
        self._callbacks.append(callback)
    
    def remove_callback(self, callback: NotificationCallback):
        """Remove a callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
    
    async def start(self):
        """Start the background polling task."""
        if self._running:
            logger.warning("Listener already running")
            return
        
        # Validate session
        try:
            auth_info = await self.session.validate_session()
            if not self.config.self_user_id:
                self.config.self_user_id = auth_info.get("user_id", "")
            logger.info(f"Authenticated as user: {auth_info.get('user', 'unknown')}")
        except Exception as e:
            logger.error(f"Session validation failed: {e}")
            raise
        
        # Load channel names
        await self._load_channel_names()
        
        self._running = True
        self._stats["started_at"] = time.time()
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            f"Started listener polling {len(self.config.watched_channels)} channels "
            f"every {self.config.poll_interval}s"
        )
    
    async def stop(self):
        """Stop the background polling task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Listener stopped")
    
    @property
    def is_running(self) -> bool:
        """Check if listener is running."""
        return self._running
    
    @property
    def stats(self) -> dict[str, Any]:
        """Get listener statistics."""
        return {
            **self._stats,
            "uptime": time.time() - self._stats["started_at"] if self._stats["started_at"] else 0,
            "running": self._running,
        }
    
    async def _load_channel_names(self):
        """Load channel names for watched channels."""
        try:
            channels = await self.session.get_conversations_list()
            for channel in channels:
                self._channel_names[channel["id"]] = channel.get("name", channel["id"])
        except Exception as e:
            logger.warning(f"Could not load channel names: {e}")
    
    async def _poll_loop(self):
        """Main polling loop."""
        while self._running:
            try:
                await self._poll_all_channels()
                self._stats["polls"] += 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in poll loop: {e}")
                self._stats["errors"] += 1
            
            # Wait for next poll interval
            await asyncio.sleep(self.config.poll_interval)
    
    async def _poll_all_channels(self):
        """Poll all watched channels for new messages."""
        for channel_id in self.config.watched_channels:
            try:
                await self._poll_channel(channel_id)
            except Exception as e:
                logger.error(f"Error polling channel {channel_id}: {e}")
                self._stats["errors"] += 1
    
    async def _poll_channel(self, channel_id: str):
        """Poll a single channel for new messages."""
        # Get last processed timestamp
        last_ts = await self.state_db.get_last_processed_ts(channel_id)
        
        # Fetch new messages
        messages = await self.session.get_channel_history(
            channel_id=channel_id,
            limit=50,
            oldest=last_ts,
            inclusive=False,
        )
        
        if not messages:
            return
        
        self._stats["messages_seen"] += len(messages)
        
        # Process messages (newest first, so reverse for chronological)
        messages = list(reversed(messages))
        
        newest_ts = last_ts
        for msg in messages:
            ts = msg.get("ts", "")
            
            # Track newest timestamp
            if not newest_ts or ts > newest_ts:
                newest_ts = ts
            
            # Filter and process
            if self._should_process(msg):
                await self._process_message(channel_id, msg)
        
        # Update last processed timestamp
        if newest_ts and newest_ts != last_ts:
            channel_name = self._channel_names.get(channel_id, channel_id)
            await self.state_db.set_last_processed_ts(channel_id, newest_ts, channel_name)
            if self.config.debug:
                logger.debug(f"Updated {channel_id} last_ts to {newest_ts}")
    
    def _should_process(self, message: dict[str, Any]) -> bool:
        """
        Determine if a message should trigger the agent.
        
        Filters:
        - Ignore our own messages
        - Ignore bot messages (unless watched user)
        - Process @mentions to us
        - Process messages from watched users
        - Process messages containing watched keywords
        """
        # Get message metadata
        user_id = message.get("user", "")
        text = message.get("text", "")
        subtype = message.get("subtype", "")
        
        # Ignore our own messages
        if user_id == self.config.self_user_id:
            return False
        
        # Ignore message subtypes (join, leave, etc.) unless it's a bot_message from watched user
        if subtype and subtype not in ("bot_message", "thread_broadcast"):
            return False
        
        # Always process from watched users
        if user_id in self.config.watched_users:
            return True
        
        # Check for @mentions to us
        if self.config.self_user_id:
            mention_pattern = f"<@{self.config.self_user_id}>"
            if mention_pattern in text:
                return True
        
        # Check for watched keywords
        text_lower = text.lower()
        for keyword in self.config.watched_keywords:
            if keyword in text_lower:
                return True
        
        return False
    
    def _extract_matched_keywords(self, text: str) -> list[str]:
        """Extract which watched keywords matched the message."""
        text_lower = text.lower()
        return [kw for kw in self.config.watched_keywords if kw in text_lower]
    
    async def _resolve_user_name(self, user_id: str) -> str:
        """Resolve user ID to name, with caching."""
        # Check cache first
        cached = await self.state_db.get_user_name(user_id)
        if cached:
            return cached
        
        # Fetch from API
        try:
            user_info = await self.session.get_user_info(user_id)
            user_name = user_info.get("name", user_id)
            display_name = user_info.get("profile", {}).get("display_name", "")
            real_name = user_info.get("real_name", "")
            
            # Cache it
            await self.state_db.cache_user(user_id, user_name, display_name, real_name)
            
            return display_name or user_name
        except Exception as e:
            logger.warning(f"Could not resolve user {user_id}: {e}")
            return user_id
    
    async def _process_message(self, channel_id: str, message: dict[str, Any]):
        """Process a message that passed filtering."""
        ts = message.get("ts", "")
        user_id = message.get("user", "")
        text = message.get("text", "")
        thread_ts = message.get("thread_ts")
        
        # Resolve user name
        user_name = await self._resolve_user_name(user_id)
        
        # Check if it's a mention
        is_mention = bool(
            self.config.self_user_id and
            f"<@{self.config.self_user_id}>" in text
        )
        
        # Check if DM
        is_dm = channel_id.startswith("D")
        
        # Get channel name
        channel_name = self._channel_names.get(channel_id, channel_id)
        
        # Create pending message
        pending = PendingMessage(
            id=f"{channel_id}_{ts}",
            channel_id=channel_id,
            channel_name=channel_name,
            user_id=user_id,
            user_name=user_name,
            text=text,
            timestamp=ts,
            thread_ts=thread_ts,
            is_mention=is_mention,
            is_dm=is_dm,
            matched_keywords=self._extract_matched_keywords(text),
            created_at=time.time(),
            raw_message=message,
        )
        
        # Add to pending queue
        await self.state_db.add_pending_message(pending)
        self._stats["messages_queued"] += 1
        
        logger.info(
            f"Queued message from {user_name} in #{channel_name}: "
            f"{text[:50]}{'...' if len(text) > 50 else ''}"
        )
        
        # Trigger callbacks
        for callback in self._callbacks:
            try:
                callback(pending)
            except Exception as e:
                logger.error(f"Callback error: {e}")


class SlackListenerManager:
    """
    Manages the complete listener lifecycle.
    
    Integrates session, state, and listener components.
    Can be used standalone or as part of the MCP server.
    """
    
    def __init__(self):
        """Initialize the manager (components created on start)."""
        self.session: SlackSession | None = None
        self.state_db: SlackStateDB | None = None
        self.listener: SlackListener | None = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize all components."""
        if self._initialized:
            return
        
        # Create session from environment
        self.session = SlackSession.from_env()
        
        # Create state database
        self.state_db = SlackStateDB()
        await self.state_db.connect()
        
        # Create listener
        self.listener = SlackListener(
            session=self.session,
            state_db=self.state_db,
        )
        
        self._initialized = True
        logger.info("SlackListenerManager initialized")
    
    async def start(self):
        """Start the listener."""
        await self.initialize()
        await self.listener.start()
    
    async def stop(self):
        """Stop the listener and cleanup."""
        if self.listener:
            await self.listener.stop()
        if self.session:
            await self.session.close()
        if self.state_db:
            await self.state_db.close()
        self._initialized = False
    
    async def get_pending_messages(
        self,
        limit: int = 50,
        channel_id: str | None = None,
    ) -> list[PendingMessage]:
        """Get pending messages from the queue."""
        await self.initialize()
        return await self.state_db.get_pending_messages(limit, channel_id)
    
    async def mark_processed(self, message_id: str):
        """Mark a message as processed."""
        await self.initialize()
        await self.state_db.mark_message_processed(message_id)
    
    async def get_status(self) -> dict[str, Any]:
        """Get listener status."""
        if not self._initialized or not self.listener:
            return {"status": "not_initialized", "running": False}
        
        pending_count = await self.state_db.get_pending_count()
        
        return {
            "status": "running" if self.listener.is_running else "stopped",
            "running": self.listener.is_running,
            "pending_messages": pending_count,
            "stats": self.listener.stats,
            "config": {
                "poll_interval": self.listener.config.poll_interval,
                "watched_channels": len(self.listener.config.watched_channels),
                "watched_keywords": self.listener.config.watched_keywords,
            },
        }

