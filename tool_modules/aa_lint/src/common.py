"""Shared helpers for Lint tool modules.

Extracted from tools_basic.py and tools_extra.py to eliminate duplication (DUP-004).
"""

import os

from server.utils import resolve_repo_path


def _resolve_repo_path_local(repo: str, repo_paths: dict) -> str:
    """Resolve repository name to absolute path."""
    if os.path.isabs(repo):
        return repo
    if repo in repo_paths:
        return os.path.expanduser(repo_paths[repo])
    if repo == ".":
        return os.getcwd()
    path = resolve_repo_path(repo)
    if os.path.isdir(path):
        return path
    raise ValueError(f"Repository not found: {repo}")
