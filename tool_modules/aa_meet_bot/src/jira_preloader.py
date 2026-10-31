"""
Jira Context Preloader.

Preloads sprint information before joining meetings so the bot
can respond quickly to Jira-related questions.

Uses the MCP Jira tools for reliable access.
"""

import asyncio
import functools
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from tool_modules.aa_meet_bot.src.config import get_config
from tool_modules.aa_meet_bot.src.llm_responder import get_llm_responder

logger = logging.getLogger(__name__)

# Failures expected while talking to Jira or the LLM responder: network/file
# errors, bad JSON and unexpected response shapes.
_JIRA_ERRORS: tuple[type[Exception], ...] = (
    OSError,
    urllib.error.URLError,
    ValueError,
    KeyError,
    TypeError,
    AttributeError,
)


def _jira_credentials() -> tuple[str, str]:
    """Return ``(jira_url, token)`` from the environment or ~/.config/jira/config.json."""
    jira_url = os.environ.get("JIRA_URL", "https://issues.redhat.com")
    # Try JIRA_JPAT first (used by rh-issue), then JIRA_TOKEN
    jira_token = os.environ.get("JIRA_JPAT", "") or os.environ.get("JIRA_TOKEN", "")
    if not jira_token:
        config_path = Path.home() / ".config" / "jira" / "config.json"
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
                jira_token = config.get("token", "")
                jira_url = config.get("url", jira_url)
    return jira_url, jira_token


def _fetch_json(req: urllib.request.Request) -> dict:
    """Perform the (blocking) request and decode the JSON body."""
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _split_cells(line: str) -> list[str]:
    """Split a table line on ``|`` or on runs of two or more spaces."""
    if "|" in line:
        return [v.strip() for v in line.split("|") if v.strip() or v == ""]
    return [v.strip() for v in re.split(r"\s{2,}", line)]


def _find_header(lines: list[str]) -> tuple[list[str], int]:
    """Return the normalised header names and the index of the first data line."""
    for i, line in enumerate(lines):
        if "Key" in line and ("Status" in line or "Summary" in line):
            headers = [h.lower().replace(" ", "_") for h in _split_cells(line) if h]
            data_start = i + 1
            if data_start < len(lines) and "---" in lines[data_start]:
                data_start += 1
            return headers, data_start
    return [], 0


def _parse_jira_table(output: str) -> list[dict]:
    """Parse the table output from Jira MCP tools into a list of dicts."""
    lines = output.strip().split("\n")
    if len(lines) < 2:
        return []

    headers, data_start = _find_header(lines)
    if not headers:
        return []

    results = []
    for line in lines[data_start:]:
        if not line.strip() or line.startswith(("📊", "Found")):
            continue
        values = _split_cells(line)
        if len(values) >= len(headers):
            row = dict(zip(headers, values))
            if row.get("key"):
                results.append(row)

    return results


@dataclass
class SprintInfo:
    """Information about a sprint."""

    id: int
    name: str
    state: str  # "active", "closed", "future"
    start_date: datetime | None = None
    end_date: datetime | None = None
    goal: str = ""


class JiraIssue(NamedTuple):
    """Simplified (immutable) Jira issue for context."""

    key: str
    summary: str
    status: str
    assignee: str
    issue_type: str
    priority: str
    story_points: int | None = None
    labels: Sequence[str] = ()

    def to_dict(self) -> dict:
        """Serialise for the LLM responder context."""
        return {
            "key": self.key,
            "summary": self.summary,
            "status": self.status,
            "assignee": self.assignee,
            "type": self.issue_type,
            "priority": self.priority,
            "story_points": self.story_points,
            "labels": list(self.labels),
        }


class JiraPreloader:
    """
    Preloads Jira context for meeting responses.

    Uses the existing Jira MCP tools via subprocess to fetch data.
    """

    def __init__(self):
        self.config = get_config()
        self.project = "AAP"  # Default project
        self.current_sprint: SprintInfo | None = None
        self.issues: list[JiraIssue] = []
        self.my_issues: list[JiraIssue] = []
        self.last_refresh: datetime | None = None
        self.refresh_interval = timedelta(minutes=15)

    async def preload(self, project: str = "AAP") -> bool:
        """
        Preload Jira context for a project.

        Args:
            project: Jira project key

        Returns:
            True if successful
        """
        self.project = project
        logger.info("Preloading Jira context for %s...", project)

        try:
            # Fetch my issues
            my_issues = await self._fetch_my_issues()

            # Fetch sprint issues
            sprint_issues = await self._fetch_sprint_issues()

            # Update the LLM responder's context
            responder = get_llm_responder()
            responder.update_jira_context(
                issues=[i.to_dict() for i in sprint_issues],
                my_issues=[i.to_dict() for i in my_issues],
            )

            # Update sprint info in context
            if self.current_sprint:
                responder.jira_context.sprint_name = self.current_sprint.name
                responder.jira_context.sprint_goal = self.current_sprint.goal

            self.issues = sprint_issues
            self.my_issues = my_issues
            self.last_refresh = datetime.now(UTC)

            logger.info("Loaded %s personal issues, %s sprint issues", len(my_issues), len(sprint_issues))
            return True

        except _JIRA_ERRORS as e:
            logger.error("Failed to preload Jira context: %s", e)
            return False

    async def _fetch_my_issues(self) -> list[JiraIssue]:
        """Fetch issues assigned to me using MCP tools."""
        try:
            # Use the MCP jira_search tool via subprocess
            jql = f"project = {self.project} AND assignee = currentUser() AND status != Done ORDER BY updated DESC"
            return await self._jql_search(jql)
        except _JIRA_ERRORS as e:
            logger.error("Failed to fetch my issues: %s", e)
            return []

    async def _fetch_sprint_issues(self) -> list[JiraIssue]:
        """Fetch issues in the current sprint."""
        try:
            # Try to get active sprint issues
            return await self._jql_search(
                f"project = {self.project} AND Sprint in openSprints() ORDER BY status ASC, priority DESC"
            )
        except _JIRA_ERRORS as e:
            logger.error("Failed to fetch sprint issues: %s", e)
            return []

    async def _jql_search(self, jql: str, max_results: int = 50) -> list[JiraIssue]:
        """Execute a JQL search using the Jira REST API directly."""
        try:
            jira_url, jira_token = _jira_credentials()
            if not jira_token:
                logger.warning("No Jira token found")
                return []

            params = urllib.parse.urlencode(
                {
                    "jql": jql,
                    "maxResults": max_results,
                    "fields": "key,summary,status,assignee,issuetype,priority,customfield_10016,labels",
                }
            )
            req = urllib.request.Request(f"{jira_url}/rest/api/2/search?{params}")
            req.add_header("Authorization", f"Bearer {jira_token}")
            req.add_header("Content-Type", "application/json")

            data = await asyncio.get_running_loop().run_in_executor(None, _fetch_json, req)
            return [self._parse_issue(issue_data) for issue_data in data.get("issues", [])]

        except _JIRA_ERRORS as e:
            logger.error("JQL search error: %s", e)
            return []

    def _parse_issue(self, data: dict) -> JiraIssue:
        """Parse a Jira issue from API response."""
        fields = data.get("fields", data)

        return JiraIssue(
            key=data.get("key", ""),
            summary=fields.get("summary", ""),
            status=(
                fields.get("status", {}).get("name", "")
                if isinstance(fields.get("status"), dict)
                else str(fields.get("status", ""))
            ),
            assignee=(
                fields.get("assignee", {}).get("displayName", "Unassigned")
                if isinstance(fields.get("assignee"), dict)
                else str(fields.get("assignee", "Unassigned"))
            ),
            issue_type=(
                fields.get("issuetype", {}).get("name", "")
                if isinstance(fields.get("issuetype"), dict)
                else str(fields.get("issuetype", ""))
            ),
            priority=(
                fields.get("priority", {}).get("name", "")
                if isinstance(fields.get("priority"), dict)
                else str(fields.get("priority", ""))
            ),
            story_points=fields.get("customfield_10016"),  # Story points field
            labels=fields.get("labels", []),
        )

    async def refresh_if_stale(self) -> bool:
        """Refresh context if it's stale."""
        if self.last_refresh is None:
            return await self.preload(self.project)

        if datetime.now(UTC) - self.last_refresh > self.refresh_interval:
            logger.info("Jira context is stale, refreshing...")
            return await self.preload(self.project)

        return True

    def get_issue_summary(self, issue_key: str) -> str | None:
        """Get a quick summary of an issue."""
        for issue in self.issues + self.my_issues:
            if issue.key.upper() == issue_key.upper():
                return f"{issue.key}: {issue.summary} ({issue.status})"
        return None

    def get_status_summary(self) -> str:
        """Get a summary of current sprint status."""
        if not self.issues:
            return "No sprint data loaded."

        # Count by status
        status_counts: dict[str, int] = {}
        for issue in self.issues:
            status = issue.status
            status_counts[status] = status_counts.get(status, 0) + 1

        # Format summary
        parts = []
        for status, count in sorted(status_counts.items()):
            parts.append(f"{count} {status}")

        my_count = len(self.my_issues)

        return f"Sprint has {len(self.issues)} items: {', '.join(parts)}. I have {my_count} assigned."


@functools.cache
def get_jira_preloader() -> JiraPreloader:
    """Get or create the global Jira preloader instance."""
    return JiraPreloader()


async def preload_jira_context(project: str = "AAP") -> bool:
    """
    Convenience function to preload Jira context.

    Call this before joining a meeting.
    """
    preloader = get_jira_preloader()
    return await preloader.preload(project)
