"""AA Jira MCP Server - Jira issue tracking operations.

Uses the rh-issue CLI for Red Hat Jira operations.
Authentication: JIRA_JPAT environment variable.
"""

import asyncio
import logging
import os
import subprocess

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Create the MCP server


async def run_rh_issue(args: list[str], timeout: int = 30) -> tuple[bool, str]:
    """Run rh-issue command and return (success, output)."""
    cmd = ["rh-issue"] + args
    
    # Ensure required env vars are set
    env = os.environ.copy()
    if "JIRA_AFFECTS_VERSION" not in env:
        env["JIRA_AFFECTS_VERSION"] = "1.0"
    
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        
        output = result.stdout
        if result.returncode != 0:
            output = result.stderr or result.stdout or "Command failed"
            return False, output
        
        return True, output
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return False, "rh-issue CLI not found. Install with: pip install rh-issue"
    except Exception as e:
        return False, str(e)


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
        story_points: int = 0,
    ) -> str:
        """
        Create a new Jira issue.

        Args:
            issue_type: Type of issue - "bug", "story", "task", "spike"
            summary: Issue title/summary
            story_points: Story points (optional, for stories)

        Returns:
            The created issue key and details.
        """
        args = ["create-issue", issue_type, summary]
        if story_points > 0:
            args.extend(["--story-points", str(story_points)])

        success, output = await run_rh_issue(args, timeout=60)

        if not success:
            return f"❌ Failed to create issue: {output}"

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
                steps = ["1. Review requirements", "2. Create feature branch", "3. Start implementation"]
            elif status == "In Progress":
                steps = ["1. Continue implementation", "2. Run local tests", "3. Create MR when ready"]
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

    return len([m for m in dir() if not m.startswith('_')])  # Approximate count
