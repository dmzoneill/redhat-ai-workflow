"""Git tool definitions.

This module provides the tool registration function that can be called
by the shared server infrastructure.
"""

import asyncio
import logging
import os
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


async def run_git(
    args: list[str],
    cwd: str | None = None,
    timeout: int = 60,
) -> tuple[bool, str]:
    """Run git command and return (success, output)."""
    cmd = ["git"] + args
    
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        
        output = result.stdout
        if result.returncode != 0:
            output = result.stderr or result.stdout or "Command failed"
            return False, output
        
        return True, output
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return False, "git not found"
    except Exception as e:
        return False, str(e)


def resolve_repo_path(repo: str) -> str:
    """Resolve repository name to path."""
    if os.path.isdir(repo):
        return repo
    
    for base in [Path.home() / "src", Path.home() / "repos", Path.home() / "projects"]:
        candidate = base / repo
        if candidate.exists():
            return str(candidate)
    
    return repo


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
        
        success, output = await run_git(["rev-list", "--left-right", "--count", "@{u}...HEAD"], cwd=path)
        if success and output.strip():
            parts = output.strip().split()
            if len(parts) == 2:
                behind, ahead = int(parts[0]), int(parts[1])
                if ahead or behind:
                    lines.append(f"\n**Sync:** ↑{ahead} ahead, ↓{behind} behind remote")
        
        return "\n".join(lines)
    tool_count += 1
    
    @server.tool()
    async def git_branch_list(repo: str, all_branches: bool = False) -> str:
        """List branches in a repository."""
        path = resolve_repo_path(repo)
        
        args = ["branch", "--format=%(refname:short)|%(upstream:short)|%(committerdate:relative)"]
        if all_branches:
            args.append("-a")
        
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
            
        Returns:
            Commit history.
        """
        path = resolve_repo_path(repo)
        
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
        if branch:
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
    tool_count += 1
    
    @server.tool()
    async def git_checkout(repo: str, target: str, create: bool = False) -> str:
        """Switch branches or restore files."""
        path = resolve_repo_path(repo)
        
        args = ["checkout"]
        if create:
            args.append("-b")
        args.append(target)
        
        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to checkout: {output}"
        
        return f"✅ Switched to `{target}`\n\n{output}"
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
    async def git_commit(repo: str, message: str, all_changes: bool = False, issue_key: str = "", commit_type: str = "", scope: str = "") -> str:
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
        
        return f"✅ Committed as `{hash_.strip()}`\n\n**Message:** `{formatted_message}`\n\n{output}"
    tool_count += 1
    
    @server.tool()
    async def git_push(repo: str, branch: str = "", set_upstream: bool = False, force: bool = False) -> str:
        """Push commits to remote."""
        path = resolve_repo_path(repo)
        
        args = ["push"]
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
        
        return f"✅ Pushed successfully\n\n{output}"
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
    async def git_fetch(repo: str, prune: bool = True) -> str:
        """Fetch changes from remote without merging."""
        path = resolve_repo_path(repo)
        
        args = ["fetch", "--all"]
        if prune:
            args.append("--prune")
        
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
    
    return tool_count

