"""Standardised config loading for tool modules.

Eliminates the repeated pattern found in 15+ modules:

    def _get_X_config() -> dict:
        config = load_config()
        return config.get("section", {})

Usage:
    from tool_modules.common.config import ToolModuleConfig

    # Simple section config
    config = ToolModuleConfig("prometheus")
    url = config["url"]
    token = config.get("token", "")

    # With environment variable fallbacks
    config = ToolModuleConfig("quay", env_prefix="QUAY")
    api_url = config.get("api_url")  # Falls back to QUAY_API_URL env var

    # One-shot function for simple cases
    from tool_modules.common.config import get_module_config
    cfg = get_module_config("kibana")
"""

import os
from functools import lru_cache
from typing import Any


@lru_cache(maxsize=32)
def get_module_config(section: str) -> dict:
    """Load a configuration section from config.json.

    This is the simplest way to get config. For more features (env vars,
    nested keys, defaults), use ToolModuleConfig.

    Args:
        section: Top-level key in config.json (e.g., "prometheus", "quay")

    Returns:
        Dict from that section, or empty dict if not found.
    """
    from server.utils import load_config

    config = load_config()
    return config.get(section, {})


def clear_config_cache() -> None:
    """Clear the config cache. Call after config.json changes."""
    get_module_config.cache_clear()


class ToolModuleConfig:
    """Lazy-loading config for a tool module.

    Provides dict-like access to a section of config.json with optional
    environment variable fallbacks.

    Args:
        section: Top-level key in config.json (e.g., "prometheus")
        env_prefix: Optional prefix for environment variable fallbacks.
                    If set, config.get("api_url") will also check
                    {ENV_PREFIX}_API_URL.
        defaults: Default values for keys not found in config or env.
    """

    def __init__(
        self,
        section: str,
        env_prefix: str | None = None,
        defaults: dict[str, Any] | None = None,
    ):
        self._section = section
        self._env_prefix = env_prefix.upper() if env_prefix else None
        self._defaults = defaults or {}
        self._data: dict | None = None

    @property
    def data(self) -> dict:
        """Lazy-load the config section."""
        if self._data is None:
            self._data = get_module_config(self._section)
        return self._data

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value with optional env var fallback.

        Resolution order:
        1. config.json section value
        2. Environment variable ({ENV_PREFIX}_{KEY_UPPER})
        3. Constructor defaults
        4. Provided default argument
        """
        # 1. Config.json
        value = self.data.get(key)
        if value is not None:
            return value

        # 2. Environment variable
        if self._env_prefix:
            env_key = f"{self._env_prefix}_{key.upper()}"
            env_value = os.environ.get(env_key)
            if env_value is not None:
                return env_value

        # 3. Constructor defaults
        if key in self._defaults:
            return self._defaults[key]

        # 4. Provided default
        return default

    def __getitem__(self, key: str) -> Any:
        """Dict-like access. Raises KeyError if not found."""
        value = self.get(key)
        if value is None:
            raise KeyError(f"Config key '{key}' not found in section '{self._section}'")
        return value

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def __repr__(self) -> str:
        return f"ToolModuleConfig(section={self._section!r}, keys={list(self.data.keys())})"
