"""GitHub Memory Adapter - Query GitHub for PRs, issues, workflows, and releases.

This adapter provides memory access to GitHub data including:
- Pull requests (open, merged, your PRs)
- Issues
- Workflow/Actions status
- Releases
- Code search
"""

import logging
from typing import Any

from services.memory_abstraction.models import AdapterResult, HealthStatus, MemoryItem
from services.memory_abstraction.registry import memory_adapter

logger = logging.getLogger(__name__)


def _get_github_tools():
    """Import GitHub tools lazily."""
    try:
        from tool_modules.aa_github.src.tools_basic import (
            _gh_auth_status_impl,
            _gh_issue_list_impl,
            _gh_pr_list_impl,
            _gh_pr_view_impl,
            _gh_run_list_impl,
            _gh_search_issues_impl,
        )

        return {
            "pr_list": _gh_pr_list_impl,
            "pr_view": _gh_pr_view_impl,
            "issue_list": _gh_issue_list_impl,
            "run_list": _gh_run_list_impl,
            "search_issues": _gh_search_issues_impl,
            "auth_status": _gh_auth_status_impl,
        }
    except ImportError as e:
        logger.warning(f"GitHub tools not available: {e}")
        return None


@memory_adapter(
    name="github",
    display_name="GitHub",
    capabilities={"query", "search"},
    intent_keywords=[
        "pr",
        "pull request",
        "github",
        "workflow",
        "actions",
        "release",
        "gh",
        "fork",
        "star",
        "contributor",
    ],
    priority=52,
    latency_class="slow",  # External GitHub API
)
class GitHubAdapter:
    """Memory adapter for GitHub data."""

    def __init__(self):
        self._tools = None

    def _ensure_tools(self):
        """Ensure tools are loaded."""
        if self._tools is None:
            self._tools = _get_github_tools()
        return self._tools is not None

    async def query(
        self,
        question: str,
        context: dict[str, Any] | None = None,
    ) -> AdapterResult:
        """Query GitHub for relevant information.

        Args:
            question: Natural language question about GitHub data
            context: Optional context (repo, filters)

        Returns:
            AdapterResult with PRs, issues, or workflow info
        """
        if not self._ensure_tools():
            return AdapterResult(
                source="github",
                items=[],
                error="GitHub tools not available",
            )

        items = []
        errors = []

        question_lower = question.lower()

        try:
            # Query PRs if relevant
            if any(
                kw in question_lower for kw in ["pr", "pull", "review", "merge", "open"]
            ):
                pr_items = await self._query_prs(question_lower, context)
                items.extend(pr_items)

            # Query workflows/actions if relevant
            if any(
                kw in question_lower
                for kw in ["workflow", "action", "ci", "build", "run"]
            ):
                workflow_items = await self._query_workflows(question_lower, context)
                items.extend(workflow_items)

            # Query issues if relevant
            if any(kw in question_lower for kw in ["issue", "bug", "feature", "task"]):
                issue_items = await self._query_issues(question_lower, context)
                items.extend(issue_items)

            # Default: get open PRs if no specific query
            if not items:
                pr_items = await self._query_prs("open", context)
                items.extend(pr_items)

        except Exception as e:
            logger.error(f"GitHub query failed: {e}", exc_info=True)
            errors.append(str(e))

        return AdapterResult(
            source="github",
            items=items,
            error="; ".join(errors) if errors else None,
        )

    async def _query_prs(
        self,
        question: str,
        context: dict[str, Any] | None,
    ) -> list[MemoryItem]:
        """Query pull requests."""
        items = []

        try:
            # Determine state filter
            if "merged" in question:
                state = "merged"
            elif "closed" in question:
                state = "closed"
            else:
                state = "open"

            # Get repo from context
            repo = context.get("repo") if context else None

            # Call the PR list implementation
            result = await self._tools["pr_list"](
                state=state,
                author="@me" if "my" in question else None,
                limit=10,
                repo=repo,
            )

            if result and "error" not in result.lower():
                # Parse PR output
                lines = result.split("\n")
                for line in lines:
                    if line.strip().startswith("#"):
                        # PR entry like "#123 Title"
                        items.append(
                            MemoryItem(
                                id=f"github-pr-{hash(line)}",
                                source="github",
                                type="pull_request",
                                content=line,
                                summary=line[:100],
                                relevance=0.8,
                                metadata={"raw": line},
                            )
                        )

        except Exception as e:
            logger.warning(f"Failed to query PRs: {e}")

        return items

    async def _query_workflows(
        self,
        question: str,
        context: dict[str, Any] | None,
    ) -> list[MemoryItem]:
        """Query workflow runs."""
        items = []

        try:
            repo = context.get("repo") if context else None

            result = await self._tools["run_list"](
                limit=5,
                repo=repo,
            )

            if result and "error" not in result.lower():
                lines = result.split("\n")
                for line in lines:
                    if line.strip() and not line.startswith("#"):
                        items.append(
                            MemoryItem(
                                id=f"github-workflow-{hash(line)}",
                                source="github",
                                type="workflow_run",
                                content=line,
                                summary=line[:100],
                                relevance=0.7,
                                metadata={"raw": line},
                            )
                        )

        except Exception as e:
            logger.warning(f"Failed to query workflows: {e}")

        return items

    async def _query_issues(
        self,
        question: str,
        context: dict[str, Any] | None,
    ) -> list[MemoryItem]:
        """Query GitHub issues."""
        items = []

        try:
            repo = context.get("repo") if context else None

            result = await self._tools["issue_list"](
                state="open",
                limit=10,
                repo=repo,
            )

            if result and "error" not in result.lower():
                lines = result.split("\n")
                for line in lines:
                    if line.strip().startswith("#"):
                        items.append(
                            MemoryItem(
                                id=f"github-issue-{hash(line)}",
                                source="github",
                                type="issue",
                                content=line,
                                summary=line[:100],
                                relevance=0.7,
                                metadata={"raw": line},
                            )
                        )

        except Exception as e:
            logger.warning(f"Failed to query issues: {e}")

        return items

    async def search(
        self,
        query: str,
        limit: int = 10,
        context: dict[str, Any] | None = None,
    ) -> AdapterResult:
        """Search GitHub issues and PRs."""
        if not self._ensure_tools():
            return AdapterResult(
                source="github",
                items=[],
                error="GitHub tools not available",
            )

        items = []

        try:
            # Use GitHub's search API
            result = await self._tools["search_issues"](
                query=query,
                limit=limit,
            )

            if result and "error" not in result.lower():
                lines = result.split("\n")
                for line in lines:
                    if line.strip() and not line.startswith("#"):
                        items.append(
                            MemoryItem(
                                id=f"github-search-{hash(line)}",
                                source="github",
                                type="search_result",
                                content=line,
                                summary=line[:100],
                                relevance=0.75,
                                metadata={"query": query, "raw": line},
                            )
                        )

        except Exception as e:
            logger.error(f"GitHub search failed: {e}")
            return AdapterResult(
                source="github",
                items=[],
                error=str(e),
            )

        return AdapterResult(
            source="github",
            items=items,
        )

    async def store(
        self,
        key: str,
        value: Any,
        context: dict[str, Any] | None = None,
    ) -> AdapterResult:
        """Store not supported for GitHub."""
        return AdapterResult(
            source="github",
            items=[],
            error="GitHub adapter is read-only",
        )

    async def health_check(self) -> HealthStatus:
        """Check GitHub connectivity."""
        if not self._ensure_tools():
            return HealthStatus(
                healthy=False,
                error="GitHub tools not available",
            )

        try:
            result = await self._tools["auth_status"]()

            if result and "Logged in" in result:
                return HealthStatus(
                    healthy=True,
                    details={"auth": "ok"},
                )
            else:
                return HealthStatus(
                    healthy=False,
                    error=f"GitHub auth issue: {result[:100] if result else 'no response'}",
                )

        except Exception as e:
            return HealthStatus(
                healthy=False,
                error=f"GitHub health check failed: {e}",
            )
