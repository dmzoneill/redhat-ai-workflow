"""GitHub CLI (gh) tool definitions - Repository and workflow management.

Provides:
Repository tools:
- gh_repo_list: List repositories
- gh_repo_view: View repository details
- gh_repo_clone: Clone a repository
- gh_repo_create: Create a new repository
- gh_repo_fork: Fork a repository
- gh_repo_delete: Delete a repository

Pull Request tools:
- gh_pr_list: List pull requests
- gh_pr_view: View pull request details
- gh_pr_create: Create a pull request
- gh_pr_checkout: Checkout a pull request locally
- gh_pr_merge: Merge a pull request
- gh_pr_close: Close a pull request
- gh_pr_reopen: Reopen a pull request
- gh_pr_review: Review a pull request
- gh_pr_diff: View pull request diff
- gh_pr_checks: View PR check status

Issue tools:
- gh_issue_list: List issues
- gh_issue_view: View issue details
- gh_issue_create: Create an issue
- gh_issue_close: Close an issue
- gh_issue_reopen: Reopen an issue
- gh_issue_comment: Add comment to an issue
- gh_issue_edit: Edit an issue

Workflow/Actions tools:
- gh_workflow_list: List workflows
- gh_workflow_view: View workflow details
- gh_run_list: List workflow runs
- gh_run_view: View workflow run details
- gh_run_watch: Watch a workflow run
- gh_run_rerun: Re-run a workflow
- gh_run_cancel: Cancel a workflow run
- gh_run_download: Download workflow artifacts

Release tools:
- gh_release_list: List releases
- gh_release_view: View release details
- gh_release_create: Create a release
- gh_release_delete: Delete a release
- gh_release_download: Download release assets

Gist tools:
- gh_gist_list: List gists
- gh_gist_view: View gist contents
- gh_gist_create: Create a gist

Search tools:
- gh_search_repos: Search repositories
- gh_search_issues: Search issues/PRs
- gh_search_code: Search code

Auth tools:
- gh_auth_status: Check authentication status
"""

import logging
import os

from fastmcp import FastMCP

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import run_cmd, truncate_output

logger = logging.getLogger(__name__)


def _get_gh_env() -> dict:
    """Get environment variables for gh commands.

    Returns:
        Environment dict with GitHub CLI variables set.
    """
    env = os.environ.copy()
    # Disable interactive prompts
    env.setdefault("GH_PROMPT_DISABLED", "1")
    # Use non-interactive mode
    env.setdefault("GH_NO_UPDATE_NOTIFIER", "1")
    return env


# =============================================================================
# Repository Tools
# =============================================================================


@auto_heal()
async def _gh_repo_list_impl(
    owner: str = "",
    limit: int = 30,
    visibility: str = "",
    fork: bool | None = None,
    source: bool | None = None,
    language: str = "",
    topic: str = "",
    archived: bool | None = None,
) -> str:
    """
    List repositories.

    Args:
        owner: Owner/org to list repos for (default: authenticated user)
        limit: Maximum number of repos to list
        visibility: Filter by visibility (public, private, internal)
        fork: Filter by fork status (True=forks only, False=non-forks only)
        source: Filter by source status (True=non-forks, False=forks)
        language: Filter by primary language
        topic: Filter by topic
        archived: Filter by archived status

    Returns:
        List of repositories.
    """
    cmd = ["gh", "repo", "list"]

    if owner:
        cmd.append(owner)

    cmd.extend(["--limit", str(limit)])

    if visibility:
        cmd.extend(["--visibility", visibility])
    if fork is True:
        cmd.append("--fork")
    if fork is False:
        cmd.append("--no-fork")
    if source is True:
        cmd.append("--source")
    if language:
        cmd.extend(["--language", language])
    if topic:
        cmd.extend(["--topic", topic])
    if archived is True:
        cmd.append("--archived")
    if archived is False:
        cmd.append("--no-archived")

    success, output = await run_cmd(cmd, timeout=60, env=_get_gh_env())

    if success:
        return f"## Repositories\n\n```\n{output}\n```"
    return f"❌ Failed to list repositories: {output}"


@auto_heal()
async def _gh_repo_view_impl(
    repo: str = "",
    web: bool = False,
) -> str:
    """
    View repository details.

    Args:
        repo: Repository in OWNER/REPO format (default: current repo)
        web: Open in browser instead of showing details

    Returns:
        Repository details.
    """
    cmd = ["gh", "repo", "view"]

    if repo:
        cmd.append(repo)
    if web:
        cmd.append("--web")
        success, output = await run_cmd(cmd, timeout=30, env=_get_gh_env())
        if success:
            return f"✅ Opened {repo or 'repository'} in browser"
        return f"❌ Failed to open repository: {output}"

    success, output = await run_cmd(cmd, timeout=30, env=_get_gh_env())

    if success:
        return f"## Repository Details\n\n{output}"
    return f"❌ Failed to view repository: {output}"


@auto_heal()
async def _gh_repo_clone_impl(
    repo: str,
    directory: str = "",
    cwd: str = "",
) -> str:
    """
    Clone a repository.

    Args:
        repo: Repository in OWNER/REPO format or URL
        directory: Directory to clone into
        cwd: Working directory for clone operation

    Returns:
        Clone result.
    """
    cmd = ["gh", "repo", "clone", repo]

    if directory:
        cmd.append(directory)

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=300, env=_get_gh_env())

    if success:
        return f"✅ Cloned {repo}\n\n{output}"
    return f"❌ Failed to clone repository: {output}"


@auto_heal()
async def _gh_repo_create_impl(
    name: str,
    description: str = "",
    visibility: str = "private",
    clone: bool = False,
    template: str = "",
    add_readme: bool = False,
    gitignore: str = "",
    license_type: str = "",
) -> str:
    """
    Create a new repository.

    Args:
        name: Repository name (or OWNER/NAME for org repos)
        description: Repository description
        visibility: Visibility (public, private, internal)
        clone: Clone the repository after creation
        template: Template repository to use (OWNER/REPO)
        add_readme: Add a README file
        gitignore: Gitignore template to use
        license_type: License to add (e.g., mit, apache-2.0, gpl-3.0)

    Returns:
        Creation result.
    """
    cmd = ["gh", "repo", "create", name, f"--{visibility}"]

    if description:
        cmd.extend(["--description", description])
    if clone:
        cmd.append("--clone")
    if template:
        cmd.extend(["--template", template])
    if add_readme:
        cmd.append("--add-readme")
    if gitignore:
        cmd.extend(["--gitignore", gitignore])
    if license_type:
        cmd.extend(["--license", license_type])

    success, output = await run_cmd(cmd, timeout=60, env=_get_gh_env())

    if success:
        return f"✅ Repository '{name}' created\n\n{output}"
    return f"❌ Failed to create repository: {output}"


@auto_heal()
async def _gh_repo_fork_impl(
    repo: str = "",
    clone: bool = False,
    remote: bool = True,
    org: str = "",
) -> str:
    """
    Fork a repository.

    Args:
        repo: Repository to fork (OWNER/REPO, default: current repo)
        clone: Clone the fork after creation
        remote: Add remote for fork
        org: Organization to fork into

    Returns:
        Fork result.
    """
    cmd = ["gh", "repo", "fork"]

    if repo:
        cmd.append(repo)
    if clone:
        cmd.append("--clone")
    if remote:
        cmd.append("--remote")
    if org:
        cmd.extend(["--org", org])

    success, output = await run_cmd(cmd, timeout=120, env=_get_gh_env())

    if success:
        return f"✅ Repository forked\n\n{output}"
    return f"❌ Failed to fork repository: {output}"


@auto_heal()
async def _gh_repo_delete_impl(
    repo: str,
    confirm: bool = True,
) -> str:
    """
    Delete a repository.

    Args:
        repo: Repository to delete (OWNER/REPO)
        confirm: Skip confirmation (required for non-interactive)

    Returns:
        Deletion result.
    """
    cmd = ["gh", "repo", "delete", repo]

    if confirm:
        cmd.append("--yes")

    success, output = await run_cmd(cmd, timeout=60, env=_get_gh_env())

    if success:
        return f"✅ Repository '{repo}' deleted"
    return f"❌ Failed to delete repository: {output}"


# =============================================================================
# Pull Request Tools
# =============================================================================


@auto_heal()
async def _gh_pr_list_impl(
    repo: str = "",
    state: str = "open",
    limit: int = 30,
    author: str = "",
    assignee: str = "",
    label: str = "",
    base: str = "",
    head: str = "",
    search: str = "",
    cwd: str = "",
) -> str:
    """
    List pull requests.

    Args:
        repo: Repository (OWNER/REPO, default: current repo)
        state: PR state (open, closed, merged, all)
        limit: Maximum number of PRs to list
        author: Filter by author
        assignee: Filter by assignee
        label: Filter by label
        base: Filter by base branch
        head: Filter by head branch
        search: Search query
        cwd: Working directory

    Returns:
        List of pull requests.
    """
    cmd = ["gh", "pr", "list"]

    if repo:
        cmd.extend(["--repo", repo])

    cmd.extend(["--state", state, "--limit", str(limit)])

    if author:
        cmd.extend(["--author", author])
    if assignee:
        cmd.extend(["--assignee", assignee])
    if label:
        cmd.extend(["--label", label])
    if base:
        cmd.extend(["--base", base])
    if head:
        cmd.extend(["--head", head])
    if search:
        cmd.extend(["--search", search])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"## Pull Requests ({state})\n\n```\n{output}\n```"
    return f"❌ Failed to list PRs: {output}"


@auto_heal()
async def _gh_pr_view_impl(
    pr: str = "",
    repo: str = "",
    comments: bool = False,
    cwd: str = "",
) -> str:
    """
    View pull request details.

    Args:
        pr: PR number or branch name (default: current branch)
        repo: Repository (OWNER/REPO)
        comments: Include comments
        cwd: Working directory

    Returns:
        Pull request details.
    """
    cmd = ["gh", "pr", "view"]

    if pr:
        cmd.append(pr)
    if repo:
        cmd.extend(["--repo", repo])
    if comments:
        cmd.append("--comments")

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"## Pull Request\n\n{output}"
    return f"❌ Failed to view PR: {output}"


@auto_heal()
async def _gh_pr_create_impl(
    title: str,
    body: str = "",
    base: str = "",
    head: str = "",
    draft: bool = False,
    assignee: str = "",
    reviewer: str = "",
    label: str = "",
    milestone: str = "",
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    Create a pull request.

    Args:
        title: PR title
        body: PR body/description
        base: Base branch (default: default branch)
        head: Head branch (default: current branch)
        draft: Create as draft PR
        assignee: Assignees (comma-separated)
        reviewer: Reviewers (comma-separated)
        label: Labels (comma-separated)
        milestone: Milestone name or number
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Created PR details.
    """
    cmd = ["gh", "pr", "create", "--title", title]

    if body:
        cmd.extend(["--body", body])
    if base:
        cmd.extend(["--base", base])
    if head:
        cmd.extend(["--head", head])
    if draft:
        cmd.append("--draft")
    if assignee:
        cmd.extend(["--assignee", assignee])
    if reviewer:
        cmd.extend(["--reviewer", reviewer])
    if label:
        cmd.extend(["--label", label])
    if milestone:
        cmd.extend(["--milestone", milestone])
    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"✅ Pull request created\n\n{output}"
    return f"❌ Failed to create PR: {output}"


@auto_heal()
async def _gh_pr_checkout_impl(
    pr: str,
    branch: str = "",
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    Checkout a pull request locally.

    Args:
        pr: PR number or URL
        branch: Local branch name to use
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Checkout result.
    """
    cmd = ["gh", "pr", "checkout", pr]

    if branch:
        cmd.extend(["--branch", branch])
    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=120, env=_get_gh_env())

    if success:
        return f"✅ Checked out PR #{pr}\n\n{output}"
    return f"❌ Failed to checkout PR: {output}"


@auto_heal()
async def _gh_pr_merge_impl(
    pr: str = "",
    method: str = "merge",
    delete_branch: bool = True,
    auto: bool = False,
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    Merge a pull request.

    Args:
        pr: PR number (default: PR for current branch)
        method: Merge method (merge, squash, rebase)
        delete_branch: Delete branch after merge
        auto: Enable auto-merge when checks pass
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Merge result.
    """
    cmd = ["gh", "pr", "merge"]

    if pr:
        cmd.append(pr)

    cmd.append(f"--{method}")

    if delete_branch:
        cmd.append("--delete-branch")
    if auto:
        cmd.append("--auto")
    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"✅ Pull request merged\n\n{output}"
    return f"❌ Failed to merge PR: {output}"


@auto_heal()
async def _gh_pr_close_impl(
    pr: str,
    comment: str = "",
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    Close a pull request.

    Args:
        pr: PR number
        comment: Comment to add when closing
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Close result.
    """
    cmd = ["gh", "pr", "close", pr]

    if comment:
        cmd.extend(["--comment", comment])
    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"✅ PR #{pr} closed\n\n{output}"
    return f"❌ Failed to close PR: {output}"


@auto_heal()
async def _gh_pr_reopen_impl(
    pr: str,
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    Reopen a pull request.

    Args:
        pr: PR number
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Reopen result.
    """
    cmd = ["gh", "pr", "reopen", pr]

    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"✅ PR #{pr} reopened\n\n{output}"
    return f"❌ Failed to reopen PR: {output}"


@auto_heal()
async def _gh_pr_review_impl(
    pr: str,
    action: str = "comment",
    body: str = "",
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    Review a pull request.

    Args:
        pr: PR number
        action: Review action (approve, request-changes, comment)
        body: Review body/comment
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Review result.
    """
    cmd = ["gh", "pr", "review", pr, f"--{action}"]

    if body:
        cmd.extend(["--body", body])
    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"✅ Review submitted for PR #{pr}\n\n{output}"
    return f"❌ Failed to review PR: {output}"


@auto_heal()
async def _gh_pr_diff_impl(
    pr: str = "",
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    View pull request diff.

    Args:
        pr: PR number (default: current branch)
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        PR diff.
    """
    cmd = ["gh", "pr", "diff"]

    if pr:
        cmd.append(pr)
    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"## PR Diff\n\n```diff\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Failed to get PR diff: {output}"


@auto_heal()
async def _gh_pr_checks_impl(
    pr: str = "",
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    View PR check/CI status.

    Args:
        pr: PR number (default: current branch)
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Check status.
    """
    cmd = ["gh", "pr", "checks"]

    if pr:
        cmd.append(pr)
    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"## PR Checks\n\n```\n{output}\n```"
    return f"❌ Failed to get PR checks: {output}"


# =============================================================================
# Issue Tools
# =============================================================================


@auto_heal()
async def _gh_issue_list_impl(
    repo: str = "",
    state: str = "open",
    limit: int = 30,
    author: str = "",
    assignee: str = "",
    label: str = "",
    milestone: str = "",
    search: str = "",
    cwd: str = "",
) -> str:
    """
    List issues.

    Args:
        repo: Repository (OWNER/REPO, default: current repo)
        state: Issue state (open, closed, all)
        limit: Maximum number of issues to list
        author: Filter by author
        assignee: Filter by assignee
        label: Filter by label
        milestone: Filter by milestone
        search: Search query
        cwd: Working directory

    Returns:
        List of issues.
    """
    cmd = ["gh", "issue", "list"]

    if repo:
        cmd.extend(["--repo", repo])

    cmd.extend(["--state", state, "--limit", str(limit)])

    if author:
        cmd.extend(["--author", author])
    if assignee:
        cmd.extend(["--assignee", assignee])
    if label:
        cmd.extend(["--label", label])
    if milestone:
        cmd.extend(["--milestone", milestone])
    if search:
        cmd.extend(["--search", search])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"## Issues ({state})\n\n```\n{output}\n```"
    return f"❌ Failed to list issues: {output}"


@auto_heal()
async def _gh_issue_view_impl(
    issue: str,
    repo: str = "",
    comments: bool = False,
    cwd: str = "",
) -> str:
    """
    View issue details.

    Args:
        issue: Issue number
        repo: Repository (OWNER/REPO)
        comments: Include comments
        cwd: Working directory

    Returns:
        Issue details.
    """
    cmd = ["gh", "issue", "view", issue]

    if repo:
        cmd.extend(["--repo", repo])
    if comments:
        cmd.append("--comments")

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"## Issue #{issue}\n\n{output}"
    return f"❌ Failed to view issue: {output}"


@auto_heal()
async def _gh_issue_create_impl(
    title: str,
    body: str = "",
    assignee: str = "",
    label: str = "",
    milestone: str = "",
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    Create an issue.

    Args:
        title: Issue title
        body: Issue body/description
        assignee: Assignees (comma-separated)
        label: Labels (comma-separated)
        milestone: Milestone name or number
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Created issue details.
    """
    cmd = ["gh", "issue", "create", "--title", title]

    if body:
        cmd.extend(["--body", body])
    if assignee:
        cmd.extend(["--assignee", assignee])
    if label:
        cmd.extend(["--label", label])
    if milestone:
        cmd.extend(["--milestone", milestone])
    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"✅ Issue created\n\n{output}"
    return f"❌ Failed to create issue: {output}"


@auto_heal()
async def _gh_issue_close_impl(
    issue: str,
    reason: str = "",
    comment: str = "",
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    Close an issue.

    Args:
        issue: Issue number
        reason: Close reason (completed, not_planned)
        comment: Comment to add when closing
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Close result.
    """
    cmd = ["gh", "issue", "close", issue]

    if reason:
        cmd.extend(["--reason", reason])
    if comment:
        cmd.extend(["--comment", comment])
    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"✅ Issue #{issue} closed\n\n{output}"
    return f"❌ Failed to close issue: {output}"


@auto_heal()
async def _gh_issue_reopen_impl(
    issue: str,
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    Reopen an issue.

    Args:
        issue: Issue number
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Reopen result.
    """
    cmd = ["gh", "issue", "reopen", issue]

    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"✅ Issue #{issue} reopened\n\n{output}"
    return f"❌ Failed to reopen issue: {output}"


@auto_heal()
async def _gh_issue_comment_impl(
    issue: str,
    body: str,
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    Add a comment to an issue.

    Args:
        issue: Issue number
        body: Comment body
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Comment result.
    """
    cmd = ["gh", "issue", "comment", issue, "--body", body]

    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"✅ Comment added to issue #{issue}\n\n{output}"
    return f"❌ Failed to add comment: {output}"


@auto_heal()
async def _gh_issue_edit_impl(
    issue: str,
    title: str = "",
    body: str = "",
    add_label: str = "",
    remove_label: str = "",
    add_assignee: str = "",
    remove_assignee: str = "",
    milestone: str = "",
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    Edit an issue.

    Args:
        issue: Issue number
        title: New title
        body: New body
        add_label: Labels to add
        remove_label: Labels to remove
        add_assignee: Assignees to add
        remove_assignee: Assignees to remove
        milestone: Milestone to set
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Edit result.
    """
    cmd = ["gh", "issue", "edit", issue]

    if title:
        cmd.extend(["--title", title])
    if body:
        cmd.extend(["--body", body])
    if add_label:
        cmd.extend(["--add-label", add_label])
    if remove_label:
        cmd.extend(["--remove-label", remove_label])
    if add_assignee:
        cmd.extend(["--add-assignee", add_assignee])
    if remove_assignee:
        cmd.extend(["--remove-assignee", remove_assignee])
    if milestone:
        cmd.extend(["--milestone", milestone])
    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"✅ Issue #{issue} updated\n\n{output}"
    return f"❌ Failed to edit issue: {output}"


# =============================================================================
# Workflow/Actions Tools
# =============================================================================


@auto_heal()
async def _gh_workflow_list_impl(
    repo: str = "",
    limit: int = 50,
    cwd: str = "",
) -> str:
    """
    List workflows.

    Args:
        repo: Repository (OWNER/REPO)
        limit: Maximum number of workflows to list
        cwd: Working directory

    Returns:
        List of workflows.
    """
    cmd = ["gh", "workflow", "list", "--limit", str(limit)]

    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"## Workflows\n\n```\n{output}\n```"
    return f"❌ Failed to list workflows: {output}"


@auto_heal()
async def _gh_workflow_view_impl(
    workflow: str,
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    View workflow details.

    Args:
        workflow: Workflow name or ID
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Workflow details.
    """
    cmd = ["gh", "workflow", "view", workflow]

    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"## Workflow: {workflow}\n\n{output}"
    return f"❌ Failed to view workflow: {output}"


@auto_heal()
async def _gh_run_list_impl(
    repo: str = "",
    workflow: str = "",
    branch: str = "",
    user: str = "",
    status: str = "",
    limit: int = 20,
    cwd: str = "",
) -> str:
    """
    List workflow runs.

    Args:
        repo: Repository (OWNER/REPO)
        workflow: Filter by workflow name or ID
        branch: Filter by branch
        user: Filter by user who triggered
        status: Filter by status (queued, in_progress, completed, etc.)
        limit: Maximum number of runs to list
        cwd: Working directory

    Returns:
        List of workflow runs.
    """
    cmd = ["gh", "run", "list", "--limit", str(limit)]

    if repo:
        cmd.extend(["--repo", repo])
    if workflow:
        cmd.extend(["--workflow", workflow])
    if branch:
        cmd.extend(["--branch", branch])
    if user:
        cmd.extend(["--user", user])
    if status:
        cmd.extend(["--status", status])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"## Workflow Runs\n\n```\n{output}\n```"
    return f"❌ Failed to list runs: {output}"


@auto_heal()
async def _gh_run_view_impl(
    run_id: str,
    repo: str = "",
    log: bool = False,
    cwd: str = "",
) -> str:
    """
    View workflow run details.

    Args:
        run_id: Run ID
        repo: Repository (OWNER/REPO)
        log: Show run log
        cwd: Working directory

    Returns:
        Run details.
    """
    cmd = ["gh", "run", "view", run_id]

    if repo:
        cmd.extend(["--repo", repo])
    if log:
        cmd.append("--log")

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=120, env=_get_gh_env())

    if success:
        truncated = truncate_output(output, max_length=5000, mode="tail")
        return f"## Run {run_id}\n\n```\n{truncated}\n```"
    return f"❌ Failed to view run: {output}"


@auto_heal()
async def _gh_run_watch_impl(
    run_id: str,
    repo: str = "",
    exit_status: bool = True,
    cwd: str = "",
    timeout: int = 600,
) -> str:
    """
    Watch a workflow run until completion.

    Args:
        run_id: Run ID
        repo: Repository (OWNER/REPO)
        exit_status: Exit with run's exit status
        cwd: Working directory
        timeout: Timeout in seconds

    Returns:
        Final run status.
    """
    cmd = ["gh", "run", "watch", run_id]

    if repo:
        cmd.extend(["--repo", repo])
    if exit_status:
        cmd.append("--exit-status")

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=timeout, env=_get_gh_env())

    if success:
        return f"✅ Run {run_id} completed successfully\n\n{output}"
    return f"❌ Run {run_id} failed or timed out:\n\n{output}"


@auto_heal()
async def _gh_run_rerun_impl(
    run_id: str,
    failed: bool = False,
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    Re-run a workflow.

    Args:
        run_id: Run ID
        failed: Only re-run failed jobs
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Rerun result.
    """
    cmd = ["gh", "run", "rerun", run_id]

    if failed:
        cmd.append("--failed")
    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"✅ Run {run_id} re-triggered\n\n{output}"
    return f"❌ Failed to rerun: {output}"


@auto_heal()
async def _gh_run_cancel_impl(
    run_id: str,
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    Cancel a workflow run.

    Args:
        run_id: Run ID
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Cancel result.
    """
    cmd = ["gh", "run", "cancel", run_id]

    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"✅ Run {run_id} cancelled\n\n{output}"
    return f"❌ Failed to cancel run: {output}"


@auto_heal()
async def _gh_run_download_impl(
    run_id: str,
    name: str = "",
    dir_path: str = "",
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    Download workflow artifacts.

    Args:
        run_id: Run ID
        name: Artifact name to download (default: all)
        dir_path: Directory to download to
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Download result.
    """
    cmd = ["gh", "run", "download", run_id]

    if name:
        cmd.extend(["--name", name])
    if dir_path:
        cmd.extend(["--dir", dir_path])
    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=300, env=_get_gh_env())

    if success:
        return f"✅ Artifacts downloaded\n\n{output}"
    return f"❌ Failed to download artifacts: {output}"


# =============================================================================
# Release Tools
# =============================================================================


@auto_heal()
async def _gh_release_list_impl(
    repo: str = "",
    limit: int = 30,
    cwd: str = "",
) -> str:
    """
    List releases.

    Args:
        repo: Repository (OWNER/REPO)
        limit: Maximum number of releases to list
        cwd: Working directory

    Returns:
        List of releases.
    """
    cmd = ["gh", "release", "list", "--limit", str(limit)]

    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"## Releases\n\n```\n{output}\n```"
    return f"❌ Failed to list releases: {output}"


@auto_heal()
async def _gh_release_view_impl(
    tag: str = "",
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    View release details.

    Args:
        tag: Release tag (default: latest)
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Release details.
    """
    cmd = ["gh", "release", "view"]

    if tag:
        cmd.append(tag)
    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"## Release\n\n{output}"
    return f"❌ Failed to view release: {output}"


@auto_heal()
async def _gh_release_create_impl(
    tag: str,
    title: str = "",
    notes: str = "",
    target: str = "",
    draft: bool = False,
    prerelease: bool = False,
    generate_notes: bool = False,
    files: str = "",
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    Create a release.

    Args:
        tag: Release tag
        title: Release title
        notes: Release notes
        target: Target branch or commit SHA
        draft: Create as draft
        prerelease: Mark as prerelease
        generate_notes: Auto-generate release notes
        files: Files to upload (space-separated paths)
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Created release details.
    """
    cmd = ["gh", "release", "create", tag]

    if title:
        cmd.extend(["--title", title])
    if notes:
        cmd.extend(["--notes", notes])
    if target:
        cmd.extend(["--target", target])
    if draft:
        cmd.append("--draft")
    if prerelease:
        cmd.append("--prerelease")
    if generate_notes:
        cmd.append("--generate-notes")
    if repo:
        cmd.extend(["--repo", repo])
    if files:
        cmd.extend(files.split())

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=120, env=_get_gh_env())

    if success:
        return f"✅ Release {tag} created\n\n{output}"
    return f"❌ Failed to create release: {output}"


@auto_heal()
async def _gh_release_delete_impl(
    tag: str,
    cleanup_tag: bool = False,
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    Delete a release.

    Args:
        tag: Release tag
        cleanup_tag: Also delete the git tag
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Delete result.
    """
    cmd = ["gh", "release", "delete", tag, "--yes"]

    if cleanup_tag:
        cmd.append("--cleanup-tag")
    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=60, env=_get_gh_env())

    if success:
        return f"✅ Release {tag} deleted"
    return f"❌ Failed to delete release: {output}"


@auto_heal()
async def _gh_release_download_impl(
    tag: str = "",
    pattern: str = "",
    dir_path: str = "",
    repo: str = "",
    cwd: str = "",
) -> str:
    """
    Download release assets.

    Args:
        tag: Release tag (default: latest)
        pattern: Glob pattern for assets to download
        dir_path: Directory to download to
        repo: Repository (OWNER/REPO)
        cwd: Working directory

    Returns:
        Download result.
    """
    cmd = ["gh", "release", "download"]

    if tag:
        cmd.append(tag)
    if pattern:
        cmd.extend(["--pattern", pattern])
    if dir_path:
        cmd.extend(["--dir", dir_path])
    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, cwd=cwd if cwd else None, timeout=300, env=_get_gh_env())

    if success:
        return f"✅ Release assets downloaded\n\n{output}"
    return f"❌ Failed to download assets: {output}"


# =============================================================================
# Gist Tools
# =============================================================================


@auto_heal()
async def _gh_gist_list_impl(
    limit: int = 30,
    public: bool | None = None,
) -> str:
    """
    List gists.

    Args:
        limit: Maximum number of gists to list
        public: Filter by visibility (True=public, False=secret)

    Returns:
        List of gists.
    """
    cmd = ["gh", "gist", "list", "--limit", str(limit)]

    if public is True:
        cmd.append("--public")
    if public is False:
        cmd.append("--secret")

    success, output = await run_cmd(cmd, timeout=60, env=_get_gh_env())

    if success:
        return f"## Gists\n\n```\n{output}\n```"
    return f"❌ Failed to list gists: {output}"


@auto_heal()
async def _gh_gist_view_impl(
    gist_id: str,
    filename: str = "",
    raw: bool = False,
) -> str:
    """
    View gist contents.

    Args:
        gist_id: Gist ID or URL
        filename: Specific file to view
        raw: Show raw content without formatting

    Returns:
        Gist contents.
    """
    cmd = ["gh", "gist", "view", gist_id]

    if filename:
        cmd.extend(["--filename", filename])
    if raw:
        cmd.append("--raw")

    success, output = await run_cmd(cmd, timeout=60, env=_get_gh_env())

    if success:
        return f"## Gist\n\n```\n{truncate_output(output, max_length=5000, mode='head')}\n```"
    return f"❌ Failed to view gist: {output}"


@auto_heal()
async def _gh_gist_create_impl(
    files: str,
    description: str = "",
    public: bool = False,
) -> str:
    """
    Create a gist.

    Args:
        files: Files to include (space-separated paths)
        description: Gist description
        public: Make gist public

    Returns:
        Created gist URL.
    """
    cmd = ["gh", "gist", "create"]

    if description:
        cmd.extend(["--desc", description])
    if public:
        cmd.append("--public")

    cmd.extend(files.split())

    success, output = await run_cmd(cmd, timeout=60, env=_get_gh_env())

    if success:
        return f"✅ Gist created\n\n{output}"
    return f"❌ Failed to create gist: {output}"


# =============================================================================
# Search Tools
# =============================================================================


@auto_heal()
async def _gh_search_repos_impl(
    query: str,
    limit: int = 30,
    sort: str = "",
    order: str = "",
    language: str = "",
    owner: str = "",
) -> str:
    """
    Search repositories.

    Args:
        query: Search query
        limit: Maximum results
        sort: Sort by (stars, forks, updated, help-wanted-issues)
        order: Sort order (asc, desc)
        language: Filter by language
        owner: Filter by owner

    Returns:
        Search results.
    """
    cmd = ["gh", "search", "repos", query, "--limit", str(limit)]

    if sort:
        cmd.extend(["--sort", sort])
    if order:
        cmd.extend(["--order", order])
    if language:
        cmd.extend(["--language", language])
    if owner:
        cmd.extend(["--owner", owner])

    success, output = await run_cmd(cmd, timeout=60, env=_get_gh_env())

    if success:
        return f"## Repository Search: {query}\n\n```\n{output}\n```"
    return f"❌ Search failed: {output}"


@auto_heal()
async def _gh_search_issues_impl(
    query: str,
    limit: int = 30,
    sort: str = "",
    order: str = "",
    state: str = "",
    repo: str = "",
) -> str:
    """
    Search issues and pull requests.

    Args:
        query: Search query
        limit: Maximum results
        sort: Sort by (created, updated, comments, reactions)
        order: Sort order (asc, desc)
        state: Filter by state (open, closed)
        repo: Filter by repository

    Returns:
        Search results.
    """
    cmd = ["gh", "search", "issues", query, "--limit", str(limit)]

    if sort:
        cmd.extend(["--sort", sort])
    if order:
        cmd.extend(["--order", order])
    if state:
        cmd.extend(["--state", state])
    if repo:
        cmd.extend(["--repo", repo])

    success, output = await run_cmd(cmd, timeout=60, env=_get_gh_env())

    if success:
        return f"## Issue Search: {query}\n\n```\n{output}\n```"
    return f"❌ Search failed: {output}"


@auto_heal()
async def _gh_search_code_impl(
    query: str,
    limit: int = 30,
    repo: str = "",
    language: str = "",
    filename: str = "",
    extension: str = "",
) -> str:
    """
    Search code.

    Args:
        query: Search query
        limit: Maximum results
        repo: Filter by repository
        language: Filter by language
        filename: Filter by filename
        extension: Filter by file extension

    Returns:
        Search results.
    """
    cmd = ["gh", "search", "code", query, "--limit", str(limit)]

    if repo:
        cmd.extend(["--repo", repo])
    if language:
        cmd.extend(["--language", language])
    if filename:
        cmd.extend(["--filename", filename])
    if extension:
        cmd.extend(["--extension", extension])

    success, output = await run_cmd(cmd, timeout=60, env=_get_gh_env())

    if success:
        return f"## Code Search: {query}\n\n```\n{output}\n```"
    return f"❌ Search failed: {output}"


# =============================================================================
# Auth Tools
# =============================================================================


@auto_heal()
async def _gh_auth_status_impl() -> str:
    """
    Check GitHub authentication status.

    Returns:
        Authentication status and logged-in user.
    """
    cmd = ["gh", "auth", "status"]

    success, output = await run_cmd(cmd, timeout=30, env=_get_gh_env())

    if success:
        return f"## GitHub Auth Status\n\n```\n{output}\n```"
    return f"⚠️ Auth status:\n\n```\n{output}\n```"


# =============================================================================
# Tool Registration
# =============================================================================


def register_tools(server: FastMCP) -> int:  # noqa: C901
    """
    Register GitHub CLI tools with the MCP server.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    registry = ToolRegistry(server)

    # Repository tools
    @auto_heal()
    @registry.tool()
    async def gh_repo_list(
        owner: str = "",
        limit: int = 30,
        visibility: str = "",
        language: str = "",
        topic: str = "",
    ) -> str:
        """
        List repositories.

        Args:
            owner: Owner/org to list repos for (default: authenticated user)
            limit: Maximum number of repos to list
            visibility: Filter by visibility (public, private, internal)
            language: Filter by primary language
            topic: Filter by topic

        Returns:
            List of repositories.
        """
        return await _gh_repo_list_impl(owner, limit, visibility, None, None, language, topic, None)

    @auto_heal()
    @registry.tool()
    async def gh_repo_view(repo: str = "", web: bool = False) -> str:
        """
        View repository details.

        Args:
            repo: Repository in OWNER/REPO format (default: current repo)
            web: Open in browser instead of showing details

        Returns:
            Repository details.
        """
        return await _gh_repo_view_impl(repo, web)

    @auto_heal()
    @registry.tool()
    async def gh_repo_clone(repo: str, directory: str = "", cwd: str = "") -> str:
        """
        Clone a repository.

        Args:
            repo: Repository in OWNER/REPO format or URL
            directory: Directory to clone into
            cwd: Working directory for clone operation

        Returns:
            Clone result.
        """
        return await _gh_repo_clone_impl(repo, directory, cwd)

    @auto_heal()
    @registry.tool()
    async def gh_repo_create(
        name: str,
        description: str = "",
        visibility: str = "private",
        clone: bool = False,
        template: str = "",
        add_readme: bool = False,
    ) -> str:
        """
        Create a new repository.

        Args:
            name: Repository name (or OWNER/NAME for org repos)
            description: Repository description
            visibility: Visibility (public, private, internal)
            clone: Clone the repository after creation
            template: Template repository to use (OWNER/REPO)
            add_readme: Add a README file

        Returns:
            Creation result.
        """
        return await _gh_repo_create_impl(name, description, visibility, clone, template, add_readme, "", "")

    @auto_heal()
    @registry.tool()
    async def gh_repo_fork(repo: str = "", clone: bool = False, org: str = "") -> str:
        """
        Fork a repository.

        Args:
            repo: Repository to fork (OWNER/REPO, default: current repo)
            clone: Clone the fork after creation
            org: Organization to fork into

        Returns:
            Fork result.
        """
        return await _gh_repo_fork_impl(repo, clone, True, org)

    # Pull Request tools
    @auto_heal()
    @registry.tool()
    async def gh_pr_list(
        repo: str = "",
        state: str = "open",
        limit: int = 30,
        author: str = "",
        label: str = "",
        base: str = "",
        cwd: str = "",
    ) -> str:
        """
        List pull requests.

        Args:
            repo: Repository (OWNER/REPO, default: current repo)
            state: PR state (open, closed, merged, all)
            limit: Maximum number of PRs to list
            author: Filter by author
            label: Filter by label
            base: Filter by base branch
            cwd: Working directory

        Returns:
            List of pull requests.
        """
        return await _gh_pr_list_impl(repo, state, limit, author, "", label, base, "", "", cwd)

    @auto_heal()
    @registry.tool()
    async def gh_pr_view(pr: str = "", repo: str = "", comments: bool = False, cwd: str = "") -> str:
        """
        View pull request details.

        Args:
            pr: PR number or branch name (default: current branch)
            repo: Repository (OWNER/REPO)
            comments: Include comments
            cwd: Working directory

        Returns:
            Pull request details.
        """
        return await _gh_pr_view_impl(pr, repo, comments, cwd)

    @auto_heal()
    @registry.tool()
    async def gh_pr_create(
        title: str,
        body: str = "",
        base: str = "",
        draft: bool = False,
        reviewer: str = "",
        label: str = "",
        repo: str = "",
        cwd: str = "",
    ) -> str:
        """
        Create a pull request.

        Args:
            title: PR title
            body: PR body/description
            base: Base branch (default: default branch)
            draft: Create as draft PR
            reviewer: Reviewers (comma-separated)
            label: Labels (comma-separated)
            repo: Repository (OWNER/REPO)
            cwd: Working directory

        Returns:
            Created PR details.
        """
        return await _gh_pr_create_impl(title, body, base, "", draft, "", reviewer, label, "", repo, cwd)

    @auto_heal()
    @registry.tool()
    async def gh_pr_checkout(pr: str, branch: str = "", repo: str = "", cwd: str = "") -> str:
        """
        Checkout a pull request locally.

        Args:
            pr: PR number or URL
            branch: Local branch name to use
            repo: Repository (OWNER/REPO)
            cwd: Working directory

        Returns:
            Checkout result.
        """
        return await _gh_pr_checkout_impl(pr, branch, repo, cwd)

    @auto_heal()
    @registry.tool()
    async def gh_pr_merge(
        pr: str = "",
        method: str = "merge",
        delete_branch: bool = True,
        auto: bool = False,
        repo: str = "",
        cwd: str = "",
    ) -> str:
        """
        Merge a pull request.

        Args:
            pr: PR number (default: PR for current branch)
            method: Merge method (merge, squash, rebase)
            delete_branch: Delete branch after merge
            auto: Enable auto-merge when checks pass
            repo: Repository (OWNER/REPO)
            cwd: Working directory

        Returns:
            Merge result.
        """
        return await _gh_pr_merge_impl(pr, method, delete_branch, auto, repo, cwd)

    @auto_heal()
    @registry.tool()
    async def gh_pr_close(pr: str, comment: str = "", repo: str = "", cwd: str = "") -> str:
        """
        Close a pull request.

        Args:
            pr: PR number
            comment: Comment to add when closing
            repo: Repository (OWNER/REPO)
            cwd: Working directory

        Returns:
            Close result.
        """
        return await _gh_pr_close_impl(pr, comment, repo, cwd)

    @auto_heal()
    @registry.tool()
    async def gh_pr_review(
        pr: str,
        action: str = "comment",
        body: str = "",
        repo: str = "",
        cwd: str = "",
    ) -> str:
        """
        Review a pull request.

        Args:
            pr: PR number
            action: Review action (approve, request-changes, comment)
            body: Review body/comment
            repo: Repository (OWNER/REPO)
            cwd: Working directory

        Returns:
            Review result.
        """
        return await _gh_pr_review_impl(pr, action, body, repo, cwd)

    @auto_heal()
    @registry.tool()
    async def gh_pr_diff(pr: str = "", repo: str = "", cwd: str = "") -> str:
        """
        View pull request diff.

        Args:
            pr: PR number (default: current branch)
            repo: Repository (OWNER/REPO)
            cwd: Working directory

        Returns:
            PR diff.
        """
        return await _gh_pr_diff_impl(pr, repo, cwd)

    @auto_heal()
    @registry.tool()
    async def gh_pr_checks(pr: str = "", repo: str = "", cwd: str = "") -> str:
        """
        View PR check/CI status.

        Args:
            pr: PR number (default: current branch)
            repo: Repository (OWNER/REPO)
            cwd: Working directory

        Returns:
            Check status.
        """
        return await _gh_pr_checks_impl(pr, repo, cwd)

    # Issue tools
    @auto_heal()
    @registry.tool()
    async def gh_issue_list(
        repo: str = "",
        state: str = "open",
        limit: int = 30,
        author: str = "",
        assignee: str = "",
        label: str = "",
        cwd: str = "",
    ) -> str:
        """
        List issues.

        Args:
            repo: Repository (OWNER/REPO, default: current repo)
            state: Issue state (open, closed, all)
            limit: Maximum number of issues to list
            author: Filter by author
            assignee: Filter by assignee
            label: Filter by label
            cwd: Working directory

        Returns:
            List of issues.
        """
        return await _gh_issue_list_impl(repo, state, limit, author, assignee, label, "", "", cwd)

    @auto_heal()
    @registry.tool()
    async def gh_issue_view(issue: str, repo: str = "", comments: bool = False, cwd: str = "") -> str:
        """
        View issue details.

        Args:
            issue: Issue number
            repo: Repository (OWNER/REPO)
            comments: Include comments
            cwd: Working directory

        Returns:
            Issue details.
        """
        return await _gh_issue_view_impl(issue, repo, comments, cwd)

    @auto_heal()
    @registry.tool()
    async def gh_issue_create(
        title: str,
        body: str = "",
        assignee: str = "",
        label: str = "",
        repo: str = "",
        cwd: str = "",
    ) -> str:
        """
        Create an issue.

        Args:
            title: Issue title
            body: Issue body/description
            assignee: Assignees (comma-separated)
            label: Labels (comma-separated)
            repo: Repository (OWNER/REPO)
            cwd: Working directory

        Returns:
            Created issue details.
        """
        return await _gh_issue_create_impl(title, body, assignee, label, "", repo, cwd)

    @auto_heal()
    @registry.tool()
    async def gh_issue_close(issue: str, reason: str = "", comment: str = "", repo: str = "", cwd: str = "") -> str:
        """
        Close an issue.

        Args:
            issue: Issue number
            reason: Close reason (completed, not_planned)
            comment: Comment to add when closing
            repo: Repository (OWNER/REPO)
            cwd: Working directory

        Returns:
            Close result.
        """
        return await _gh_issue_close_impl(issue, reason, comment, repo, cwd)

    @auto_heal()
    @registry.tool()
    async def gh_issue_comment(issue: str, body: str, repo: str = "", cwd: str = "") -> str:
        """
        Add a comment to an issue.

        Args:
            issue: Issue number
            body: Comment body
            repo: Repository (OWNER/REPO)
            cwd: Working directory

        Returns:
            Comment result.
        """
        return await _gh_issue_comment_impl(issue, body, repo, cwd)

    # Workflow/Actions tools
    @auto_heal()
    @registry.tool()
    async def gh_workflow_list(repo: str = "", limit: int = 50, cwd: str = "") -> str:
        """
        List workflows.

        Args:
            repo: Repository (OWNER/REPO)
            limit: Maximum number of workflows to list
            cwd: Working directory

        Returns:
            List of workflows.
        """
        return await _gh_workflow_list_impl(repo, limit, cwd)

    @auto_heal()
    @registry.tool()
    async def gh_run_list(
        repo: str = "",
        workflow: str = "",
        branch: str = "",
        status: str = "",
        limit: int = 20,
        cwd: str = "",
    ) -> str:
        """
        List workflow runs.

        Args:
            repo: Repository (OWNER/REPO)
            workflow: Filter by workflow name or ID
            branch: Filter by branch
            status: Filter by status (queued, in_progress, completed, etc.)
            limit: Maximum number of runs to list
            cwd: Working directory

        Returns:
            List of workflow runs.
        """
        return await _gh_run_list_impl(repo, workflow, branch, "", status, limit, cwd)

    @auto_heal()
    @registry.tool()
    async def gh_run_view(run_id: str, repo: str = "", log: bool = False, cwd: str = "") -> str:
        """
        View workflow run details.

        Args:
            run_id: Run ID
            repo: Repository (OWNER/REPO)
            log: Show run log
            cwd: Working directory

        Returns:
            Run details.
        """
        return await _gh_run_view_impl(run_id, repo, log, cwd)

    @auto_heal()
    @registry.tool()
    async def gh_run_rerun(run_id: str, failed: bool = False, repo: str = "", cwd: str = "") -> str:
        """
        Re-run a workflow.

        Args:
            run_id: Run ID
            failed: Only re-run failed jobs
            repo: Repository (OWNER/REPO)
            cwd: Working directory

        Returns:
            Rerun result.
        """
        return await _gh_run_rerun_impl(run_id, failed, repo, cwd)

    @auto_heal()
    @registry.tool()
    async def gh_run_cancel(run_id: str, repo: str = "", cwd: str = "") -> str:
        """
        Cancel a workflow run.

        Args:
            run_id: Run ID
            repo: Repository (OWNER/REPO)
            cwd: Working directory

        Returns:
            Cancel result.
        """
        return await _gh_run_cancel_impl(run_id, repo, cwd)

    # Release tools
    @auto_heal()
    @registry.tool()
    async def gh_release_list(repo: str = "", limit: int = 30, cwd: str = "") -> str:
        """
        List releases.

        Args:
            repo: Repository (OWNER/REPO)
            limit: Maximum number of releases to list
            cwd: Working directory

        Returns:
            List of releases.
        """
        return await _gh_release_list_impl(repo, limit, cwd)

    @auto_heal()
    @registry.tool()
    async def gh_release_view(tag: str = "", repo: str = "", cwd: str = "") -> str:
        """
        View release details.

        Args:
            tag: Release tag (default: latest)
            repo: Repository (OWNER/REPO)
            cwd: Working directory

        Returns:
            Release details.
        """
        return await _gh_release_view_impl(tag, repo, cwd)

    @auto_heal()
    @registry.tool()
    async def gh_release_create(
        tag: str,
        title: str = "",
        notes: str = "",
        target: str = "",
        draft: bool = False,
        prerelease: bool = False,
        generate_notes: bool = False,
        repo: str = "",
        cwd: str = "",
    ) -> str:
        """
        Create a release.

        Args:
            tag: Release tag
            title: Release title
            notes: Release notes
            target: Target branch or commit SHA
            draft: Create as draft
            prerelease: Mark as prerelease
            generate_notes: Auto-generate release notes
            repo: Repository (OWNER/REPO)
            cwd: Working directory

        Returns:
            Created release details.
        """
        return await _gh_release_create_impl(
            tag, title, notes, target, draft, prerelease, generate_notes, "", repo, cwd
        )

    @auto_heal()
    @registry.tool()
    async def gh_release_delete(tag: str, cleanup_tag: bool = False, repo: str = "", cwd: str = "") -> str:
        """
        Delete a release.

        Args:
            tag: Release tag
            cleanup_tag: Also delete the git tag
            repo: Repository (OWNER/REPO)
            cwd: Working directory

        Returns:
            Delete result.
        """
        return await _gh_release_delete_impl(tag, cleanup_tag, repo, cwd)

    # Search tools
    @auto_heal()
    @registry.tool()
    async def gh_search_repos(
        query: str,
        limit: int = 30,
        sort: str = "",
        language: str = "",
        owner: str = "",
    ) -> str:
        """
        Search repositories.

        Args:
            query: Search query
            limit: Maximum results
            sort: Sort by (stars, forks, updated, help-wanted-issues)
            language: Filter by language
            owner: Filter by owner

        Returns:
            Search results.
        """
        return await _gh_search_repos_impl(query, limit, sort, "", language, owner)

    @auto_heal()
    @registry.tool()
    async def gh_search_issues(
        query: str,
        limit: int = 30,
        sort: str = "",
        state: str = "",
        repo: str = "",
    ) -> str:
        """
        Search issues and pull requests.

        Args:
            query: Search query
            limit: Maximum results
            sort: Sort by (created, updated, comments, reactions)
            state: Filter by state (open, closed)
            repo: Filter by repository

        Returns:
            Search results.
        """
        return await _gh_search_issues_impl(query, limit, sort, "", state, repo)

    @auto_heal()
    @registry.tool()
    async def gh_search_code(
        query: str,
        limit: int = 30,
        repo: str = "",
        language: str = "",
        extension: str = "",
    ) -> str:
        """
        Search code.

        Args:
            query: Search query
            limit: Maximum results
            repo: Filter by repository
            language: Filter by language
            extension: Filter by file extension

        Returns:
            Search results.
        """
        return await _gh_search_code_impl(query, limit, repo, language, "", extension)

    # Gist tools
    @auto_heal()
    @registry.tool()
    async def gh_gist_list(limit: int = 30) -> str:
        """
        List gists.

        Args:
            limit: Maximum number of gists to list

        Returns:
            List of gists.
        """
        return await _gh_gist_list_impl(limit, None)

    @auto_heal()
    @registry.tool()
    async def gh_gist_view(gist_id: str, filename: str = "", raw: bool = False) -> str:
        """
        View gist contents.

        Args:
            gist_id: Gist ID or URL
            filename: Specific file to view
            raw: Show raw content without formatting

        Returns:
            Gist contents.
        """
        return await _gh_gist_view_impl(gist_id, filename, raw)

    @auto_heal()
    @registry.tool()
    async def gh_gist_create(files: str, description: str = "", public: bool = False) -> str:
        """
        Create a gist.

        Args:
            files: Files to include (space-separated paths)
            description: Gist description
            public: Make gist public

        Returns:
            Created gist URL.
        """
        return await _gh_gist_create_impl(files, description, public)

    # Auth tools
    @auto_heal()
    @registry.tool()
    async def gh_auth_status() -> str:
        """
        Check GitHub authentication status.

        Returns:
            Authentication status and logged-in user.
        """
        return await _gh_auth_status_impl()

    return registry.count
