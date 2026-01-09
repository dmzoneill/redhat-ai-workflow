"""Git Basic Tools - Essential git operations.

This module provides the basic git tools used for everyday development.
For advanced operations (rebase, merge, docker), see tools_extra.py.

Tools included (~15):
- git_status, git_config_get, git_branch_list, git_log, git_diff
- git_branch_create, git_checkout, git_add, git_commit
- git_push, git_pull, git_fetch, git_stash, git_remote_info
"""

import logging
import os

from mcp.server.fastmcp import FastMCP

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import resolve_repo_path, run_cmd, truncate_output

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT  # noqa: F401 - side effect: adds to sys.path

logger = logging.getLogger(__name__)


async def run_git(
    args: list[str],
    cwd: str | None = None,
    timeout: int = 60,
) -> tuple[bool, str]:
    """Run git command and return (success, output)."""
    cmd = ["git"] + args
    return await run_cmd(cmd, cwd=cwd, timeout=timeout)


def register_tools(server: FastMCP) -> int:
    """Register basic git tools with the MCP server."""
    registry = ToolRegistry(server)

    # ==================== STATUS & INFO ====================

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
            staged = []
            modified = []
            untracked = []

            for line in output.strip().split("\n"):
                if not line:
                    continue
                status = line[:2]
                file = line[3:]

                if status[0] in "MADRC":
                    staged.append(f"  - `{file}`")
                if status[1] == "M":
                    modified.append(f"  - `{file}`")
                elif status == "??":
                    untracked.append(f"  - `{file}`")

            if staged:
                lines.append("\n### Staged")
                lines.extend(staged)
            if modified:
                lines.append("\n### Modified (unstaged)")
                lines.extend(modified)
            if untracked:
                lines.append("\n### Untracked")
                lines.extend(untracked[:10])
                if len(untracked) > 10:
                    lines.append(f"  - ... and {len(untracked) - 10} more")

        success, output = await run_git(["rev-list", "--left-right", "--count", "@{u}...HEAD"], cwd=path)
        if success and output.strip():
            parts = output.strip().split()
            if len(parts) == 2:
                behind, ahead = int(parts[0]), int(parts[1])
                if ahead or behind:
                    lines.append(f"\n**Sync:** ↑{ahead} ahead, ↓{behind} behind remote")

        return "\n".join(lines)

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
        path = resolve_repo_path(repo)

        success, output = await run_git(["config", "--get", key], cwd=path)
        if not success:
            return f"❌ Config key not found: {key}"

        return output.strip()

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
        path = resolve_repo_path(repo)

        args = ["branch", "--format=%(refname:short)|%(upstream:short)|%(committerdate:relative)"]
        if all_branches:
            args.append("-a")
        if merged:
            args.append(f"--merged={merged}")
        if no_merged:
            args.append(f"--no-merged={no_merged}")

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to list branches: {output}"

        _, current = await run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
        current = current.strip()

        lines = [f"## Branches in `{repo}`", f"**Current:** `{current}`", ""]

        for line in output.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            branch = parts[0]
            upstream = parts[1] if len(parts) > 1 else ""
            date = parts[2] if len(parts) > 2 else ""

            icon = "→" if branch == current else " "
            track = f" → `{upstream}`" if upstream else ""
            age = f" ({date})" if date else ""

            lines.append(f"{icon} `{branch}`{track}{age}")

        return "\n".join(lines)

    @auto_heal()
    @registry.tool()
    async def git_log(
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

        Returns:
            Commit history or count.
        """
        path = resolve_repo_path(repo)

        # Count-only mode
        if count_only:
            args = ["rev-list", "--count"]
            if range_spec:
                args.append(range_spec)
            elif branch:
                args.append(branch)
            else:
                args.append("HEAD")

            success, output = await run_git(args, cwd=path)
            if not success:
                return f"❌ Failed to count: {output}"
            return output.strip()

        # Regular log
        if oneline:
            args = ["log", f"-{limit}", "--oneline", "--decorate"]
        else:
            args = ["log", f"-{limit}", "--format=%h|%an|%ar|%s"]

        if author:
            args.append(f"--author={author}")
        if since:
            args.append(f"--since={since}")
        if until:
            args.append(f"--until={until}")
        if merges_only:
            args.append("--merges")
        if no_merges:
            args.append("--no-merges")

        # Range or branch comes last
        if range_spec:
            args.append(range_spec)
        elif branch:
            args.append(branch)

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to get log: {output}"

        # Build header
        filters = []
        if author:
            filters.append(f"by {author}")
        if since:
            filters.append(f"since {since}")
        if until:
            filters.append(f"until {until}")
        if range_spec:
            filters.append(f"range {range_spec}")
        if merges_only:
            filters.append("merges only")
        if no_merges:
            filters.append("no merges")
        filter_str = f" ({', '.join(filters)})" if filters else ""

        lines = [f"## Recent Commits in `{repo}`{filter_str}", ""]

        if not output.strip():
            lines.append("*No commits found matching criteria*")
            return "\n".join(lines)

        if oneline:
            for line in output.strip().split("\n")[:limit]:
                lines.append(f"- `{line}`")
        else:
            for line in output.strip().split("\n")[:limit]:
                parts = line.split("|")
                if len(parts) >= 4:
                    hash_, author_name, date, msg = parts[0], parts[1], parts[2], parts[3]
                    lines.append(f"- `{hash_}` {msg}")
                    lines.append(f"  *{author_name}* - {date}")

        return "\n".join(lines)

    @auto_heal()
    @registry.tool()
    async def git_diff(repo: str, staged: bool = False, file: str = "") -> str:
        """Show uncommitted changes."""
        path = resolve_repo_path(repo)

        args = ["diff", "--stat"]
        if staged:
            args.append("--staged")
        if file:
            args.extend(["--", file])

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to get diff: {output}"

        if not output.strip():
            return "No changes to show"

        args2 = ["diff"]
        if staged:
            args2.append("--staged")
        if file:
            args2.extend(["--", file])

        _, full_diff = await run_git(args2, cwd=path)
        full_diff = truncate_output(full_diff, max_length=10000)

        lines = [
            f"## Diff: `{repo}`" + (" (staged)" if staged else ""),
            "",
            "### Summary",
            "```",
            output,
            "```",
            "",
            "### Changes",
            "```diff",
            full_diff,
            "```",
        ]

        return "\n".join(lines)

    @auto_heal()
    @registry.tool()
    async def git_branch_create(repo: str, branch_name: str, base: str = "", checkout: bool = True) -> str:
        """Create a new branch."""
        path = resolve_repo_path(repo)

        if checkout:
            args = ["checkout", "-b", branch_name]
            if base:
                args.append(base)
        else:
            args = ["branch", branch_name]
            if base:
                args.append(base)

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to create branch: {output}"

        lines = [f"✅ Created branch `{branch_name}`", f"**Repository:** `{repo}`"]
        if base:
            lines.append(f"**Base:** `{base}`")
        if checkout:
            lines.append(f"**Switched to:** `{branch_name}`")

        return "\n".join(lines)

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
        """
        path = resolve_repo_path(repo)

        args = ["checkout"]
        if force_create:
            args.append("-B")
        elif create:
            args.append("-b")
        args.append(target)

        if start_point:
            args.append(start_point)

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to checkout: {output}"

        action = "Created and switched" if (create or force_create) else "Switched"
        return f"✅ {action} to `{target}`\n\n{output}"

    @auto_heal()
    @registry.tool()
    async def git_add(repo: str, files: str = ".") -> str:
        """Stage files for commit."""
        path = resolve_repo_path(repo)

        args = ["add"] + files.split()

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to stage files: {output}"

        _, staged = await run_git(["diff", "--staged", "--name-only"], cwd=path)

        lines = ["✅ Files staged", ""]
        for f in staged.strip().split("\n")[:20]:
            if f:
                lines.append(f"- `{f}`")

        return "\n".join(lines)

    @auto_heal()
    @registry.tool()
    async def git_commit(
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
        """
        import re

        path = resolve_repo_path(repo)

        # Load commit format helpers from config.json
        try:
            from scripts.common.config_loader import format_commit_message, get_commit_format

            commit_cfg = get_commit_format()
            valid_types = commit_cfg["types"]
            use_config_formatter = True
        except ImportError:
            valid_types = ["feat", "fix", "refactor", "docs", "test", "chore", "style", "perf"]
            use_config_formatter = False

        # Auto-detect issue key from branch name if not provided
        if not issue_key:
            success, branch_name = await run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
            if success and branch_name:
                match = re.match(r"([A-Z]{2,10}-\d{3,6})", branch_name.strip().upper())
                if match:
                    issue_key = match.group(1)

        # Run linting if requested
        if run_lint:
            try:
                from scripts.common.lint_utils import format_lint_error, run_lint_check

                lint_result = run_lint_check(path)
                if not lint_result.passed:
                    return format_lint_error(lint_result)
            except ImportError:
                pass

        # Auto-detect commit type from message content if not provided
        if issue_key and not commit_type:
            msg_lower = message.lower()
            if any(w in msg_lower for w in ["fix", "bug", "issue", "error", "patch"]):
                commit_type = "fix"
            elif any(w in msg_lower for w in ["add", "new", "feature", "implement", "create"]):
                commit_type = "feat"
            elif any(w in msg_lower for w in ["refactor", "clean", "improve", "restructure"]):
                commit_type = "refactor"
            elif any(w in msg_lower for w in ["doc", "readme", "comment", "documentation"]):
                commit_type = "docs"
            elif any(w in msg_lower for w in ["test", "spec", "coverage"]):
                commit_type = "test"
            elif any(w in msg_lower for w in ["style", "format", "lint"]):
                commit_type = "style"
            elif any(w in msg_lower for w in ["perf", "performance", "optimize", "speed"]):
                commit_type = "perf"
            else:
                commit_type = "chore"

        # Validate commit type against config
        if issue_key and commit_type and commit_type not in valid_types:
            return (
                f"❌ Invalid commit type '{commit_type}'.\n\n"
                f"Valid types: {', '.join(valid_types)}\n\n"
                f"Use one of these types or update config.json commit_format.types"
            )

        # Format commit message using config pattern
        if use_config_formatter and issue_key:
            formatted_message = format_commit_message(
                description=message,
                issue_key=issue_key,
                commit_type=commit_type or "chore",
                scope=scope,
            )
        elif issue_key:
            if scope:
                formatted_message = f"{issue_key} - {commit_type or 'chore'}({scope}): {message}"
            else:
                formatted_message = f"{issue_key} - {commit_type or 'chore'}: {message}"
        else:
            formatted_message = message

        args = ["commit", "-m", formatted_message]
        if all_changes:
            args.insert(1, "-a")

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to commit: {output}"

        _, hash_ = await run_git(["rev-parse", "--short", "HEAD"], cwd=path)

        return f"✅ Committed as `{hash_.strip()}`\n\n**Message:** `{formatted_message}`\n\n{output}"

    @auto_heal()
    @registry.tool()
    async def git_push(
        repo: str,
        branch: str = "",
        set_upstream: bool = False,
        force: bool = False,
        dry_run: bool = False,
    ) -> str:
        """
        Push commits to remote.

        Args:
            repo: Repository path
            branch: Branch to push (default: current)
            set_upstream: Set upstream tracking (-u flag)
            force: Force push with lease (--force-with-lease)
            dry_run: Show what would be pushed without pushing

        Returns:
            Push result.
        """
        path = resolve_repo_path(repo)

        args = ["push"]
        if dry_run:
            args.append("--dry-run")
        if set_upstream:
            args.extend(["-u", "origin"])
        if force:
            args.append("--force-with-lease")
        if branch:
            if not set_upstream:
                args.append("origin")
            args.append(branch)

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to push: {output}"

        prefix = "(dry-run) " if dry_run else ""
        return f"✅ {prefix}Pushed successfully\n\n{output}"

    @auto_heal()
    @registry.tool()
    async def git_pull(repo: str, rebase: bool = False) -> str:
        """Pull changes from remote."""
        path = resolve_repo_path(repo)

        args = ["pull"]
        if rebase:
            args.append("--rebase")

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to pull: {output}"

        return f"✅ Pulled successfully\n\n{output}"

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
        path = resolve_repo_path(repo)

        args = ["fetch"]
        if not remote and not refspec:
            args.append("--all")
        if prune:
            args.append("--prune")
        if remote:
            args.append(remote)
        if branch and not refspec:
            args.append(branch)
        if refspec:
            if not remote:
                args.append("origin")
            args.append(refspec)

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to fetch: {output}"

        return f"✅ Fetched successfully\n\n{output or 'Already up to date.'}"

    @auto_heal()
    @registry.tool()
    async def git_stash(repo: str, action: str = "push", message: str = "") -> str:
        """Stash or restore changes."""
        path = resolve_repo_path(repo)

        args = ["stash", action]
        if action == "push" and message:
            args.extend(["-m", message])

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to stash: {output}"

        if action == "list":
            if not output.strip():
                return "No stashes"
            lines = ["## Stash List", ""]
            for line in output.strip().split("\n"):
                lines.append(f"- {line}")
            return "\n".join(lines)

        return f"✅ Stash {action} successful\n\n{output or 'Done'}"

    @auto_heal()
    @registry.tool()
    async def git_remote_info(repo: str) -> str:
        """Get remote repository information."""
        path = resolve_repo_path(repo)

        success, output = await run_git(["remote", "-v"], cwd=path)
        if not success:
            return f"❌ Failed to get remotes: {output}"

        lines = [f"## Remotes for `{repo}`", ""]

        seen = set()
        for line in output.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 2:
                name, url = parts[0], parts[1]
                if (name, url) not in seen:
                    seen.add((name, url))
                    lines.append(f"- **{name}:** `{url}`")

        return "\n".join(lines)

    return registry.count
