"""Notification Engine - Multi-channel notifications for scheduled jobs.

Provides:
- NotificationEngine: Dispatches notifications to multiple backends
- Supports: Slack, desktop (notify-send/osascript), memory log
- Configurable per-job notification channels
"""

import asyncio
import logging
import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Project paths
PROJECT_DIR = Path(__file__).parent.parent.parent.parent
MEMORY_DIR = PROJECT_DIR / "memory"


class NotificationBackend:
    """Base class for notification backends."""

    async def send(
        self,
        title: str,
        message: str,
        success: bool = True,
        **kwargs,
    ) -> bool:
        """Send a notification.

        Args:
            title: Notification title
            message: Notification body
            success: Whether this is a success or failure notification
            **kwargs: Additional backend-specific options

        Returns:
            True if notification was sent successfully
        """
        raise NotImplementedError


class SlackNotificationBackend(NotificationBackend):
    """Send notifications via Slack."""

    def __init__(self, server: "FastMCP | None" = None, config: dict | None = None):
        self.server = server
        self.config = config or {}

    async def send(
        self,
        title: str,
        message: str,
        success: bool = True,
        **kwargs,
    ) -> bool:
        """Send notification to Slack."""
        if not self.server:
            logger.warning("No server configured for Slack notifications")
            return False

        # Get channel from config or kwargs
        channel = kwargs.get("channel") or self.config.get("default_channel")
        if not channel:
            # Try to get self DM channel from config
            channel = self.config.get("self_dm_channel")

        if not channel:
            logger.warning("No Slack channel configured")
            return False

        # Format message
        emoji = "✅" if success else "❌"
        formatted_message = f"{emoji} *{title}*\n\n{message[:2000]}"

        try:
            # Call slack_send_message tool
            await self.server.call_tool(
                "slack_send_message",
                {
                    "channel": channel,
                    "message": formatted_message,
                },
            )
            logger.info(f"Slack notification sent to {channel}")
            return True
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
            return False


class DesktopNotificationBackend(NotificationBackend):
    """Send desktop notifications using notify-send (Linux) or osascript (macOS)."""

    def __init__(self):
        self.system = platform.system()

    async def send(
        self,
        title: str,
        message: str,
        success: bool = True,
        **kwargs,
    ) -> bool:
        """Send desktop notification."""
        # Truncate message for desktop notification
        short_message = message[:200] + "..." if len(message) > 200 else message

        try:
            if self.system == "Linux":
                return await self._send_linux(title, short_message, success)
            elif self.system == "Darwin":
                return await self._send_macos(title, short_message, success)
            else:
                logger.warning(f"Desktop notifications not supported on {self.system}")
                return False
        except Exception as e:
            logger.error(f"Failed to send desktop notification: {e}")
            return False

    async def _send_linux(self, title: str, message: str, success: bool) -> bool:
        """Send notification on Linux using notify-send."""
        icon = "dialog-information" if success else "dialog-error"
        urgency = "normal" if success else "critical"

        proc = await asyncio.create_subprocess_exec(
            "notify-send",
            "--icon",
            icon,
            "--urgency",
            urgency,
            "--app-name",
            "AA Workflow",
            title,
            message,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0

    async def _send_macos(self, title: str, message: str, success: bool) -> bool:
        """Send notification on macOS using osascript."""
        # Escape quotes in message
        escaped_title = title.replace('"', '\\"')
        escaped_message = message.replace('"', '\\"')

        script = f'display notification "{escaped_message}" with title "{escaped_title}"'

        proc = await asyncio.create_subprocess_exec(
            "osascript",
            "-e",
            script,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0


class MemoryNotificationBackend(NotificationBackend):
    """Log notifications to memory for later review."""

    def __init__(self, memory_dir: Path | None = None):
        self.memory_dir = memory_dir or MEMORY_DIR
        self.notifications_file = self.memory_dir / "state" / "notifications.yaml"

    async def send(
        self,
        title: str,
        message: str,
        success: bool = True,
        **kwargs,
    ) -> bool:
        """Log notification to memory."""
        try:
            # Load existing notifications
            notifications = []
            if self.notifications_file.exists():
                with open(self.notifications_file) as f:
                    data = yaml.safe_load(f) or {}
                    notifications = data.get("notifications", [])

            # Add new notification
            notifications.append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "title": title,
                    "message": message[:500],  # Truncate for storage
                    "success": success,
                    "job_name": kwargs.get("job_name", ""),
                    "skill": kwargs.get("skill", ""),
                }
            )

            # Keep last 100 notifications
            notifications = notifications[-100:]

            # Save
            self.notifications_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.notifications_file, "w") as f:
                yaml.dump(
                    {"notifications": notifications},
                    f,
                    default_flow_style=False,
                )

            logger.debug(f"Notification logged to memory: {title}")
            return True

        except Exception as e:
            logger.error(f"Failed to log notification to memory: {e}")
            return False


class NotificationEngine:
    """Multi-channel notification dispatcher."""

    def __init__(
        self,
        server: "FastMCP | None" = None,
        config: dict | None = None,
    ):
        """Initialize notification engine.

        Args:
            server: FastMCP server for Slack tool calls
            config: Configuration dict (from config.json)
        """
        self.server = server
        self.config = config or {}

        # Initialize backends
        self.backends: dict[str, NotificationBackend] = {
            "slack": SlackNotificationBackend(
                server=server,
                config=self.config.get("slack", {}),
            ),
            "desktop": DesktopNotificationBackend(),
            "memory": MemoryNotificationBackend(),
        }

    async def notify(
        self,
        job_name: str,
        skill: str,
        success: bool,
        output: str | None = None,
        error: str | None = None,
        channels: list[str] | None = None,
    ):
        """Send notifications for a job completion.

        Args:
            job_name: Name of the completed job
            skill: Skill that was executed
            success: Whether the job succeeded
            output: Job output (for success)
            error: Error message (for failure)
            channels: List of notification channels to use
        """
        if not channels:
            channels = ["memory"]  # Always log to memory by default

        # Build notification content
        title = f"Scheduled Job: {job_name}"
        if success:
            message = f"✅ Skill `{skill}` completed successfully.\n\n"
            if output:
                # Extract summary from output (first few lines)
                lines = output.split("\n")[:10]
                message += "\n".join(lines)
        else:
            message = f"❌ Skill `{skill}` failed.\n\n"
            if error:
                message += f"Error: {error}"

        # Send to each channel
        results = {}
        for channel in channels:
            backend = self.backends.get(channel)
            if backend:
                try:
                    result = await backend.send(
                        title=title,
                        message=message,
                        success=success,
                        job_name=job_name,
                        skill=skill,
                    )
                    results[channel] = result
                except Exception as e:
                    logger.error(f"Notification to {channel} failed: {e}")
                    results[channel] = False
            else:
                logger.warning(f"Unknown notification channel: {channel}")
                results[channel] = False

        return results

    async def send_custom(
        self,
        title: str,
        message: str,
        channels: list[str],
        success: bool = True,
        **kwargs,
    ):
        """Send a custom notification.

        Args:
            title: Notification title
            message: Notification body
            channels: List of channels to send to
            success: Whether this is a success notification
            **kwargs: Additional options passed to backends
        """
        results = {}
        for channel in channels:
            backend = self.backends.get(channel)
            if backend:
                try:
                    result = await backend.send(
                        title=title,
                        message=message,
                        success=success,
                        **kwargs,
                    )
                    results[channel] = result
                except Exception as e:
                    logger.error(f"Notification to {channel} failed: {e}")
                    results[channel] = False

        return results

    def get_recent_notifications(self, limit: int = 20) -> list[dict]:
        """Get recent notifications from memory log.

        Args:
            limit: Maximum number of notifications to return

        Returns:
            List of recent notification entries
        """
        memory_backend = self.backends.get("memory")
        if not isinstance(memory_backend, MemoryNotificationBackend):
            return []

        try:
            if memory_backend.notifications_file.exists():
                with open(memory_backend.notifications_file) as f:
                    data = yaml.safe_load(f) or {}
                    notifications = data.get("notifications", [])
                    return notifications[-limit:]
        except Exception as e:
            logger.error(f"Failed to read notifications: {e}")

        return []

    def get_available_channels(self) -> list[str]:
        """Get list of available notification channels."""
        return list(self.backends.keys())


# Global notification engine instance
_notification_engine: NotificationEngine | None = None


def get_notification_engine() -> NotificationEngine | None:
    """Get the global notification engine instance."""
    return _notification_engine


def init_notification_engine(
    server: "FastMCP | None" = None,
    config: dict | None = None,
) -> NotificationEngine:
    """Initialize the global notification engine instance."""
    global _notification_engine
    _notification_engine = NotificationEngine(server=server, config=config)
    return _notification_engine


async def send_notification(
    job_name: str,
    skill: str,
    success: bool,
    output: str | None = None,
    error: str | None = None,
    channels: list[str] | None = None,
):
    """Convenience function to send notifications via global engine."""
    if _notification_engine:
        await _notification_engine.notify(
            job_name=job_name,
            skill=skill,
            success=success,
            output=output,
            error=error,
            channels=channels,
        )
