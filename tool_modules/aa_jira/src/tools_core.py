"""Jira core tools - essential issue management operations.

This module provides the minimal set of Jira tools needed for most workflows:
- jira_get_issue, jira_view_issue: View issue details
- jira_search, jira_my_issues: Find issues
- jira_add_comment: Add comments
- jira_transition: Change status

For additional tools (create, clone, assign, etc.), use:
- jira_basic: Loads core + basic tools
- tool_exec("jira_create_issue", {...}): Call specific tools on-demand

Total: ~6 core tools (down from 17 in basic)
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
        _jira_add_comment_impl,
        _jira_get_issue_impl,
        _jira_my_issues_impl,
        _jira_search_impl,
        _jira_transition_impl,
        _jira_view_issue_impl,
    )
except ImportError:
    # Direct loading - use importlib to avoid sys.path pollution
    _basic_file = Path(__file__).parent / "tools_basic.py"
    _spec = importlib.util.spec_from_file_location("jira_tools_basic", _basic_file)
    _basic_module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_basic_module)
    _jira_add_comment_impl = _basic_module._jira_add_comment_impl
    _jira_get_issue_impl = _basic_module._jira_get_issue_impl
    _jira_my_issues_impl = _basic_module._jira_my_issues_impl
    _jira_search_impl = _basic_module._jira_search_impl
    _jira_transition_impl = _basic_module._jira_transition_impl
    _jira_view_issue_impl = _basic_module._jira_view_issue_impl

logger = logging.getLogger(__name__)


def register_tools(server: FastMCP) -> int:
    """
    Register core Jira tools with the MCP server.

    Core tools (~6 tools):
    - jira_get_issue: Get issue details (JSON)
    - jira_view_issue: View issue (formatted)
    - jira_search: Search with JQL
    - jira_my_issues: List my assigned issues
    - jira_add_comment: Add comment to issue
    - jira_transition: Change issue status

    For additional tools, load jira_basic or use tool_exec().
    """
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def jira_get_issue(issue_key: str) -> str:
        """
        Get Jira issue details as JSON.

        Args:
            issue_key: Issue key (e.g., "AAP-12345")

        Returns:
            Issue details in JSON format.
        """
        return await _jira_get_issue_impl(issue_key)

    @auto_heal()
    @registry.tool()
    async def jira_view_issue(issue_key: str) -> str:
        """
        View Jira issue in human-readable format.

        Args:
            issue_key: Issue key (e.g., "AAP-12345")

        Returns:
            Formatted issue details.
        """
        return await _jira_view_issue_impl(issue_key)

    @auto_heal()
    @registry.tool()
    async def jira_search(jql: str, max_results: int = 20) -> str:
        """
        Search Jira issues using JQL.

        Args:
            jql: JQL query string
            max_results: Maximum results to return (default: 20)

        Returns:
            List of matching issues.
        """
        return await _jira_search_impl(jql, max_results)

    @auto_heal()
    @registry.tool()
    async def jira_my_issues(status: str = "") -> str:
        """
        List issues assigned to me.

        Args:
            status: Filter by status (optional)

        Returns:
            List of my assigned issues.
        """
        return await _jira_my_issues_impl(status)

    @auto_heal()
    @registry.tool()
    async def jira_add_comment(issue_key: str, comment: str) -> str:
        """
        Add a comment to a Jira issue.

        Args:
            issue_key: Issue key (e.g., "AAP-12345")
            comment: Comment text

        Returns:
            Confirmation of comment added.
        """
        return await _jira_add_comment_impl(issue_key, comment)

    @auto_heal()
    @registry.tool()
    async def jira_transition(issue_key: str, status: str) -> str:
        """
        Transition a Jira issue to a new status.

        Args:
            issue_key: Issue key (e.g., "AAP-12345")
            status: Target status (e.g., "In Progress", "Done")

        Returns:
            Confirmation of status change.
        """
        return await _jira_transition_impl(issue_key, status)

    logger.info(f"Registered {registry.count} core Jira tools")
    return registry.count
