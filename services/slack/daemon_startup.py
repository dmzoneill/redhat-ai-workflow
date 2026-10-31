"""Slack daemon state and start-up: authentication, listener config, DM discovery.

``SlackDaemonCore`` owns the daemon's grouped state (options, components and
connections) and the start-up helpers that fill the connections in.
"""

import importlib
import logging
from dataclasses import dataclass
from typing import Any

from services.slack.approval_manager import ApprovalManager
from services.slack.errors import SLACK_ERRORS
from services.slack.message_processor import AlertDetector, ChannelPermissions, UserClassifier
from services.slack.response_builder import DesktopNotifier, ResponseGenerator, TerminalUI
from services.slack.slack_config import SETTINGS, get_slack_config, refresh_slack_credentials

logger = logging.getLogger(__name__)

DEFAULT_POLL_MIN = 5.0
DEFAULT_POLL_MAX = 15.0


@dataclass
class SlackDaemonOptions:
    """Command-line options for the Slack daemon."""

    dry_run: bool = False
    poll_interval_min: float = DEFAULT_POLL_MIN
    poll_interval_max: float = DEFAULT_POLL_MAX
    enable_notify: bool = True
    debug_mode: bool = False
    debug_redirect_channel: str = ""


@dataclass
class SlackComponents:
    """The daemon's message-handling helpers."""

    ui: TerminalUI
    notifier: DesktopNotifier
    response_generator: ResponseGenerator
    user_classifier: UserClassifier
    channel_permissions: ChannelPermissions
    alert_detector: AlertDetector
    approval_manager: ApprovalManager


@dataclass
class SlackConnections:
    """Live Slack session, state database, listener and helpers built at start-up."""

    session: Any = None
    state_db: Any = None
    listener: Any = None
    command_handler: Any = None
    background_sync: Any = None


def build_components(verbose: bool, enable_notify: bool) -> SlackComponents:
    """Create the daemon's helpers. Raises RuntimeError if Claude is unavailable."""
    ui = TerminalUI(verbose=verbose)
    notifier = DesktopNotifier(enabled=enable_notify)
    return SlackComponents(
        ui=ui,
        notifier=notifier,
        response_generator=ResponseGenerator(notifier=notifier),
        user_classifier=UserClassifier(),
        channel_permissions=ChannelPermissions(),
        alert_detector=AlertDetector(),
        approval_manager=ApprovalManager(notifier=notifier, ui=ui),
    )


def config_list(key: str, lower: bool = False) -> list[str]:
    """Read a list setting that may also be a comma-separated string."""
    value = get_slack_config(key, [])
    if isinstance(value, str):
        items = [v.strip() for v in value.split(",") if v.strip()]
        return [v.lower() for v in items] if lower else items
    return list(value)


def _add_new(discovered: list[str], channel_ids: Any) -> None:
    """Append channel ids not already in ``discovered``, keeping order."""
    for channel_id in channel_ids:
        if channel_id and channel_id not in discovered:
            discovered.append(channel_id)


def _counts(discovered: list[str]) -> tuple[int, int]:
    """Return (DMs, group DMs starting with G) in ``discovered``."""
    return sum(1 for c in discovered if c.startswith("D")), sum(1 for c in discovered if c.startswith("G"))


class SlackDaemonCore:
    """Daemon state plus the start-up and background-sync helpers."""

    def __init__(self, options: SlackDaemonOptions, verbose: bool) -> None:
        self.options = options
        # Initialize Claude-based response generator (REQUIRED); raises RuntimeError if unavailable
        self.parts = build_components(verbose, options.enable_notify)
        self.conn = SlackConnections()
        self._dbus_handler: Any = None

    @property
    def dry_run(self) -> bool:
        """Process messages without sending replies."""
        return self.options.dry_run

    @property
    def debug_mode(self) -> bool:
        """Redirect every reply to the self-DM channel."""
        return self.options.debug_mode

    async def start_background_sync(self) -> None:
        """Start the background sync process for cache population."""
        sync_config = SETTINGS.slack.get("background_sync", {})
        try:
            sync_module = importlib.import_module("src.background_sync")
        except ImportError as e:
            logger.warning("Background sync module not available: %s", e)
            print(f"⚠️  Background sync not available: {e}")
            return
        if not sync_config.get("enabled", True):
            print("⏸️  Background sync disabled in config")
            return

        try:
            config = sync_module.SyncConfig(
                min_delay_seconds=sync_config.get("min_delay_seconds", 1.0),
                max_delay_seconds=sync_config.get("max_delay_seconds", 3.0),
                delay_start_seconds=sync_config.get("delay_start_seconds", 60.0),
                download_photos=sync_config.get("download_photos", True),
                max_members_per_channel=sync_config.get("max_members_per_channel", 200),
                full_sync_interval_hours=sync_config.get("full_sync_interval_hours", 24.0),
            )
            self.conn.background_sync = sync_module.BackgroundSync(
                slack_client=self.conn.session,
                state_db=self.conn.state_db,
                config=config,
            )
            sync_module.set_background_sync(self.conn.background_sync)
            await self.conn.background_sync.start()
        except SLACK_ERRORS as e:
            logger.error("Failed to start background sync: %s", e)
            print(f"⚠️  Background sync failed to start: {e}")
            return

        rate = f"{config.min_delay_seconds}-{config.max_delay_seconds}s"
        print(f"✅ Background sync started (delay: {config.delay_start_seconds}s, rate: {rate})")
        logger.info("Background sync started: delay=%ss, rate=%s/req", config.delay_start_seconds, rate)

    async def stop_background_sync(self) -> None:
        """Stop the background sync process."""
        if self.conn.background_sync:
            try:
                await self.conn.background_sync.stop()
                logger.info("Background sync stopped")
            except SLACK_ERRORS as e:
                logger.error("Error stopping background sync: %s", e)

    def _print_missing_credentials(self) -> None:
        self.parts.ui.print_error(
            "Missing Slack credentials. Set in config.json or environment:\n"
            "  SLACK_XOXC_TOKEN and SLACK_D_COOKIE\n"
            "Or run: python scripts/get_slack_creds.py"
        )

    async def _try_authenticate(self, session_cls: Any) -> bool | None:
        """One sign-in attempt: True signed in, None missing credentials; raises on failure."""
        xoxc_token = get_slack_config("auth.xoxc_token", "", "SLACK_XOXC_TOKEN")
        d_cookie = get_slack_config("auth.d_cookie", "", "SLACK_D_COOKIE")
        workspace_id = get_slack_config("auth.workspace_id", "", "SLACK_WORKSPACE_ID")
        if not xoxc_token or not d_cookie:
            return None

        self.conn.session = session_cls(xoxc_token=xoxc_token, d_cookie=d_cookie, workspace_id=workspace_id)
        auth = await self.conn.session.validate_session()
        print(f"✅ Authenticated as: {auth.get('user', 'unknown')}")
        if self._dbus_handler:
            self._dbus_handler.session = self.conn.session
        return True

    async def init_slack_auth(self) -> bool:
        """Initialize Slack session with automatic credential refresh on failure."""
        session_cls = importlib.import_module("src.slack_client").SlackSession

        for attempt in range(2):  # Try twice: once with current creds, once after refresh
            try:
                signed_in = await self._try_authenticate(session_cls)
            except SLACK_ERRORS as e:
                if attempt == 0:
                    print(f"⚠️  Authentication failed: {e}")
                    print("   Attempting to refresh credentials from Chrome...")
                    if refresh_slack_credentials():
                        continue  # Retry with refreshed credentials
                self.parts.ui.print_error(
                    f"Slack authentication failed after retry: {e}\nTry running: python scripts/get_slack_creds.py"
                )
                return False

            if signed_in:
                return True
            if attempt == 0:
                print("⚠️  Missing Slack credentials, attempting to refresh from Chrome...")
                if refresh_slack_credentials():
                    continue  # Retry with refreshed credentials
            self._print_missing_credentials()
            return False

        self.parts.ui.print_error("Failed to authenticate with Slack")
        return False

    async def init_listener_config(self) -> Any:
        """Initialize listener configuration from config.json."""
        listener_config_cls = importlib.import_module("src.listener").ListenerConfig

        watched_channels = config_list("listener.watched_channels")

        # Auto-discover DMs and MPDMs (private group chats)
        if get_slack_config("listener.auto_watch_dms", True) and self.conn.session:
            _add_new(watched_channels, await self.discover_dm_channels())

        poll_interval_min = get_slack_config("listener.poll_interval_min", DEFAULT_POLL_MIN)
        poll_interval_max = get_slack_config("listener.poll_interval_max", DEFAULT_POLL_MAX)

        # Allow command line to override
        if self.options.poll_interval_min != DEFAULT_POLL_MIN:
            poll_interval_min = self.options.poll_interval_min
        if self.options.poll_interval_max != DEFAULT_POLL_MAX:
            poll_interval_max = self.options.poll_interval_max

        return listener_config_cls(
            poll_interval_min=poll_interval_min,
            poll_interval_max=poll_interval_max,
            watched_channels=watched_channels,
            watched_keywords=config_list("listener.watched_keywords", lower=True),
            self_user_id=get_slack_config("listener.self_user_id", "", "SLACK_SELF_USER_ID"),
            # Self-DM channel for testing (messages from self in this channel are processed)
            self_dm_channel=get_slack_config("listener.self_dm_channel", "", "SLACK_SELF_DM_CHANNEL"),
            # Alert channels (auto-investigate - all messages in these channels are processed)
            alert_channels=get_slack_config("listener.alert_channels", {}),
        )

    async def _dms_from_counts(self) -> list[str]:
        """DMs and MPDMs from client.counts (works on enterprise Slack)."""
        discovered: list[str] = []
        try:
            result = await self.conn.session.get_client_counts()
        except SLACK_ERRORS as e:
            logger.debug("client.counts failed: %s", e)
            return discovered
        if result.get("ok"):
            _add_new(discovered, (im.get("id") for im in result.get("ims", [])))
            _add_new(discovered, (mpim.get("id") for mpim in result.get("mpims", [])))
        if discovered:
            dm_count = sum(1 for c in discovered if c.startswith("D"))
            logger.info(
                "Discovered %d DMs via client.counts (%d DMs, %d MPDMs)",
                len(discovered),
                dm_count,
                len(discovered) - dm_count,
            )
        return discovered

    async def _dms_from_sidebar(self) -> list[str]:
        """DMs and group DMs from the sidebar channel sections."""
        discovered: list[str] = []
        try:
            result = await self.conn.session.get_channel_sections()
        except SLACK_ERRORS as exc:
            logger.debug("Suppressed error: %s", exc)
            return discovered
        if result.get("ok"):
            for section in result.get("channel_sections", []):
                ids = section.get("channel_ids_page", {}).get("channel_ids", [])
                _add_new(discovered, (c for c in ids if c.startswith(("D", "G"))))
        if discovered:
            logger.info("Discovered %d DMs from sidebar (%d DMs, %d MPDMs)", len(discovered), *_counts(discovered))
        return discovered

    async def _dms_from_conversations(self) -> list[str]:
        """DMs and MPDMs from conversations.list (usually blocked on enterprise)."""
        discovered: list[str] = []
        try:
            conversations = await self.conn.session.get_conversations_list(types="im,mpim", limit=200)
        except SLACK_ERRORS as e:
            if "enterprise_is_restricted" in str(e):
                logger.info("DM auto-discovery blocked - use @me watch to get channel IDs")
            return discovered
        _add_new(discovered, (conv.get("id") for conv in conversations if not conv.get("is_archived")))
        if discovered:
            logger.info("Discovered %d DMs (%d DMs, %d MPDMs)", len(discovered), *_counts(discovered))
        return discovered

    async def discover_dm_channels(self) -> list[str]:
        """Discover all DMs and MPDMs (private group chats) the user is in.

        Tries client.counts, then the sidebar sections, then conversations.list,
        and returns the first non-empty result. Returns channel IDs for:
        - D*: Direct messages (1:1 DMs)
        - C*/G* (mpim): Multi-person direct messages (group DMs / private chats)
        """
        for method in (self._dms_from_counts, self._dms_from_sidebar, self._dms_from_conversations):
            discovered = await method()
            if discovered:
                return discovered
        return []
