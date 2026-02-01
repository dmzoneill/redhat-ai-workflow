"""AA Jira MCP Server - Jira issue tracking operations.

Uses the rh-issue CLI for Red Hat Jira operations.
Authentication: JIRA_JPAT environment variable.
"""

import logging
from typing import cast

from fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization


from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import get_project_root, load_config, run_cmd

# Setup project path for server imports


def _get_jira_url() -> str:
    """Get Jira URL from config."""
    config = load_config()
    return cast(dict, config.get("jira", {})).get("url", "https://issues.redhat.com")


logger = logging.getLogger(__name__)


async def run_rh_issue(args: list[str], timeout: int = 30) -> tuple[bool, str]:
    """Run rh-issue command through user's shell environment.

    Uses unified run_cmd which sources ~/.bashrc for:
    - JIRA_JPAT and other env vars
    - pipenv virtualenv access (needs HOME)
    - User's PATH with ~/bin
    """
    # Use unified run_cmd (sources shell by default)
    success, output = await run_cmd(["rh-issue"] + args, timeout=timeout)

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

    return True, output


# ==================== READ OPERATIONS ====================


# ==================== TOOL IMPLEMENTATIONS ====================


def _get_markdown_converter(convert_markdown: bool):
    """Get markdown to Jira converter function."""
    if not convert_markdown:
        return None

    try:
        import sys

        scripts_path = str(get_project_root() / "scripts")
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)
        from common.jira_utils import markdown_to_jira

        return markdown_to_jira
    except ImportError:
        # Fallback: basic conversion
        def basic_converter(text: str) -> str:
            return text.replace("**", "*").replace("`", "{{")

        return basic_converter


def _build_story_yaml_fields(
    summary: str,
    user_story: str,
    acceptance_criteria: str,
    supporting_documentation: str,
    definition_of_done: str,
    convert_fn,
) -> dict:
    """Build YAML fields specific to story issues with defaults."""
    return {
        "User Story": (convert_fn(user_story) if user_story else f"As a user, I want {summary.lower()}."),
        "Acceptance Criteria": (
            convert_fn(acceptance_criteria) if acceptance_criteria else "* Functionality works as described"
        ),
        "Supporting Documentation": (convert_fn(supporting_documentation) if supporting_documentation else "N/A"),
        "Definition of Done": (
            convert_fn(definition_of_done) if definition_of_done else "* Code reviewed and merged\n* Tests pass"
        ),
    }


def _build_yaml_data_for_jira(
    issue_type_normalized: str,
    summary: str,
    description: str,
    user_story: str,
    acceptance_criteria: str,
    supporting_documentation: str,
    definition_of_done: str,
    labels: str,
    components: str,
    convert_fn,
    problem_description: str = "",
) -> dict:
    """Build complete YAML data structure for Jira issue."""
    yaml_data = {}

    if description:
        yaml_data["Description"] = convert_fn(description)

    # Problem Description - required by AAP project for all issue types
    if problem_description:
        yaml_data["Problem Description"] = convert_fn(problem_description)
    elif description:
        # Fall back to description if problem_description not provided
        yaml_data["Problem Description"] = convert_fn(description)

    # For stories, provide defaults if required fields are empty
    if issue_type_normalized == "story":
        yaml_data.update(
            _build_story_yaml_fields(
                summary,
                user_story,
                acceptance_criteria,
                supporting_documentation,
                definition_of_done,
                convert_fn,
            )
        )
    else:
        # For non-stories, only include if provided
        if user_story:
            yaml_data["User Story"] = convert_fn(user_story)
        if acceptance_criteria:
            yaml_data["Acceptance Criteria"] = convert_fn(acceptance_criteria)
        if supporting_documentation:
            yaml_data["Supporting Documentation"] = convert_fn(supporting_documentation)
        # Definition of Done - required by AAP for all issue types
        if definition_of_done:
            yaml_data["Definition of Done"] = convert_fn(definition_of_done)
        else:
            # Provide default if not specified (AAP requires this field)
            yaml_data["Definition of Done"] = "* Code reviewed and merged\n* Tests pass"

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

    return yaml_data


def _parse_create_issue_result(success: bool, output: str) -> str:
    """Parse the result of jira create-issue command."""
    import re

    if not success:
        return f"❌ Failed to create issue: {output}"

    # Extract issue key from output
    issue_key_match = re.search(r"([A-Z]+-\d+)", output)
    if issue_key_match:
        issue_key = issue_key_match.group(1)
        url = f"{_get_jira_url()}/browse/{issue_key}"
        return f"✅ Issue created: [{issue_key}]({url})\n\n{output}"

    return f"✅ Issue created\n\n{output}"


async def _jira_get_active_sprint_impl(project: str = "AAP") -> dict:
    """
    Get the active sprint for a project.

    Args:
        project: Jira project key (default: AAP)

    Returns:
        Dict with sprint info: {id, name, state, startDate, endDate} or {error: ...}
    """
    import re

    success, output = await run_rh_issue(["get-sprint"], timeout=30)

    if not success:
        return {"error": output}

    # Parse output like:
    # 🏃 Active Sprint: Cloud Analytics Sprint 2026-4
    #    State: active
    #    ID: 81987
    #    Start: 2026-01-22
    #    End: 2026-01-29

    sprint_info = {}

    # Extract sprint name
    name_match = re.search(r"Active Sprint:\s*(.+)", output)
    if name_match:
        sprint_info["name"] = name_match.group(1).strip()

    # Extract ID
    id_match = re.search(r"ID:\s*(\d+)", output)
    if id_match:
        sprint_info["id"] = int(id_match.group(1))

    # Extract state
    state_match = re.search(r"State:\s*(\w+)", output)
    if state_match:
        sprint_info["state"] = state_match.group(1)

    # Extract dates
    start_match = re.search(r"Start:\s*([\d-]+)", output)
    if start_match:
        sprint_info["startDate"] = start_match.group(1)

    end_match = re.search(r"End:\s*([\d-]+)", output)
    if end_match:
        sprint_info["endDate"] = end_match.group(1)

    if not sprint_info.get("id"):
        return {"error": f"Could not parse sprint info from: {output}"}

    return sprint_info


async def _jira_get_sprint_issues_impl(sprint_id: int, max_results: int = 100) -> list[dict]:
    """
    Get all issues in a sprint.

    Args:
        sprint_id: Sprint ID from Jira
        max_results: Maximum number of issues to return

    Returns:
        List of issue dicts with key, summary, status, priority, storyPoints, assignee, issueType
    """
    import re

    jql = f"sprint = {sprint_id}"
    success, output = await run_rh_issue(["search", jql, "--max-results", str(max_results)], timeout=60)

    if not success:
        logger.error(f"Failed to get sprint issues: {output}")
        return []

    # Parse tabular output
    # Key       | Issuetype | Status      | Priority | Summary | Assignee | Reporter | Sprint | Story Points | Blocked
    issues = []
    lines = output.strip().split("\n")

    # Skip header and separator lines
    data_lines = [line for line in lines if line.strip() and not line.startswith("-") and "|" in line]

    for line in data_lines[1:]:  # Skip header row
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 5:
            key = parts[0]
            if not re.match(r"^[A-Z]+-\d+$", key):
                continue  # Skip non-issue lines

            issue = {
                "key": key,
                "issueType": parts[1] if len(parts) > 1 else "",
                "jiraStatus": parts[2] if len(parts) > 2 else "",
                "priority": parts[3] if len(parts) > 3 else "",
                "summary": parts[4] if len(parts) > 4 else "",
                "assignee": parts[5] if len(parts) > 5 else "",
            }

            # Parse story points (may be "—" for none)
            if len(parts) > 8:
                sp = parts[8].strip()
                if sp and sp != "—" and sp.isdigit():
                    issue["storyPoints"] = int(sp)
                else:
                    issue["storyPoints"] = 0
            else:
                issue["storyPoints"] = 0

            issues.append(issue)

    return issues


# Expose for direct import by sprint_bot
async def jira_get_active_sprint(project: str = "AAP") -> dict:
    """Get the active sprint for a project (for internal use by sprint_bot)."""
    return await _jira_get_active_sprint_impl(project)


async def jira_get_sprint_issues(sprint_id: int, max_results: int = 100) -> list[dict]:
    """Get all issues in a sprint (for internal use by sprint_bot)."""
    return await _jira_get_sprint_issues_impl(sprint_id)


@auto_heal()
async def _jira_add_comment_impl(issue_key: str, comment: str) -> str:
    """
    Add a comment to a Jira issue.

    Args:
        issue_key: The Jira issue key (e.g., AAP-12345)
        comment: The comment text to add

    Returns:
        Confirmation of the comment.
    """
    # rh-issue add-comment requires -t flag for comment text and --no-ai to skip AI improvement
    success, output = await run_rh_issue(["add-comment", issue_key, "-t", comment, "--no-ai"])

    if not success:
        return f"❌ Failed to add comment: {output}"

    return f"✅ Comment added to {issue_key}\n\n{output}"


@auto_heal()
async def _jira_add_link_impl(
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
async def _jira_assign_impl(issue_key: str, assignee: str) -> str:
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
async def _jira_clone_issue_impl(issue_key: str, new_summary: str = "") -> str:
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
async def _jira_create_issue_impl(
    issue_type: str,
    summary: str,
    description: str = "",
    problem_description: str = "",
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

    AAP project requires Problem Description and Definition of Done for all issue types.
    If not provided, description is used as fallback for Problem Description,
    and a sensible default is used for Definition of Done.

    Args:
        issue_type: Type of issue - "bug", "story", "task", "epic" (case insensitive)
        summary: Issue title/summary
        description: Issue description (accepts Markdown)
        problem_description: Problem description - required by AAP (falls back to description)
        user_story: User story text (accepts Markdown)
        acceptance_criteria: Acceptance criteria (accepts Markdown)
        supporting_documentation: Supporting documentation (accepts Markdown)
        definition_of_done: Definition of done (accepts Markdown) - required by AAP
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
    import tempfile
    from pathlib import Path

    import yaml

    # Normalize issue type to lowercase
    valid_types = {"bug", "story", "task", "epic", "spike", "subtask"}
    issue_type_normalized = issue_type.lower().strip()

    if issue_type_normalized not in valid_types:
        types_str = ", ".join(sorted(valid_types))
        return f"❌ Invalid issue type: '{issue_type}'. Valid types: {types_str}"

    # Get markdown converter
    markdown_to_jira = _get_markdown_converter(convert_markdown)

    def convert(text: str) -> str:
        """Convert markdown if enabled and converter available."""
        if convert_markdown and markdown_to_jira and text:
            return markdown_to_jira(text)
        return text

    # Build YAML data
    yaml_data = _build_yaml_data_for_jira(
        issue_type_normalized,
        summary,
        description,
        user_story,
        acceptance_criteria,
        supporting_documentation,
        definition_of_done,
        labels,
        components,
        convert,
        problem_description,
    )

    # Write YAML to temp file
    yaml_content = yaml.dump(yaml_data, default_flow_style=False, allow_unicode=True, sort_keys=False)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        input_file = f.name

    try:
        # Build CLI args
        args = [
            "create-issue",
            issue_type_normalized,
            summary,
            "--input-file",
            input_file,
            "--no-ai",
        ]

        if story_points is not None and story_points > 0:
            args.extend(["--story-points", str(story_points)])

        success, output = await run_rh_issue(args, timeout=60)
    finally:
        # Clean up temp file
        Path(input_file).unlink(missing_ok=True)

    return _parse_create_issue_result(success, output)


@auto_heal()
async def _jira_get_issue_impl(issue_key: str) -> str:
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
async def _jira_list_blocked_impl() -> str:
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
async def _jira_list_issues_impl(
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
    args = ["list-issues", "-p", project]
    if status:
        args.extend(["--status", status])
    if assignee:
        args.extend(["--assignee", assignee])

    success, output = await run_rh_issue(args, timeout=60)

    if not success:
        return f"❌ Failed to list issues: {output}"

    return output


@auto_heal()
async def _jira_my_issues_impl(status: str = "") -> str:
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
async def _jira_search_impl(jql: str, max_results: int = 20) -> str:
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
async def _jira_set_epic_impl(issue_key: str, epic_key: str) -> str:
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
async def _jira_set_priority_impl(issue_key: str, priority: str) -> str:
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
async def _jira_set_status_impl(issue_key: str, status: str) -> str:
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
async def _jira_set_story_points_impl(issue_key: str, points: int) -> str:
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
async def _jira_transition_impl(issue_key: str, status: str) -> str:
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
async def _jira_view_issue_impl(issue_key: str) -> str:
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
async def _jira_view_issue_json_impl(issue_key: str) -> str:
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


def _register_write_tools(registry: ToolRegistry) -> None:
    """Register write tools."""

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
        return await _jira_add_comment_impl(issue_key, comment)

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
        return await _jira_add_link_impl(from_issue, to_issue, link_type)

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
        return await _jira_assign_impl(issue_key, assignee)

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
        return await _jira_clone_issue_impl(issue_key, new_summary)

    @auto_heal()
    @registry.tool()
    async def jira_create_issue(
        issue_type: str,
        summary: str,
        description: str = "",
        problem_description: str = "",
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

        AAP project requires Problem Description and Definition of Done for all issue types.
        If not provided, description is used as fallback for Problem Description,
        and a sensible default is used for Definition of Done.

        Args:
            issue_type: Type of issue - "bug", "story", "task", "epic" (case insensitive)
            summary: Issue title/summary
            description: Issue description (accepts Markdown)
            problem_description: Problem description - required by AAP (falls back to description)
            user_story: User story text (accepts Markdown)
            acceptance_criteria: Acceptance criteria (accepts Markdown)
            supporting_documentation: Supporting documentation (accepts Markdown)
            definition_of_done: Definition of done (accepts Markdown) - required by AAP
            story_points: Story points (optional, for stories)
            labels: Comma-separated labels (e.g., "testing,performance")
            components: Comma-separated components (e.g., "Automation Analytics")
            project: Jira project key (default: AAP)
            convert_markdown: Whether to convert Markdown to Jira markup (default: True)

        Returns:
            The created issue key and details.

        Example:
            jira_create_issue(
                issue_type="task",
                summary="Fix Slack bot issue creation",
                description="The @me jira command fails to create issues.",
                problem_description="create_jira_issue skill missing required AAP fields"
            )
        """
        return await _jira_create_issue_impl(
            issue_type,
            summary,
            description,
            problem_description,
            user_story,
            acceptance_criteria,
            supporting_documentation,
            definition_of_done,
            story_points,
            labels,
            components,
            project,
            convert_markdown,
        )

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
        return await _jira_transition_impl(issue_key, status)


def _register_update_tools(registry: ToolRegistry) -> None:
    """Register update tools."""

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
        return await _jira_set_epic_impl(issue_key, epic_key)

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
        return await _jira_set_priority_impl(issue_key, priority)

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
        return await _jira_set_status_impl(issue_key, status)

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
        return await _jira_set_story_points_impl(issue_key, points)


def _register_read_tools(registry: ToolRegistry) -> None:
    """Register read tools."""

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
        return await _jira_get_issue_impl(issue_key)

    @auto_heal()
    @registry.tool()
    async def jira_list_blocked() -> str:
        """
        List all blocked issues with blocker details.

        Returns:
            List of blocked issues and what's blocking them.
        """
        return await _jira_list_blocked_impl()

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
        return await _jira_list_issues_impl(project, status, assignee)

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
        return await _jira_my_issues_impl(status)

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
        return await _jira_search_impl(jql, max_results)

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
        return await _jira_view_issue_impl(issue_key)

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
        return await _jira_view_issue_json_impl(issue_key)


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    _register_write_tools(registry)
    _register_update_tools(registry)
    _register_read_tools(registry)

    return registry.count
