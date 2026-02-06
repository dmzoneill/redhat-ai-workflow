"""
Jira Memory Adapter - Memory source for Jira issue context.

This adapter exposes Jira issues as a memory source, allowing
the memory abstraction layer to query issue details, status,
and related information.

It wraps the existing Jira tool functionality.
"""

import json
import logging
import re
from typing import Any

from services.memory_abstraction.models import AdapterResult, HealthStatus, MemoryItem, SourceFilter
from services.memory_abstraction.registry import memory_adapter

logger = logging.getLogger(__name__)

# Issue key pattern
ISSUE_KEY_PATTERN = re.compile(r"\b(AAP|APPSRE|KONFLUX|JIRA)-\d+\b", re.IGNORECASE)


@memory_adapter(
    name="jira",
    display_name="Jira Issues",
    capabilities={"query"},
    intent_keywords=[
        "issue",
        "ticket",
        "jira",
        "aap",
        "appsre",
        "konflux",
        "status",
        "assignee",
        "sprint",
        "epic",
        "story",
        "bug",
        "acceptance criteria",
        "description",
    ],
    priority=55,
    latency_class="slow",  # External Jira API
)
class JiraAdapter:
    """
    Adapter for Jira issue information.

    Provides access to issue details, status, and context
    from Red Hat Jira.
    """

    async def query(
        self,
        question: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """
        Query Jira for issue information.

        Args:
            question: Question about an issue (should contain issue key)
            filter: Optional filter with issue_key

        Returns:
            AdapterResult with issue details
        """
        try:
            # Import the existing Jira implementation
            from tool_modules.aa_jira.src.tools_basic import run_rh_issue

            # Extract issue key from question or filter
            issue_key = None
            if filter and filter.extra:
                issue_key = filter.extra.get("issue_key")

            if not issue_key:
                # Try to extract from question
                match = ISSUE_KEY_PATTERN.search(question)
                if match:
                    issue_key = match.group(0).upper()

            if not issue_key:
                return AdapterResult(
                    source="jira",
                    items=[],
                    error="No issue key found in query. Include an issue key like AAP-12345.",
                )

            # Get issue details
            success, output = await run_rh_issue(["view", issue_key, "--json"])

            if not success:
                return AdapterResult(
                    source="jira",
                    items=[],
                    error=f"Failed to fetch issue: {output[:200]}",
                )

            # Parse JSON output
            try:
                issue_data = json.loads(output)
            except json.JSONDecodeError:
                # Fallback to text output
                return AdapterResult(
                    source="jira",
                    found=True,
                    items=[self._text_to_memory_item(issue_key, output)],
                )

            # Convert to MemoryItem
            item = self._to_memory_item(issue_key, issue_data)

            return AdapterResult(
                source="jira",
                found=True,
                items=[item],
            )

        except ImportError as e:
            logger.error(f"Jira module not available: {e}")
            return AdapterResult(
                source="jira",
                found=False,
                items=[],
                error="Jira module not available",
            )
        except Exception as e:
            logger.error(f"Jira query failed: {e}")
            return AdapterResult(
                source="jira",
                found=False,
                items=[],
                error=str(e),
            )

    async def search(
        self,
        query: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Search is the same as query for Jira."""
        return await self.query(query, filter)

    async def store(
        self,
        key: str,
        value: Any,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Jira adapter is read-only (use jira_* tools for writes)."""
        return AdapterResult(
            source="jira",
            items=[],
            error="Use jira_add_comment or jira_transition for Jira updates",
        )

    async def health_check(self) -> HealthStatus:
        """Check if Jira is accessible."""
        try:
            from tool_modules.aa_jira.src.tools_basic import run_rh_issue

            # Quick test - list config profiles (fast, doesn't hit API)
            success, output = await run_rh_issue(["config", "list-profiles"], timeout=10)

            return HealthStatus(
                healthy=success,
                error=None if success else output[:100],
                details={"config": "ok"} if success else {},
            )
        except ImportError:
            return HealthStatus(
                healthy=False,
                error="Jira module not available",
            )
        except Exception as e:
            return HealthStatus(healthy=False, error=str(e))

    def _to_memory_item(self, issue_key: str, data: dict) -> MemoryItem:
        """Convert Jira issue data to MemoryItem."""
        fields = data.get("fields", {})

        summary = fields.get("summary", "No summary")
        status = fields.get("status", {}).get("name", "Unknown")
        assignee = fields.get("assignee", {})
        assignee_name = assignee.get("displayName", "Unassigned") if assignee else "Unassigned"

        # Build content
        content_parts = [
            f"**{issue_key}: {summary}**",
            f"Status: {status}",
            f"Assignee: {assignee_name}",
        ]

        # Add description if present
        description = fields.get("description", "")
        if description:
            # Truncate long descriptions
            if len(description) > 500:
                description = description[:500] + "..."
            content_parts.append(f"\n**Description:**\n{description}")

        # Add acceptance criteria if present
        ac = fields.get("customfield_12313440", "")  # Common AC field
        if ac:
            if len(ac) > 300:
                ac = ac[:300] + "..."
            content_parts.append(f"\n**Acceptance Criteria:**\n{ac}")

        return MemoryItem(
            source="jira",
            type="issue",
            relevance=0.9,  # Jira issues are highly relevant when requested
            summary=f"{issue_key}: {summary} ({status})",
            content="\n".join(content_parts),
            metadata={
                "issue_key": issue_key,
                "status": status,
                "assignee": assignee_name,
                "issue_type": fields.get("issuetype", {}).get("name", "Unknown"),
                "priority": fields.get("priority", {}).get("name", "Unknown"),
                "project": fields.get("project", {}).get("key", ""),
            },
        )

    def _text_to_memory_item(self, issue_key: str, text: str) -> MemoryItem:
        """Convert plain text output to MemoryItem."""
        # Extract summary from first line if possible
        lines = text.strip().split("\n")
        summary = lines[0][:100] if lines else f"Issue {issue_key}"

        return MemoryItem(
            source="jira",
            type="issue",
            relevance=0.8,
            summary=f"{issue_key}: {summary}",
            content=text[:1000],
            metadata={
                "issue_key": issue_key,
                "format": "text",
            },
        )
