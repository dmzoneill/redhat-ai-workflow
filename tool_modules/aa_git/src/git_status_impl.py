# pylint: disable=duplicate-code
"""Git tool definitions.

This module provides the tool registration function that can be called
by the shared server infrastructure.
"""

import logging
import os

from fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization


from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import resolve_repo_path
from tool_modules.aa_make.src.tools_basic import (  # pylint: disable=ungrouped-imports
    _shared__make_target_impl,
)

logger = logging.getLogger(__name__)

from tool_modules.aa_git.src.git_log_impl import (  # pylint: disable=wrong-import-position
    _format_status_sections,
    _git_blame_impl,
    _git_log_impl,
    _git_merge_abort_impl,
    _git_merge_impl,
    _git_pull_impl,
    _git_push_impl,
    _git_rebase_impl,
    _git_reset_impl,
    _git_rev_parse_impl,
    _git_show_impl,
    _git_stash_impl,
    _parse_status_output,
)
from tool_modules.aa_git.src.git_tools_impl import (  # pylint: disable=wrong-import-position
    _code_format_impl,
    _code_lint_impl,
    _docker_compose_status_impl,
    _docker_compose_up_impl,
    _docker_cp_impl,
    _docker_exec_impl,
    _git_add_impl,
    _git_branch_create_impl,
    _git_branch_list_impl,
    _git_checkout_impl,
    _git_commit_impl,
    _git_config_get_impl,
    _git_diff_impl,
    _git_diff_tree_impl,
    _git_fetch_impl,
    run_git,
)


async def _git_status_impl(repo: str) -> str:
    """
    Get the current status of a git repository.

    Args:
        repo: Repository path (e.g., "/home/user/src/myproject" or "myproject")

    Returns:
        Current branch, staged/unstaged changes, untracked files.
    """
    path = resolve_repo_path(repo)
    if not os.path.isdir(path):
        return f"❌ Not a directory: {path}"

    lines = [f"## Git Status: `{repo}`", ""]

    success, branch = await run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    if success:
        lines.append(f"**Branch:** `{branch.strip()}`")

    success, output = await run_git(["status", "--porcelain"], cwd=path)
    if not success:
        return f"❌ Failed to get status: {output}"

    if not output.strip():
        lines.append("\n✅ Working tree clean")
    else:
        # Parse output using helper
        staged, modified, untracked = _parse_status_output(output)

        # Format sections using helper
        lines.extend(_format_status_sections(staged, modified, untracked))

    success, output = await run_git(
        ["rev-list", "--left-right", "--count", "@{u}...HEAD"], cwd=path
    )
    if success and output.strip():
        parts = output.strip().split()
        if len(parts) == 2:
            behind, ahead = int(parts[0]), int(parts[1])
            if ahead or behind:
                lines.append(f"\n**Sync:** ↑{ahead} ahead, ↓{behind} behind remote")

    return "\n".join(lines)


@auto_heal()
async def _make_target_impl(repo: str, target: str, timeout: int = 120) -> str:
    return await _shared__make_target_impl(repo, target, timeout)


_make_target_impl.__doc__ = _shared__make_target_impl.__doc__


def _register_code_quality_tools(registry: ToolRegistry) -> None:
    """Register code quality tools."""

    @auto_heal()
    @registry.tool()
    async def git_format(
        repo: str,
        check_only: bool = False,
        tool: str = "black",
        paths: str = ".",
    ) -> str:
        """
        Format code using black, isort, or ruff.

        Args:
            repo: Repository path
            check_only: Just check formatting, don't modify files
            tool: Formatter to use (black, isort, ruff)
            paths: Paths to format (default: current directory)

        Returns:
            Formatting result.
        """
        return await _code_format_impl(repo, check_only, tool, paths)

    @auto_heal()
    @registry.tool()
    async def git_lint(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        repo: str,
        tool: str = "flake8",
        paths: str = ".",
        max_line_length: int = 100,
        ignore: str = "E501,W503,E203",
        exclude: str = ".git,__pycache__,migrations,venv,.venv",
    ) -> str:
        """
        Run linting checks on code using flake8, ruff, or pylint.

        Args:
            repo: Repository path
            tool: Linter to use (flake8, ruff, pylint)
            paths: Paths to lint (default: current directory)
            max_line_length: Maximum line length (default: 100)
            ignore: Comma-separated error codes to ignore
            exclude: Comma-separated directories to exclude

        Returns:
            Linting results with issues found.
        """
        return await _code_lint_impl(
            repo, tool, paths, max_line_length, ignore, exclude
        )


def _register_docker_tools(registry: ToolRegistry) -> None:
    """Register docker tools."""

    @auto_heal()
    @registry.tool()
    async def docker_compose_status(
        repo: str,
        filter_name: str = "",
    ) -> str:
        """
        Check docker-compose container status.

        Args:
            repo: Repository path (where docker-compose.yml is)
            filter_name: Filter containers by name

        Returns:
            Container status.
        """
        return await _docker_compose_status_impl(repo, filter_name)

    @auto_heal()
    @registry.tool()
    async def docker_compose_up(
        repo: str,
        detach: bool = True,
        services: str = "",
        timeout: int = 180,
    ) -> str:
        """
        Start docker-compose services.

        Args:
            repo: Repository path (where docker-compose.yml is)
            detach: Run in background
            services: Specific services to start (space-separated, empty = all)
            timeout: Timeout in seconds

        Returns:
            Startup result.
        """
        return await _docker_compose_up_impl(repo, detach, services, timeout)

    @auto_heal()
    @registry.tool()
    async def docker_cp(
        source: str,
        destination: str,
        to_container: bool = True,
    ) -> str:
        """
        Copy files to/from a Docker container.

        Args:
            source: Source path (local path or container:path)
            destination: Destination path (container:path or local path)
            to_container: If True, copy from local to container

        Returns:
            Copy result.

        Examples:
            docker_cp("/tmp/script.sh", "my_container:/tmp/script.sh", to_container=True)
            docker_cp("my_container:/var/log/app.log", "/tmp/app.log", to_container=False)
        """
        return await _docker_cp_impl(source, destination, to_container)

    @auto_heal()
    @registry.tool()
    async def docker_exec(
        container: str,
        command: str,
        timeout: int = 300,
    ) -> str:
        """
        Execute a command in a running Docker container.

        Args:
            container: Container name or ID
            command: Command to execute
            timeout: Timeout in seconds

        Returns:
            Command output.
        """
        return await _docker_exec_impl(container, command, timeout)


def _register_git_basic_ops_tools(registry: ToolRegistry) -> None:
    """Register git basic ops tools."""

    @auto_heal()
    @registry.tool()
    async def git_add(repo: str, files: str = ".") -> str:
        """Stage files for commit."""
        return await _git_add_impl(repo, files)

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
        """Show uncommitted changes."""
        return await _git_diff_impl(repo, staged, file)

    @auto_heal()
    @registry.tool()
    async def git_diff_tree(
        repo: str,
        commit: str,
        name_only: bool = True,
    ) -> str:
        """
        Get list of files changed in a commit.

        Args:
            repo: Repository path
            commit: Commit SHA to inspect
            name_only: Return only filenames (default: True)

        Returns:
            List of changed files.
        """
        return await _git_diff_tree_impl(repo, commit, name_only)

    @auto_heal()
    @registry.tool()
    async def git_show(
        repo: str,
        commit: str = "HEAD",
        format: str = "",  # pylint: disable=redefined-builtin
        name_only: bool = False,
    ) -> str:
        """
        Show commit details.

        Args:
            repo: Repository path
            commit: Commit SHA or reference (default: HEAD)
            format: Custom format string (e.g., "%s%n%b" for subject+body)
            name_only: Show only file names, not diff

        Returns:
            Commit details.
        """
        return await _git_show_impl(repo, commit, format, name_only)

    @auto_heal()
    @registry.tool()
    async def git_log(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        repo: str,
        limit: int = 10,
        oneline: bool = True,
        author: str = "",
        since: str = "",
        until: str = "",
        branch: str = "",
        range_spec: str = "",
        merges_only: bool = False,
        no_merges: bool = False,
        count_only: bool = False,
        numstat: bool = False,
    ) -> str:
        """
        Show commit history with optional filters.

        Args:
            repo: Repository name or path
            limit: Maximum commits to show
            oneline: Use compact format
            author: Filter by author name/email
            since: Only commits after date (e.g., "2024-01-01", "yesterday", "1 week ago")
            until: Only commits before date
            branch: Specific branch to show (default: current)
            range_spec: Commit range (e.g., "origin/main..HEAD", "main..feature")
            merges_only: Show only merge commits (--merges)
            no_merges: Exclude merge commits (--no-merges)
            count_only: Return only count of commits (for range comparisons)
            numstat: Show number of added/deleted lines per file (--numstat)

        Returns:
            Commit history or count.

        Examples:
            git_log(repo, range_spec="origin/main..HEAD")  # Commits ahead of main
            git_log(repo, merges_only=True, range_spec="main..feature")  # Merge commits only
            git_log(repo, count_only=True, range_spec="HEAD..origin/main")  # How many behind
            git_log(repo, numstat=True, since="1 week ago")  # Lines changed this week
        """
        return await _git_log_impl(
            repo,
            limit,
            oneline,
            author,
            since,
            until,
            branch,
            range_spec,
            merges_only,
            no_merges,
            count_only,
            numstat,
        )


def _register_git_branching_tools(registry: ToolRegistry) -> None:
    """Register git branching tools."""

    @auto_heal()
    @registry.tool()
    async def git_branch_create(
        repo: str, branch_name: str, base: str = "", checkout: bool = True
    ) -> str:
        """Create a new branch."""
        return await _git_branch_create_impl(repo, branch_name, base, checkout)

    @auto_heal()
    @registry.tool()
    async def git_branch_list(
        repo: str,
        all_branches: bool = False,
        merged: str = "",
        no_merged: str = "",
    ) -> str:
        """
        List branches in a repository.

        Args:
            repo: Repository path
            all_branches: Include remote branches
            merged: Show branches merged into specified branch (e.g., "main")
            no_merged: Show branches NOT merged into specified branch

        Returns:
            Branch list.
        """
        return await _git_branch_list_impl(repo, all_branches, merged, no_merged)

    @auto_heal()
    @registry.tool()
    async def git_checkout(
        repo: str,
        target: str,
        create: bool = False,
        force_create: bool = False,
        start_point: str = "",
    ) -> str:
        """
        Switch branches or restore files.

        Args:
            repo: Repository path
            target: Branch name or file to checkout
            create: Create new branch (-b flag)
            force_create: Force create branch, resetting if exists (-B flag)
            start_point: Starting point for new branch (e.g., "origin/main")

        Returns:
            Checkout result.

        Examples:
            git_checkout(repo, "main")  # Switch to main
            git_checkout(repo, "feature", create=True)  # Create and switch
            git_checkout(repo, "feature", force_create=True, start_point="origin/feature")
        """
        return await _git_checkout_impl(repo, target, create, force_create, start_point)

    @auto_heal()
    @registry.tool()
    async def git_config_get(repo: str, key: str) -> str:
        """
        Get a git config value.

        Args:
            repo: Repository path
            key: Config key (e.g., "user.email", "user.name", "remote.origin.url")

        Returns:
            Config value or error message.
        """
        return await _git_config_get_impl(repo, key)


def _register_git_commits_tools(registry: ToolRegistry) -> None:
    """Register git commits tools."""

    @auto_heal()
    @registry.tool()
    async def git_commit(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        repo: str,
        message: str,
        all_changes: bool = False,
        issue_key: str = "",
        commit_type: str = "",
        scope: str = "",
        run_lint: bool = False,
    ) -> str:
        """
        Commit staged changes with optional conventional commit format.

        Args:
            repo: Repository path
            message: Commit message
            all_changes: Stage all changes before commit (-a flag)
            issue_key: Jira issue key for conventional commit prefix
            commit_type: Commit type (feat, fix, refactor, etc.)
            scope: Optional scope for conventional commit
            run_lint: Run black/flake8 check before committing (blocks on errors)

        Returns:
            Commit result or lint error.

        Commit Format (from config.json):
            {issue_key} - {type}({scope}): {description}

        Valid types are loaded from config.json commit_format.types.
        """
        return await _git_commit_impl(
            repo, message, all_changes, issue_key, commit_type, scope, run_lint
        )

    @auto_heal()
    @registry.tool()
    async def git_fetch(
        repo: str,
        prune: bool = True,
        remote: str = "",
        branch: str = "",
        refspec: str = "",
    ) -> str:
        """
        Fetch changes from remote without merging.

        Args:
            repo: Repository path
            prune: Remove remote-tracking refs that no longer exist on remote
            remote: Specific remote to fetch from (default: all)
            branch: Specific branch to fetch
            refspec: Custom refspec (e.g., "merge-requests/123/head:mr-123")

        Returns:
            Fetch result.
        """
        return await _git_fetch_impl(repo, prune, remote, branch, refspec)

    @auto_heal()
    @registry.tool()
    async def git_rev_parse(
        repo: str,
        ref: str,
        short: bool = False,
        verify: bool = True,
    ) -> str:
        """
        Resolve a git reference to its SHA.

        Args:
            repo: Repository path
            ref: Reference to resolve (branch, tag, short SHA, HEAD, etc.)
            short: Return short SHA (7 chars) instead of full 40-char
            verify: Verify the reference exists (fail if not found)

        Returns:
            The resolved SHA, or error message.

        Examples:
            git_rev_parse(repo, "HEAD")           -> "a1b2c3d4e5..."
            git_rev_parse(repo, "main")           -> "f6g7h8i9..."
            git_rev_parse(repo, "abc123", short=True) -> "abc1234"
        """
        return await _git_rev_parse_impl(repo, ref, short, verify)


def _register_git_remote_tools(registry: ToolRegistry) -> None:
    """Register git remote tools."""

    @auto_heal()
    @registry.tool()
    async def git_pull(repo: str, rebase: bool = False) -> str:
        """Pull changes from remote."""
        return await _git_pull_impl(repo, rebase)

    @auto_heal()
    @registry.tool()
    async def git_push(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        repo: str,
        branch: str = "",
        set_upstream: bool = False,
        force: bool = False,
        dry_run: bool = False,
        run_lint: bool = False,
    ) -> str:
        """
        Push commits to remote.

        Args:
            repo: Repository path
            branch: Branch to push (default: current)
            set_upstream: Set upstream tracking (-u flag)
            force: Force push with lease (--force-with-lease)
            dry_run: Show what would be pushed without pushing
            run_lint: Run black/flake8 check before pushing (blocks on errors)

        Returns:
            Push result or lint error.
        """
        return await _git_push_impl(
            repo, branch, set_upstream, force, dry_run, run_lint
        )


def _register_git_advanced_tools(registry: ToolRegistry) -> None:
    """Register git advanced tools."""

    @auto_heal()
    @registry.tool()
    async def git_merge(
        repo: str,
        target: str,
        no_commit: bool = False,
        no_ff: bool = False,
        message: str = "",
    ) -> str:
        """
        Merge a branch into the current branch.

        Args:
            repo: Repository path
            target: Branch or commit to merge
            no_commit: Don't commit the merge (for testing mergeability)
            no_ff: Always create a merge commit, even if fast-forward is possible
            message: Custom merge commit message

        Returns:
            Merge result.
        """
        return await _git_merge_impl(repo, target, no_commit, no_ff, message)

    @auto_heal()
    @registry.tool()
    async def git_merge_abort(repo: str) -> str:
        """
        Abort an in-progress merge.

        Args:
            repo: Repository path

        Returns:
            Success or error message.
        """
        return await _git_merge_abort_impl(repo)

    @auto_heal()
    @registry.tool()
    async def git_rebase(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        repo: str,
        onto: str = "",
        abort: bool = False,
        continue_rebase: bool = False,
        skip: bool = False,
        interactive: bool = False,
    ) -> str:
        """
        Rebase current branch onto another branch, or manage in-progress rebase.

        Args:
            repo: Repository path
            onto: Branch/commit to rebase onto (e.g., "origin/main", "main")
            abort: Abort an in-progress rebase
            continue_rebase: Continue after resolving conflicts
            skip: Skip current commit and continue rebase
            interactive: Use interactive rebase (opens editor - not recommended for automation)

        Returns:
            Rebase status with conflict information if any.
        """
        return await _git_rebase_impl(
            repo, onto, abort, continue_rebase, skip, interactive
        )

    @auto_heal()
    @registry.tool()
    async def git_reset(repo: str, target: str = "HEAD", mode: str = "mixed") -> str:
        """Reset current HEAD to specified state."""
        return await _git_reset_impl(repo, target, mode)

    @auto_heal()
    @registry.tool()
    async def git_stash(repo: str, action: str = "push", message: str = "") -> str:
        """Stash or restore changes."""
        return await _git_stash_impl(repo, action, message)

    @auto_heal()
    @registry.tool()
    async def git_blame(repo: str, file: str, lines: str = "") -> str:
        """Get blame information for a file.

        Args:
            repo: Repository path
            file: File path to blame
            lines: Optional line range (e.g., "1,10" for lines 1-10)

        Returns:
            Blame output showing who last modified each line.
        """
        return await _git_blame_impl(repo, file, lines)


def _register_build_tools(registry: ToolRegistry) -> None:
    """Register build tools."""

    @auto_heal()
    @registry.tool()
    async def make_target(
        repo: str,
        target: str,
        timeout: int = 120,
    ) -> str:
        """
        Run a make target in the repository.

        Args:
            repo: Repository path
            target: Make target to run (e.g., "test", "migrations", "data", "build")
            timeout: Timeout in seconds

        Returns:
            Make output.
        """
        return await _make_target_impl(repo, target, timeout)


def register_tools(server: FastMCP) -> int:
    """
    Register git tools with the MCP server.

    Note: Some tools have been moved to separate modules:
    - aa_docker: docker_compose_*, docker_cp, docker_exec
    - aa_make: make_target

    This module includes git_format and git_lint for code quality checks.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    registry = ToolRegistry(server)

    # Only register git-specific tools
    _register_git_basic_ops_tools(registry)
    _register_git_branching_tools(registry)
    _register_git_commits_tools(registry)
    _register_git_remote_tools(registry)
    _register_git_advanced_tools(registry)

    return registry.count
