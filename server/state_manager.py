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

import fcntl
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from threading import Timer
from typing import Any

logger = logging.getLogger(__name__)

# Project root (this file is at server/state_manager.py)
PROJECT_ROOT = Path(__file__).parent.parent
STATE_FILE = PROJECT_ROOT / "state.json"

# Debounce delay in seconds
DEBOUNCE_DELAY = 2.0

# Default state structure
DEFAULT_STATE: dict[str, Any] = {
    "version": 1,
    "services": {
        "scheduler": {"enabled": False},
        "sprint_bot": {"enabled": False},
        "google_calendar": {"enabled": False},
        "gmail": {"enabled": False},
    },
    "jobs": {},
    "last_updated": None,
}


class StateManager:
    """Thread-safe, debounced state manager.

    Singleton pattern ensures one manager per process.
    Cross-process safety via file locking.

    Features:
    - Thread-safe: RLock protects all operations
    - Debounced writes: Changes batched before disk write
    - Auto-reload: Detects external file changes via mtime
    - File locking: fcntl.flock prevents cross-process corruption
    """

    _instance: "StateManager | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "StateManager":
        """Singleton pattern - one instance per process."""
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._initialized = False
                cls._instance = instance
            return cls._instance

    def __init__(self):
        """Initialize the state manager (only runs once due to singleton)."""
        if getattr(self, "_initialized", False):
            return

        self._lock = threading.RLock()
        self._cache: dict[str, Any] = {}
        self._dirty = False
        self._last_mtime: float = 0.0
        self._debounce_timer: Timer | None = None
        self._initialized = True

        # Load initial state
        self._load()

        logger.debug(f"StateManager initialized from {STATE_FILE}")

    def _load(self) -> None:
        """Load state from disk (internal, no lock)."""
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE) as f:
                    self._cache = json.load(f)
                self._last_mtime = STATE_FILE.stat().st_mtime
                logger.debug(f"State loaded, {len(self._cache)} sections")
            else:
                # No state file - use defaults
                self._cache = json.loads(json.dumps(DEFAULT_STATE))  # Deep copy
                self._last_mtime = 0.0
                logger.info(f"State file not found, using defaults: {STATE_FILE}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in state.json: {e}")
            self._cache = json.loads(json.dumps(DEFAULT_STATE))
        except OSError as e:
            logger.error(f"Failed to read state.json: {e}")
            self._cache = json.loads(json.dumps(DEFAULT_STATE))

    def _check_reload(self) -> None:
        """Check if file was modified externally and reload if needed (internal, no lock)."""
        try:
            if STATE_FILE.exists():
                current_mtime = STATE_FILE.stat().st_mtime
                if current_mtime > self._last_mtime:
                    logger.info("State file changed externally, reloading")
                    self._load()
        except OSError:
            pass

    def _mark_dirty(self) -> None:
        """Mark state as dirty and schedule debounced write (internal, no lock)."""
        self._dirty = True

        # Cancel existing timer
        if self._debounce_timer is not None:
            self._debounce_timer.cancel()

        # Schedule flush after debounce delay
        self._debounce_timer = Timer(DEBOUNCE_DELAY, self._flush_debounced)
        self._debounce_timer.daemon = True  # Don't block process exit
        self._debounce_timer.start()

    def _flush_debounced(self) -> None:
        """Called by debounce timer to flush changes."""
        with self._lock:
            self._flush_internal()

    def _flush_internal(self) -> None:
        """Write state to disk with file locking (internal, assumes lock held)."""
        if not self._dirty:
            return

        try:
            # Ensure parent directory exists
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

            # Update timestamp
            self._cache["last_updated"] = datetime.now().isoformat()

            # Write with exclusive file lock
            with open(STATE_FILE, "w") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(self._cache, f, indent=2)
                    f.write("\n")  # Trailing newline
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            self._dirty = False
            self._last_mtime = STATE_FILE.stat().st_mtime
            logger.debug("State flushed to disk")

        except OSError as e:
            logger.error(f"Failed to write state.json: {e}")

    # ==================== Public API ====================

    def get(self, section: str, key: str | None = None, default: Any = None) -> Any:
        """Get a state value.

        Args:
            section: Top-level section name (e.g., "services", "jobs")
            key: Optional key within section. If None, returns entire section.
            default: Default value if not found

        Returns:
            State value or default

        Examples:
            state.get("services")  # Returns entire services section
            state.get("services", "scheduler", {})  # Returns scheduler state
        """
        with self._lock:
            self._check_reload()

            section_data = self._cache.get(section)
            if section_data is None:
                return default

            if key is None:
                return section_data

            if isinstance(section_data, dict):
                return section_data.get(key, default)

            return default

    def get_all(self) -> dict[str, Any]:
        """Get entire state as a dictionary.

        Returns:
            Copy of the entire state
        """
        with self._lock:
            self._check_reload()
            return dict(self._cache)

    def set(self, section: str, key: str, value: Any, flush: bool = False) -> None:
        """Set a state value.

        Args:
            section: Top-level section name
            key: Key within section
            value: Value to set
            flush: If True, write to disk immediately (default: debounced)

        Examples:
            state.set("services", "scheduler", {"enabled": True})
            state.set("jobs", "morning_coffee", {"enabled": False}, flush=True)
        """
        with self._lock:
            self._check_reload()

            if section not in self._cache:
                self._cache[section] = {}

            if not isinstance(self._cache[section], dict):
                self._cache[section] = {}

            self._cache[section][key] = value
            self._mark_dirty()

            if flush:
                self._flush_internal()

    def update_section(self, section: str, data: dict[str, Any], merge: bool = True, flush: bool = False) -> None:
        """Update an entire section.

        Args:
            section: Top-level section name
            data: Dictionary of values to set
            merge: If True, merge with existing values. If False, replace entire section.
            flush: If True, write to disk immediately
        """
        with self._lock:
            self._check_reload()

            if merge and section in self._cache and isinstance(self._cache[section], dict):
                self._cache[section].update(data)
            else:
                self._cache[section] = data

            self._mark_dirty()

            if flush:
                self._flush_internal()

    def delete(self, section: str, key: str | None = None, flush: bool = False) -> bool:
        """Delete a state value or section.

        Args:
            section: Top-level section name
            key: Optional key within section. If None, deletes entire section.
            flush: If True, write to disk immediately

        Returns:
            True if something was deleted, False otherwise
        """
        with self._lock:
            self._check_reload()

            if section not in self._cache:
                return False

            if key is None:
                del self._cache[section]
                self._mark_dirty()
                if flush:
                    self._flush_internal()
                return True

            if isinstance(self._cache[section], dict) and key in self._cache[section]:
                del self._cache[section][key]
                self._mark_dirty()
                if flush:
                    self._flush_internal()
                return True

            return False

    def flush(self) -> None:
        """Force write pending changes to disk immediately."""
        with self._lock:
            # Cancel pending debounce timer
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None

            self._flush_internal()

    def reload(self) -> None:
        """Force reload state from disk, discarding any pending changes."""
        with self._lock:
            # Cancel pending debounce timer
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None

            self._dirty = False
            self._load()

    def has_section(self, section: str) -> bool:
        """Check if a section exists."""
        with self._lock:
            self._check_reload()
            return section in self._cache

    def sections(self) -> list[str]:
        """Get list of all section names."""
        with self._lock:
            self._check_reload()
            return list(self._cache.keys())

    @property
    def is_dirty(self) -> bool:
        """Check if there are pending changes not yet written to disk."""
        with self._lock:
            return self._dirty

    @property
    def state_file(self) -> Path:
        """Get the path to the state file."""
        return STATE_FILE

    # ==================== Convenience Methods ====================

    def is_service_enabled(self, service: str) -> bool:
        """Check if a service is enabled.

        Args:
            service: Service name (scheduler, sprint_bot, google_calendar, gmail)

        Returns:
            True if enabled, False otherwise
        """
        service_state = self.get("services", service, {})
        if isinstance(service_state, dict):
            return service_state.get("enabled", False)
        return False

    def set_service_enabled(self, service: str, enabled: bool, flush: bool = False) -> None:
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

    def set_job_enabled(self, job_name: str, enabled: bool, flush: bool = False) -> None:
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
        return {name: state.get("enabled", True) if isinstance(state, dict) else True for name, state in jobs.items()}

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

    def set_meeting_override(self, meet_key: str, status: str, flush: bool = True) -> None:
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
