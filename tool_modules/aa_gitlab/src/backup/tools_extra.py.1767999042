"""Gitlab Extra Tools - Advanced gitlab operations.

For basic operations, see tools_basic.py.

Tools included (~14):
- gitlab_mr_approve, gitlab_mr_revoke, gitlab_mr_merge, ...
"""

import asyncio
import os
import re
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import get_gitlab_host, get_section_config, truncate_output  # noqa: F401

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT  # noqa: F401 - side effect: adds to sys.path

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


def register_tools(server: FastMCP) -> int:
    """Register extra gitlab tools with the MCP server."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_approve(project: str, mr_id: int) -> str:
        """Approve a merge request."""
        success, output = await run_glab(["mr", "approve", str(mr_id)], repo=project)
        return f"✅ MR !{mr_id} Approved" if success else f"❌ Failed: {output}"

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_revoke(project: str, mr_id: int) -> str:
        """Revoke approval from a merge request."""
        success, output = await run_glab(["mr", "revoke", str(mr_id)], repo=project)
        return f"✅ Approval revoked from !{mr_id}" if success else f"❌ Failed: {output}"

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
        args = ["mr", "merge", str(mr_id), "--yes"]
        if squash:
            args.append("--squash")
        if remove_source_branch:
            args.append("--remove-source-branch")
        if when_pipeline_succeeds:
            args.append("--when-pipeline-succeeds")
        success, output = await run_glab(args, repo=project)
        return f"✅ MR !{mr_id} Merged\n\n{output}" if success else f"❌ Failed: {output}"

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_close(project: str, mr_id: int) -> str:
        """Close a merge request without merging."""
        success, output = await run_glab(["mr", "close", str(mr_id)], repo=project)
        return f"✅ MR !{mr_id} Closed" if success else f"❌ Failed: {output}"

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_reopen(project: str, mr_id: int) -> str:
        """Reopen a closed merge request."""
        success, output = await run_glab(["mr", "reopen", str(mr_id)], repo=project)
        return f"✅ MR !{mr_id} Reopened" if success else f"❌ Failed: {output}"

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_rebase(project: str, mr_id: int) -> str:
        """Rebase a merge request's source branch against target."""
        success, output = await run_glab(["mr", "rebase", str(mr_id)], repo=project)
        return f"✅ MR !{mr_id} Rebased" if success else f"❌ Failed: {output}"

    # NOTE: gitlab_mr_checkout removed - interactive git operation

    @auto_heal()
    @registry.tool()
    async def gitlab_mr_approvers(project: str, mr_id: int) -> str:
        """List eligible approvers for a merge request."""
        success, output = await run_glab(["mr", "approvers", str(mr_id)], repo=project)
        return output if success else f"❌ Failed: {output}"

    # ==================== CI/CD PIPELINES ====================

    @auto_heal()
    @registry.tool()
    async def gitlab_ci_cancel(project: str, pipeline_id: int = 0) -> str:
        """Cancel a running pipeline."""
        args = ["ci", "cancel"]
        if pipeline_id > 0:
            args.append(str(pipeline_id))
        success, output = await run_glab(args, repo=project)
        return "✅ Pipeline Cancelled" if success else f"❌ Failed: {output}"

    @auto_heal()
    @registry.tool()
    async def gitlab_ci_lint(project: str) -> str:
        """Lint/validate the .gitlab-ci.yml file."""
        success, output = await run_glab(["ci", "lint"], repo=project)
        return f"✅ CI Config Valid\n\n{output}" if success else f"❌ Lint failed:\n\n{output}"

    # ==================== REPOSITORY ====================

    @auto_heal()
    @registry.tool()
    async def gitlab_issue_create(
        project: str, title: str, description: str = "", labels: str = "", assignee: str = ""
    ) -> str:
        """Create a new GitLab issue."""
        args = ["issue", "create", "--title", title, "--yes"]
        if description:
            args.extend(["--description", description])
        if labels:
            args.extend(["--label", labels])
        if assignee:
            args.extend(["--assignee", assignee])
        success, output = await run_glab(args, repo=project)
        return f"✅ Issue Created\n\n{output}" if success else f"❌ Failed: {output}"

    # ==================== MISC ====================

    @auto_heal()
    @registry.tool()
    async def gitlab_label_list(project: str) -> str:
        """List all labels in a project."""
        success, output = await run_glab(["label", "list"], repo=project)
        return output if success else f"❌ Failed: {output}"

    @auto_heal()
    @registry.tool()
    async def gitlab_release_list(project: str) -> str:
        """List releases for a project."""
        success, output = await run_glab(["release", "list"], repo=project)
        return output if success else f"❌ Failed: {output}"

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

    # REMOVED: gitlab_get_mr - duplicate of gitlab_mr_view

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
        # glab doesn't have a direct comments command, so we use mr view which includes discussions
        success, output = await run_glab(["mr", "view", str(mr_id), "--comments"], repo=project)
        if not success:
            # Fallback to basic view
            success, output = await run_glab(["mr", "view", str(mr_id), "--web=false"], repo=project)
        return f"## Comments on !{mr_id}\n\n{output}" if success else f"❌ Failed: {output}"

    # REMOVED: gitlab_pipeline_status - duplicate of gitlab_ci_status
    # REMOVED: gitlab_search_mrs_by_issue - use gitlab_mr_list with search param

    return registry.count
