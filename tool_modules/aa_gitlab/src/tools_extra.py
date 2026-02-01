"""AA GitLab MCP Server - GitLab operations via glab CLI (extra tools).

Authentication: glab auth login or GITLAB_TOKEN environment variable.

Supports:
- Running from project directories (auto-resolved from config.json)
- Full GitLab URLs (parsed to extract project and MR ID)
- Direct project paths with --repo flag
"""

import re
from pathlib import Path

from fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization


from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import get_gitlab_host, get_section_config, run_cmd

# Use shared implementation from utils
GITLAB_HOST = get_gitlab_host()


def _load_repo_config() -> dict[str, dict]:
    """Load repository configuration from config.json."""
    return get_section_config("repositories", {})


def _resolve_gitlab_to_local(gitlab_path: str) -> str | None:
    """
    Resolve a GitLab project path to a local directory.

    Args:
        gitlab_path: e.g., "automation-analytics/automation-analytics-backend" or just "app-interface"

    Returns:
        Local directory path or None if not found.
    """
    repos = _load_repo_config()
    for repo_name, repo_config in repos.items():
        # Match by full gitlab path OR by repo name (short name)
        if repo_config.get("gitlab") == gitlab_path or repo_name == gitlab_path:
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

    # Use unified run_cmd with GITLAB_HOST env var
    return await run_cmd(cmd, cwd=run_cwd, env={"GITLAB_HOST": GITLAB_HOST}, timeout=timeout)


# ==================== MERGE REQUESTS ====================


# ==================== TOOL IMPLEMENTATIONS ====================


async def _gitlab_ci_cancel_impl(project: str, pipeline_id: int) -> str:
    """Implementation of gitlab_ci_cancel tool."""
    args = ["ci", "cancel"]
    if pipeline_id > 0:
        args.append(str(pipeline_id))
    success, output = await run_glab(args, repo=project)
    return "✅ Pipeline Cancelled" if success else f"❌ Failed: {output}"


async def _gitlab_ci_retry_impl(project: str, job_id: int) -> str:
    """Implementation of gitlab_ci_retry tool."""
    success, output = await run_glab(["ci", "retry", str(job_id)], repo=project)
    return f"✅ Job {job_id} Retried" if success else f"❌ Failed: {output}"


async def _gitlab_ci_run_impl(project: str, branch: str, variables: str) -> str:
    """Implementation of gitlab_ci_run tool."""
    args = ["ci", "run"]
    if branch:
        args.extend(["--branch", branch])
    if variables:
        for var in variables.split(","):
            args.extend(["--variables", var.strip()])
    success, output = await run_glab(args, repo=project)
    return f"✅ Pipeline Started\n\n{output}" if success else f"❌ Failed: {output}"


async def _gitlab_issue_create_impl(project: str, title: str, description: str, labels: str, assignee: str) -> str:
    """Implementation of gitlab_issue_create tool."""
    args = ["issue", "create", "--title", title, "--yes"]
    if description:
        args.extend(["--description", description])
    if labels:
        args.extend(["--label", labels])
    if assignee:
        args.extend(["--assignee", assignee])
    success, output = await run_glab(args, repo=project)
    return f"✅ Issue Created\n\n{output}" if success else f"❌ Failed: {output}"


async def _gitlab_issue_list_impl(project: str, state: str, label: str, assignee: str) -> str:
    """Implementation of gitlab_issue_list tool."""
    args = ["issue", "list"]
    if state == "closed":
        args.append("--closed")
    elif state == "all":
        args.append("--all")
    elif state == "opened":
        args.append("--opened")

    if label:
        args.extend(["--label", label])
    if assignee:
        args.extend(["--assignee", assignee])
    success, output = await run_glab(args, repo=project)
    return output if success else f"❌ Failed: {output}"


async def _gitlab_issue_view_impl(project: str, issue_id: int) -> str:
    """Implementation of gitlab_issue_view tool."""
    success, output = await run_glab(["issue", "view", str(issue_id), "--web=false"], repo=project)
    return output if success else f"❌ Failed: {output}"


async def _gitlab_label_list_impl(project: str) -> str:
    """Implementation of gitlab_label_list tool."""
    success, output = await run_glab(["label", "list"], repo=project)
    return output if success else f"❌ Failed: {output}"


async def _gitlab_mr_merge_impl(
    project: str,
    mr_id: int,
    squash: bool,
    remove_source_branch: bool,
    when_pipeline_succeeds: bool,
) -> str:
    """Implementation of gitlab_mr_merge tool."""
    args = ["mr", "merge", str(mr_id), "--yes"]
    if squash:
        args.append("--squash")
    if remove_source_branch:
        args.append("--remove-source-branch")
    if when_pipeline_succeeds:
        args.append("--when-pipeline-succeeds")
    success, output = await run_glab(args, repo=project)
    return f"✅ MR !{mr_id} Merged\n\n{output}" if success else f"❌ Failed: {output}"


async def _gitlab_mr_rebase_impl(project: str, mr_id: int) -> str:
    """Implementation of gitlab_mr_rebase tool."""
    success, output = await run_glab(["mr", "rebase", str(mr_id)], repo=project)
    return f"✅ MR !{mr_id} Rebased" if success else f"❌ Failed: {output}"


async def _gitlab_mr_reopen_impl(project: str, mr_id: int) -> str:
    """Implementation of gitlab_mr_reopen tool."""
    success, output = await run_glab(["mr", "reopen", str(mr_id)], repo=project)
    return f"✅ MR !{mr_id} Reopened" if success else f"❌ Failed: {output}"


async def _gitlab_mr_revoke_impl(project: str, mr_id: int) -> str:
    """Implementation of gitlab_mr_revoke tool."""
    success, output = await run_glab(["mr", "revoke", str(mr_id)], repo=project)
    return f"✅ Approval revoked from !{mr_id}" if success else f"❌ Failed: {output}"


async def _gitlab_release_list_impl(project: str) -> str:
    """Implementation of gitlab_release_list tool."""
    success, output = await run_glab(["release", "list"], repo=project)
    return output if success else f"❌ Failed: {output}"


async def _gitlab_repo_view_impl(project: str) -> str:
    """Implementation of gitlab_repo_view tool."""
    success, output = await run_glab(["repo", "view", "--web=false"], repo=project)
    return output if success else f"❌ Failed: {output}"


async def _gitlab_user_info_impl() -> str:
    """Implementation of gitlab_user_info tool."""
    success, output = await run_glab(["auth", "status"])
    return output if success else f"❌ Failed: {output}"


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    # REMOVED: gitlab_view_url - low value, just returns URL content

    # ==================== TOOLS NOT USED IN SKILLS ====================
    @auto_heal()
    @registry.tool()
    async def gitlab_ci_cancel(project: str, pipeline_id: int = 0) -> str:
        """Cancel a running pipeline."""
        return await _gitlab_ci_cancel_impl(project, pipeline_id)

    @auto_heal()
    @registry.tool()
    async def gitlab_ci_retry(project: str, job_id: int) -> str:
        """Retry a failed CI/CD job."""
        return await _gitlab_ci_retry_impl(project, job_id)

    @auto_heal()
    @registry.tool()
    async def gitlab_ci_run(project: str, branch: str = "", variables: str = "") -> str:
        """Trigger a new pipeline run."""
        return await _gitlab_ci_run_impl(project, branch, variables)

    @auto_heal()
    @registry.tool()
    async def gitlab_issue_create(
        project: str,
        title: str,
        description: str = "",
        labels: str = "",
        assignee: str = "",
    ) -> str:
        """Create a new GitLab issue."""
        return await _gitlab_issue_create_impl(project, title, description, labels, assignee)

    @auto_heal()
    @registry.tool()
    async def gitlab_issue_list(project: str, state: str = "opened", label: str = "", assignee: str = "") -> str:
        """List GitLab issues for a project.

        Args:
            project: GitLab project path
            state: Filter by state - 'opened', 'closed', or 'all'
            label: Filter by label name
            assignee: Filter by assignee username
        """
        return await _gitlab_issue_list_impl(project, state, label, assignee)

    @auto_heal()
    @registry.tool()
    async def gitlab_issue_view(project: str, issue_id: int) -> str:
        """View a GitLab issue."""
        return await _gitlab_issue_view_impl(project, issue_id)

    @auto_heal()
    @registry.tool()
    async def gitlab_label_list(project: str) -> str:
        """List all labels in a project."""
        return await _gitlab_label_list_impl(project)

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_merge(
        project: str,
        mr_id: int,
        squash: bool = False,
        remove_source_branch: bool = True,
        when_pipeline_succeeds: bool = True,
    ) -> str:
        """Merge a merge request."""
        return await _gitlab_mr_merge_impl(project, mr_id, squash, remove_source_branch, when_pipeline_succeeds)

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_rebase(project: str, mr_id: int) -> str:
        """Rebase a merge request's source branch against target."""
        return await _gitlab_mr_rebase_impl(project, mr_id)

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_reopen(project: str, mr_id: int) -> str:
        """Reopen a closed merge request."""
        return await _gitlab_mr_reopen_impl(project, mr_id)

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_revoke(project: str, mr_id: int) -> str:
        """Revoke approval from a merge request."""
        return await _gitlab_mr_revoke_impl(project, mr_id)

    @auto_heal()
    @registry.tool()
    async def gitlab_release_list(project: str) -> str:
        """List releases for a project."""
        return await _gitlab_release_list_impl(project)

    @auto_heal()
    @registry.tool()
    async def gitlab_repo_view(project: str) -> str:
        """View repository/project information."""
        return await _gitlab_repo_view_impl(project)

    @auto_heal()
    @registry.tool()
    async def gitlab_user_info() -> str:
        """Get current authenticated GitLab user information."""
        return await _gitlab_user_info_impl()

    return registry.count
