"""Git tool definitions.

This module provides the tool registration function that can be called
by the shared server infrastructure.
"""

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Add aa-common to path for shared utilities
SERVERS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SERVERS_DIR / "aa-common"))

from src.utils import resolve_repo_path, run_cmd

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
    """
    Register git tools with the MCP server.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    tool_count = 0

    # ==================== STATUS & INFO ====================

    @server.tool()
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

    tool_count += 1

    @server.tool()
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

    tool_count += 1

    @server.tool()
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

    tool_count += 1

    @server.tool()
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
        if numstat:
            args.append("--numstat")
            if oneline:
                # For numstat with oneline, use a different format
                args = [a for a in args if a != "--oneline"]
                args.insert(2, "--pretty=format:%h %s")

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

    tool_count += 1

    @server.tool()
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

        if len(full_diff) > 10000:
            full_diff = full_diff[:10000] + "\n\n... (truncated)"

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

    tool_count += 1

    @server.tool()
    async def git_show(
        repo: str,
        commit: str = "HEAD",
        format: str = "",
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
        path = resolve_repo_path(repo)

        args = ["show", commit]
        if format:
            args.append(f"--format={format}")
        if name_only:
            args.append("--name-only")

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to show commit: {output}"

        if len(output) > 5000:
            output = output[:5000] + "\n\n... (truncated)"

        return output

    tool_count += 1

    @server.tool()
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
        path = resolve_repo_path(repo)

        args = ["diff-tree", "--no-commit-id", "-r", commit]
        if name_only:
            args.append("--name-only")

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to get diff-tree: {output}"

        return output.strip()

    tool_count += 1

    @server.tool()
    async def git_branch_create(
        repo: str, branch_name: str, base: str = "", checkout: bool = True
    ) -> str:
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

    tool_count += 1

    @server.tool()
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

    tool_count += 1

    @server.tool()
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

    tool_count += 1

    @server.tool()
    async def git_commit(
        repo: str,
        message: str,
        all_changes: bool = False,
        issue_key: str = "",
        commit_type: str = "",
        scope: str = "",
    ) -> str:
        """Commit staged changes with optional conventional commit format."""
        path = resolve_repo_path(repo)

        if issue_key:
            if not commit_type:
                msg_lower = message.lower()
                if any(w in msg_lower for w in ["fix", "bug", "issue", "error"]):
                    commit_type = "fix"
                elif any(w in msg_lower for w in ["add", "new", "feature", "implement"]):
                    commit_type = "feat"
                elif any(w in msg_lower for w in ["refactor", "clean", "improve"]):
                    commit_type = "refactor"
                elif any(w in msg_lower for w in ["doc", "readme", "comment"]):
                    commit_type = "docs"
                elif any(w in msg_lower for w in ["test"]):
                    commit_type = "test"
                else:
                    commit_type = "chore"

            if scope:
                formatted_message = f"{issue_key} - {commit_type}({scope}): {message}"
            else:
                formatted_message = f"{issue_key} - {commit_type}: {message}"
        else:
            formatted_message = message

        args = ["commit", "-m", formatted_message]
        if all_changes:
            args.insert(1, "-a")

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to commit: {output}"

        _, hash_ = await run_git(["rev-parse", "--short", "HEAD"], cwd=path)

        return (
            f"✅ Committed as `{hash_.strip()}`\n\n**Message:** `{formatted_message}`\n\n{output}"
        )

    tool_count += 1

    @server.tool()
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

    tool_count += 1

    @server.tool()
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

    tool_count += 1

    @server.tool()
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

    tool_count += 1

    @server.tool()
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

    tool_count += 1

    @server.tool()
    async def git_reset(repo: str, target: str = "HEAD", mode: str = "mixed") -> str:
        """Reset current HEAD to specified state."""
        path = resolve_repo_path(repo)

        args = ["reset", f"--{mode}", target]

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to reset: {output}"

        warning = "⚠️ Changes discarded!" if mode == "hard" else ""
        return f"✅ Reset to `{target}` ({mode}) {warning}\n\n{output or 'Done'}"

    tool_count += 1

    @server.tool()
    async def git_clean(repo: str, dry_run: bool = True) -> str:
        """Remove untracked files."""
        path = resolve_repo_path(repo)

        args = ["clean", "-fd"]
        if dry_run:
            args.append("-n")

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to clean: {output}"

        prefix = "Would remove" if dry_run else "Removed"
        if not output.strip():
            return "No untracked files to remove"

        lines = [f"## {prefix}:", ""]
        for line in output.strip().split("\n"):
            lines.append(f"- {line}")

        if dry_run:
            lines.append("\n*Run with dry_run=False to actually delete*")

        return "\n".join(lines)

    tool_count += 1

    @server.tool()
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

    tool_count += 1

    # ==================== REBASE ====================

    @server.tool()
    async def git_rebase(
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
        path = resolve_repo_path(repo)

        # Handle rebase control operations
        if abort:
            success, output = await run_git(["rebase", "--abort"], cwd=path)
            if success:
                return "✅ Rebase aborted. Back to original state."
            return f"❌ Failed to abort rebase: {output}"

        if continue_rebase:
            success, output = await run_git(["rebase", "--continue"], cwd=path)
            if success:
                return f"✅ Rebase continued successfully.\n\n{output}"
            return f"❌ Conflicts remain or rebase failed:\n{output}"

        if skip:
            success, output = await run_git(["rebase", "--skip"], cwd=path)
            if success:
                return f"✅ Skipped commit, continuing rebase.\n\n{output}"
            return f"❌ Failed to skip: {output}"

        # Start new rebase
        if not onto:
            return "❌ Must specify 'onto' branch for rebase, or use abort/continue_rebase/skip"

        args = ["rebase"]
        if interactive:
            args.append("-i")
        args.append(onto)

        success, output = await run_git(args, cwd=path)

        if success:
            return f"✅ Successfully rebased onto `{onto}`\n\n{output or 'Rebase complete.'}"

        # Check for conflicts
        status_ok, status_output = await run_git(["status", "--porcelain"], cwd=path)

        conflict_files = []
        if status_ok:
            for line in status_output.split("\n"):
                # UU = both modified, AA = both added, DU = deleted by us
                if (
                    line.startswith("UU")
                    or line.startswith("AA")
                    or line.startswith("DU")
                    or line.startswith("UD")
                ):
                    conflict_files.append(line[3:].strip())

        if conflict_files:
            lines = [
                f"⚠️ Rebase paused - {len(conflict_files)} conflict(s) detected",
                "",
                "**Conflict files:**",
            ]
            for f in conflict_files[:10]:
                lines.append(f"- `{f}`")
            if len(conflict_files) > 10:
                lines.append(f"- ... and {len(conflict_files) - 10} more")

            lines.extend(
                [
                    "",
                    "**Next steps:**",
                    "1. Resolve conflicts in the files above",
                    "2. Stage resolved files: `git_add(repo, 'file1 file2')`",
                    "3. Continue: `git_rebase(repo, continue_rebase=True)`",
                    "   Or abort: `git_rebase(repo, abort=True)`",
                ]
            )
            return "\n".join(lines)

        return f"❌ Rebase failed:\n{output}"

    tool_count += 1

    @server.tool()
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
        path = resolve_repo_path(repo)

        args = ["rev-parse"]
        if verify:
            args.append("--verify")
        if short:
            args.append("--short")
        args.append(ref)

        success, output = await run_git(args, cwd=path)

        if not success:
            # Try fetching and retrying
            await run_git(["fetch", "origin"], cwd=path)
            success, output = await run_git(args, cwd=path)

        if not success:
            return f"❌ Could not resolve ref '{ref}': {output}"

        sha = output.strip()

        # Validate SHA format
        if not sha or (not short and len(sha) != 40) or (short and len(sha) < 7):
            return f"❌ Invalid SHA returned for '{ref}': {sha}"

        return sha

    tool_count += 1

    @server.tool()
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
        path = resolve_repo_path(repo)

        args = ["merge"]
        if no_commit:
            args.append("--no-commit")
        if no_ff:
            args.append("--no-ff")
        if message:
            args.extend(["-m", message])
        args.append(target)

        success, output = await run_git(args, cwd=path)

        if success:
            return f"✅ Merged {target} successfully\n\n{output}"

        if "conflict" in output.lower():
            return f"⚠️ Merge conflicts detected:\n\n{output}"

        return f"❌ Merge failed: {output}"

    tool_count += 1

    @server.tool()
    async def git_merge_abort(repo: str) -> str:
        """
        Abort an in-progress merge.

        Args:
            repo: Repository path

        Returns:
            Success or error message.
        """
        path = resolve_repo_path(repo)

        success, output = await run_git(["merge", "--abort"], cwd=path)

        if success:
            return "✅ Merge aborted. Working tree restored."
        return f"❌ Failed to abort merge (perhaps no merge in progress?): {output}"

    tool_count += 1

    # ==================== CODE FORMATTING ====================

    @server.tool()
    async def code_format(
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
        path = resolve_repo_path(repo)

        if tool == "black":
            cmd = ["black"]
            if check_only:
                cmd.append("--check")
            cmd.extend(paths.split())
        elif tool == "isort":
            cmd = ["isort"]
            if check_only:
                cmd.append("--check-only")
            cmd.extend(paths.split())
        elif tool == "ruff":
            cmd = ["ruff", "format"]
            if check_only:
                cmd.append("--check")
            cmd.extend(paths.split())
        else:
            return f"❌ Unknown formatter: {tool}. Use 'black', 'isort', or 'ruff'"

        success, output = await run_cmd(cmd, cwd=path, timeout=120)

        if success:
            if check_only:
                return f"✅ Code formatting check passed ({tool})"
            return f"✅ Code formatted with {tool}\n\n{output or 'All files formatted.'}"

        if check_only:
            return f"⚠️ Formatting issues found ({tool}):\n\n{output}"
        return f"❌ Formatting failed:\n{output}"

    tool_count += 1

    @server.tool()
    async def code_lint(
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
        path = resolve_repo_path(repo)

        if tool == "flake8":
            cmd = [
                "flake8",
                f"--max-line-length={max_line_length}",
                f"--ignore={ignore}",
                f"--exclude={exclude}",
            ]
            cmd.extend(paths.split())
        elif tool == "ruff":
            cmd = ["ruff", "check"]
            if ignore:
                cmd.extend(["--ignore", ignore])
            cmd.extend(paths.split())
        elif tool == "pylint":
            cmd = ["pylint", f"--max-line-length={max_line_length}"]
            if ignore:
                cmd.extend([f"--disable={ignore}"])
            cmd.extend(paths.split())
        else:
            return f"❌ Unknown linter: {tool}. Use 'flake8', 'ruff', or 'pylint'"

        success, output = await run_cmd(cmd, cwd=path, timeout=120)

        if success:
            return f"✅ Linting passed ({tool}) - no issues found"

        # Parse output to count issues
        lines = output.strip().split("\n") if output.strip() else []
        issue_count = len([l for l in lines if l.strip() and ":" in l])

        # Truncate if too long
        if len(output) > 3000:
            output = output[:3000] + f"\n\n... truncated ({issue_count} total issues)"

        return f"⚠️ Linting issues found ({tool}): {issue_count} issues\n\n```\n{output}\n```"

    tool_count += 1

    # ==================== BUILD/MAKE ====================

    @server.tool()
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
        path = resolve_repo_path(repo)

        cmd = ["make", target]
        success, output = await run_cmd(cmd, cwd=path, timeout=timeout)

        if success:
            return (
                f"✅ make {target} completed\n\n{output[-2000:] if len(output) > 2000 else output}"
            )
        return f"❌ make {target} failed:\n{output[-2000:] if len(output) > 2000 else output}"

    tool_count += 1

    # ==================== DOCKER ====================

    @server.tool()
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
        path = resolve_repo_path(repo)

        cmd = ["docker", "ps", "--format", "{{.Names}}|{{.Status}}|{{.Ports}}"]
        if filter_name:
            cmd.extend(["--filter", f"name={filter_name}"])

        success, output = await run_cmd(cmd, timeout=30)

        if not success:
            return f"❌ Docker not running or not available: {output}"

        if not output.strip():
            return "No containers running" + (f" matching '{filter_name}'" if filter_name else "")

        lines = ["## Docker Containers", ""]
        for line in output.strip().split("\n"):
            parts = line.split("|")
            if len(parts) >= 2:
                name, status = parts[0], parts[1]
                ports = parts[2] if len(parts) > 2 else ""
                icon = "🟢" if "Up" in status else "🔴"
                lines.append(f"{icon} **{name}**: {status}")
                if ports:
                    lines.append(f"   Ports: {ports}")

        return "\n".join(lines)

    tool_count += 1

    @server.tool()
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
        path = resolve_repo_path(repo)

        cmd = ["docker-compose", "up"]
        if detach:
            cmd.append("-d")
        if services:
            cmd.extend(services.split())

        success, output = await run_cmd(cmd, cwd=path, timeout=timeout)

        if success:
            return f"✅ docker-compose up completed\n\n{output[-1000:] if len(output) > 1000 else output}"
        return f"❌ docker-compose up failed:\n{output}"

    tool_count += 1

    @server.tool()
    async def docker_compose_down(
        repo: str,
        volumes: bool = False,
        timeout: int = 60,
    ) -> str:
        """
        Stop docker-compose services.

        Args:
            repo: Repository path
            volumes: Also remove volumes
            timeout: Timeout in seconds

        Returns:
            Shutdown result.
        """
        path = resolve_repo_path(repo)

        cmd = ["docker-compose", "down"]
        if volumes:
            cmd.append("-v")

        success, output = await run_cmd(cmd, cwd=path, timeout=timeout)

        if success:
            return f"✅ docker-compose down completed\n\n{output}"
        return f"❌ docker-compose down failed:\n{output}"

    tool_count += 1

    @server.tool()
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
        cmd = ["docker", "cp", source, destination]

        success, output = await run_cmd(cmd, timeout=60)

        if success:
            direction = "to container" if to_container else "from container"
            return f"✅ Copied {direction}: {source} → {destination}"
        return f"❌ Copy failed: {output}"

    tool_count += 1

    @server.tool()
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
        cmd = ["docker", "exec", container, "bash", "-c", command]

        success, output = await run_cmd(cmd, timeout=timeout)

        if success:
            return f"## Docker exec: {command[:50]}...\n\n```\n{output}\n```"
        return f"❌ Docker exec failed:\n{output}"

    tool_count += 1

    return tool_count
