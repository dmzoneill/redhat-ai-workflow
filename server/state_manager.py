"""Centralized State Manager.

Provides thread-safe, debounced access to state.json with:
- File locking for cross-process safety (fcntl.flock)
- Automatic cache invalidation via mtime checking
- Debounced writes to reduce disk I/O
- Section-based API for clean access patterns

This manages RUNTIME STATE (enabled flags, toggles) separate from
CONFIGURATION (config.json) which holds static settings.

Usage:
    from server.state_manager import state

    # Read
    scheduler_enabled = state.is_service_enabled("scheduler")
    job_enabled = state.is_job_enabled("morning_coffee")

    # Write
    state.set_service_enabled("scheduler", True)
    state.set_job_enabled("morning_coffee", False, flush=True)

    # Low-level access
    state.get("services", "scheduler", default={})
    state.set("services", "scheduler", {"enabled": True})

    # Force operations
    state.flush()   # Write pending changes now
    state.reload()  # Force reload from disk
"""

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from server.json_file_manager import JsonFileManager
from server.paths import STATE_FILE

logger = logging.getLogger(__name__)

# Default state structure
# NOTE: Service enabled flags are NOT stored here. config.json is the source
# of truth for whether a service is enabled. state.json only stores runtime
# overrides (e.g., temporarily disabling a service via the UI).
DEFAULT_STATE: dict[str, Any] = {
    "version": 1,
    "services": {},  # Runtime overrides only, not defaults
    "jobs": {},
    "last_updated": None,
}


class StateManager(JsonFileManager):
    """Thread-safe, debounced state manager.

    Singleton pattern ensures one manager per process.
    Cross-process safety via file locking.

    Inherits core file I/O from JsonFileManager and adds:
    - Service enable/disable convenience methods
    - Job enable/disable convenience methods
    - Meeting override management
    - Automatic last_updated timestamp on flush
    """

    _instance: "StateManager | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "StateManager":
        """Singleton pattern - one instance per process."""
        with cls._instance_lock:
            if cls._instance is None:
                instance = super(JsonFileManager, cls).__new__(cls)
                instance._initialized = False
                cls._instance = instance
            return cls._instance

    @property  # type: ignore[override]
    def _file_path(self) -> Path:
        """Delegate to module-level STATE_FILE so patching works in tests."""
        return STATE_FILE

    @_file_path.setter
    def _file_path(self, value: Path) -> None:
        """No-op setter; path always comes from STATE_FILE."""
        pass

    def __init__(self):
        """Initialize the state manager (only runs once due to singleton)."""
        if getattr(self, "_initialized", False):
            return

        self._default_data = DEFAULT_STATE
        self._file_label = "state.json"
        self._initialized = True

        super().__init__()

    def _on_pre_flush(self) -> None:
        """Update timestamp before writing to disk."""
        self._cache["last_updated"] = datetime.now().isoformat()

    @property
    def state_file(self) -> Path:
        """Get the path to the state file."""
        return STATE_FILE

    # ==================== Convenience Methods ====================

    def is_service_enabled(self, service: str) -> bool:
        """Check if a service is enabled.

        Checks state.json for a runtime override first. If no override exists,
        falls back to config.json as the source of truth for service enabled flags.

        Args:
            service: Service name (scheduler, sprint_bot, google_calendar, gmail)

        Returns:
            True if enabled, False otherwise
        """
        # Check state.json for runtime override
        service_state = self.get("services", service, {})
        if isinstance(service_state, dict) and "enabled" in service_state:
            return service_state["enabled"]

        # Fall back to config.json as source of truth
        try:
            from server.config_manager import config as config_mgr

            # Map service names to config.json sections
            # e.g., "scheduler" -> config.schedules.enabled
            #        "sprint_bot" -> config.sprint.enabled
            service_to_config = {
                "scheduler": ("schedules", "enabled"),
                "sprint_bot": ("sprint", "enabled"),
                "google_calendar": ("google_calendar", "enabled"),
                "gmail": ("gmail", "enabled"),
            }
            if service in service_to_config:
                section, key = service_to_config[service]
                return bool(config_mgr.get(section, key, False))
            # Generic: check config.<service>.enabled
            return bool(config_mgr.get(service, "enabled", False))
        except Exception:
            return False

    def set_service_enabled(
        self, service: str, enabled: bool, flush: bool = False
    ) -> None:
        """Enable or disable a service.

        Args:
            service: Service name
            enabled: True to enable, False to disable
            flush: If True, write to disk immediately
        """
        self.set("services", service, {"enabled": enabled}, flush=flush)

    def is_job_enabled(self, job_name: str) -> bool:
        """Check if a scheduled job is enabled.

        Args:
            job_name: Job name

        Returns:
            True if enabled, False otherwise (defaults to True if not set)
        """
        job_state = self.get("jobs", job_name, {})
        if isinstance(job_state, dict):
            # Jobs default to True if not explicitly disabled
            return job_state.get("enabled", True)
        return True

    def set_job_enabled(
        self, job_name: str, enabled: bool, flush: bool = False
    ) -> None:
        """Enable or disable a scheduled job.

        Args:
            job_name: Job name
            enabled: True to enable, False to disable
            flush: If True, write to disk immediately
        """
        self.set("jobs", job_name, {"enabled": enabled}, flush=flush)

    def get_all_job_states(self) -> dict[str, bool]:
        """Get enabled state for all jobs.

        Returns:
            Dict mapping job name to enabled state
        """
        jobs = self.get("jobs", default={})
        if not isinstance(jobs, dict):
            return {}
        return {
            name: state.get("enabled", True) if isinstance(state, dict) else True
            for name, state in jobs.items()
        }

    # ==================== Meeting Overrides ====================

    def get_meeting_overrides(self) -> dict[str, Any]:
        """Get all meeting status overrides.

        Returns:
            Dict mapping meet_key to override data {status, timestamp}
        """
        return self.get("meetings", "overrides", {})

    def get_meeting_override(self, meet_key: str) -> str | None:
        """Get the status override for a specific meeting.

        Args:
            meet_key: Meeting key (e.g., 'abc-defg-hij' from Google Meet URL)

        Returns:
            Status string ('skip', 'join', etc.) or None if not set
        """
        overrides = self.get("meetings", "overrides", {})
        override = overrides.get(meet_key)
        if isinstance(override, dict):
            return override.get("status")
        return None

    def set_meeting_override(
        self, meet_key: str, status: str, flush: bool = True
    ) -> None:
        """Set a meeting status override.

        Args:
            meet_key: Meeting key (e.g., 'abc-defg-hij' from Google Meet URL)
            status: Status to set ('skip', 'join', etc.)
            flush: If True, write to disk immediately
        """
        import time

        overrides = self.get("meetings", "overrides", {})
        overrides[meet_key] = {"status": status, "timestamp": time.time()}
        self.set("meetings", "overrides", overrides, flush=flush)

    def clear_meeting_override(self, meet_key: str, flush: bool = True) -> bool:
        """Clear a meeting status override.

        Args:
            meet_key: Meeting key to clear
            flush: If True, write to disk immediately

        Returns:
            True if override was cleared, False if it didn't exist
        """
        overrides = self.get("meetings", "overrides", {})
        if meet_key in overrides:
            del overrides[meet_key]
            self.set("meetings", "overrides", overrides, flush=flush)
            return True
        return False


# Global singleton instance for convenient access
state = StateManager()
