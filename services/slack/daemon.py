#!/usr/bin/env python3
"""
Autonomous Slack Persona Daemon

A standalone process that monitors Slack and responds using Claude + MCP tools.
The daemon is just a Slack interface - all intelligence goes through ClaudeAgent,
which routes to MCP servers (aa_jira, aa_gitlab, aa_k8s, aa_bonfire, etc.)

Requirements:
- Claude API credentials (ANTHROPIC_API_KEY or Vertex AI)
- Slack credentials (config.json or environment variables)

Features:
- Continuous Slack monitoring with configurable poll interval
- Claude-powered message understanding and tool execution
- User classification (safe/concerned/unknown) for response modulation
- Rich terminal UI with status display
- Graceful shutdown handling
- Systemd watchdog support

Usage:
    python -m services.slack                    # Run with Claude
    python -m services.slack --dry-run          # Process but don't respond
    python -m services.slack --verbose          # Detailed logging
    python -m services.slack --dbus             # Enable D-Bus IPC

Configuration:
    All settings are read from config.json under the "slack" key.
    Environment variables can override config.json values.
"""

import asyncio
import importlib
import logging
import signal
import time
from typing import Any

from services.base.daemon import BaseDaemon, sd_notify
from services.base.dbus import DaemonDBusBase
from services.base.sleep_wake import SleepWakeMonitor
from services.slack import slack_config
from services.slack.approval_manager import ApprovalManager
from services.slack.command_handler import CommandHandler
from services.slack.daemon_messages import SlackMessageHandling
from services.slack.daemon_startup import SlackDaemonOptions
from services.slack.errors import SLACK_ERRORS
from services.slack.message_processor import (
    AlertDetector,
    ChannelPermissions,
    ResponseRules,
    UserCategory,
    UserClassification,
    UserClassifier,
)
from services.slack.response_builder import DesktopNotifier, ResponseGenerator, TerminalUI
from services.slack.slack_config import PROJECT_ROOT, get_slack_config, refresh_slack_credentials

__all__ = [
    "PROJECT_ROOT",
    "AlertDetector",
    "ApprovalManager",
    "ChannelPermissions",
    "CommandHandler",
    "DesktopNotifier",
    "ResponseGenerator",
    "ResponseRules",
    "SlackDaemon",
    "SlackDaemonOptions",
    "TerminalUI",
    "UserCategory",
    "UserClassification",
    "UserClassifier",
    "get_slack_config",
    "refresh_slack_credentials",
]

logger = logging.getLogger(__name__)


def __getattr__(name: str) -> Any:
    """Keep ``CONFIG`` and ``SLACK_CONFIG`` pointing at the current settings."""
    if name in ("CONFIG", "SLACK_CONFIG"):
        return getattr(slack_config, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class SlackDaemon(SlackMessageHandling, DaemonDBusBase, BaseDaemon):
    """
    Main autonomous Slack agent daemon.

    All message understanding and tool execution goes through ClaudeAgent.
    The daemon is just a Slack interface - all intelligence is in Claude.

    Components (extracted into separate modules):
    - message_processor: UserClassifier, AlertDetector, ResponseRules
    - response_builder: ResponseGenerator, DesktopNotifier, TerminalUI
    - approval_manager: ApprovalManager for concerned user workflow
    - command_handler: CommandHandler for @me commands
    - daemon_startup / daemon_messages: start-up and per-message handling
    """

    # BaseDaemon configuration
    name = "slack"
    description = "Slack Persona Daemon"

    # D-Bus configuration
    service_name = "com.aiworkflow.BotSlack"
    object_path = "/com/aiworkflow/BotSlack"
    interface_name = "com.aiworkflow.BotSlack"

    def __init__(self, verbose: bool = False, enable_dbus: bool = False, **options: Any):
        """Create the daemon.

        ``options`` are the SlackDaemonOptions keywords: dry_run, poll_interval_min,
        poll_interval_max, enable_notify and debug_mode.
        """
        BaseDaemon.__init__(self, verbose=verbose, enable_dbus=enable_dbus)
        DaemonDBusBase.__init__(self)
        # Debug mode: redirect all messages to self
        options.setdefault("debug_redirect_channel", get_slack_config("listener.self_dm_channel", ""))
        SlackMessageHandling.__init__(self, SlackDaemonOptions(**options), verbose)

        self._running = False

        # D-Bus support (legacy handler)
        if enable_dbus:
            try:
                dbus_module = importlib.import_module("services.slack.dbus")
                self._dbus_handler = dbus_module.SlackDaemonWithDBus()
                self._dbus_handler.history = dbus_module.MessageHistory()
                logger.info("D-Bus support enabled")
            except ImportError as e:
                logger.warning("D-Bus not available: %s", e)

        # Sleep/wake monitor
        self._sleep_monitor: SleepWakeMonitor | None = None

    @property
    def _pending_reviews(self) -> list[dict]:
        """Proxy to approval_manager for backward compatibility."""
        return self.parts.approval_manager.pending_reviews

    async def _on_system_wake(self):
        """Handle system wake from sleep."""
        logger.info("System wake detected - refreshing Slack connection...")
        print("\n🌅 System wake detected - refreshing...")

        # Re-validate Slack session (may have expired during sleep)
        if self.conn.session:
            try:
                auth = await self.conn.session.validate_session()
                logger.info("Slack session still valid: %s", auth.get("user", "unknown"))
                print("   ✅ Slack session valid")
            except SLACK_ERRORS as e:
                logger.warning("Slack session invalid after wake: %s", e)
                print(f"   ⚠️  Slack session needs refresh: {e}")

        print("   ✅ Wake handling complete\n")

    # ==================== D-Bus Interface Methods ====================

    async def get_service_stats(self) -> dict:
        """Return slack-specific statistics."""
        listener = self.conn.listener
        stats = {
            "messages_processed": 0,
            "messages_pending": 0,
            "listener_running": listener.is_running if listener else False,
        }

        if listener:
            listener_stats = listener.stats
            stats["polls"] = listener_stats.get("polls", 0)
            stats["messages_seen"] = listener_stats.get("messages_seen", 0)
            stats["messages_processed"] = listener_stats.get("messages_processed", 0)

        if self.conn.state_db:
            try:
                pending = await self.conn.state_db.get_pending_messages(limit=100)
                stats["messages_pending"] = len(pending)
            except SLACK_ERRORS as exc:
                logger.debug("Suppressed error: %s", exc)

        return stats

    async def get_service_status(self) -> dict:
        """Return detailed service status."""
        base = self.get_base_stats()
        service = await self.get_service_stats()
        return {**base, **service}

    # ==================== Lifecycle ====================

    async def start_dbus(self):
        """
        Override base class start_dbus to use the custom SlackPersonaDBusInterface.

        This provides the full Slack-specific D-Bus API (GetMyChannels, GetPending, etc.)
        instead of just the basic daemon methods.
        """
        if self._dbus_handler:
            await self._dbus_handler.start_dbus()
            self._dbus_handler.is_running = True
            self._dbus_handler.start_time = self.start_time
            print("✅ D-Bus IPC enabled (com.aiworkflow.BotSlack)")
            return True
        return False

    async def stop_dbus(self):
        """Override base class stop_dbus to use the custom handler."""
        if self._dbus_handler:
            self._dbus_handler.is_running = False
            await self._dbus_handler.stop_dbus()

    @staticmethod
    def _state_db_path() -> str:
        """State database path - centralized in server.paths."""
        try:
            return str(importlib.import_module("server.paths").SLACK_STATE_DB_FILE)
        except ImportError:
            return str(get_slack_config("state_db_path", "./slack_state.db"))

    async def startup(self):
        """Initialize daemon resources."""
        await super().startup()

        listener_cls = importlib.import_module("src.listener").SlackListener
        state_db_cls = importlib.import_module("src.persistence").SlackStateDB

        self.parts.ui.print_header(debug_mode=self.options.debug_mode)

        # Start sleep/wake monitor
        self._sleep_monitor = SleepWakeMonitor(on_wake_callback=self._on_system_wake)
        await self._sleep_monitor.start()
        print("✅ Sleep/wake monitor started")

        # Initialize Slack session with automatic credential refresh
        if not await self.init_slack_auth():
            raise RuntimeError("Failed to initialize Slack authentication")

        self.conn.state_db = state_db_cls(self._state_db_path())
        await self.conn.state_db.connect()
        print("✅ State database connected")

        # Initialize listener configuration (async to discover DMs/MPDMs)
        config = await self.init_listener_config()
        self.conn.listener = listener_cls(self.conn.session, self.conn.state_db, config)

        # Initialize @me command handler with session and Claude agent
        self.conn.command_handler = CommandHandler(
            slack_client=self.conn.session,
            claude_agent=self.parts.response_generator.claude_agent,
            notifier=self.parts.notifier,
        )
        print("✅ @me command handler initialized")

        self._print_startup_status(config)

        await self.conn.listener.start()
        self._running = True

        # Update D-Bus handler with listener reference for health checks
        if self._dbus_handler:
            self._dbus_handler.listener = self.conn.listener
            self._dbus_handler.state_db = self.conn.state_db

        await self.start_background_sync()

        self.parts.notifier.started()
        logger.info("Slack daemon ready")

    async def run_daemon(self):
        """Main daemon loop."""
        await self._main_loop()

    async def health_check(self) -> dict:
        """Perform a health check on the slack daemon."""
        self._last_health_check = time.time()

        listener = self.conn.listener
        checks = {
            "running": self._running,
            "listener_active": bool(listener and listener.is_running),
            "session_valid": self.conn.session is not None,
            "state_db_connected": self.conn.state_db is not None,
        }

        healthy = all(checks.values())

        return {
            "healthy": healthy,
            "checks": checks,
            "message": ("Slack daemon is healthy" if healthy else "Slack daemon has issues"),
            "timestamp": self._last_health_check,
        }

    def _watchdog_healthy_now(self) -> bool:
        """D-Bus connected (when enabled) and the listener reporting stats."""
        if self._dbus_handler and not getattr(self._dbus_handler, "_bus", None):
            logger.warning("Watchdog: D-Bus not connected")
            return False
        if self.conn.listener:
            try:
                if not self.conn.listener.stats:
                    logger.warning("Watchdog: Listener not responding")
                    return False
            except SLACK_ERRORS as e:
                logger.warning("Watchdog: Listener check failed: %s", e)
                return False
        return True

    async def _watchdog_loop_internal(self, interval: float):
        """Periodically notify systemd that the daemon is healthy.

        Verifies D-Bus interface is responding before sending ping.
        """
        logger.info("Watchdog enabled, pinging every %.1fs", interval)

        while self._running:
            try:
                if self._watchdog_healthy_now():
                    sd_notify("WATCHDOG=1")
                else:
                    logger.warning("Watchdog: Health check failed, not sending ping")
            except SLACK_ERRORS as e:
                logger.error("Watchdog loop error: %s", e)

            await asyncio.sleep(interval)

    async def _main_loop(self):
        """Main processing loop."""
        loop_count = 0
        last_poll_count = 0
        while self._running:
            try:
                loop_count += 1
                stats = self.conn.listener.stats

                if loop_count % 10 == 1:
                    logger.debug(
                        "Loop %d: polls=%s, seen=%s", loop_count, stats.get("polls", 0), stats.get("messages_seen", 0)
                    )

                self.parts.ui.print_status(stats)

                # Track successful polls for health monitoring
                current_poll_count = stats.get("polls", 0)
                if self._dbus_handler and current_poll_count > last_poll_count:
                    self._dbus_handler.record_successful_poll()
                    last_poll_count = current_poll_count

                for msg in await self.conn.state_db.get_pending_messages(limit=10):
                    await self.process_message(msg)

                await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except SLACK_ERRORS as e:
                self.parts.ui.print_error(str(e))
                # Track failures for health monitoring
                if self._dbus_handler:
                    self._dbus_handler.record_api_failure()
                await asyncio.sleep(5)

    async def shutdown(self):
        """Clean up daemon resources."""
        logger.info("Slack daemon shutting down...")

        self._running = False
        self.parts.notifier.stopped()

        await self.stop_background_sync()

        if self._sleep_monitor:
            try:
                await asyncio.wait_for(self._sleep_monitor.stop(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Sleep monitor stop timed out")

        # D-Bus is stopped by super().shutdown() via stop_dbus() override
        conn = self.conn
        if conn.listener:
            await conn.listener.stop()
        if conn.session:
            await conn.session.close()
        if conn.state_db:
            await conn.state_db.close()

        # Get final listener stats for shutdown summary
        self.parts.ui.print_shutdown(conn.listener.stats if conn.listener else {})

        await super().shutdown()
        logger.info("Slack daemon stopped")

    def _print_watch_summary(self, config: Any) -> None:
        """Conversations, keywords, alert channels and user lists."""
        channels = config.watched_channels
        dm_count = sum(1 for c in channels if c.startswith("D"))
        mpdm_count = sum(1 for c in channels if c.startswith("G"))

        print(f"✅ Watching {len(channels)} conversations:")
        print(f"   • {len(channels) - dm_count - mpdm_count} channels, {dm_count} DMs, {mpdm_count} group DMs (MPDMs)")
        print(f"✅ Keywords: {', '.join(config.watched_keywords) or 'none'}")
        if config.self_dm_channel:
            print(f"✅ Self-DM testing enabled: {config.self_dm_channel}")

        alert_channels = self.parts.alert_detector.alert_channels
        if alert_channels:
            print(f"🚨 Alert channels: {len(alert_channels)} (auto-investigate enabled)")
            for info in alert_channels.values():
                auto = "✓" if info.get("auto_investigate") else "✗"
                print(f"   • {info.get('environment', 'unknown')}: {info.get('namespace', 'unknown')} [{auto}]")

        users = self.parts.user_classifier
        safe_count = len(users.safe_user_ids) + len(users.safe_user_names)
        concerned_count = len(users.concerned_user_ids) + len(users.concerned_user_names)
        print(f"✅ User lists: {safe_count} safe, {concerned_count} concerned")

    def _print_rules_summary(self) -> None:
        """Response rules and desktop notification status."""
        rules = self.parts.channel_permissions
        print("✅ Response rules:")
        print("   • DMs: Always respond" if rules.dm_enabled else "   • DMs: Disabled")

        if rules.mention_enabled:
            triggers = list(rules.trigger_mentions)[:3]
            trigger_str = ", ".join(triggers) if triggers else "(bot mention)"
            print(f"   • Channels: Only when mentioned ({trigger_str})")
        else:
            print("   • Channels: All messages")

        if rules.blocked_channels:
            print(f"   • Blocked: {len(rules.blocked_channels)} channels")

        if self.parts.notifier.enabled:
            print("✅ Desktop notifications: enabled (libnotify)")
        else:
            print("⚠️  Desktop notifications: disabled (install PyGObject)")

    def _print_mode_summary(self) -> None:
        """Claude agent, dry-run and debug-mode status."""
        agent: Any = self.parts.response_generator.claude_agent
        backend = "Vertex AI" if agent.use_vertex else "Direct API"
        print(f"🧠 Claude Agent: {backend} ({agent.model})")

        if self.options.dry_run:
            print("⚠️  DRY RUN MODE - no responses will be sent")

        if self.options.debug_mode:
            if self.options.debug_redirect_channel:
                print(f"🐛 DEBUG MODE - all responses redirected to self-DM ({self.options.debug_redirect_channel})")
            else:
                print("⚠️  DEBUG MODE enabled but no self_dm_channel configured in config.json!")
                print("   Set slack.listener.self_dm_channel to your DM channel ID")

    def _print_startup_status(self, config: Any) -> None:
        """Print startup status summary."""
        self._print_watch_summary(config)
        self._print_rules_summary()
        self._print_mode_summary()
        print()

    def setup_signal_handlers(self, loop=None):
        """Set up signal handlers for graceful shutdown.

        Args:
            loop: The asyncio event loop. If None, uses get_running_loop().
        """
        if loop is None:
            loop = asyncio.get_running_loop()

        def signal_handler():
            self._running = False
            self._shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)


if __name__ == "__main__":
    SlackDaemon.main()
