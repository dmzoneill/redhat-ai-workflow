"""AA GitLab MCP Server - GitLab operations via glab CLI.

Authentication: glab auth login or GITLAB_TOKEN environment variable.

Supports:
- Running from project directories (auto-resolved from config.json)
- Full GitLab URLs (parsed to extract project and MR ID)
- Direct project paths with --repo flag
"""

import asyncio
import os
import re
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization


from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import get_gitlab_host, get_section_config, truncate_output

# Setup project path for server imports


# Use shared implementation from utils
GITLAB_HOST = get_gitlab_host()


def _load_repo_config() -> dict[str, dict]:
    """Load repository configuration from config.json."""
    return get_section_config("repositories", {})


def _resolve_gitlab_to_local(gitlab_path: str) -> str | None:
    """
    Resolve a GitLab project path to a local directory.

    Args:
        gitlab_path: e.g., "automation-analytics/automation-analytics-backend"

    Returns:
        Local directory path or None if not found.
    """
    repos = _load_repo_config()
    for _repo_name, repo_config in repos.items():
        if repo_config.get("gitlab") == gitlab_path:
            local_path = repo_config.get("path")
            if local_path and Path(local_path).exists():
                return local_path
    return None


def parse_gitlab_url(url_or_id: str) -> tuple[str | None, str | None]:
    """
    Parse a GitLab URL or MR reference to extract project and MR ID.

    Args:
        url_or_id: Full URL, "!123", or just "123"

    Returns:
        (project_path, mr_id) - either can be None

    Examples:
        "https://gitlab.cee.redhat.com/automation-analytics/automation-analytics-backend/-/merge_requests/1449"
        -> ("automation-analytics/automation-analytics-backend", "1449")

        "!1449" -> (None, "1449")
        "1449"  -> (None, "1449")
    """
    # Full URL pattern
    url_match = re.match(r"https?://[^/]+/(.+?)/-/merge_requests/(\d+)", url_or_id)
    if url_match:
        return url_match.group(1), url_match.group(2)

    # Issue URL pattern
    issue_match = re.match(r"https?://[^/]+/(.+?)/-/issues/(\d+)", url_or_id)
    if issue_match:
        return issue_match.group(1), issue_match.group(2)

    # Just an ID (with or without !)
    clean_id = url_or_id.lstrip("!").strip()
    if clean_id.isdigit():
        return None, clean_id

    return None, None


async def run_glab(
    args: list[str], repo: str | None = None, cwd: str | None = None, timeout: int = 60
) -> tuple[bool, str]:
    """
    Run glab command and return (success, output).

    Args:
        args: glab command arguments
        repo: GitLab project path (used with --repo if no cwd)
        cwd: Local directory to run from (preferred over --repo)
        timeout: Command timeout in seconds
    """
    cmd = ["glab"] + args

    # If we have a local directory, run from there (glab uses git remote)
    # Otherwise, use --repo flag
    run_cwd = None
    if cwd and Path(cwd).exists():
        run_cwd = cwd
    elif repo:
        # Try to resolve to local directory first
        local_dir = _resolve_gitlab_to_local(repo)
        if local_dir:
            run_cwd = local_dir
        else:
            cmd.extend(["--repo", repo])

    env = os.environ.copy()
    env["GITLAB_HOST"] = GITLAB_HOST

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=run_cwd,
        )
        output = result.stdout
        if result.returncode != 0:
            output = result.stderr or result.stdout or "Command failed"
            return False, output
        return True, output
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return False, "glab CLI not found. Install with: brew install glab"
    except Exception as e:
        return False, str(e)


# ==================== MERGE REQUESTS ====================


# ==================== TOOL IMPLEMENTATIONS ====================


async def _gitlab_ci_lint_impl(project: str) -> str:
    """Implementation of gitlab_ci_lint tool."""
    success, output = await run_glab(["ci", "lint"], repo=project)
    return f"✅ CI Config Valid\n\n{output}" if success else f"❌ Lint failed:\n\n{output}"


async def _gitlab_ci_list_impl(project: str, status: str = "", page: int = 1) -> str:
    """Implementation of gitlab_ci_list tool."""
    args = ["ci", "list", "--page", str(page)]
    if status:
        args.extend(["--status", status])
    success, output = await run_glab(args, repo=project)
    return output if success else f"❌ Failed: {output}"


async def _gitlab_ci_status_impl(project: str, branch: str = "") -> str:
    """Implementation of gitlab_ci_status tool."""
    args = ["ci", "status"]
    if branch:
        args.extend(["--branch", branch])
    success, output = await run_glab(args, repo=project)
    return output if success else f"❌ Failed: {output}"


async def _gitlab_ci_trace_impl(project: str, job_id: int) -> str:
    """Implementation of gitlab_ci_trace tool."""
    success, output = await run_glab(["ci", "trace", str(job_id)], repo=project, timeout=120)
    if not success:
        return f"❌ Failed: {output}"
    return f"## Job {job_id} Log\n\n```\n{truncate_output(output, max_length=15000, mode='tail')}\n```"


async def _gitlab_ci_view_impl(project: str, branch: str = "") -> str:
    """Implementation of gitlab_ci_view tool."""
    args = ["ci", "view"]
    if branch:
        args.append(branch)
    success, output = await run_glab(args, repo=project)
    return output if success else f"❌ Failed: {output}"


async def _gitlab_list_mrs_impl(
    project: str,
    state: str = "opened",
    author: str = "",
) -> str:
    """Implementation of gitlab_list_mrs tool."""
    # glab uses flags instead of --state: --closed, --merged, --all
    args = ["mr", "list"]
    if state == "closed":
        args.append("--closed")
    elif state == "merged":
        args.append("--merged")
    elif state == "all":
        args.append("--all")
    # "opened" is the default, no flag needed

    if author:
        args.extend(["--author", author])
    success, output = await run_glab(args, repo=project)
    if not success:
        return f"❌ Failed: {output}"
    return f"## MRs in {project}\n\n{output}"


async def _gitlab_mr_approve_impl(project: str, mr_id: int) -> str:
    """Implementation of gitlab_mr_approve tool."""
    success, output = await run_glab(["mr", "approve", str(mr_id)], repo=project)
    return f"✅ MR !{mr_id} Approved" if success else f"❌ Failed: {output}"


async def _gitlab_mr_approvers_impl(project: str, mr_id: int) -> str:
    """Implementation of gitlab_mr_approvers tool."""
    success, output = await run_glab(["mr", "approvers", str(mr_id)], repo=project)
    return output if success else f"❌ Failed: {output}"


async def _gitlab_mr_close_impl(project: str, mr_id: int) -> str:
    """Implementation of gitlab_mr_close tool."""
    success, output = await run_glab(["mr", "close", str(mr_id)], repo=project)
    return f"✅ MR !{mr_id} Closed" if success else f"❌ Failed: {output}"


async def _gitlab_mr_comment_impl(project: str, mr_id: int, message: str) -> str:
    """Implementation of gitlab_mr_comment tool."""
    success, output = await run_glab(["mr", "note", str(mr_id), "--message", message], repo=project)
    return f"✅ Comment added to !{mr_id}" if success else f"❌ Failed: {output}"


async def _gitlab_mr_comments_impl(project: str, mr_id: int) -> str:
    """Implementation of gitlab_mr_comments tool."""
    # glab doesn't have a direct comments command, so we use mr view which includes discussions
    success, output = await run_glab(["mr", "view", str(mr_id), "--comments"], repo=project)
    if not success:
        # Fallback to basic view
        success, output = await run_glab(["mr", "view", str(mr_id), "--web=false"], repo=project)
    return f"## Comments on !{mr_id}\n\n{output}" if success else f"❌ Failed: {output}"


async def _gitlab_mr_create_impl(
    project: str,
    title: str = "",
    description: str = "",
    source_branch: str = "",
    target_branch: str = "main",
    draft: bool = False,
    labels: str = "",
    assignee: str = "",
    reviewer: str = "",
) -> str:
    """Implementation of gitlab_mr_create tool."""
    args = ["mr", "create", "--target-branch", target_branch]
    if title:
        args.extend(["--title", title])
    else:
        args.append("--fill")
    if description:
        args.extend(["--description", description])
    if source_branch:
        args.extend(["--source-branch", source_branch])
    if draft:
        args.append("--draft")
    if labels:
        args.extend(["--label", labels])
    if assignee:
        args.extend(["--assignee", assignee])
    if reviewer:
        args.extend(["--reviewer", reviewer])
    args.append("--yes")
    success, output = await run_glab(args, repo=project)
    return f"✅ MR Created\n\n{output}" if success else f"❌ Failed: {output}"


async def _gitlab_mr_diff_impl(project: str, mr_id: int) -> str:
    """Implementation of gitlab_mr_diff tool."""
    success, output = await run_glab(["mr", "diff", str(mr_id)], repo=project, timeout=120)
    if not success:
        return f"❌ Failed: {output}"
    return f"## Diff for !{mr_id}\n\n```diff\n{truncate_output(output, max_length=10000)}\n```"


async def _gitlab_mr_list_impl(
    project: str,
    state: str = "opened",
    author: str = "",
    assignee: str = "",
    reviewer: str = "",
    label: str = "",
) -> str:
    """Implementation of gitlab_mr_list tool."""
    # glab uses flags instead of --state: --closed, --merged, --all
    args = ["mr", "list"]
    if state == "closed":
        args.append("--closed")
    elif state == "merged":
        args.append("--merged")
    elif state == "all":
        args.append("--all")
    # "opened" is the default, no flag needed

    if author:
        args.extend(["--author", author])
    if assignee:
        args.extend(["--assignee", assignee])
    if reviewer:
        args.extend(["--reviewer", reviewer])
    if label:
        args.extend(["--label", label])
    success, output = await run_glab(args, repo=project)
    return output if success else f"❌ Failed: {output}"


async def _gitlab_mr_update_impl(
    project: str,
    mr_id: int,
    title: str = "",
    description: str = "",
    add_label: str = "",
    remove_label: str = "",
    assignee: str = "",
    reviewer: str = "",
    draft: bool | None = None,
) -> str:
    """Implementation of gitlab_mr_update tool."""
    args = ["mr", "update", str(mr_id)]
    if title:
        args.extend(["--title", title])
    if description:
        args.extend(["--description", description])
    if add_label:
        args.extend(["--label", add_label])
    if remove_label:
        args.extend(["--unlabel", remove_label])
    if assignee:
        args.extend(["--assignee", assignee])
    if reviewer:
        args.extend(["--reviewer", reviewer])
    if draft is True:
        args.append("--draft")
    elif draft is False:
        args.append("--ready")
    success, output = await run_glab(args, repo=project)
    return f"✅ MR !{mr_id} Updated\n\n{output}" if success else f"❌ Failed: {output}"


async def _gitlab_mr_view_impl(project: str, mr_id: int) -> str:
    """Implementation of gitlab_mr_view tool."""
    success, output = await run_glab(["mr", "view", str(mr_id), "--web=false"], repo=project)
    return output if success else f"❌ Failed: {output}"


def _register_ci_tools(registry: ToolRegistry) -> None:
    """Register GitLab CI/CD tools."""

    @auto_heal()
    @registry.tool()
    async def gitlab_ci_lint(project: str) -> str:
        """Lint/validate the .gitlab-ci.yml file."""
        return await _gitlab_ci_lint_impl(project)

    @auto_heal()
    @registry.tool()
    async def gitlab_ci_list(project: str, status: str = "", page: int = 1) -> str:
        """List CI/CD pipelines for a project."""
        return await _gitlab_ci_list_impl(project, status, page)

    @auto_heal()
    @registry.tool()
    async def gitlab_ci_status(project: str, branch: str = "") -> str:
        """Get the status of the latest pipeline on a branch."""
        return await _gitlab_ci_status_impl(project, branch)

    @auto_heal()
    @registry.tool()
    async def gitlab_ci_trace(project: str, job_id: int) -> str:
        """Get the log output from a CI/CD job."""
        return await _gitlab_ci_trace_impl(project, job_id)

    @auto_heal()
    @registry.tool()
    async def gitlab_ci_view(project: str, branch: str = "") -> str:
        """View detailed pipeline information with all jobs."""
        return await _gitlab_ci_view_impl(project, branch)


def _register_mr_tools(registry: ToolRegistry) -> None:
    """Register GitLab Merge Request tools."""

    @auto_heal()
    @registry.tool()
    async def gitlab_list_mrs(
        project: str,
        state: str = "opened",
        author: str = "",
    ) -> str:
        """
        List merge requests for a GitLab project (alias for gitlab_mr_list).

        Args:
            project: Project name or path
            state: MR state - 'opened', 'merged', 'closed', or 'all'
            author: Filter by author username

        Returns:
            List of merge requests.
        """
        return await _gitlab_list_mrs_impl(project, state, author)

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_approve(project: str, mr_id: int) -> str:
        """Approve a merge request."""
        return await _gitlab_mr_approve_impl(project, mr_id)

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_approvers(project: str, mr_id: int) -> str:
        """List eligible approvers for a merge request."""
        return await _gitlab_mr_approvers_impl(project, mr_id)

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_close(project: str, mr_id: int) -> str:
        """Close a merge request without merging."""
        return await _gitlab_mr_close_impl(project, mr_id)

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_comment(project: str, mr_id: int, message: str) -> str:
        """Add a comment to a merge request."""
        return await _gitlab_mr_comment_impl(project, mr_id, message)

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_comments(project: str, mr_id: int) -> str:
        """
        Get comments/feedback on a merge request.

        Args:
            project: Project name or path
            mr_id: Merge request IID

        Returns:
            List of comments on the MR.
        """
        return await _gitlab_mr_comments_impl(project, mr_id)

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_create(
        project: str,
        title: str = "",
        description: str = "",
        source_branch: str = "",
        target_branch: str = "main",
        draft: bool = False,
        labels: str = "",
        assignee: str = "",
        reviewer: str = "",
    ) -> str:
        """Create a new merge request."""
        return await _gitlab_mr_create_impl(
            project, title, description, source_branch, target_branch, draft, labels, assignee, reviewer
        )

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_diff(project: str, mr_id: int) -> str:
        """View the diff/changes in a merge request."""
        return await _gitlab_mr_diff_impl(project, mr_id)

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_list(
        project: str,
        state: str = "opened",
        author: str = "",
        assignee: str = "",
        reviewer: str = "",
        label: str = "",
    ) -> str:
        """List merge requests for a GitLab project.

        Args:
            project: GitLab project path
            state: Filter by state - 'opened', 'closed', 'merged', or 'all'
            author: Filter by author username
            assignee: Filter by assignee username
            reviewer: Filter by reviewer username
            label: Filter by label name
        """
        return await _gitlab_mr_list_impl(project, state, author, assignee, reviewer, label)

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_update(
        project: str,
        mr_id: int,
        title: str = "",
        description: str = "",
        add_label: str = "",
        remove_label: str = "",
        assignee: str = "",
        reviewer: str = "",
        draft: bool | None = None,
    ) -> str:
        """Update an existing merge request."""
        return await _gitlab_mr_update_impl(
            project, mr_id, title, description, add_label, remove_label, assignee, reviewer, draft
        )

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_view(project: str, mr_id: int) -> str:
        """View detailed information about a merge request."""
        return await _gitlab_mr_view_impl(project, mr_id)


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    # REMOVED: gitlab_view_url - low value, just returns URL content

    # Register CI tools
    _register_ci_tools(registry)

    # Register MR tools
    _register_mr_tools(registry)

    return registry.count
