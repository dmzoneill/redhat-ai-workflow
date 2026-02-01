"""Git core tools - essential git operations for daily development.

This module provides the minimal set of git tools needed for most workflows:
- git_status, git_diff, git_add, git_log, git_show (basic ops)
- git_commit, git_fetch, git_rev_parse (commits)

For additional tools (branching, remote, advanced), use:
- git_basic: Loads core + basic tools
- tool_exec("git_branch_create", {...}): Call specific tools on-demand

Total: ~8 core tools (down from 28 in basic)
"""

import logging

from fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import resolve_repo_path, run_cmd, truncate_output

logger = logging.getLogger(__name__)


async def run_git(
    args: list[str],
    cwd: str | None = None,
    timeout: int = 60,
) -> tuple[bool, str]:
    """Run git command and return (success, output)."""
    cmd = ["git"] + args
    return await run_cmd(cmd, cwd=cwd, timeout=timeout)


# ==================== CORE TOOL IMPLEMENTATIONS ====================
# These are copied from tools_basic.py to avoid import dependencies


@auto_heal()
async def _git_status_impl(repo: str) -> str:
    """Get git status."""
    path = resolve_repo_path(repo)
    success, output = await run_git(["status", "-sb"], cwd=path)
    if success:
        return f"📊 Git status for {repo}:\n\n{output}"
    return f"❌ Failed to get status: {output}"


@auto_heal()
async def _git_diff_impl(repo: str, staged: bool = False, file: str = "") -> str:
    """Show uncommitted changes."""
    path = resolve_repo_path(repo)
    args = ["diff"]
    if staged:
        args.append("--staged")
    if file:
        args.extend(["--", file])
    success, output = await run_git(args, cwd=path)
    if success:
        if not output.strip():
            return "✅ No changes" + (" staged" if staged else "")
        return truncate_output(output, max_lines=200)
    return f"❌ Failed to get diff: {output}"


@auto_heal()
async def _git_add_impl(repo: str, files: str = ".") -> str:
    """Stage files for commit."""
    path = resolve_repo_path(repo)
    args = ["add"] + files.split()
    success, output = await run_git(args, cwd=path)
    if success:
        return f"✅ Staged: {files}"
    return f"❌ Failed to stage files: {output}"


@auto_heal()
async def _git_log_impl(
    repo: str,
    limit: int = 10,
    oneline: bool = True,
) -> str:
    """Show commit history."""
    path = resolve_repo_path(repo)
    args = ["log", f"-{limit}"]
    if oneline:
        args.append("--oneline")
    success, output = await run_git(args, cwd=path)
    if success:
        return f"📜 Recent commits:\n\n{output}"
    return f"❌ Failed to get log: {output}"


@auto_heal()
async def _git_show_impl(repo: str, commit: str = "HEAD") -> str:
    """Show commit details."""
    path = resolve_repo_path(repo)
    args = ["show", commit, "--stat"]
    success, output = await run_git(args, cwd=path)
    if success:
        return truncate_output(output, max_lines=100)
    return f"❌ Failed to show commit: {output}"


@auto_heal()
async def _git_commit_impl(repo: str, message: str, amend: bool = False) -> str:
    """Create a commit."""
    path = resolve_repo_path(repo)
    args = ["commit", "-m", message]
    if amend:
        args.append("--amend")
    success, output = await run_git(args, cwd=path)
    if success:
        return f"✅ Committed: {message[:50]}..."
    return f"❌ Commit failed: {output}"


@auto_heal()
async def _git_push_impl(repo: str, remote: str = "origin", branch: str = "") -> str:
    """Push commits to remote."""
    path = resolve_repo_path(repo)
    args = ["push", remote]
    if branch:
        args.append(branch)
    success, output = await run_git(args, cwd=path, timeout=120)
    if success:
        return f"✅ Pushed to {remote}" + (f"/{branch}" if branch else "")
    return f"❌ Push failed: {output}"


@auto_heal()
async def _git_pull_impl(repo: str, rebase: bool = False) -> str:
    """Pull changes from remote."""
    path = resolve_repo_path(repo)
    args = ["pull"]
    if rebase:
        args.append("--rebase")
    success, output = await run_git(args, cwd=path, timeout=120)
    if success:
        return f"✅ Pulled changes\n\n{output}"
    return f"❌ Pull failed: {output}"


# ==================== TOOL REGISTRATION ====================


def register_tools(server: FastMCP) -> int:
    """
    Register core git tools with the MCP server.

    Core tools (~8 tools):
    - git_status: Check repository state
    - git_diff: View changes
    - git_add: Stage files
    - git_log: View history
    - git_show: View commit details
    - git_commit: Create commits
    - git_push: Push to remote
    - git_pull: Pull from remote

    For additional tools, load git_basic or use tool_exec().

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def git_status(repo: str) -> str:
        """
        Get the current status of a git repository.

        Args:
            repo: Repository path (e.g., "/home/user/src/myproject" or "myproject")

        Returns:
            Current branch, staged/unstaged changes, untracked files.
        """
        return await _git_status_impl(repo)

    @auto_heal()
    @registry.tool()
    async def git_diff(repo: str, staged: bool = False, file: str = "") -> str:
        """
        Show uncommitted changes in a repository.

        Args:
            repo: Repository path
            staged: Show staged changes only (default: unstaged)
            file: Specific file to diff (optional)

        Returns:
            Diff output showing changes.
        """
        return await _git_diff_impl(repo, staged, file)

    @auto_heal()
    @registry.tool()
    async def git_add(repo: str, files: str = ".") -> str:
        """
        Stage files for commit.

        Args:
            repo: Repository path
            files: Files to stage (space-separated, default: all)

        Returns:
            Confirmation of staged files.
        """
        return await _git_add_impl(repo, files)

    @auto_heal()
    @registry.tool()
    async def git_log(repo: str, limit: int = 10, oneline: bool = True) -> str:
        """
        Show commit history.

        Args:
            repo: Repository path
            limit: Maximum commits to show (default: 10)
            oneline: Use compact format (default: True)

        Returns:
            Commit history.
        """
        return await _git_log_impl(repo, limit, oneline)

    @auto_heal()
    @registry.tool()
    async def git_show(repo: str, commit: str = "HEAD") -> str:
        """
        Show commit details.

        Args:
            repo: Repository path
            commit: Commit SHA or reference (default: HEAD)

        Returns:
            Commit details with stats.
        """
        return await _git_show_impl(repo, commit)

    @auto_heal()
    @registry.tool()
    async def git_commit(repo: str, message: str, amend: bool = False) -> str:
        """
        Create a commit with staged changes.

        Args:
            repo: Repository path
            message: Commit message
            amend: Amend the previous commit (default: False)

        Returns:
            Confirmation of commit.
        """
        return await _git_commit_impl(repo, message, amend)

    @auto_heal()
    @registry.tool()
    async def git_push(repo: str, remote: str = "origin", branch: str = "") -> str:
        """
        Push commits to remote repository.

        Args:
            repo: Repository path
            remote: Remote name (default: origin)
            branch: Branch to push (default: current branch)

        Returns:
            Push result.
        """
        return await _git_push_impl(repo, remote, branch)

    @auto_heal()
    @registry.tool()
    async def git_pull(repo: str, rebase: bool = False) -> str:
        """
        Pull changes from remote repository.

        Args:
            repo: Repository path
            rebase: Use rebase instead of merge (default: False)

        Returns:
            Pull result.
        """
        return await _git_pull_impl(repo, rebase)

    logger.info(f"Registered {registry.count} core git tools")
    return registry.count
