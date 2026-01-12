"""Shared repository resolution utilities.

Provides consistent repo path resolution across skills.
"""

import os
from dataclasses import dataclass
from typing import Any, Optional

from scripts.common.config_loader import load_config


@dataclass
class ResolvedRepo:
    """Resolved repository information."""

    path: str
    gitlab_project: str
    default_branch: str
    jira_project: str
    name: str

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "gitlab_project": self.gitlab_project,
            "default_branch": self.default_branch,
            "jira_project": self.jira_project,
            "name": self.name,
        }


def _resolve_by_path(repo_path: str, repos: dict) -> tuple[Optional[str], str, dict]:
    """Resolve repo by explicit path."""
    for rname, cfg in repos.items():
        if cfg.get("path") == repo_path:
            return repo_path, rname, cfg
    return repo_path, "", {}


def _resolve_by_name(repo_name: str, repos: dict) -> tuple[Optional[str], str, dict]:
    """Resolve repo by config name."""
    if repo_name in repos:
        repo_config = repos[repo_name]
        return repo_config.get("path", ""), repo_name, repo_config
    return None, "", {}


def _resolve_by_issue_key(issue_key: str, repos: dict) -> tuple[Optional[str], str, dict]:
    """Resolve repo by Jira issue key prefix."""
    project_prefix = issue_key.split("-")[0].upper()
    matches = []
    for rname, cfg in repos.items():
        if cfg.get("jira_project") == project_prefix:
            matches.append({"name": rname, "config": cfg})

    if len(matches) == 1:
        return matches[0]["config"].get("path", ""), matches[0]["name"], matches[0]["config"]
    if len(matches) > 1:
        names = ", ".join(m["name"] for m in matches)
        raise ValueError(f"Multiple repos match {project_prefix}: {names}. Specify repo_name.")
    return None, "", {}


def _resolve_by_cwd(repos: dict) -> tuple[Optional[str], str, dict]:
    """Resolve repo by current working directory."""
    cwd = os.getcwd()
    if os.path.exists(os.path.join(cwd, ".git")):
        for rname, cfg in repos.items():
            if cfg.get("path") == cwd:
                return cwd, rname, cfg
        return cwd, "", {}
    return None, "", {}


def resolve_repo(
    repo_path: Optional[str] = None,
    repo_name: Optional[str] = None,
    issue_key: Optional[str] = None,
    target_branch: Optional[str] = None,
) -> ResolvedRepo:
    """
    Resolve repository from various inputs.

    Priority:
    1. Explicit repo_path
    2. repo_name from config
    3. issue_key prefix match
    4. Current working directory

    Args:
        repo_path: Explicit path to repository
        repo_name: Repository name from config
        issue_key: Jira issue key to match against repo jira_project
        target_branch: Override default branch

    Returns:
        ResolvedRepo with path and metadata

    Raises:
        ValueError: If repository cannot be resolved
    """
    config = load_config()
    repos = config.get("repositories", {})

    resolved_path = None
    name = ""
    repo_config: dict[str, Any] = {}

    # Try resolution strategies in priority order
    if repo_path and repo_path not in ("", "."):
        resolved_path, name, repo_config = _resolve_by_path(repo_path, repos)
    elif repo_name:
        resolved_path, name, repo_config = _resolve_by_name(repo_name, repos)
    elif issue_key:
        resolved_path, name, repo_config = _resolve_by_issue_key(issue_key, repos)

    if not resolved_path:
        resolved_path, name, repo_config = _resolve_by_cwd(repos)

    if not resolved_path or not os.path.exists(resolved_path):
        raise ValueError(f"Repository not found: {resolved_path or 'not specified'}")

    # Extract metadata
    gitlab_project = repo_config.get("gitlab", "")
    default_branch = repo_config.get("default_branch", "main")
    jira_project = repo_config.get("jira_project", "")

    if target_branch:
        default_branch = target_branch

    return ResolvedRepo(
        path=resolved_path,
        gitlab_project=gitlab_project,
        default_branch=default_branch,
        jira_project=jira_project,
        name=name,
    )
