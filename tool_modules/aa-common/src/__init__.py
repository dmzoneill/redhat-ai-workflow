"""AA Common - Shared utilities for AA MCP servers."""

from .config import get_os_env, load_config

# Backward compatibility alias
load_repos_config = load_config

__all__ = ["load_config", "load_repos_config", "get_os_env"]
