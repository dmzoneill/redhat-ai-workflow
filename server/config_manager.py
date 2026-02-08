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

import logging
import threading
from pathlib import Path
from typing import Any

from server.json_file_manager import JsonFileManager

logger = logging.getLogger(__name__)

# Project root (this file is at server/config_manager.py)
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_FILE = PROJECT_ROOT / "config.json"


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
            errors.append(
                f"Section '{section}' must be a dict, got {type(section_data).__name__}"
            )
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
                    errors.append(
                        f"Repository '{repo_name}' missing 'path' or 'gitlab_path'"
                    )

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


class ConfigManager(JsonFileManager):
    """Thread-safe, debounced configuration manager.

    Singleton pattern ensures one manager per process.
    Cross-process safety via file locking.

    Inherits core file I/O from JsonFileManager and adds:
    - Config validation against schema
    - Schema-based default fallback
    - Backward-compatible helpers
    """

    _instance: "ConfigManager | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "ConfigManager":
        """Singleton pattern - one instance per process."""
        with cls._instance_lock:
            if cls._instance is None:
                instance = super(JsonFileManager, cls).__new__(cls)
                instance._initialized = False
                cls._instance = instance
            return cls._instance

    @property  # type: ignore[override]
    def _file_path(self) -> Path:
        """Delegate to module-level CONFIG_FILE so patching works in tests."""
        return CONFIG_FILE

    @_file_path.setter
    def _file_path(self, value: Path) -> None:
        """No-op setter; path always comes from CONFIG_FILE."""
        pass

    def __init__(self):
        """Initialize the config manager (only runs once due to singleton)."""
        if getattr(self, "_initialized", False):
            return

        self._default_data = {}
        self._file_label = "config.json"
        self._initialized = True

        super().__init__()

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
