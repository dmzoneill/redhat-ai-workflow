"""AA GitLab MCP Server - GitLab operations via glab CLI (extra tools).

Authentication: glab auth login or GITLAB_TOKEN environment variable.

Supports:
- Running from project directories (auto-resolved from config.json)
- Full GitLab URLs (parsed to extract project and MR ID)
- Direct project paths with --repo flag
"""

import urllib.parse

from fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization


from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry

from .common import run_glab

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


async def _gitlab_issue_create_impl(
    project: str, title: str, description: str, labels: str, assignee: str
) -> str:
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


async def _gitlab_issue_list_impl(
    project: str, state: str, label: str, assignee: str
) -> str:
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
    success, output = await run_glab(
        ["issue", "view", str(issue_id), "--web=false"], repo=project
    )
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


async def _gitlab_file_read_impl(project: str, file_path: str, ref: str = "") -> str:
    """Implementation of gitlab_file_read tool."""
    encoded_project = urllib.parse.quote(project, safe="")
    encoded_file_path = urllib.parse.quote(file_path, safe="")

    endpoint = f"projects/{encoded_project}/repository/files/{encoded_file_path}/raw"
    if ref:
        endpoint += f"?ref={urllib.parse.quote(ref, safe='')}"

    success, output = await run_glab(["api", endpoint], repo=project)
    if not success:
        return f"❌ Failed to read file '{file_path}': {output}"
    return output


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
        return await _gitlab_issue_create_impl(
            project, title, description, labels, assignee
        )

    @auto_heal()
    @registry.tool()
    async def gitlab_issue_list(
        project: str, state: str = "opened", label: str = "", assignee: str = ""
    ) -> str:
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
        return await _gitlab_mr_merge_impl(
            project, mr_id, squash, remove_source_branch, when_pipeline_succeeds
        )

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
    async def gitlab_file_read(project: str, file_path: str, ref: str = "") -> str:
        """Read a file from a GitLab repository.

        Args:
            project: GitLab project path (e.g., "automation-analytics/automation-analytics-backend")
            file_path: Path to the file in the repository
            ref: Branch or commit ref (defaults to default branch)

        Returns:
            File contents.
        """
        return await _gitlab_file_read_impl(project, file_path, ref)

    @auto_heal()
    @registry.tool()
    async def gitlab_user_info() -> str:
        """Get current authenticated GitLab user information."""
        return await _gitlab_user_info_impl()

    return registry.count
