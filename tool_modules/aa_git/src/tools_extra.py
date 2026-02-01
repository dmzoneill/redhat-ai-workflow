"""Git tool definitions.

This module provides the tool registration function that can be called
by the shared server infrastructure.
"""

import logging

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
