"""AA Jira MCP Server - Jira issue tracking operations.

Uses the rh-issue CLI for Red Hat Jira operations.
Authentication: JIRA_JPAT environment variable.
"""

import logging
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Add aa-common to path for shared utilities
SERVERS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SERVERS_DIR / "aa-common"))

from src.utils import get_project_root, get_section_config, run_cmd_shell

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
                f"  export JIRA_URL='https://issues.redhat.com'\n\n"
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

    @server.tool()
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

    @server.tool()
    async def jira_view_issue_json(issue_key: str) -> str:
        """
        Get Jira issue data as JSON for parsing.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)

        Returns:
            Issue data in JSON format.
        """
        success, output = await run_rh_issue(["view-issue", issue_key, "--output", "json"])

        if not success:
            return f"❌ Failed to get issue: {output}"

        return output

    @server.tool()
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

    @server.tool()
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

    @server.tool()
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

    @server.tool()
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

    @server.tool()
    async def jira_lint(issue_key: str, fix: bool = False) -> str:
        """
        Lint a Jira issue for quality and completeness.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)
            fix: Whether to automatically fix issues (default: False)

        Returns:
            Quality report and any issues found.
        """
        args = ["lint", issue_key]
        if fix:
            args.append("--fix")

        success, output = await run_rh_issue(args, timeout=60)

        # Lint may return non-zero if issues found, but still useful output
        return output

    # ==================== WRITE OPERATIONS ====================

    @server.tool()
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

    @server.tool()
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

    @server.tool()
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

    @server.tool()
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

    @server.tool()
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

    @server.tool()
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

    @server.tool()
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

    @server.tool()
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

    @server.tool()
    async def jira_create_issue(
        issue_type: str,
        summary: str,
        description: str = "",
        story_points: int = 0,
        labels: str = "",
        components: str = "",
        project: str = "AAP",
        convert_markdown: bool = True,
    ) -> str:
        """
        Create a new Jira issue.

        Accepts Markdown in description and auto-converts to Jira wiki markup.
        Issue type is case-insensitive (Story, story, STORY all work).

        Args:
            issue_type: Type of issue - "bug", "story", "task", "epic" (case insensitive)
            summary: Issue title/summary
            description: Issue description (accepts Markdown, auto-converted to Jira markup)
            story_points: Story points (optional, for stories)
            labels: Comma-separated labels (e.g., "testing,performance")
            components: Comma-separated components (e.g., "Automation Analytics")
            project: Jira project key (default: AAP)
            convert_markdown: Whether to convert Markdown to Jira markup (default: True)

        Returns:
            The created issue key and details.

        Example:
            jira_create_issue(
                issue_type="story",
                summary="Add pytest-xdist support",
                description="## Overview\\n\\n**Speed up** test suite with parallel execution.",
                labels="testing,performance",
                components="Automation Analytics"
            )
        """
        import re
        import sys
        from pathlib import Path

        # Normalize issue type to lowercase
        valid_types = {"bug", "story", "task", "epic", "spike", "subtask"}
        issue_type_normalized = issue_type.lower().strip()

        if issue_type_normalized not in valid_types:
            return f"❌ Invalid issue type: '{issue_type}'. Valid types: {', '.join(sorted(valid_types))}"

        # Convert Markdown to Jira if needed
        if convert_markdown and description:
            try:
                scripts_path = str(get_project_root() / "scripts")
                if scripts_path not in sys.path:
                    sys.path.insert(0, scripts_path)
                from common.jira_utils import markdown_to_jira

                description = markdown_to_jira(description)
            except ImportError:
                # Fallback: basic conversion
                description = description.replace("**", "*").replace("`", "{{")

        args = ["create-issue", issue_type_normalized, summary, "--project", project]

        if description:
            args.extend(["--description", description])

        if story_points > 0:
            args.extend(["--story-points", str(story_points)])

        if labels:
            for label in labels.split(","):
                label = label.strip()
                if label:
                    args.extend(["--label", label])

        if components:
            for comp in components.split(","):
                comp = comp.strip()
                if comp:
                    args.extend(["--component", comp])

        success, output = await run_rh_issue(args, timeout=60)

        if not success:
            return f"❌ Failed to create issue: {output}\n\n💡 Tip: If env vars are missing, use the create_jira_issue skill instead which runs via CLI with your shell environment."

        # Extract issue key from output
        issue_key_match = re.search(r"([A-Z]+-\d+)", output)
        if issue_key_match:
            issue_key = issue_key_match.group(1)
            url = f"https://issues.redhat.com/browse/{issue_key}"
            return f"✅ Issue created: [{issue_key}]({url})\n\n{output}"

        return f"✅ Issue created\n\n{output}"

    @server.tool()
    async def jira_clone_issue(issue_key: str, new_summary: str = "") -> str:
        """
        Create a copy of an existing Jira issue.

        Args:
            issue_key: The issue to clone (e.g., AAP-12345)
            new_summary: New summary for the cloned issue (optional)

        Returns:
            The cloned issue key and details.
        """
        args = ["clone-issue", issue_key]
        if new_summary:
            args.extend(["--new-summary", new_summary])

        success, output = await run_rh_issue(args, timeout=60)

        if not success:
            return f"❌ Failed to clone issue: {output}"

        return f"✅ Issue cloned\n\n{output}"

    @server.tool()
    async def jira_add_link(
        from_issue: str,
        to_issue: str,
        link_type: str = "relates-to",
    ) -> str:
        """
        Create a link between two Jira issues.

        Args:
            from_issue: Source issue key (e.g., AAP-12345)
            to_issue: Target issue key (e.g., AAP-12346)
            link_type: Type of link - "blocks", "relates-to", "duplicates", "clones"

        Returns:
            Confirmation of the link.
        """
        success, output = await run_rh_issue(["add-link", from_issue, to_issue, link_type])

        if not success:
            return f"❌ Failed to add link: {output}"

        return f"🔗 {from_issue} {link_type} {to_issue}\n\n{output}"

    @server.tool()
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

    @server.tool()
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

    @server.tool()
    async def jira_open_browser(issue_key: str) -> str:
        """
        Open a Jira issue in the web browser.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)

        Returns:
            Confirmation that browser was opened.
        """
        success, output = await run_rh_issue(["open-issue", issue_key])

        if not success:
            return f"❌ Failed to open browser: {output}"

        return f"🌐 Opened {issue_key} in browser"

    # ==================== ADDITIONAL TOOLS (from jira_tools) ====================

    @server.tool()
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

    @server.tool()
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

    @server.tool()
    async def jira_ai_helper(issue_key: str, action: str = "summarize") -> str:
        """
        AI helper for Jira issues - provides structured analysis.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)
            action: What to do - "summarize", "next_steps", "blockers"

        Returns:
            AI-assisted analysis of the issue.
        """
        # Get issue details
        success, output = await run_rh_issue(["view-issue", issue_key, "--output", "json"])
        if not success:
            return f"❌ Failed to get issue: {output}"

        try:
            import json

            issue = json.loads(output)
        except:
            return f"❌ Failed to parse issue data"

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

    @server.tool()
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

    return len([m for m in dir() if not m.startswith("_")])  # Approximate count
