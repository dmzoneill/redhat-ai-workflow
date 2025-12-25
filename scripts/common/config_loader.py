"""
Shared configuration loading for skills.

Provides a standardized way to load config.json from multiple locations.
Skills should import from this module instead of reimplementing config loading.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


# Standard config file locations (in order of preference)
CONFIG_PATHS = [
    Path.cwd() / "config.json",
    Path.home() / "src/redhat-ai-workflow/config.json",
    Path(__file__).parent.parent.parent / "config.json",
]


def load_config() -> Dict[str, Any]:
    """
    Load config.json from standard locations.
    
    Searches in order:
    1. Current working directory
    2. ~/src/redhat-ai-workflow/
    3. Project root (relative to this file)
    
    Returns:
        Config dict, or empty dict if not found
    """
    for config_path in CONFIG_PATHS:
        if config_path.exists():
            try:
                with open(config_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                continue
    return {}


def get_config_section(section: str, default: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Get a specific section from config.json.
    
    Args:
        section: Top-level key in config (e.g., 'jira', 'gitlab', 'repositories')
        default: Default value if section not found
        
    Returns:
        Section dict or default
    """
    config = load_config()
    return config.get(section, default or {})


def get_user_config() -> Dict[str, Any]:
    """
    Get user configuration from config.json.
    
    Returns:
        User config with keys like 'username', 'email', 'timezone'
    """
    config = load_config()
    return config.get("user", {})


def get_username() -> str:
    """
    Get the configured username.
    
    Falls back to OS user if not configured.
    """
    user_config = get_user_config()
    return user_config.get("username") or os.getenv("USER", "unknown")


def get_jira_url() -> str:
    """
    Get the Jira instance URL.
    
    Falls back to default Red Hat Jira if not configured.
    """
    config = load_config()
    return config.get("jira", {}).get("url", "https://issues.redhat.com")


def get_timezone() -> str:
    """
    Get the configured timezone.
    
    Falls back to Europe/Dublin if not configured.
    """
    user_config = get_user_config()
    return user_config.get("timezone", "Europe/Dublin")


def get_repo_config(repo_name: str) -> Dict[str, Any]:
    """
    Get configuration for a specific repository.
    
    Args:
        repo_name: Repository name (key in repositories section)
        
    Returns:
        Repository config dict or empty dict
    """
    config = load_config()
    return config.get("repositories", {}).get(repo_name, {})


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
        result.update({
            "name": repo_name,
            "path": repo.get("path", result["path"]),
            "gitlab": repo.get("gitlab"),
            "jira_project": repo.get("jira_project"),
        })
        return result
    
    # 2. Match by issue key prefix
    if issue_key:
        project_prefix = issue_key.split("-")[0].upper()
        for name, repo in repos.items():
            if repo.get("jira_project") == project_prefix:
                result.update({
                    "name": name,
                    "path": repo.get("path", result["path"]),
                    "gitlab": repo.get("gitlab"),
                    "jira_project": repo.get("jira_project"),
                })
                return result
    
    # 3. Match by current working directory
    check_cwd = cwd or os.getcwd()
    for name, repo in repos.items():
        if repo.get("path") == check_cwd:
            result.update({
                "name": name,
                "path": repo.get("path"),
                "gitlab": repo.get("gitlab"),
                "jira_project": repo.get("jira_project"),
            })
            return result
    
    # 4. Fall back to first configured repo
    if repos:
        first_name = next(iter(repos))
        first_repo = repos[first_name]
        result.update({
            "name": first_name,
            "path": first_repo.get("path", result["path"]),
            "gitlab": first_repo.get("gitlab"),
            "jira_project": first_repo.get("jira_project"),
        })
    
    return result

