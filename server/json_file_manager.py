"""JSON File Manager Base Class.

Provides thread-safe, debounced access to a JSON file with:
- File locking for cross-process safety (fcntl.flock)
- Automatic cache invalidation via mtime checking
- Debounced writes to reduce disk I/O
- Section-based API for clean access patterns

This is the shared base class for ConfigManager and StateManager.
"""

import fcntl
import json
import logging
import threading
from pathlib import Path
from threading import Timer
from typing import Any

logger = logging.getLogger(__name__)

# Debounce delay in seconds
DEBOUNCE_DELAY = 2.0


class JsonFileManager:
    """Thread-safe, debounced JSON file manager.

    Subclasses must set:
    - _file_path: Path to the JSON file
    - _default_data: Default data when file is missing (optional, defaults to {})

    Subclasses may override:
    - _on_load(): Called after data is loaded from disk
    - _on_pre_flush(): Called before data is written to disk
    - _file_label: Human-readable label for log messages (e.g., "config.json")

    Features:
    - Thread-safe: RLock protects all operations
    - Debounced writes: Changes batched before disk write
    - Auto-reload: Detects external file changes via mtime
    - File locking: fcntl.flock prevents cross-process corruption
    """

    # Subclasses must set these before __init__ or in __init__ before calling super
    _file_path: Path
    _default_data: dict[str, Any] = {}
    _file_label: str = "JSON file"

    def __init__(self):
        """Initialize the JSON file manager."""
        self._lock = threading.RLock()
        self._cache: dict[str, Any] = {}
        self._dirty = False
        self._last_mtime: float = 0.0
        self._debounce_timer: Timer | None = None

        # Load initial data
        self._load()

        logger.debug(f"{self._file_label} manager initialized from {self._file_path}")

    def _load(self) -> None:
        """Load data from disk (internal, no lock)."""
        try:
            if self._file_path.exists():
                with open(self._file_path) as f:
                    self._cache = json.load(f)
                self._last_mtime = self._file_path.stat().st_mtime
                logger.debug(f"{self._file_label} loaded, {len(self._cache)} sections")
            else:
                # Use default data (deep copy to avoid shared state)
                self._cache = (
                    json.loads(json.dumps(self._default_data))
                    if self._default_data
                    else {}
                )
                self._last_mtime = 0.0
                if self._default_data:
                    logger.info(
                        f"{self._file_label} not found, using defaults: {self._file_path}"
                    )
                else:
                    logger.warning(f"{self._file_label} not found: {self._file_path}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {self._file_label}: {e}")
            self._cache = (
                json.loads(json.dumps(self._default_data)) if self._default_data else {}
            )
        except OSError as e:
            logger.error(f"Failed to read {self._file_label}: {e}")
            self._cache = (
                json.loads(json.dumps(self._default_data)) if self._default_data else {}
            )

    def _check_reload(self) -> None:
        """Check if file was modified externally and reload if needed (internal, no lock)."""
        try:
            if self._file_path.exists():
                current_mtime = self._file_path.stat().st_mtime
                if current_mtime > self._last_mtime:
                    logger.info(f"{self._file_label} changed externally, reloading")
                    self._load()
        except OSError:
            pass

    def _mark_dirty(self) -> None:
        """Mark data as dirty and schedule debounced write (internal, no lock)."""
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

    def _on_pre_flush(self) -> None:
        """Hook called before writing data to disk. Override in subclasses."""
        pass

    def _flush_internal(self) -> None:
        """Write data to disk with file locking (internal, assumes lock held)."""
        if not self._dirty:
            return

        try:
            # Ensure parent directory exists
            self._file_path.parent.mkdir(parents=True, exist_ok=True)

            # Pre-flush hook for subclasses
            self._on_pre_flush()

            # Write with exclusive file lock
            with open(self._file_path, "w") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(self._cache, f, indent=2)
                    f.write("\n")  # Trailing newline
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            self._dirty = False
            self._last_mtime = self._file_path.stat().st_mtime
            logger.debug(f"{self._file_label} flushed to disk")

        except OSError as e:
            logger.error(f"Failed to write {self._file_label}: {e}")

    # ==================== Public API ====================

    def get(self, section: str, key: str | None = None, default: Any = None) -> Any:
        """Get a value.

        Args:
            section: Top-level section name
            key: Optional key within section. If None, returns entire section.
            default: Default value if not found

        Returns:
            Value or default
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
        """Get entire data as a dictionary.

        Returns:
            Copy of the entire data
        """
        with self._lock:
            self._check_reload()
            return dict(self._cache)

    def set(self, section: str, key: str, value: Any, flush: bool = False) -> None:
        """Set a value.

        Args:
            section: Top-level section name
            key: Key within section
            value: Value to set
            flush: If True, write to disk immediately (default: debounced)
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

    def update_section(
        self,
        section: str,
        data: dict[str, Any],
        merge: bool = True,
        flush: bool = False,
    ) -> None:
        """Update an entire section.

        Args:
            section: Top-level section name
            data: Dictionary of values to set
            merge: If True, merge with existing values. If False, replace entire section.
            flush: If True, write to disk immediately
        """
        with self._lock:
            self._check_reload()

            if (
                merge
                and section in self._cache
                and isinstance(self._cache[section], dict)
            ):
                self._cache[section].update(data)
            else:
                self._cache[section] = data

            self._mark_dirty()

            if flush:
                self._flush_internal()

    def delete(self, section: str, key: str | None = None, flush: bool = False) -> bool:
        """Delete a value or section.

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
        """Force reload from disk, discarding any pending changes."""
        with self._lock:
            # Cancel pending debounce timer
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None

            self._dirty = False
            self._load()

    def has_section(self, section: str) -> bool:
        """Check if a section exists.

        Args:
            section: Top-level section name

        Returns:
            True if section exists
        """
        with self._lock:
            self._check_reload()
            return section in self._cache

    def sections(self) -> list[str]:
        """Get list of all section names.

        Returns:
            List of top-level section names
        """
        with self._lock:
            self._check_reload()
            return list(self._cache.keys())

    @property
    def is_dirty(self) -> bool:
        """Check if there are pending changes not yet written to disk."""
        with self._lock:
            return bool(self._dirty)
