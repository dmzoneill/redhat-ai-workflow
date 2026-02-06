"""AA Jira MCP Server - Jira issue tracking operations (extra tools).

Uses the rh-issue CLI for Red Hat Jira operations.
Authentication: JIRA_JPAT environment variable.
"""

import json
import logging
import os
from typing import cast

import httpx
from fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization


from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import load_config, run_cmd

# Setup project path for server imports


def _get_jira_url() -> str:
    """Get Jira URL from config."""
    config = load_config()
    return cast(dict, config.get("jira", {})).get("url", "https://issues.redhat.com")


def _get_jira_auth() -> tuple[str, str]:
    """Get Jira base URL and Bearer token for direct REST API calls.

    Returns:
        Tuple of (base_url, token). Token may be empty if not configured.
    """
    base_url = os.environ.get("JIRA_URL", "") or _get_jira_url()
    token = os.environ.get("JIRA_JPAT", "") or os.environ.get("JIRA_TOKEN", "")
    return base_url, token


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


async def _jira_add_flag_impl(issue_key: str) -> str:
    """Implementation of jira_add_flag tool."""
    success, output = await run_rh_issue(["add-flag", issue_key])
    if not success:
        return f"❌ Failed to add flag: {output}"
    return f"🚩 Flag added to {issue_key}\n\n{output}"


async def _jira_add_to_sprint_impl(issue_key: str, sprint_id: str) -> str:
    """Implementation of jira_add_to_sprint tool."""
    args = ["add-to-sprint", issue_key]
    if sprint_id:
        args.extend(["--sprint", sprint_id])
    success, output = await run_rh_issue(args)
    if not success:
        return f"❌ Failed to add to sprint: {output}"
    return f"✅ {issue_key} added to sprint\n\n{output}"


async def _jira_ai_helper_impl(issue_key: str, action: str) -> str:
    """Implementation of jira_ai_helper tool."""
    import re

    success, output = await run_rh_issue(["view-issue", issue_key])
    if not success:
        return f"❌ Failed to get issue: {output}"

    issue = {}
    for line in output.split("\n"):
        match = re.match(r"^([a-z][a-z_ /]+?)\s*:\s*(.*)$", line.strip(), re.IGNORECASE)
        if match:
            key = match.group(1).strip().lower().replace(" ", "_").replace("/", "_")
            value = match.group(2).strip()
            issue[key] = value

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


async def _jira_block_impl(issue_key: str, reason: str) -> str:
    """Implementation of jira_block tool.

    Marks an issue as blocked with a reason. This sets the blocked flag
    and blocked reason field in Jira.
    """
    args = ["block", issue_key, reason]
    success, output = await run_rh_issue(args)
    if not success:
        return f"❌ Failed to block: {output}"
    return f"🚧 {issue_key} marked as blocked\n**Reason:** {reason}\n\n{output}"


async def _jira_lint_impl(issue_key: str) -> str:
    """Implementation of jira_lint tool."""
    success, output = await run_rh_issue(["lint", issue_key], timeout=60)
    return output


async def _jira_remove_flag_impl(issue_key: str) -> str:
    """Implementation of jira_remove_flag tool."""
    success, output = await run_rh_issue(["remove-flag", issue_key])
    if not success:
        return f"❌ Failed to remove flag: {output}"
    return f"✅ Flag removed from {issue_key}\n\n{output}"


async def _jira_remove_sprint_impl(issue_key: str) -> str:
    """Implementation of jira_remove_sprint tool."""
    success, output = await run_rh_issue(["remove-sprint", issue_key])
    if not success:
        return f"❌ Failed to remove from sprint: {output}"
    return f"✅ {issue_key} removed from sprint\n\n{output}"


async def _jira_set_summary_impl(issue_key: str, summary: str) -> str:
    """Implementation of jira_set_summary tool."""
    success, output = await run_rh_issue(["set-summary", issue_key, summary])
    if not success:
        return f"❌ Failed to set summary: {output}"
    return f"✅ Summary for {issue_key} updated to: **{summary}**\n\n{output}"


async def _jira_show_template_impl(issue_type: str) -> str:
    """Implementation of jira_show_template tool."""
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
  - technical-debt

Components:
  - Automation Analytics

"Story Points": 2
""",
        "epic": """# YAML Template for Epic
# Save this to a file and use with: rh-issue create-issue epic "Summary" --input-file epic.yaml

Summary: "Modernize Automation Analytics UI"

Description: |
  h2. Epic Overview

  Complete overhaul of the Automation Analytics UI to use modern design patterns.

  h3. Goals

  * Improve user experience
  * Reduce page load times
  * Modernize visual design

  h3. Success Criteria

  * 50% faster load times
  * 90% positive user feedback
  * All WCAG 2.1 AA requirements met

Labels:
  - epic
  - ui-ux

Components:
  - Automation Analytics

"Start Date": 2024-Q1
"Target End": 2024-Q2
""",
    }

    if issue_type not in templates:
        return f"""❌ Unknown issue type: {issue_type}

Available types:
  - story
  - bug
  - task
  - epic

Usage: jira_show_template("story")
"""

    return templates[issue_type]


async def _jira_unassign_impl(issue_key: str) -> str:
    """Implementation of jira_unassign tool."""
    success, output = await run_rh_issue(["unassign", issue_key])
    if not success:
        return f"❌ Failed to unassign: {output}"
    return f"✅ {issue_key} unassigned\n\n{output}"


async def _jira_unblock_impl(issue_key: str) -> str:
    """Implementation of jira_unblock tool.

    Clears the blocked flag and blocked reason field in Jira.
    """
    success, output = await run_rh_issue(["unblock", issue_key])
    if not success:
        return f"❌ Failed to unblock: {output}"
    return f"✅ {issue_key} unblocked\n\n{output}"


async def _jira_get_transitions_impl(issue_key: str) -> str:
    """Implementation of jira_get_transitions tool.

    Calls GET /rest/api/2/issue/{issue_key}/transitions to retrieve
    the available workflow transitions for the issue.
    """
    base_url, token = _get_jira_auth()
    if not token:
        return (
            "❌ Jira authentication not configured.\n\n"
            "Ensure JIRA_JPAT is set in your ~/.bashrc:\n"
            f"  export JIRA_JPAT='your-token'\n"
            f"  export JIRA_URL='{base_url}'"
        )

    url = f"{base_url}/rest/api/2/issue/{issue_key}/transitions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers)

    if resp.status_code == 401:
        return "❌ Jira authentication failed (401 Unauthorized).\n\n" "Check that your JIRA_JPAT token is valid."
    if resp.status_code == 404:
        return f"❌ Issue {issue_key} not found."
    if resp.status_code != 200:
        return f"❌ Failed to get transitions (HTTP {resp.status_code}): {resp.text}"

    data = resp.json()
    transitions = data.get("transitions", [])

    if not transitions:
        return f"No transitions available for {issue_key}."

    lines = [f"Available transitions for {issue_key}:\n"]
    for t in transitions:
        tid = t.get("id", "")
        name = t.get("name", "")
        to_status = t.get("to", {}).get("name", "")
        lines.append(f"  - {name} (id: {tid}) -> {to_status}")

    return "\n".join(lines)


async def _jira_update_issue_impl(
    issue_key: str,
    fields: str = "",
    summary: str = "",
    description: str = "",
    labels: str = "",
    components: str = "",
) -> str:
    """Implementation of jira_update_issue tool.

    Calls PUT /rest/api/2/issue/{issue_key} to update issue fields.
    Builds the fields payload from individual shortcut parameters
    and/or a raw JSON fields string.
    """
    base_url, token = _get_jira_auth()
    if not token:
        return (
            "❌ Jira authentication not configured.\n\n"
            "Ensure JIRA_JPAT is set in your ~/.bashrc:\n"
            f"  export JIRA_JPAT='your-token'\n"
            f"  export JIRA_URL='{base_url}'"
        )

    # Start with user-supplied raw fields JSON
    update_fields: dict = {}
    if fields:
        try:
            update_fields = json.loads(fields)
        except json.JSONDecodeError as exc:
            return f"❌ Invalid JSON in 'fields' parameter: {exc}"

    # Apply shortcut parameters (these override fields if both provided)
    if summary:
        update_fields["summary"] = summary
    if description:
        update_fields["description"] = description
    if labels:
        label_list = [lbl.strip() for lbl in labels.split(",") if lbl.strip()]
        update_fields["labels"] = label_list
    if components:
        comp_list = [{"name": c.strip()} for c in components.split(",") if c.strip()]
        update_fields["components"] = comp_list

    if not update_fields:
        return "❌ No fields to update. Provide at least one of: fields, summary, description, labels, components."

    url = f"{base_url}/rest/api/2/issue/{issue_key}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"fields": update_fields}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.put(url, headers=headers, json=payload)

    if resp.status_code == 401:
        return "❌ Jira authentication failed (401 Unauthorized).\n\n" "Check that your JIRA_JPAT token is valid."
    if resp.status_code == 404:
        return f"❌ Issue {issue_key} not found."
    if resp.status_code == 400:
        # Jira returns details about invalid fields
        try:
            error_data = resp.json()
            errors = error_data.get("errors", {})
            messages = error_data.get("errorMessages", [])
            details = []
            for field_name, msg in errors.items():
                details.append(f"  - {field_name}: {msg}")
            for msg in messages:
                details.append(f"  - {msg}")
            return f"❌ Failed to update {issue_key} (invalid fields):\n" + "\n".join(details)
        except Exception:
            return f"❌ Failed to update {issue_key} (HTTP 400): {resp.text}"
    if resp.status_code not in (200, 204):
        return f"❌ Failed to update {issue_key} (HTTP {resp.status_code}): {resp.text}"

    updated_keys = ", ".join(update_fields.keys())
    return f"✅ {issue_key} updated successfully.\n\n**Updated fields:** {updated_keys}"


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
        return await _jira_add_flag_impl(issue_key)

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
        return await _jira_add_to_sprint_impl(issue_key, sprint_id)

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
        return await _jira_ai_helper_impl(issue_key, action)

    @auto_heal()
    @registry.tool()
    async def jira_block(issue_key: str, reason: str) -> str:
        """
        Mark a Jira issue as blocked with a reason.

        This sets the blocked flag and blocked reason field in Jira.
        Use this when work cannot proceed due to missing information,
        external dependencies, or other blockers.

        Args:
            issue_key: The issue to mark as blocked (e.g., AAP-12345)
            reason: The reason for blocking (e.g., "Waiting for API spec from team X")

        Returns:
            Confirmation that the issue was marked as blocked.
        """
        return await _jira_block_impl(issue_key, reason)

    @auto_heal()
    @registry.tool()
    async def jira_lint(issue_key: str) -> str:
        """
        Run quality checks on a Jira issue (check description, acceptance criteria, etc.).

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)

        Returns:
            Lint results and suggestions.
        """
        return await _jira_lint_impl(issue_key)

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
        return await _jira_remove_flag_impl(issue_key)

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
        return await _jira_remove_sprint_impl(issue_key)

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
        return await _jira_set_summary_impl(issue_key, summary)

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
        return await _jira_show_template_impl(issue_type)

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
        return await _jira_unassign_impl(issue_key)

    @auto_heal()
    @registry.tool()
    async def jira_unblock(issue_key: str) -> str:
        """
        Remove the blocked status from a Jira issue.

        Clears the blocked flag and blocked reason field in Jira.
        Use this when a blocker has been resolved and work can continue.

        Args:
            issue_key: The issue to unblock (e.g., AAP-12345)

        Returns:
            Confirmation that the issue was unblocked.
        """
        return await _jira_unblock_impl(issue_key)

    @auto_heal()
    @registry.tool()
    async def jira_get_transitions(issue_key: str) -> str:
        """
        Get available transitions for a Jira issue.

        Returns the list of valid status transitions that can be applied
        to the issue in its current state. Use this to discover which
        statuses you can transition to before calling jira_transition.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)

        Returns:
            List of available transitions with their IDs and names.
        """
        return await _jira_get_transitions_impl(issue_key)

    @auto_heal()
    @registry.tool()
    async def jira_update_issue(
        issue_key: str,
        fields: str = "",
        summary: str = "",
        description: str = "",
        labels: str = "",
        components: str = "",
    ) -> str:
        """
        Update fields on a Jira issue.

        Supports both a raw JSON fields string and convenient shortcut
        parameters. Shortcut parameters override the corresponding key
        in the fields JSON when both are provided.

        Args:
            issue_key: The Jira issue key (e.g., AAP-12345)
            fields: JSON string of fields to update (e.g., '{"priority": {"name": "High"}}')
            summary: New summary (shortcut, overrides fields.summary)
            description: New description (shortcut, overrides fields.description)
            labels: Comma-separated labels to set (e.g., "bug,urgent")
            components: Comma-separated components to set (e.g., "Automation Analytics")

        Returns:
            Confirmation of the update.
        """
        return await _jira_update_issue_impl(issue_key, fields, summary, description, labels, components)

    return registry.count
