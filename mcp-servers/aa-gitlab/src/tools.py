"""AA GitLab MCP Server - GitLab operations via glab CLI.

Authentication: glab auth login or GITLAB_TOKEN environment variable.
"""

import asyncio
import os
import subprocess

from mcp.server.fastmcp import FastMCP


GITLAB_HOST = os.getenv("GITLAB_HOST", "gitlab.com")  # Configure in GITLAB_HOST env or config.json


async def run_glab(args: list[str], repo: str | None = None, timeout: int = 60) -> tuple[bool, str]:
    """Run glab command and return (success, output)."""
    cmd = ["glab"] + args
    if repo:
        cmd.extend(["--repo", repo])
    
    env = os.environ.copy()
    env["GITLAB_HOST"] = GITLAB_HOST
    
    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=timeout, env=env
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

def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    
    @server.tool()
    async def gitlab_mr_list(
        project: str, state: str = "opened", author: str = "", assignee: str = "", reviewer: str = "", label: str = ""
    ) -> str:
        """List merge requests for a GitLab project."""
        args = ["mr", "list", "--state", state]
        if author: args.extend(["--author", author])
        if assignee: args.extend(["--assignee", assignee])
        if reviewer: args.extend(["--reviewer", reviewer])
        if label: args.extend(["--label", label])
        success, output = await run_glab(args, repo=project)
        return output if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_mr_view(project: str, mr_id: int) -> str:
        """View detailed information about a merge request."""
        success, output = await run_glab(["mr", "view", str(mr_id), "--web=false"], repo=project)
        return output if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_mr_create(
        project: str, title: str = "", description: str = "", source_branch: str = "",
        target_branch: str = "main", draft: bool = False, labels: str = "", assignee: str = "", reviewer: str = ""
    ) -> str:
        """Create a new merge request."""
        args = ["mr", "create", "--target-branch", target_branch]
        if title: args.extend(["--title", title])
        else: args.append("--fill")
        if description: args.extend(["--description", description])
        if source_branch: args.extend(["--source-branch", source_branch])
        if draft: args.append("--draft")
        if labels: args.extend(["--label", labels])
        if assignee: args.extend(["--assignee", assignee])
        if reviewer: args.extend(["--reviewer", reviewer])
        args.append("--yes")
        success, output = await run_glab(args, repo=project)
        return f"✅ MR Created\n\n{output}" if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_mr_update(
        project: str, mr_id: int, title: str = "", description: str = "",
        add_label: str = "", remove_label: str = "", assignee: str = "", reviewer: str = "", draft: bool | None = None
    ) -> str:
        """Update an existing merge request."""
        args = ["mr", "update", str(mr_id)]
        if title: args.extend(["--title", title])
        if description: args.extend(["--description", description])
        if add_label: args.extend(["--label", add_label])
        if remove_label: args.extend(["--unlabel", remove_label])
        if assignee: args.extend(["--assignee", assignee])
        if reviewer: args.extend(["--reviewer", reviewer])
        if draft is True: args.append("--draft")
        elif draft is False: args.append("--ready")
        success, output = await run_glab(args, repo=project)
        return f"✅ MR !{mr_id} Updated\n\n{output}" if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_mr_approve(project: str, mr_id: int) -> str:
        """Approve a merge request."""
        success, output = await run_glab(["mr", "approve", str(mr_id)], repo=project)
        return f"✅ MR !{mr_id} Approved" if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_mr_revoke(project: str, mr_id: int) -> str:
        """Revoke approval from a merge request."""
        success, output = await run_glab(["mr", "revoke", str(mr_id)], repo=project)
        return f"✅ Approval revoked from !{mr_id}" if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_mr_merge(
        project: str, mr_id: int, squash: bool = False, remove_source_branch: bool = True, when_pipeline_succeeds: bool = True
    ) -> str:
        """Merge a merge request."""
        args = ["mr", "merge", str(mr_id), "--yes"]
        if squash: args.append("--squash")
        if remove_source_branch: args.append("--remove-source-branch")
        if when_pipeline_succeeds: args.append("--when-pipeline-succeeds")
        success, output = await run_glab(args, repo=project)
        return f"✅ MR !{mr_id} Merged\n\n{output}" if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_mr_close(project: str, mr_id: int) -> str:
        """Close a merge request without merging."""
        success, output = await run_glab(["mr", "close", str(mr_id)], repo=project)
        return f"✅ MR !{mr_id} Closed" if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_mr_reopen(project: str, mr_id: int) -> str:
        """Reopen a closed merge request."""
        success, output = await run_glab(["mr", "reopen", str(mr_id)], repo=project)
        return f"✅ MR !{mr_id} Reopened" if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_mr_comment(project: str, mr_id: int, message: str) -> str:
        """Add a comment to a merge request."""
        success, output = await run_glab(["mr", "note", str(mr_id), "--message", message], repo=project)
        return f"✅ Comment added to !{mr_id}" if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_mr_diff(project: str, mr_id: int) -> str:
        """View the diff/changes in a merge request."""
        success, output = await run_glab(["mr", "diff", str(mr_id)], repo=project, timeout=120)
        if not success:
            return f"❌ Failed: {output}"
        if len(output) > 10000:
            output = output[:10000] + "\n\n... (truncated)"
        return f"## Diff for !{mr_id}\n\n```diff\n{output}\n```"


    @server.tool()
    async def gitlab_mr_rebase(project: str, mr_id: int) -> str:
        """Rebase a merge request's source branch against target."""
        success, output = await run_glab(["mr", "rebase", str(mr_id)], repo=project)
        return f"✅ MR !{mr_id} Rebased" if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_mr_checkout(project: str, mr_id: int) -> str:
        """Checkout a merge request branch locally."""
        success, output = await run_glab(["mr", "checkout", str(mr_id)], repo=project)
        return f"✅ Checked out MR !{mr_id}\n\n{output}" if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_mr_approvers(project: str, mr_id: int) -> str:
        """List eligible approvers for a merge request."""
        success, output = await run_glab(["mr", "approvers", str(mr_id)], repo=project)
        return output if success else f"❌ Failed: {output}"


    # ==================== CI/CD PIPELINES ====================

    @server.tool()
    async def gitlab_ci_list(project: str, status: str = "", page: int = 1) -> str:
        """List CI/CD pipelines for a project."""
        args = ["ci", "list", "--page", str(page)]
        if status: args.extend(["--status", status])
        success, output = await run_glab(args, repo=project)
        return output if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_ci_status(project: str, branch: str = "") -> str:
        """Get the status of the latest pipeline on a branch."""
        args = ["ci", "status"]
        if branch: args.extend(["--branch", branch])
        success, output = await run_glab(args, repo=project)
        return output if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_ci_view(project: str, branch: str = "") -> str:
        """View detailed pipeline information with all jobs."""
        args = ["ci", "view"]
        if branch: args.append(branch)
        success, output = await run_glab(args, repo=project)
        return output if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_ci_run(project: str, branch: str = "", variables: str = "") -> str:
        """Trigger a new pipeline run."""
        args = ["ci", "run"]
        if branch: args.extend(["--branch", branch])
        if variables:
            for var in variables.split(","):
                args.extend(["--variables", var.strip()])
        success, output = await run_glab(args, repo=project)
        return f"✅ Pipeline Started\n\n{output}" if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_ci_retry(project: str, job_id: int) -> str:
        """Retry a failed CI/CD job."""
        success, output = await run_glab(["ci", "retry", str(job_id)], repo=project)
        return f"✅ Job {job_id} Retried" if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_ci_cancel(project: str, pipeline_id: int = 0) -> str:
        """Cancel a running pipeline."""
        args = ["ci", "cancel"]
        if pipeline_id > 0: args.append(str(pipeline_id))
        success, output = await run_glab(args, repo=project)
        return f"✅ Pipeline Cancelled" if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_ci_trace(project: str, job_id: int) -> str:
        """Get the log output from a CI/CD job."""
        success, output = await run_glab(["ci", "trace", str(job_id)], repo=project, timeout=120)
        if not success:
            return f"❌ Failed: {output}"
        if len(output) > 15000:
            output = "... (truncated)\n\n" + output[-15000:]
        return f"## Job {job_id} Log\n\n```\n{output}\n```"


    @server.tool()
    async def gitlab_ci_lint(project: str) -> str:
        """Lint/validate the .gitlab-ci.yml file."""
        success, output = await run_glab(["ci", "lint"], repo=project)
        return f"✅ CI Config Valid\n\n{output}" if success else f"❌ Lint failed:\n\n{output}"


    # ==================== REPOSITORY ====================

    @server.tool()
    async def gitlab_repo_view(project: str) -> str:
        """View repository/project information."""
        success, output = await run_glab(["repo", "view", "--web=false"], repo=project)
        return output if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_repo_clone(project: str) -> str:
        """Get clone command for a GitLab repository."""
        clone_url = f"git@{GITLAB_HOST}:{project}.git"
        return f"## Clone {project}\n\n```bash\ngit clone {clone_url}\n```"


    # ==================== ISSUES ====================

    @server.tool()
    async def gitlab_issue_list(project: str, state: str = "opened", label: str = "", assignee: str = "") -> str:
        """List GitLab issues for a project."""
        args = ["issue", "list", "--state", state]
        if label: args.extend(["--label", label])
        if assignee: args.extend(["--assignee", assignee])
        success, output = await run_glab(args, repo=project)
        return output if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_issue_view(project: str, issue_id: int) -> str:
        """View a GitLab issue."""
        success, output = await run_glab(["issue", "view", str(issue_id), "--web=false"], repo=project)
        return output if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_issue_create(project: str, title: str, description: str = "", labels: str = "", assignee: str = "") -> str:
        """Create a new GitLab issue."""
        args = ["issue", "create", "--title", title, "--yes"]
        if description: args.extend(["--description", description])
        if labels: args.extend(["--label", labels])
        if assignee: args.extend(["--assignee", assignee])
        success, output = await run_glab(args, repo=project)
        return f"✅ Issue Created\n\n{output}" if success else f"❌ Failed: {output}"


    # ==================== MISC ====================

    @server.tool()
    async def gitlab_label_list(project: str) -> str:
        """List all labels in a project."""
        success, output = await run_glab(["label", "list"], repo=project)
        return output if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_release_list(project: str) -> str:
        """List releases for a project."""
        success, output = await run_glab(["release", "list"], repo=project)
        return output if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_user_info() -> str:
        """Get current authenticated GitLab user information."""
        success, output = await run_glab(["auth", "status"])
        return output if success else f"❌ Failed: {output}"


    # ==================== ADDITIONAL TOOLS (from gitlab_tools) ====================

    @server.tool()
    async def gitlab_list_mrs(
        project: str,
        state: str = "opened",
        author: str = "",
    ) -> str:
        """
        List merge requests for a GitLab project (alias for gitlab_mr_list).

        Args:
            project: Project name or path
            state: MR state - opened, merged, closed, all
            author: Filter by author username

        Returns:
            List of merge requests.
        """
        args = ["mr", "list", "--state", state]
        if author:
            args.extend(["--author", author])
        success, output = await run_glab(args, repo=project)
        if not success:
            return f"❌ Failed: {output}"
        return f"## MRs in {project}\n\n{output}"


    @server.tool()
    async def gitlab_get_mr(project: str, mr_id: int) -> str:
        """
        Get details of a specific merge request (alias for gitlab_mr_view).

        Args:
            project: Project name or path
            mr_id: Merge request IID

        Returns:
            Detailed MR information.
        """
        success, output = await run_glab(["mr", "view", str(mr_id), "--web=false"], repo=project)
        return output if success else f"❌ Failed: {output}"


    @server.tool()
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


    @server.tool()
    async def gitlab_pipeline_status(project: str, mr_id: int = 0, branch: str = "") -> str:
        """
        Get pipeline status for a merge request or branch.

        Args:
            project: Project name or path
            mr_id: Merge request IID (optional)
            branch: Branch name (optional, uses current if not specified)

        Returns:
            Pipeline status with job details.
        """
        if mr_id > 0:
            # Get MR pipeline
            success, output = await run_glab(["mr", "view", str(mr_id), "--web=false"], repo=project)
            if not success:
                return f"❌ Failed: {output}"
            # Extract pipeline info from MR view
            return f"## Pipeline for !{mr_id}\n\n{output}"
        else:
            # Get branch pipeline
            args = ["ci", "view"]
            if branch:
                args.append(branch)
            success, output = await run_glab(args, repo=project)
            return f"## Pipeline Status\n\n{output}" if success else f"❌ Failed: {output}"


    @server.tool()
    async def gitlab_search_mrs_by_issue(
        project: str,
        issue_key: str,
    ) -> str:
        """
        Search for merge requests related to a Jira issue.

        Args:
            project: Project name or path
            issue_key: Jira issue key (e.g., AAP-12345)

        Returns:
            List of MRs mentioning the issue key.
        """
        # Search in MR titles/descriptions for the issue key
        success, output = await run_glab(["mr", "list", "--state", "all", "--search", issue_key], repo=project)
        if not success:
            return f"❌ Failed: {output}"
        if not output.strip() or "no merge requests" in output.lower():
            return f"No MRs found for {issue_key} in {project}"
        return f"## MRs for {issue_key}\n\n{output}"

    return len([m for m in dir() if not m.startswith('_')])  # Approximate count
