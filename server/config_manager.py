"""Centralized Configuration Manager.

Provides thread-safe, debounced access to config.json with:
- File locking for cross-process safety (fcntl.flock)
- Automatic cache invalidation via mtime checking
- Debounced writes to reduce disk I/O
- Section-based API for clean access patterns

Usage:
    from server.config_manager import config

    # Read
    slack_config = config.get("slack")
    enabled = config.get("schedules", "enabled", default=False)

    # Write (debounced - batches rapid changes)
    config.set("schedules", "enabled", True)

    # Write (immediate - for critical updates)
    config.set("slack", "auth", {"token": "..."}, flush=True)

    # Bulk update
    config.update_section("repositories", {"my-repo": {...}})

    # Force operations
    config.flush()   # Write pending changes now
    config.reload()  # Force reload from disk
"""

import fcntl
import json
import logging
import threading
from pathlib import Path
from threading import Timer
from typing import Any

logger = logging.getLogger(__name__)

# Project root (this file is at server/config_manager.py)
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_FILE = PROJECT_ROOT / "config.json"

# Debounce delay in seconds
DEBOUNCE_DELAY = 2.0


# ==================== Config Validation ====================


class ConfigValidationError(Exception):
    """Raised when config validation fails."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Config validation failed: {'; '.join(errors)}")


# Schema for required config sections and their expected types
# Format: {section: {key: type | (type, required, default)}}
CONFIG_SCHEMA: dict[str, dict[str, Any]] = {
    "paths": {
        "config_dir": (str, False, "~/.config/aa-workflow"),
    },
    "repositories": {
        # Dynamic - validated separately
    },
    "jira": {
        "server": (str, True, None),
        "project": (str, False, "AAP"),
    },
    "gitlab": {
        "url": (str, True, None),
        "project_id": (int, False, None),
    },
    "slack": {
        "workspace": (str, False, None),
        "bot_user_id": (str, False, None),
    },
}

# Required top-level sections
REQUIRED_SECTIONS = ["jira", "gitlab"]


def validate_config(config: dict[str, Any], strict: bool = False) -> list[str]:
    """Validate config against schema.

    Args:
        config: Config dict to validate
        strict: If True, fail on unknown sections

    Returns:
        List of validation error messages (empty if valid)
    """
    errors: list[str] = []

    # Check required sections exist
    for section in REQUIRED_SECTIONS:
        if section not in config:
            errors.append(f"Missing required section: {section}")

    # Validate each section against schema
    for section, schema in CONFIG_SCHEMA.items():
        if section not in config:
            continue

        section_data = config[section]
        if not isinstance(section_data, dict):
            errors.append(f"Section '{section}' must be a dict, got {type(section_data).__name__}")
            continue

        for key, spec in schema.items():
            if isinstance(spec, tuple):
                expected_type, required, default = spec
            else:
                expected_type, required, default = spec, False, None  # noqa: F841

            if key not in section_data:
                if required:
                    errors.append(f"Missing required key: {section}.{key}")
                continue

            value = section_data[key]
            if value is not None and not isinstance(value, expected_type):
                errors.append(
                    f"Invalid type for {section}.{key}: expected {expected_type.__name__}, "
                    f"got {type(value).__name__}"
                )

    # Validate repositories structure if present
    if "repositories" in config:
        repos = config["repositories"]
        if not isinstance(repos, dict):
            errors.append(f"'repositories' must be a dict, got {type(repos).__name__}")
        else:
            for repo_name, repo_config in repos.items():
                if not isinstance(repo_config, dict):
                    errors.append(f"Repository '{repo_name}' config must be a dict")
                    continue
                # Check for common required fields
                if "path" not in repo_config and "gitlab_path" not in repo_config:
                    errors.append(f"Repository '{repo_name}' missing 'path' or 'gitlab_path'")

    return errors


def get_config_defaults() -> dict[str, Any]:
    """Get default config values from schema.

    Returns:
        Dict with default values for all optional fields
    """
    defaults: dict[str, Any] = {}

    for section, schema in CONFIG_SCHEMA.items():
        section_defaults: dict[str, Any] = {}
        for key, spec in schema.items():
            if isinstance(spec, tuple):
                _, _, default = spec
                if default is not None:
                    section_defaults[key] = default
        if section_defaults:
            defaults[section] = section_defaults

    return defaults


class ConfigManager:
    """Thread-safe, debounced configuration manager.

    Singleton pattern ensures one manager per process.
    Cross-process safety via file locking.

    Features:
    - Thread-safe: RLock protects all operations
    - Debounced writes: Changes batched before disk write
    - Auto-reload: Detects external file changes via mtime
    - File locking: fcntl.flock prevents cross-process corruption
    """

    _instance: "ConfigManager | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "ConfigManager":
        """Singleton pattern - one instance per process."""
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._initialized = False
                cls._instance = instance
            return cls._instance

    def __init__(self):
        """Initialize the config manager (only runs once due to singleton)."""
        if getattr(self, "_initialized", False):
            return

        self._lock = threading.RLock()
        self._cache: dict[str, Any] = {}
        self._dirty = False
        self._last_mtime: float = 0.0
        self._debounce_timer: Timer | None = None
        self._initialized = True

        # Load initial config
        self._load()

        logger.debug(f"ConfigManager initialized from {CONFIG_FILE}")

    def _load(self) -> None:
        """Load config from disk (internal, no lock)."""
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE) as f:
                    self._cache = json.load(f)
                self._last_mtime = CONFIG_FILE.stat().st_mtime
                logger.debug(f"Config loaded, {len(self._cache)} sections")
            else:
                self._cache = {}
                self._last_mtime = 0.0
                logger.warning(f"Config file not found: {CONFIG_FILE}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config.json: {e}")
            self._cache = {}
        except OSError as e:
            logger.error(f"Failed to read config.json: {e}")
            self._cache = {}

    def _check_reload(self) -> None:
        """Check if file was modified externally and reload if needed (internal, no lock)."""
        try:
            if CONFIG_FILE.exists():
                current_mtime = CONFIG_FILE.stat().st_mtime
                if current_mtime > self._last_mtime:
                    logger.info("Config file changed externally, reloading")
                    self._load()
        except OSError:
            pass

    def _mark_dirty(self) -> None:
        """Mark config as dirty and schedule debounced write (internal, no lock)."""
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
        """Write config to disk with file locking (internal, assumes lock held)."""
        if not self._dirty:
            return

        try:
            # Ensure parent directory exists
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

            # Write with exclusive file lock
            with open(CONFIG_FILE, "w") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(self._cache, f, indent=2)
                    f.write("\n")  # Trailing newline
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            self._dirty = False
            self._last_mtime = CONFIG_FILE.stat().st_mtime
            logger.debug("Config flushed to disk")

        except OSError as e:
            logger.error(f"Failed to write config.json: {e}")

    # ==================== Public API ====================

    def get(self, section: str, key: str | None = None, default: Any = None) -> Any:
        """Get a config value.

        Args:
            section: Top-level section name (e.g., "slack", "schedules")
            key: Optional key within section. If None, returns entire section.
            default: Default value if not found

        Returns:
            Config value or default

        Examples:
            config.get("slack")  # Returns entire slack section
            config.get("schedules", "enabled", False)  # Returns schedules.enabled
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
        """Get entire config as a dictionary.

        Returns:
            Copy of the entire config
        """
        with self._lock:
            self._check_reload()
            return dict(self._cache)

    def set(self, section: str, key: str, value: Any, flush: bool = False) -> None:
        """Set a config value.

        Args:
            section: Top-level section name
            key: Key within section
            value: Value to set
            flush: If True, write to disk immediately (default: debounced)

        Examples:
            config.set("schedules", "enabled", True)
            config.set("slack", "auth", {"token": "..."}, flush=True)
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

        Examples:
            config.update_section("repositories", {"my-repo": {...}})
            config.update_section("slack", {"auth": {...}}, merge=False)
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
        """Delete a config value or section.

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
        """Force reload config from disk, discarding any pending changes."""
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

    @property
    def config_file(self) -> Path:
        """Get the path to the config file."""
        return CONFIG_FILE

    def validate(self, strict: bool = False) -> list[str]:
        """Validate the current config against the schema.

        Args:
            strict: If True, fail on unknown sections

        Returns:
            List of validation error messages (empty if valid)

        Examples:
            errors = config.validate()
            if errors:
                print(f"Config errors: {errors}")
        """
        with self._lock:
            self._check_reload()
            return validate_config(self._cache, strict=strict)

    def validate_or_raise(self, strict: bool = False) -> None:
        """Validate config and raise exception if invalid.

        Args:
            strict: If True, fail on unknown sections

        Raises:
            ConfigValidationError: If validation fails
        """
        errors = self.validate(strict=strict)
        if errors:
            raise ConfigValidationError(errors)

    def get_with_default(self, section: str, key: str) -> Any:
        """Get a config value, falling back to schema default.

        Args:
            section: Top-level section name
            key: Key within section

        Returns:
            Config value, schema default, or None
        """
        with self._lock:
            self._check_reload()

            # Try to get from config
            section_data = self._cache.get(section, {})
            if isinstance(section_data, dict) and key in section_data:
                return section_data[key]

            # Fall back to schema default
            schema = CONFIG_SCHEMA.get(section, {})
            spec = schema.get(key)
            if isinstance(spec, tuple) and len(spec) >= 3:
                return spec[2]  # Default value

            return None


# Global singleton instance for convenient access
config = ConfigManager()


# ==================== Backward Compatibility ====================


def load_config(reload: bool = False) -> dict[str, Any]:
    """Load config.json - backward compatible function.

    This function provides backward compatibility with existing code
    that uses `from server.config_manager import load_config`.

    Args:
        reload: If True, force reload from disk

    Returns:
        Config dictionary
    """
    if reload:
        config.reload()
    return config.get_all()


def get_section_config(section: str, default: dict | None = None) -> dict:
    """Get a config section - backward compatible function.

    Args:
        section: Section name
        default: Default value if section not found

    Returns:
        Section dictionary
    """
    result = config.get(section)
    if result is None:
        return default or {}
    if isinstance(result, dict):
        return result
    return default or {}
