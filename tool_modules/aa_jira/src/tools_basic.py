"""AA Jira MCP Server - Jira issue tracking operations.

Uses the rh-issue CLI for Red Hat Jira operations.
Authentication: JIRA_JPAT environment variable.
"""

import logging
from typing import cast

from mcp.server.fastmcp import FastMCP

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import get_project_root, load_config, run_cmd_shell

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

    @auto_heal()

    # ==================== TOOLS USED IN SKILLS ====================

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

    @auto_heal()
    @registry.tool()
    async def jira_create_issue(
        issue_type: str,
        summary: str,
        description: str = "",
        user_story: str = "",
        acceptance_criteria: str = "",
        supporting_documentation: str = "",
        definition_of_done: str = "",
        story_points: int | None = None,
        labels: str = "",
        components: str = "",
        project: str = "AAP",
        convert_markdown: bool = True,
    ) -> str:
        """
        Create a new Jira issue using the rh-issue CLI with --input-file.

        Accepts Markdown in all text fields and auto-converts to Jira wiki markup.
        Issue type is case-insensitive (Story, story, STORY all work).

        The CLI requires these fields for stories: User Story, Acceptance Criteria,
        Supporting Documentation, Definition of Done. If not provided, sensible
        defaults are used to avoid interactive prompts.

        Args:
            issue_type: Type of issue - "bug", "story", "task", "epic" (case insensitive)
            summary: Issue title/summary
            description: Issue description (accepts Markdown)
            user_story: User story text (accepts Markdown)
            acceptance_criteria: Acceptance criteria (accepts Markdown)
            supporting_documentation: Supporting documentation (accepts Markdown)
            definition_of_done: Definition of done (accepts Markdown)
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
                description="## Overview\\n\\nSpeed up test suite with parallel execution.",
                user_story="As a developer, I want faster test runs.",
                acceptance_criteria="- Tests run in parallel\\n- No flaky tests",
                labels="testing,performance"
            )
        """
        import re
        import sys
        import tempfile
        from pathlib import Path

        import yaml

        # Normalize issue type to lowercase
        valid_types = {"bug", "story", "task", "epic", "spike", "subtask"}
        issue_type_normalized = issue_type.lower().strip()

        if issue_type_normalized not in valid_types:
            types_str = ", ".join(sorted(valid_types))
            return f"❌ Invalid issue type: '{issue_type}'. Valid types: {types_str}"

        # Import markdown converter
        markdown_to_jira = None
        if convert_markdown:
            try:
                scripts_path = str(get_project_root() / "scripts")
                if scripts_path not in sys.path:
                    sys.path.insert(0, scripts_path)
                from common.jira_utils import markdown_to_jira as converter

                markdown_to_jira = converter
            except ImportError:
                # Fallback: basic conversion
                def markdown_to_jira(text: str) -> str:
                    return text.replace("**", "*").replace("`", "{{")

        def convert(text: str) -> str:
            """Convert markdown if enabled and converter available."""
            if convert_markdown and markdown_to_jira and text:
                return markdown_to_jira(text)
            return text

        # Build the YAML content with Title Case field names (required by CLI)
        yaml_data: dict = {}

        if description:
            yaml_data["Description"] = convert(description)

        # For stories, provide defaults if required fields are empty
        if issue_type_normalized == "story":
            yaml_data["User Story"] = convert(user_story) if user_story else f"As a user, I want {summary.lower()}."
            yaml_data["Acceptance Criteria"] = (
                convert(acceptance_criteria) if acceptance_criteria else "* Functionality works as described"
            )
            yaml_data["Supporting Documentation"] = (
                convert(supporting_documentation) if supporting_documentation else "N/A"
            )
            yaml_data["Definition of Done"] = (
                convert(definition_of_done) if definition_of_done else "* Code reviewed and merged\n* Tests pass"
            )
        else:
            # For non-stories, only include if provided
            if user_story:
                yaml_data["User Story"] = convert(user_story)
            if acceptance_criteria:
                yaml_data["Acceptance Criteria"] = convert(acceptance_criteria)
            if supporting_documentation:
                yaml_data["Supporting Documentation"] = convert(supporting_documentation)
            if definition_of_done:
                yaml_data["Definition of Done"] = convert(definition_of_done)

        # Labels as list
        if labels:
            label_list = [lbl.strip() for lbl in labels.split(",") if lbl.strip()]
            if label_list:
                yaml_data["Labels"] = label_list

        # Components as list
        if components:
            comp_list = [c.strip() for c in components.split(",") if c.strip()]
            if comp_list:
                yaml_data["Components"] = comp_list

        # Write YAML to temp file
        yaml_content = yaml.dump(yaml_data, default_flow_style=False, allow_unicode=True, sort_keys=False)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            input_file = f.name

        try:
            # Build CLI args
            args = ["create-issue", issue_type_normalized, summary, "--input-file", input_file, "--no-ai"]

            if story_points is not None and story_points > 0:
                args.extend(["--story-points", str(story_points)])

            success, output = await run_rh_issue(args, timeout=60)
        finally:
            # Clean up temp file
            Path(input_file).unlink(missing_ok=True)

        if not success:
            return f"❌ Failed to create issue: {output}"

        # Extract issue key from output
        issue_key_match = re.search(r"([A-Z]+-\d+)", output)
        if issue_key_match:
            issue_key = issue_key_match.group(1)
            url = f"{_get_jira_url()}/browse/{issue_key}"
            return f"✅ Issue created: [{issue_key}]({url})\n\n{output}"

        return f"✅ Issue created\n\n{output}"

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
    async def jira_set_epic(issue_key: str, epic_key: str) -> str:
        """
        Link a Jira issue to an Epic.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)
            epic_key: The Epic issue key (e.g., AAP-10000)

        Returns:
            Confirmation of the epic link.
        """
        success, output = await run_rh_issue(["set-story-epic", issue_key, epic_key])

        if not success:
            return f"❌ Failed to set epic: {output}"

        return f"✅ {issue_key} linked to Epic **{epic_key}**\n\n{output}"

    @auto_heal()
    @registry.tool()
    async def jira_set_priority(issue_key: str, priority: str) -> str:
        """
        Set the priority of a Jira issue.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)
            priority: Priority level (e.g., "Blocker", "Critical", "Major", "Normal", "Minor")

        Returns:
            Confirmation of the priority change.
        """
        success, output = await run_rh_issue(["set-priority", issue_key, priority])

        if not success:
            return f"❌ Failed to set priority: {output}"

        return f"✅ Priority for {issue_key} set to **{priority}**\n\n{output}"

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
    async def jira_set_story_points(issue_key: str, points: int) -> str:
        """
        Set the story points for a Jira issue.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)
            points: Story points value (e.g., 1, 2, 3, 5, 8, 13)

        Returns:
            Confirmation of the story points update.
        """
        success, output = await run_rh_issue(["set-story-points", issue_key, str(points)])

        if not success:
            return f"❌ Failed to set story points: {output}"

        return f"✅ Story points for {issue_key} set to **{points}**\n\n{output}"

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
