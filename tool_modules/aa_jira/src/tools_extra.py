"""AA Jira MCP Server - Jira issue tracking operations.

Uses the rh-issue CLI for Red Hat Jira operations.
Authentication: JIRA_JPAT environment variable.
"""

import logging
from typing import cast

from mcp.server.fastmcp import FastMCP

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import  load_config, run_cmd_shell

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


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

        # ==================== TOOLS NOT USED IN SKILLS ====================
    @auto_heal()
    @registry.tool()
    async def jira_add_flag(issue_key: str) -> str:
        """
        Add a flag (impediment) to a Jira issue.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)

        Returns:
            Confirmation of the flag.
        """
        success, output = await run_rh_issue(["add-flag", issue_key])

        if not success:
            return f"❌ Failed to add flag: {output}"

        return f"🚩 Flag added to {issue_key}\n\n{output}"

    @auto_heal()
    @registry.tool()
    async def jira_add_to_sprint(issue_key: str, sprint_id: str = "") -> str:
        """
        Add an issue to a sprint.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)
            sprint_id: Sprint ID (optional, uses current sprint if not specified)

        Returns:
            Confirmation of sprint assignment.
        """
        args = ["add-to-sprint", issue_key]
        if sprint_id:
            args.extend(["--sprint", sprint_id])

        success, output = await run_rh_issue(args)

        if not success:
            return f"❌ Failed to add to sprint: {output}"

        return f"✅ {issue_key} added to sprint\n\n{output}"

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
    async def jira_block(issue_key: str, blocked_by: str, reason: str = "") -> str:
        """
        Mark a Jira issue as blocked by another issue.

        Args:
            issue_key: The issue that is blocked (e.g., AAP-12345)
            blocked_by: The issue that is blocking (e.g., AAP-12346)
            reason: Optional reason for the block

        Returns:
            Confirmation of the block.
        """
        args = ["block", issue_key, blocked_by]
        if reason:
            args.append(reason)

        success, output = await run_rh_issue(args)

        if not success:
            return f"❌ Failed to block: {output}"

        return f"🚧 {issue_key} blocked by {blocked_by}\n\n{output}"

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

    @auto_heal()
    @registry.tool()
    async def jira_remove_flag(issue_key: str) -> str:
        """
        Remove a flag from a Jira issue.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)

        Returns:
            Confirmation of flag removal.
        """
        success, output = await run_rh_issue(["remove-flag", issue_key])

        if not success:
            return f"❌ Failed to remove flag: {output}"

        return f"✅ Flag removed from {issue_key}\n\n{output}"

    @auto_heal()
    @registry.tool()
    async def jira_remove_sprint(issue_key: str) -> str:
        """
        Remove an issue from its current sprint.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)

        Returns:
            Confirmation of removal.
        """
        success, output = await run_rh_issue(["remove-sprint", issue_key])

        if not success:
            return f"❌ Failed to remove from sprint: {output}"

        return f"✅ {issue_key} removed from sprint\n\n{output}"

    @auto_heal()
    @registry.tool()
    async def jira_set_summary(issue_key: str, summary: str) -> str:
        """
        Update the summary (title) of a Jira issue.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)
            summary: The new summary text for the issue

        Returns:
            Confirmation of the summary update.
        """
        success, output = await run_rh_issue(["set-summary", issue_key, summary])

        if not success:
            return f"❌ Failed to set summary: {output}"

        return f"✅ Summary for {issue_key} updated to: **{summary}**\n\n{output}"

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
    async def jira_unblock(issue_key: str, blocked_by: str) -> str:
        """
        Remove the blocked status from a Jira issue.

        Args:
            issue_key: The issue that was blocked (e.g., AAP-12345)
            blocked_by: The issue that was blocking (e.g., AAP-12346)

        Returns:
            Confirmation of the unblock.
        """
        success, output = await run_rh_issue(["unblock", issue_key, blocked_by])

        if not success:
            return f"❌ Failed to unblock: {output}"

        return f"✅ {issue_key} unblocked from {blocked_by}\n\n{output}"
