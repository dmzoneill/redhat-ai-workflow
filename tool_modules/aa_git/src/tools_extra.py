"""Git tool definitions.

This module provides the tool registration function that can be called
by the shared server infrastructure.
"""

import logging
import shlex

from fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization


from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import resolve_repo_path, run_cmd

# Setup project path for server imports


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
    registry = ToolRegistry(server)

    # ==================== STATUS & INFO ====================

    # ==================== TOOLS NOT USED IN SKILLS ====================
    @auto_heal()
    @registry.tool()
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

    @auto_heal()
    @registry.tool()
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

    @auto_heal()
    @registry.tool()
    async def git_branch_delete(
        repo: str,
        branch_name: str,
        force: bool = False,
        remote: bool = False,
    ) -> str:
        """Delete a branch locally or remotely.

        Args:
            repo: Repository path
            branch_name: Branch name to delete
            force: Force delete even if not fully merged (-D instead of -d)
            remote: Also delete the remote tracking branch

        Returns:
            Deletion result.
        """
        path = resolve_repo_path(repo)

        flag = "-D" if force else "-d"
        args = ["branch", flag, branch_name]

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to delete local branch: {output}"

        lines = [f"✅ Deleted local branch `{branch_name}`", ""]
        lines.append(output.strip() if output.strip() else "Done")

        if remote:
            remote_args = ["push", "origin", "--delete", branch_name]
            remote_success, remote_output = await run_git(remote_args, cwd=path)
            if not remote_success:
                lines.append(f"\n⚠️ Failed to delete remote branch: {remote_output}")
            else:
                lines.append(f"\n✅ Deleted remote branch `origin/{branch_name}`")

        return "\n".join(lines)

    @auto_heal()
    @registry.tool()
    async def git_cherry_pick(
        repo: str,
        commit: str,
        no_commit: bool = False,
    ) -> str:
        """Cherry-pick a commit onto the current branch.

        Args:
            repo: Repository path
            commit: Commit SHA to cherry-pick
            no_commit: Stage changes without committing (--no-commit)

        Returns:
            Cherry-pick result.
        """
        path = resolve_repo_path(repo)

        args = ["cherry-pick"]
        if no_commit:
            args.append("--no-commit")
        args.append(commit)

        success, output = await run_git(args, cwd=path)
        if not success:
            if "conflict" in output.lower():
                return f"⚠️ Cherry-pick conflicts detected:\n\n{output}"
            return f"❌ Failed to cherry-pick: {output}"

        if no_commit:
            return f"✅ Cherry-picked `{commit}` (staged, not committed)\n\n{output or 'Done'}"
        return f"✅ Cherry-picked `{commit}` successfully\n\n{output or 'Done'}"

    @auto_heal()
    @registry.tool()
    async def git_tag(
        repo: str,
        tag_name: str,
        message: str = "",
        commit: str = "",
        delete: bool = False,
    ) -> str:
        """Create or delete a git tag.

        Args:
            repo: Repository path
            tag_name: Tag name
            message: Tag message (creates annotated tag if provided)
            commit: Commit to tag (defaults to HEAD)
            delete: Delete the tag instead of creating

        Returns:
            Tag operation result.
        """
        path = resolve_repo_path(repo)

        if delete:
            args = ["tag", "-d", tag_name]
            success, output = await run_git(args, cwd=path)
            if not success:
                return f"❌ Failed to delete tag: {output}"
            return f"✅ Deleted tag `{tag_name}`\n\n{output or 'Done'}"

        if message:
            args = ["tag", "-a", tag_name, "-m", message]
        else:
            args = ["tag", tag_name]

        if commit:
            args.append(commit)

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to create tag: {output}"

        tag_type = "annotated" if message else "lightweight"
        target = f" at `{commit}`" if commit else ""
        return f"✅ Created {tag_type} tag `{tag_name}`{target}\n\n{output or 'Done'}"

    @auto_heal()
    @registry.tool()
    async def shell(command: str, cwd: str = "", timeout: int = 30) -> str:
        """Execute a shell command.

        Args:
            command: Shell command to execute
            cwd: Working directory (defaults to current directory)
            timeout: Timeout in seconds

        Returns:
            Command output (stdout + stderr).
        """
        try:
            cmd = shlex.split(command)
        except ValueError as e:
            return f"❌ Failed to parse command: {e}"

        success, output = await run_cmd(cmd, cwd=cwd or None, timeout=timeout)

        if not success:
            return f"❌ Command failed:\n{output}"
        return output or "(no output)"

    return registry.count
