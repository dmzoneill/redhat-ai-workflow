"""GitLab Memory Adapter - Query GitLab for MRs, issues, pipelines, and comments.

This adapter provides memory access to GitLab data including:
- Merge requests (open, merged, your MRs)
- Issues
- Pipeline status
- MR comments and discussions
- Code review feedback
"""

import logging
from typing import Any

from services.memory_abstraction.models import (
    AdapterResult,
    HealthStatus,
    MemoryItem,
    SourceFilter,
)
from services.memory_abstraction.registry import memory_adapter

logger = logging.getLogger(__name__)


def _get_gitlab_tools():
    """Import GitLab tools lazily."""
    try:
        from tool_modules.aa_gitlab.src.tools_basic import (
            _gitlab_ci_list_impl,
            _gitlab_mr_list_impl,
            _gitlab_mr_view_impl,
            run_glab,
        )

        return {
            "mr_list": _gitlab_mr_list_impl,
            "mr_view": _gitlab_mr_view_impl,
            "pipeline_list": _gitlab_ci_list_impl,
            "run_glab": run_glab,
        }
    except ImportError as e:
        logger.warning(f"GitLab tools not available: {e}")
        return None


@memory_adapter(
    name="gitlab",
    display_name="GitLab",
    capabilities={"query", "search"},
    intent_keywords=[
        "mr",
        "merge request",
        "pipeline",
        "gitlab",
        "review",
        "ci",
        "cd",
        "branch",
        "commit",
        "diff",
        "approval",
    ],
    priority=70,
    latency_class="slow",  # External GitLab API
)
class GitLabAdapter:
    """Memory adapter for GitLab data."""

    def __init__(self):
        self._tools = None

    def _ensure_tools(self):
        """Ensure tools are loaded."""
        if self._tools is None:
            self._tools = _get_gitlab_tools()
        return self._tools is not None

    async def query(
        self,
        question: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Query GitLab for relevant information.

        Args:
            question: Natural language question about GitLab data
            filter: Optional filter with project in extra dict

        Returns:
            AdapterResult with MRs, issues, or pipeline info
        """
        if not self._ensure_tools():
            return AdapterResult(
                source="gitlab",
                items=[],
                error="GitLab tools not available",
            )

        items = []
        errors = []

        # Extract context from filter
        context = filter.extra if filter and filter.extra else {}

        # Determine what to query based on question
        question_lower = question.lower()

        try:
            # Query MRs if relevant
            if any(kw in question_lower for kw in ["mr", "merge", "review", "pr", "open"]):
                mr_items = await self._query_mrs(question_lower, context)
                items.extend(mr_items)

            # Query pipelines if relevant
            if any(kw in question_lower for kw in ["pipeline", "ci", "build", "deploy", "status"]):
                pipeline_items = await self._query_pipelines(question_lower, context)
                items.extend(pipeline_items)

            # Note: GitLab issues not currently supported - use Jira for issue tracking

            # Default: get open MRs if no specific query
            if not items:
                mr_items = await self._query_mrs("open", context)
                items.extend(mr_items)

        except Exception as e:
            logger.error(f"GitLab query failed: {e}", exc_info=True)
            errors.append(str(e))

        return AdapterResult(
            source="gitlab",
            items=items,
            error="; ".join(errors) if errors else None,
        )

    async def _query_mrs(
        self,
        question: str,
        context: dict[str, Any] | None,
    ) -> list[MemoryItem]:
        """Query merge requests."""
        items = []

        try:
            # Determine state filter
            if "merged" in question:
                state = "merged"
            elif "closed" in question:
                state = "closed"
            else:
                state = "opened"

            # Get project from context (default to automation-analytics-backend)
            project = context.get("project") if context else "automation-analytics-backend"

            # Call the MR list implementation
            # Note: project is required first positional arg
            logger.info(
                f"Calling mr_list with project={project}, state={state}, author={'@me' if 'my' in question else ''}"
            )
            result = await self._tools["mr_list"](
                project=project,
                state=state,
                author="@me" if "my" in question else "",
            )
            logger.info(f"MR list result: {result[:200] if result else 'None'}...")

            # Parse result (it's a formatted string)
            # Format: !1491\tproject!1491\tTitle\t(main) ← (branch)
            if result and "❌" not in result:
                lines = result.split("\n")
                for line in lines:
                    # Skip header lines
                    if not line.strip() or line.startswith("Showing") or "Page" in line:
                        continue

                    # Parse tab-separated format: !ID\tproject!ID\tTitle\t(main) ← (branch)
                    parts = line.split("\t")
                    if len(parts) >= 3 and parts[0].startswith("!"):
                        mr_id = parts[0]  # !1491
                        title = parts[2] if len(parts) > 2 else ""
                        branch_info = parts[3] if len(parts) > 3 else ""

                        # Extract branch from "(main) ← (branch-name)"
                        branch = ""
                        if "←" in branch_info:
                            branch = branch_info.split("←")[-1].strip().strip("()")

                        items.append(
                            self._mr_to_item(
                                {
                                    "id": mr_id,
                                    "title": title,
                                    "branch": branch,
                                    "status": "opened",
                                }
                            )
                        )
                        logger.debug(f"Parsed MR: {mr_id} - {title[:50]}")

        except Exception as e:
            logger.warning(f"Failed to query MRs: {e}")

        return items

    def _mr_to_item(self, mr: dict) -> MemoryItem:
        """Convert MR dict to MemoryItem."""
        mr_id = mr.get("id", "unknown")
        title = mr.get("title", "")
        status = mr.get("status", "unknown")
        author = mr.get("author", "unknown")
        branch = mr.get("branch", "")

        content = f"MR {mr_id}: {title}\nStatus: {status}\nAuthor: {author}"
        if branch:
            content += f"\nBranch: {branch}"

        return MemoryItem(
            source="gitlab",
            type="merge_request",
            content=content,
            summary=f"{mr_id}: {title[:50]}..." if len(title) > 50 else f"{mr_id}: {title}",
            relevance=0.8,
            metadata={
                "id": f"gitlab-mr-{mr_id}",
                "mr_id": mr_id,
                "title": title,
                "status": status,
                "author": author,
                "branch": branch,
            },
        )

    async def _query_pipelines(
        self,
        question: str,
        context: dict[str, Any] | None,
    ) -> list[MemoryItem]:
        """Query pipeline status."""
        items = []

        try:
            project = context.get("project") if context else None

            result = await self._tools["pipeline_list"](
                limit=5,
                repo=project,
            )

            if result and "❌" not in result:
                # Parse pipeline output
                lines = result.split("\n")
                for line in lines:
                    if line.startswith("- "):
                        # Simple pipeline entry
                        items.append(
                            MemoryItem(
                                id=f"gitlab-pipeline-{hash(line)}",
                                source="gitlab",
                                type="pipeline",
                                content=line,
                                summary=line[:100],
                                relevance=0.7,
                                metadata={"raw": line},
                            )
                        )

        except Exception as e:
            logger.warning(f"Failed to query pipelines: {e}")

        return items

    async def search(
        self,
        query: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Search GitLab (delegates to query)."""
        return await self.query(query, filter)

    async def store(
        self,
        key: str,
        value: Any,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Store not supported for GitLab."""
        return AdapterResult(
            source="gitlab",
            items=[],
            error="GitLab adapter is read-only",
        )

    async def health_check(self) -> HealthStatus:
        """Check GitLab connectivity."""
        if not self._ensure_tools():
            return HealthStatus(
                healthy=False,
                error="GitLab tools not available",
            )

        try:
            # Quick auth check via glab
            success, output = await self._tools["run_glab"](["auth", "status"])

            if success or "Logged in" in output:
                return HealthStatus(
                    healthy=True,
                    details={"auth": "ok"},
                )
            else:
                return HealthStatus(
                    healthy=False,
                    error=f"GitLab auth issue: {output[:100]}",
                )

        except Exception as e:
            return HealthStatus(
                healthy=False,
                error=f"GitLab health check failed: {e}",
            )
