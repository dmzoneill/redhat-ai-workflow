"""Jira Basic Tools - Essential jira operations.

For advanced operations, see tools_extra.py.

Tools included (~15):
- jira_view_issue, jira_view_issue_json, jira_search, ...
"""

import logging
from typing import cast

from mcp.server.fastmcp import FastMCP

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import get_project_root, load_config, run_cmd_shell  # noqa: F401

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT  # noqa: F401 - side effect: adds to sys.path


def _get_jira_url() -> str:
    """Get Jira URL from config."""
    config = load_config()
    return cast(dict, config.get("jira", {})).get("url", "https://issues.redhat.com")


logger = logging.getLogger(__name__)


async def run_rh_issue(args: list[str], timeout: int = 30) -> tuple[bool, str]:
    """Run rh-issue command through user's login shell for proper environment.

    Uses shared run_cmd_shell to ensure proper environment including:
    - JIRA_JPAT and other env vars from ~/.bashrc
    - pipenv virtualenv access (needs HOME)
    - User's PATH with ~/bin
    """
    # Use shared run_cmd_shell for proper environment
    success, stdout, stderr = await run_cmd_shell(
        ["rh-issue"] + args,
        timeout=timeout,
    )

    output = stdout or stderr

    if not success:
        # Check for common auth issues
        if "JIRA_JPAT" in output or "401" in output or "Unauthorized" in output:
            return False, (
                f"❌ Jira authentication failed.\n\n"
                f"Ensure these are in your ~/.bashrc:\n"
                f"  export JIRA_JPAT='your-token'\n"
                f"  export JIRA_URL='{_get_jira_url()}'\n\n"
                f"Original error: {output}"
            )
        if "No module named" in output:
            return False, (
                f"❌ rh-issue dependency missing.\n\n"
                f"Run: cd ~/src/jira-creator && pipenv install\n\n"
                f"Original error: {output}"
            )
        return False, output

    return True, stdout


# ==================== READ OPERATIONS ====================


def register_tools(server: FastMCP) -> int:
    """Register basic jira tools with the MCP server."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def jira_view_issue(issue_key: str) -> str:
        """
        View detailed information about a Jira issue.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)

        Returns:
            Detailed issue information including status, description, acceptance criteria.
        """
        success, output = await run_rh_issue(["view-issue", issue_key])

        if not success:
            return f"❌ Failed to get issue: {output}"

        return output

    @auto_heal()
    @registry.tool()
    async def jira_view_issue_json(issue_key: str) -> str:
        """
        Get Jira issue data as structured text for parsing.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)

        Returns:
            Issue data in a parseable key-value format.
        """
        # Note: rh-issue view-issue doesn't support --output json
        # Return raw output which can be parsed as key: value pairs
        success, output = await run_rh_issue(["view-issue", issue_key])

        if not success:
            return f"❌ Failed to get issue: {output}"

        # Parse the output into a dict-like structure
        import json
        import re

        data = {"raw": output}

        # Parse key-value lines from the output
        # Format: "key             : value"
        for line in output.split("\n"):
            match = re.match(r"^([a-z][a-z_ /]+?)\s*:\s*(.*)$", line.strip(), re.IGNORECASE)
            if match:
                key = match.group(1).strip().lower().replace(" ", "_").replace("/", "_")
                value = match.group(2).strip()
                data[key] = value

        # Extract description section if present
        desc_match = re.search(r"📝 DESCRIPTION\s*-+\s*(.*?)(?=\n={5,}|\Z)", output, re.DOTALL)
        if desc_match:
            data["description"] = desc_match.group(1).strip()

        return json.dumps(data, indent=2)

    @auto_heal()
    @registry.tool()
    async def jira_search(jql: str, max_results: int = 20) -> str:
        """
        Search for Jira issues using JQL (Jira Query Language).

        Args:
            jql: JQL query string (e.g., "project = AAP AND status = Open")
            max_results: Maximum number of results to return

        Returns:
            List of matching issues.
        """
        success, output = await run_rh_issue(
            ["search", jql, "--max-results", str(max_results)],
            timeout=60,
        )

        if not success:
            return f"❌ Search failed: {output}"

        return output

    @auto_heal()
    @registry.tool()
    async def jira_list_issues(
        project: str = "AAP",
        status: str = "",
        assignee: str = "",
    ) -> str:
        """
        List issues from a Jira project with filters.

        Args:
            project: Jira project key (default: AAP)
            status: Filter by status (e.g., "In Progress", "Open")
            assignee: Filter by assignee username

        Returns:
            List of issues matching the filters.
        """
        args = ["list-issues", project]
        if status:
            args.extend(["--status", status])
        if assignee:
            args.extend(["--assignee", assignee])

        success, output = await run_rh_issue(args, timeout=60)

        if not success:
            return f"❌ Failed to list issues: {output}"

        return output

    @auto_heal()
    @registry.tool()
    async def jira_my_issues(status: str = "") -> str:
        """
        List issues assigned to the current user.

        Args:
            status: Optional status filter (e.g., "In Progress")

        Returns:
            List of your assigned issues.
        """
        jql = "assignee = currentUser()"
        if status:
            jql += f' AND status = "{status}"'

        success, output = await run_rh_issue(
            ["search", jql, "--max-results", "50"],
            timeout=60,
        )

        if not success:
            return f"❌ Failed to get issues: {output}"

        return output

    @auto_heal()
    @registry.tool()
    async def jira_list_blocked() -> str:
        """
        List all blocked issues with blocker details.

        Returns:
            List of blocked issues and what's blocking them.
        """
        success, output = await run_rh_issue(["list-blocked"], timeout=60)

        if not success:
            return f"❌ Failed to list blocked: {output}"

        return output

    @auto_heal()
    @registry.tool()
    async def jira_lint(issue_key: str) -> str:
        """
        Lint a Jira issue for quality and completeness.

        Checks issue for:
        - Description quality and formatting
        - Acceptance criteria presence and clarity
        - Epic link assignment
        - Story points (for in-progress issues)
        - Labels and components

        Note: The rh-issue CLI does not support auto-fix. Use jira_set_*
        tools to fix issues found by lint.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)

        Returns:
            Quality report and any issues found.
        """
        args = ["lint", issue_key]

        success, output = await run_rh_issue(args, timeout=60)

        # Lint may return non-zero if issues found, but still useful output
        return output

    # ==================== WRITE OPERATIONS ====================

    @auto_heal()
    @registry.tool()
    async def jira_set_status(issue_key: str, status: str) -> str:
        """
        Set the status of a Jira issue (transition it).

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)
            status: New status (e.g., "In Progress", "In Review", "Done")

        Returns:
            Confirmation of the status change.
        """
        success, output = await run_rh_issue(["set-status", issue_key, status])

        if not success:
            return f"❌ Failed to set status: {output}"

        return f"✅ {issue_key} status changed to **{status}**\n\n{output}"

    @auto_heal()
    @registry.tool()
    async def jira_assign(issue_key: str, assignee: str) -> str:
        """
        Assign a Jira issue to a user.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)
            assignee: Username to assign to (e.g., "jsmith")

        Returns:
            Confirmation of the assignment.
        """
        success, output = await run_rh_issue(["assign", issue_key, assignee])

        if not success:
            return f"❌ Failed to assign: {output}"

        return f"✅ {issue_key} assigned to **@{assignee}**\n\n{output}"

    @auto_heal()
    @registry.tool()
    async def jira_unassign(issue_key: str) -> str:
        """
        Remove the assignee from a Jira issue.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)

        Returns:
            Confirmation of the unassignment.
        """
        success, output = await run_rh_issue(["unassign", issue_key])

        if not success:
            return f"❌ Failed to unassign: {output}"

        return f"✅ {issue_key} unassigned\n\n{output}"

    @auto_heal()
    @registry.tool()
    async def jira_add_comment(issue_key: str, comment: str) -> str:
        """
        Add a comment to a Jira issue.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)
            comment: The comment text to add

        Returns:
            Confirmation of the comment.
        """
        success, output = await run_rh_issue(["add-comment", issue_key, comment])

        if not success:
            return f"❌ Failed to add comment: {output}"

        return f"✅ Comment added to {issue_key}\n\n{output}"

    @auto_heal()
    @registry.tool()
    async def jira_get_issue(issue_key: str) -> str:
        """
        Get details of a Jira issue (alias for jira_view_issue).

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)

        Returns:
            Issue details.
        """
        success, output = await run_rh_issue(["view-issue", issue_key])
        if not success:
            return f"❌ Failed: {output}"
        return output

    @auto_heal()
    @registry.tool()
    async def jira_transition(issue_key: str, status: str) -> str:
        """
        Transition a Jira issue to a new status (alias for jira_set_status).

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)
            status: The target status name

        Returns:
            Confirmation of the transition.
        """
        success, output = await run_rh_issue(["set-status", issue_key, status])
        if not success:
            return f"❌ Failed: {output}"
        return f"✅ {issue_key} transitioned to '{status}'"

    @auto_heal()
    @registry.tool()
    async def jira_ai_helper(issue_key: str, action: str = "summarize") -> str:
        """
        AI helper for Jira issues - provides structured analysis.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)
            action: What to do - "summarize", "next_steps", "blockers"

        Returns:
            AI-assisted analysis of the issue.
        """
        import re

        # Get issue details (using view-issue, no JSON output available)
        success, output = await run_rh_issue(["view-issue", issue_key])
        if not success:
            return f"❌ Failed to get issue: {output}"

        # Parse key-value pairs from output
        issue = {}
        for line in output.split("\n"):
            match = re.match(r"^([a-z][a-z_ /]+?)\s*:\s*(.*)$", line.strip(), re.IGNORECASE)
            if match:
                key = match.group(1).strip().lower().replace(" ", "_").replace("/", "_")
                value = match.group(2).strip()
                issue[key] = value

        # Extract description section if present
        desc_match = re.search(r"📝 DESCRIPTION\s*-+\s*(.*?)(?=\n={5,}|\Z)", output, re.DOTALL)
        if desc_match:
            issue["description"] = desc_match.group(1).strip()

        summary = issue.get("summary", "No summary")
        status = issue.get("status", "Unknown")
        description = issue.get("description", "No description")[:500]
        acceptance = issue.get("acceptance_criteria", "")[:300]

        if action == "summarize":
            return f"""## Issue Summary: {issue_key}

**Title:** {summary}
**Status:** {status}

**Description:**
{description}

**Acceptance Criteria:**
{acceptance if acceptance else 'Not defined'}
"""
        elif action == "next_steps":
            steps = []
            if status == "Open" or status == "New":
                steps = [
                    "1. Review requirements",
                    "2. Create feature branch",
                    "3. Start implementation",
                ]
            elif status == "In Progress":
                steps = [
                    "1. Continue implementation",
                    "2. Run local tests",
                    "3. Create MR when ready",
                ]
            elif status == "In Review" or status == "Review":
                steps = ["1. Address review feedback", "2. Update MR", "3. Get approval"]
            else:
                steps = ["1. Check issue status", "2. Determine next action"]

            return f"""## Next Steps for {issue_key}

**Current Status:** {status}

**Suggested Steps:**
{chr(10).join(steps)}
"""
        elif action == "blockers":
            return f"""## Blocker Analysis: {issue_key}

**Status:** {status}

Use `jira_list_blocked()` to see all blocked issues.
Use `jira_view_issue({issue_key})` for full details including linked issues.
"""
        else:
            return f"Unknown action: {action}. Use: summarize, next_steps, blockers"

    @auto_heal()
    @registry.tool()
    async def jira_show_template(issue_type: str = "story") -> str:
        """
        Show the expected YAML template for creating Jira issues.

        This helps understand the exact field names and format expected
        by the rh-issue CLI's --input-file option.

        Args:
            issue_type: Issue type to show template for (story, bug, task, epic)

        Returns:
            YAML template with all supported fields.
        """
        issue_type = issue_type.lower().strip()

        templates = {
            "story": """# YAML Template for Story
# Save this to a file and use with: rh-issue create-issue story "Summary" --input-file story.yaml

Summary: "Add feature X to improve Y"

Description: |
  h2. Overview

  Brief description of the feature.

  h3. Background

  Why this is needed.

"User Story": |
  As a [user role],
  I want [goal],
  So that [benefit].

"Acceptance Criteria": |
  * Criterion 1 is met
  * Criterion 2 is verified
  * Tests pass with 90% coverage

"Supporting Documentation": |
  * [Design Doc|https://docs.example.com/design]
  * [API Spec|https://docs.example.com/api]

"Definition of Done": |
  * Code reviewed and approved
  * Unit tests added
  * Integration tests pass
  * Documentation updated
  * Deployed to stage

Labels:
  - feature
  - sprint-xx

Components:
  - Automation Analytics

"Story Points": 5

"Epic Link": AAP-12345
""",
            "bug": """# YAML Template for Bug
# Save this to a file and use with: rh-issue create-issue bug "Summary" --input-file bug.yaml

Summary: "API returns 500 on empty request body"

Description: |
  h2. Bug Description

  The API crashes when receiving an empty POST body.

  h3. Steps to Reproduce

  # Send POST request to /api/v1/data
  # Include empty body: {{}}
  # Observe 500 error

  h3. Expected Behavior

  Should return 400 Bad Request with helpful message.

  h3. Actual Behavior

  Returns 500 Internal Server Error.

  h3. Environment

  * Stage environment
  * Version: 2.1.0

Labels:
  - bug
  - api

Components:
  - Automation Analytics

Priority: High
""",
            "task": """# YAML Template for Task
# Save this to a file and use with: rh-issue create-issue task "Summary" --input-file task.yaml

Summary: "Update dependencies to latest versions"

Description: |
  h2. Task Description

  Update all Python dependencies to their latest compatible versions.

  h3. Checklist

  * Update requirements.txt
  * Run test suite
  * Check for breaking changes
  * Update documentation if needed

Labels:
  - maintenance
  - dependencies

Components:
  - Automation Analytics
""",
        }

        template = templates.get(issue_type, templates["story"])

        return f"""## Jira YAML Template: {issue_type.capitalize()}

{template}

---

## Important Notes

**Field Names:** Must use Title Case with spaces in quotes:
- ✅ `"User Story":`
- ✅ `"Acceptance Criteria":`
- ❌ `user_story:` (won't work)
- ❌ `acceptance_criteria:` (won't work)

**Markup:** Use Jira wiki markup, NOT Markdown:
- `h2. Heading` not `## Heading`
- `*bold*` not `**bold**`
- `{{code}}` not `` `code` ``
- `* item` not `- item`

**Tip:** Use the `create_jira_issue` skill to auto-convert Markdown:
```
skill_run("create_jira_issue", '{{"summary": "...", "description": "## Markdown works here!"}}'
```
"""

    return registry.count
