"""GitHub core tools - essential repository and PR operations.

This module provides the minimal set of GitHub tools needed for most workflows:
- gh_repo_list, gh_repo_view: Repository info
- gh_pr_list, gh_pr_view, gh_pr_create: PR operations
- gh_pr_checkout, gh_pr_merge: PR workflow

Total: ~8 core tools (down from 35 in basic)
"""

import logging

from fastmcp import FastMCP

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

import importlib.util
from pathlib import Path

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry

# Import implementations from basic module
# Support both package import and direct loading via importlib
try:
    from .tools_basic import (
        _gh_pr_checkout_impl,
        _gh_pr_create_impl,
        _gh_pr_list_impl,
        _gh_pr_merge_impl,
        _gh_pr_view_impl,
        _gh_repo_list_impl,
        _gh_repo_view_impl,
    )
except ImportError:
    # Direct loading - use importlib to avoid sys.path pollution
    _basic_file = Path(__file__).parent / "tools_basic.py"
    _spec = importlib.util.spec_from_file_location("github_tools_basic", _basic_file)
    _basic_module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_basic_module)
    _gh_pr_checkout_impl = _basic_module._gh_pr_checkout_impl
    _gh_pr_create_impl = _basic_module._gh_pr_create_impl
    _gh_pr_list_impl = _basic_module._gh_pr_list_impl
    _gh_pr_merge_impl = _basic_module._gh_pr_merge_impl
    _gh_pr_view_impl = _basic_module._gh_pr_view_impl
    _gh_repo_list_impl = _basic_module._gh_repo_list_impl
    _gh_repo_view_impl = _basic_module._gh_repo_view_impl

logger = logging.getLogger(__name__)


def register_tools(server: FastMCP) -> int:
    """Register core GitHub tools."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def gh_repo_list(
        owner: str = "", limit: int = 30, visibility: str = ""
    ) -> str:
        """List repositories."""
        return await _gh_repo_list_impl(owner, limit, visibility)

    @auto_heal()
    @registry.tool()
    async def gh_repo_view(repo: str = "", web: bool = False) -> str:
        """View repository details."""
        return await _gh_repo_view_impl(repo, web)

    @auto_heal()
    @registry.tool()
    async def gh_pr_list(
        repo: str = "",
        state: str = "open",
        author: str = "",
        assignee: str = "",
        limit: int = 30,
    ) -> str:
        """List pull requests."""
        return await _gh_pr_list_impl(repo, state, author, assignee, limit)

    @auto_heal()
    @registry.tool()
    async def gh_pr_view(pr_number: int = 0, repo: str = "", web: bool = False) -> str:
        """View pull request details."""
        return await _gh_pr_view_impl(pr_number, repo, web)

    @auto_heal()
    @registry.tool()
    async def gh_pr_create(
        title: str,
        body: str = "",
        base: str = "main",
        head: str = "",
        repo: str = "",
        draft: bool = False,
    ) -> str:
        """Create a pull request."""
        return await _gh_pr_create_impl(title, body, base, head, repo, draft)

    @auto_heal()
    @registry.tool()
    async def gh_pr_checkout(pr_number: int, repo: str = "", cwd: str = "") -> str:
        """Checkout a pull request locally."""
        return await _gh_pr_checkout_impl(pr_number, repo, cwd)

    @auto_heal()
    @registry.tool()
    async def gh_pr_merge(
        pr_number: int,
        repo: str = "",
        method: str = "merge",
        delete_branch: bool = False,
    ) -> str:
        """Merge a pull request."""
        return await _gh_pr_merge_impl(pr_number, repo, method, delete_branch)

    logger.info(f"Registered {registry.count} core GitHub tools")
    return registry.count
