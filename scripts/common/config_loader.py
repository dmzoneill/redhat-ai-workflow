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
from typing import Any, Dict, List, Optional, cast

# Add server module to path for utils import
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def load_config() -> Dict[str, Any]:
    """
    Load config.json using ConfigManager for thread-safe access.

    Uses server/config_manager.py singleton for consistent,
    thread-safe behavior across skills and MCP tools.

    Returns:
        Config dict, or empty dict if not found
    """
    try:
        from server.config_manager import config as config_manager

        # Return a copy of all config sections
        result: Dict[str, Any] = {}
        for section in config_manager.sections():
            result[section] = config_manager.get(section, default={})
        return result
    except ImportError:
        # Fallback to utils if config_manager not available
        try:
            from server.utils import load_config as utils_load_config

            result: Dict[str, Any] = utils_load_config()
            return result
        except ImportError:
            return {}


def get_config_section(section: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Get a specific section from config.json using ConfigManager.

    Args:
        section: Top-level key in config (e.g., 'jira', 'gitlab', 'repositories')
        default: Default value if section not found

    Returns:
        Section dict or default

    Note:
        Uses ConfigManager for thread-safe access.
    """
    try:
        from server.config_manager import config as config_manager

        result: Dict[str, Any] = config_manager.get(section, default=default or {})
        return result
    except ImportError:
        # Fallback to full load
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
    return cast(str, config.get("gitlab", {}).get("host", "gitlab.cee.redhat.com"))


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


def get_commit_format() -> Dict[str, Any]:
    """
    Get commit format configuration from config.json.

    Returns:
        Dict with 'pattern', 'types', and 'examples' keys.
    """
    config = load_config()
    default_format = {
        "pattern": "{issue_key} - {type}({scope}): {description}",
        "types": ["feat", "fix", "refactor", "docs", "test", "chore", "style", "perf"],
        "examples": [
            "AAP-12345 - feat(api): Add new endpoint",
            "AAP-12345 - fix(auth): Handle token expiry",
        ],
    }
    commit_cfg = config.get("commit_format", {})
    return {
        "pattern": commit_cfg.get("pattern", default_format["pattern"]),
        "types": commit_cfg.get("types", default_format["types"]),
        "examples": commit_cfg.get("examples", default_format["examples"]),
    }


def format_commit_message(
    description: str,
    issue_key: str = "",
    commit_type: str = "chore",
    scope: str = "",
) -> str:
    """
    Format a commit message using the pattern from config.json.

    Args:
        description: The commit description/message
        issue_key: Jira issue key (e.g., AAP-12345)
        commit_type: Commit type (feat, fix, etc.)
        scope: Optional scope (e.g., api, auth)

    Returns:
        Formatted commit message matching config pattern.

    Example:
        >>> format_commit_message("Add caching", "AAP-123", "feat", "api")
        'AAP-123 - feat(api): Add caching'
    """
    commit_cfg = get_commit_format()
    valid_types = commit_cfg["types"]

    # Validate commit type
    if commit_type not in valid_types:
        commit_type = "chore"  # Default to chore if invalid

    # Build the formatted message based on config pattern:
    # {issue_key} - {type}({scope}): {description}
    if issue_key:
        if scope:
            # Full format with scope
            formatted = f"{issue_key} - {commit_type}({scope}): {description}"
        else:
            # Format without scope
            formatted = f"{issue_key} - {commit_type}: {description}"
    else:
        # No issue key - just use description
        formatted = description

    return formatted


def validate_commit_message(message: str) -> tuple[bool, List[str]]:
    """
    Validate a commit message against the config pattern.

    Args:
        message: The commit message to validate

    Returns:
        Tuple of (is_valid, list of issues)
    """
    import re

    commit_cfg = get_commit_format()
    valid_types = commit_cfg["types"]
    issues = []

    # Pattern: AAP-12345 - type(scope): description  OR  AAP-12345 - type: description
    pattern = r"^([A-Z]{2,10}-\d{3,6})\s*-\s*(\w+)(?:\(([^)]+)\))?:\s*(.+)$"
    match = re.match(pattern, message.strip())

    if not match:
        issues.append(f"Commit message doesn't match format: {commit_cfg['pattern']}")
        issues.append(f"Examples: {', '.join(commit_cfg['examples'][:2])}")
        return False, issues

    _issue_key, commit_type, _scope, description = match.groups()

    if commit_type not in valid_types:
        issues.append(f"Invalid commit type '{commit_type}'. Valid types: {', '.join(valid_types)}")

    if not description or len(description.strip()) < 3:
        issues.append("Commit description is too short (min 3 characters)")

    return len(issues) == 0, issues


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
