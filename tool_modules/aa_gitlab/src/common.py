"""Shared helpers for GitLab tool modules.

Extracted from tools_basic.py and tools_extra.py to eliminate duplication (DUP-004).
"""

import re
from pathlib import Path

from server.utils import get_gitlab_host, get_section_config, run_cmd

# Use shared implementation from utils
GITLAB_HOST = get_gitlab_host()


def _load_repo_config() -> dict[str, dict]:
    """Load repository configuration from config.json."""
    return get_section_config("repositories", {})


def _resolve_gitlab_to_local(gitlab_path: str) -> str | None:
    """
    Resolve a GitLab project path to a local directory.

    Args:
        gitlab_path: e.g., "automation-analytics/automation-analytics-backend" or just "app-interface"

    Returns:
        Local directory path or None if not found.
    """
    repos = _load_repo_config()
    for repo_name, repo_config in repos.items():
        # Match by full gitlab path OR by repo name (short name)
        if repo_config.get("gitlab") == gitlab_path or repo_name == gitlab_path:
            local_path = repo_config.get("path")
            if local_path and Path(local_path).exists():
                return local_path
    return None


def parse_gitlab_url(url_or_id: str) -> tuple[str | None, str | None]:
    """
    Parse a GitLab URL or MR reference to extract project and MR ID.

    Args:
        url_or_id: Full URL, "!123", or just "123"

    Returns:
        (project_path, mr_id) - either can be None

    Examples:
        "https://gitlab.cee.redhat.com/automation-analytics/automation-analytics-backend/-/merge_requests/1449"
        -> ("automation-analytics/automation-analytics-backend", "1449")

        "!1449" -> (None, "1449")
        "1449"  -> (None, "1449")
    """
    # Full URL pattern
    url_match = re.match(r"https?://[^/]+/(.+?)/-/merge_requests/(\d+)", url_or_id)
    if url_match:
        return url_match.group(1), url_match.group(2)

    # Issue URL pattern
    issue_match = re.match(r"https?://[^/]+/(.+?)/-/issues/(\d+)", url_or_id)
    if issue_match:
        return issue_match.group(1), issue_match.group(2)

    # Just an ID (with or without !)
    clean_id = url_or_id.lstrip("!").strip()
    if clean_id.isdigit():
        return None, clean_id

    return None, None


async def run_glab(
    args: list[str], repo: str | None = None, cwd: str | None = None, timeout: int = 60
) -> tuple[bool, str]:
    """
    Run glab command and return (success, output).

    Args:
        args: glab command arguments
        repo: GitLab project path (used with --repo if no cwd)
        cwd: Local directory to run from (preferred over --repo)
        timeout: Command timeout in seconds
    """
    cmd = ["glab"] + args

    # If we have a local directory, run from there (glab uses git remote)
    # Otherwise, use --repo flag
    run_cwd = None
    if cwd and Path(cwd).exists():
        run_cwd = cwd
    elif repo:
        # Try to resolve to local directory first
        local_dir = _resolve_gitlab_to_local(repo)
        if local_dir:
            run_cwd = local_dir
        else:
            cmd.extend(["--repo", repo])

    # Use unified run_cmd with GITLAB_HOST env var
    return await run_cmd(
        cmd, cwd=run_cwd, env={"GITLAB_HOST": GITLAB_HOST}, timeout=timeout
    )
