"""
Shared configuration loading for skills.

Provides a standardized way to load config.json and typed accessors.
Skills should import from this module instead of reimplementing config loading.

All config loading delegates to the canonical implementation in:
server/utils.py
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add server module to path for utils import
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def load_config() -> Dict[str, Any]:
    """
    Load config.json using canonical implementation.

    Delegates to server/utils.py:load_config()
    for consistent behavior across skills and MCP tools.

    Returns:
        Config dict, or empty dict if not found
    """
    try:
        from server.utils import load_config as utils_load_config

        result: Dict[str, Any] = utils_load_config()
        return result
    except ImportError:
        # Fallback if utils not available
        config_path = Path(__file__).parent.parent.parent / "config.json"
        if config_path.exists():
            with open(config_path) as f:
                loaded: Dict[str, Any] = json.load(f)
                return loaded
        return {}


def get_config_section(section: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Get a specific section from config.json.

    Args:
        section: Top-level key in config (e.g., 'jira', 'gitlab', 'repositories')
        default: Default value if section not found

    Returns:
        Section dict or default

    Note:
        This is an alias for utils.get_section_config() for naming consistency.
        Both names work - use whichever reads better in context.
    """
    config = load_config()
    result: Dict[str, Any] = config.get(section, default or {})
    return result


# Alias for compatibility with utils.py naming convention
get_section_config = get_config_section


def get_user_config() -> Dict[str, Any]:
    """
    Get user configuration from config.json.

    Returns:
        User config with keys like 'username', 'email', 'timezone'
    """
    config = load_config()
    result: Dict[str, Any] = config.get("user", {})
    return result


def get_username() -> str:
    """
    Get the configured username.

    Falls back to OS user if not configured.
    """
    user_config = get_user_config()
    username = user_config.get("username")
    if isinstance(username, str) and username:
        return str(username)
    env_user = os.getenv("USER")
    return env_user if env_user else "unknown"


def get_jira_url() -> str:
    """
    Get the Jira instance URL.

    Falls back to default Red Hat Jira if not configured.
    """
    config = load_config()
    jira_config: Dict[str, Any] = config.get("jira", {})
    url = jira_config.get("url", "https://issues.redhat.com")
    return str(url)


def get_timezone() -> str:
    """
    Get the configured timezone.

    Falls back to Europe/Dublin if not configured.
    """
    user_config = get_user_config()
    tz = user_config.get("timezone", "Europe/Dublin")
    return str(tz)


def get_repo_config(repo_name: str) -> Dict[str, Any]:
    """
    Get configuration for a specific repository.

    Args:
        repo_name: Repository name (key in repositories section)

    Returns:
        Repository config dict or empty dict
    """
    config = load_config()
    repos: Dict[str, Any] = config.get("repositories", {})
    result: Dict[str, Any] = repos.get(repo_name, {})
    return result


def resolve_repo(
    repo_name: Optional[str] = None,
    issue_key: Optional[str] = None,
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resolve repository configuration from various inputs.

    Priority:
    1. repo_name if provided
    2. Match by issue_key prefix (e.g., AAP-12345 -> AAP project)
    3. Match by current working directory
    4. Fall back to first configured repo

    Args:
        repo_name: Explicit repository name
        issue_key: Jira issue key to match by project
        cwd: Current working directory

    Returns:
        Dict with 'name', 'path', 'gitlab', 'jira_project', etc.
    """
    config = load_config()
    repos = config.get("repositories", {})

    result = {
        "name": None,
        "path": cwd or os.getcwd(),
        "gitlab": None,
        "jira_project": None,
        "jira_url": get_jira_url(),
    }

    # 1. Explicit repo name
    if repo_name and repo_name in repos:
        repo = repos[repo_name]
        result.update(
            {
                "name": repo_name,
                "path": repo.get("path", result["path"]),
                "gitlab": repo.get("gitlab"),
                "jira_project": repo.get("jira_project"),
            }
        )
        return result

    # 2. Match by issue key prefix
    if issue_key:
        project_prefix = issue_key.split("-")[0].upper()
        for name, repo in repos.items():
            if repo.get("jira_project") == project_prefix:
                result.update(
                    {
                        "name": name,
                        "path": repo.get("path", result["path"]),
                        "gitlab": repo.get("gitlab"),
                        "jira_project": repo.get("jira_project"),
                    }
                )
                return result

    # 3. Match by current working directory
    check_cwd = cwd or os.getcwd()
    for name, repo in repos.items():
        if repo.get("path") == check_cwd:
            result.update(
                {
                    "name": name,
                    "path": repo.get("path"),
                    "gitlab": repo.get("gitlab"),
                    "jira_project": repo.get("jira_project"),
                }
            )
            return result

    # 4. Fall back to first configured repo
    if repos:
        first_name = next(iter(repos))
        first_repo = repos[first_name]
        result.update(
            {
                "name": first_name,
                "path": first_repo.get("path", result["path"]),
                "gitlab": first_repo.get("gitlab"),
                "jira_project": first_repo.get("jira_project"),
            }
        )

    return result


# =============================================================================
# URL Getters
# =============================================================================


def get_gitlab_host() -> str:
    """Get GitLab host from env var, config, or default.

    Priority:
    1. GITLAB_HOST environment variable
    2. config.json gitlab.host
    3. Default: gitlab.cee.redhat.com

    Returns:
        GitLab hostname (without https://)
    """
    env_host = os.getenv("GITLAB_HOST")
    if env_host:
        return env_host
    config = load_config()
    return config.get("gitlab", {}).get("host", "gitlab.cee.redhat.com")


def get_gitlab_url() -> str:
    """Get full GitLab URL with https://.

    Returns:
        Full GitLab URL (e.g., https://gitlab.cee.redhat.com)
    """
    return f"https://{get_gitlab_host()}"


def get_quay_url() -> str:
    """Get Quay URL (static)."""
    return "https://quay.io"


# =============================================================================
# Namespace Getters
# =============================================================================


def get_konflux_namespace() -> str:
    """Get Konflux namespace from config."""
    config = load_config()
    repos = config.get("repositories", {})
    backend = repos.get("automation-analytics-backend", {})
    if backend.get("konflux_namespace"):
        return str(backend["konflux_namespace"])
    return "aap-aa-tenant"


def get_stage_namespace() -> str:
    """Get stage namespace from config."""
    config = load_config()
    return str(config.get("namespaces", {}).get("stage", {}).get("main", "tower-analytics-stage"))


def get_prod_namespace() -> str:
    """Get prod namespace from config."""
    config = load_config()
    return str(config.get("namespaces", {}).get("production", {}).get("main", "tower-analytics-prod"))


def get_jira_project() -> str:
    """Get default Jira project from config."""
    config = load_config()
    return str(config.get("jira", {}).get("default_project", "AAP"))


# =============================================================================
# Git / GitLab Getters
# =============================================================================


def get_commit_types() -> List[str]:
    """Get commit types from config."""
    config = load_config()
    types = config.get("commit_format", {}).get(
        "types", ["feat", "fix", "refactor", "docs", "test", "chore", "perf", "ci"]
    )
    return list(types) if types else []


def get_default_branch() -> str:
    """Get default branch from config (uses backend repo as default)."""
    config = load_config()
    repos = config.get("repositories", {})
    backend = repos.get("automation-analytics-backend", {})
    return str(backend.get("default_branch", "main"))


# =============================================================================
# Linting Getters
# =============================================================================


def get_flake8_ignore_codes() -> str:
    """Get flake8 ignore codes from config."""
    config = load_config()
    return str(config.get("linting", {}).get("flake8", {}).get("ignore", "E501,W503,E203"))


def get_flake8_max_line_length() -> int:
    """Get flake8 max line length from config."""
    config = load_config()
    return int(config.get("linting", {}).get("flake8", {}).get("max_line_length", 100))


# Blocking flake8 codes - these are static (semantic, not configurable)
FLAKE8_BLOCKING_CODES: List[str] = ["F401", "F811", "F821", "F822", "F823", "E999"]


# =============================================================================
# Slack Getters
# =============================================================================


def get_team_group_handle() -> str:
    """Get team group handle from config."""
    config = load_config()
    team_channel = config.get("slack", {}).get("channels", {}).get("team", {})
    return str(team_channel.get("group_handle", "aa-api-team"))


def get_team_group_id() -> str:
    """Get team group ID from config."""
    config = load_config()
    team_channel = config.get("slack", {}).get("channels", {}).get("team", {})
    return str(team_channel.get("group_id", ""))


# =============================================================================
# Memory Key Paths (for memory_read/memory_write tools)
# These are key prefixes, not filesystem paths. Use Path.home() / "src/..."
# for actual file access.
# =============================================================================

MEMORY_KEY_CURRENT_WORK = "state/current_work"
MEMORY_KEY_ENVIRONMENTS = "state/environments"
MEMORY_KEY_PATTERNS = "learned/patterns"
MEMORY_KEY_RUNBOOKS = "learned/runbooks"
MEMORY_KEY_TOOL_FIXES = "learned/tool_fixes"
MEMORY_KEY_TEAMMATE_PREFS = "learned/teammate_preferences"


# =============================================================================
# Team Config (convenience function)
# =============================================================================


def get_team_config() -> Dict[str, Any]:
    """
    Get team Slack configuration from config.

    Returns:
        Dict with team_group_id, team_group_handle, jira_url, gitlab_url
    """
    config = load_config()
    team_channel = config.get("slack", {}).get("channels", {}).get("team", {})
    gitlab_host = config.get("gitlab", {}).get("host", "gitlab.cee.redhat.com")

    return {
        "team_group_id": team_channel.get("group_id", ""),
        "team_group_handle": team_channel.get("group_handle", "aa-api-team"),
        "jira_url": get_jira_url(),
        "gitlab_url": f"https://{gitlab_host}",
    }
