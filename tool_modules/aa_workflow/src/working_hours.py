"""Working Hours Enforcer - Ensures bot actions appear human-like.

Controls when external-facing actions (Jira comments, Slack messages, etc.)
can be performed to make the bot appear more human:
- Only operates Mon-Fri 9-5 (configurable)
- Adds random delays to avoid robotic timing
- Respects timezone settings
"""

import asyncio
import logging
import random
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class WorkingHoursEnforcer:
    """Ensures external actions only happen during business hours.

    Usage:
        enforcer = WorkingHoursEnforcer(config)

        # Check if we can act now
        if enforcer.is_working_hours():
            await enforcer.add_human_delay()
            # ... perform action

        # Or wait until working hours
        await enforcer.wait_for_working_hours()
        # ... perform action
    """

    # Default configuration
    DEFAULT_CONFIG = {
        "enabled": True,
        "start_hour": 9,
        "end_hour": 17,
        "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
        "timezone": "America/New_York",
        "randomize_start": True,
        "randomize_minutes": 15,
    }

    # Day name to weekday number mapping
    DAY_NUMBERS = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the enforcer with configuration.

        Args:
            config: Working hours configuration dict. Uses defaults if not provided.
        """
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}
        self._tz = ZoneInfo(self.config["timezone"])
        self._working_days = {
            self.DAY_NUMBERS[day.lower()]
            for day in self.config["days"]
            if day.lower() in self.DAY_NUMBERS
        }

    @property
    def enabled(self) -> bool:
        """Check if working hours enforcement is enabled."""
        return self.config.get("enabled", True)

    def _now(self) -> datetime:
        """Get current time in configured timezone."""
        return datetime.now(self._tz)

    def is_working_hours(self) -> bool:
        """Check if current time is within working hours.

        Returns:
            True if within Mon-Fri 9-5 (or configured hours), False otherwise
        """
        if not self.enabled:
            return True  # Always allow if disabled

        now = self._now()

        # Check day of week
        if now.weekday() not in self._working_days:
            logger.debug(f"Not a working day: {now.strftime('%A')}")
            return False

        # Check time of day
        start = time(self.config["start_hour"], 0)
        end = time(self.config["end_hour"], 0)

        current_time = now.time()
        if not (start <= current_time < end):
            logger.debug(
                f"Outside working hours: {current_time} (working: {start}-{end})"
            )
            return False

        return True

    def get_next_working_time(self) -> datetime:
        """Calculate when the next working hours window starts.

        Returns:
            datetime of next working hours start
        """
        now = self._now()
        start_hour = self.config["start_hour"]

        # Start from today
        candidate = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)

        # If we're past start time today, move to tomorrow
        if now.time() >= time(start_hour, 0):
            candidate += timedelta(days=1)

        # Find next working day
        while candidate.weekday() not in self._working_days:
            candidate += timedelta(days=1)

        return candidate

    def add_human_delay(self) -> int:
        """Add a random delay to avoid robotic timing.

        Returns:
            Number of seconds that will be delayed
        """
        if not self.config.get("randomize_start", True):
            return 0

        max_minutes = self.config.get("randomize_minutes", 15)
        delay_seconds = random.randint(0, max_minutes * 60)

        logger.debug(
            f"Adding human delay: {delay_seconds}s ({delay_seconds // 60}m {delay_seconds % 60}s)"
        )
        return delay_seconds

    async def wait_for_delay(self) -> int:
        """Async wait for human delay.

        Returns:
            Number of seconds waited
        """
        delay = self.add_human_delay()
        if delay > 0:
            logger.info(f"Waiting {delay}s for human-like timing...")
            await asyncio.sleep(delay)
        return delay

    async def wait_for_working_hours(self) -> datetime:
        """Block until within working hours, then add random delay.

        Returns:
            datetime when work can begin
        """
        if not self.enabled:
            return self._now()

        while not self.is_working_hours():
            next_start = self.get_next_working_time()
            wait_seconds = (next_start - self._now()).total_seconds()

            if wait_seconds > 0:
                logger.info(
                    f"Outside working hours. Waiting until {next_start.strftime('%Y-%m-%d %H:%M %Z')} "
                    f"({wait_seconds / 3600:.1f} hours)"
                )
                # Sleep in chunks to allow for cancellation
                while wait_seconds > 0:
                    chunk = min(wait_seconds, 300)  # 5 minute chunks
                    await asyncio.sleep(chunk)
                    wait_seconds -= chunk

                    # Re-check in case config changed
                    if self.is_working_hours():
                        break

        # Add human delay
        await self.wait_for_delay()

        return self._now()

    def get_status(self) -> dict[str, Any]:
        """Get current working hours status.

        Returns:
            Dict with status information
        """
        now = self._now()
        is_working = self.is_working_hours()

        status = {
            "enabled": self.enabled,
            "is_working_hours": is_working,
            "current_time": now.isoformat(),
            "timezone": self.config["timezone"],
            "working_days": list(self.config["days"]),
            "working_hours": f"{self.config['start_hour']:02d}:00 - {self.config['end_hour']:02d}:00",
        }

        if not is_working:
            next_start = self.get_next_working_time()
            status["next_working_time"] = next_start.isoformat()
            status["wait_hours"] = round((next_start - now).total_seconds() / 3600, 1)

        return status

    def format_status(self) -> str:
        """Format status as human-readable string.

        Returns:
            Formatted status string
        """
        status = self.get_status()

        if not status["enabled"]:
            return "Working hours enforcement: DISABLED"

        if status["is_working_hours"]:
            return (
                "Working hours: ACTIVE\n"
                f"  Time: {self._now().strftime('%Y-%m-%d %H:%M %Z')}\n"
                f"  Hours: {status['working_hours']}\n"
                f"  Days: {', '.join(status['working_days'])}"
            )
        else:
            return (
                "Working hours: OUTSIDE\n"
                f"  Current: {self._now().strftime('%Y-%m-%d %H:%M %Z')}\n"
                f"  Next window: {status.get('next_working_time', 'N/A')}\n"
                f"  Wait: {status.get('wait_hours', 0)} hours"
            )


# Singleton instance for easy import
_enforcer: WorkingHoursEnforcer | None = None


def get_working_hours_enforcer(
    config: dict[str, Any] | None = None,
) -> WorkingHoursEnforcer:
    """Get or create the working hours enforcer singleton.

    Args:
        config: Optional config to use (only applied on first call)

    Returns:
        WorkingHoursEnforcer instance
    """
    global _enforcer
    if _enforcer is None:
        _enforcer = WorkingHoursEnforcer(config)
    return _enforcer


def reset_enforcer() -> None:
    """Reset the singleton (useful for testing)."""
    global _enforcer
    _enforcer = None
