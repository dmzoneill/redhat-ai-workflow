"""GitLab core tools - essential MR and CI operations.

This module provides the minimal set of GitLab tools needed for most workflows:
- gitlab_mr_view, gitlab_list_mrs: View MRs
- gitlab_mr_create: Create MRs
- gitlab_ci_status, gitlab_ci_view: Check CI/CD

For additional tools (approve, merge, comments, etc.), use:
- gitlab_basic: Loads core + basic tools
- tool_exec("gitlab_mr_approve", {...}): Call specific tools on-demand

Total: ~6 core tools (down from 18 in basic)
"""

import logging

from fastmcp import FastMCP

# Setup project path for server imports
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
        _gitlab_ci_status_impl,
        _gitlab_ci_view_impl,
        _gitlab_list_mrs_impl,
        _gitlab_mr_create_impl,
        _gitlab_mr_view_impl,
    )
except ImportError:
    # Direct loading - use importlib to avoid sys.path pollution
    _basic_file = Path(__file__).parent / "tools_basic.py"
    _spec = importlib.util.spec_from_file_location("gitlab_tools_basic", _basic_file)
    _basic_module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_basic_module)
    _gitlab_ci_status_impl = _basic_module._gitlab_ci_status_impl
    _gitlab_ci_view_impl = _basic_module._gitlab_ci_view_impl
    _gitlab_list_mrs_impl = _basic_module._gitlab_list_mrs_impl
    _gitlab_mr_create_impl = _basic_module._gitlab_mr_create_impl
    _gitlab_mr_view_impl = _basic_module._gitlab_mr_view_impl

logger = logging.getLogger(__name__)


def register_tools(server: FastMCP) -> int:
    """
    Register core GitLab tools with the MCP server.

    Core tools (~6 tools):
    - gitlab_mr_view: View MR details
    - gitlab_list_mrs: List MRs
    - gitlab_mr_create: Create new MR
    - gitlab_ci_status: Check pipeline status
    - gitlab_ci_view: View pipeline details

    For additional tools, load gitlab_basic or use tool_exec().
    """
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_view(project: str, mr_id: int) -> str:
        """
        View merge request details.

        Args:
            project: Project path (e.g., "automation-analytics/automation-analytics-backend")
            mr_id: Merge request ID

        Returns:
            MR details including title, description, status.
        """
        return await _gitlab_mr_view_impl(project, mr_id)

    @auto_heal()
    @registry.tool()
    async def gitlab_list_mrs(
        project: str,
        state: str = "opened",
        author: str = "",
        assignee: str = "",
        limit: int = 20,
    ) -> str:
        """
        List merge requests for a project.

        Args:
            project: Project path
            state: MR state (opened, merged, closed, all)
            author: Filter by author username
            assignee: Filter by assignee username
            limit: Maximum results

        Returns:
            List of merge requests.
        """
        return await _gitlab_list_mrs_impl(project, state, author, assignee, limit)

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_create(
        project: str,
        source_branch: str,
        target_branch: str = "main",
        title: str = "",
        description: str = "",
    ) -> str:
        """
        Create a new merge request.

        Args:
            project: Project path
            source_branch: Source branch name
            target_branch: Target branch (default: main)
            title: MR title
            description: MR description

        Returns:
            Created MR details.
        """
        return await _gitlab_mr_create_impl(
            project, source_branch, target_branch, title, description
        )

    @auto_heal()
    @registry.tool()
    async def gitlab_ci_status(project: str, branch: str = "") -> str:
        """
        Get CI/CD pipeline status for a branch.

        Args:
            project: Project path
            branch: Branch name (default: current/main)

        Returns:
            Pipeline status and job results.
        """
        return await _gitlab_ci_status_impl(project, branch)

    @auto_heal()
    @registry.tool()
    async def gitlab_ci_view(project: str, branch: str = "") -> str:
        """
        View CI/CD pipeline details.

        Args:
            project: Project path
            branch: Branch name (default: current/main)

        Returns:
            Detailed pipeline information.
        """
        return await _gitlab_ci_view_impl(project, branch)

    logger.info(f"Registered {registry.count} core GitLab tools")
    return registry.count
