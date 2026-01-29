"""Make tool definitions - Build automation tools.

Provides:
- make_target: Run make targets in repositories
"""

import logging

from mcp.server.fastmcp import FastMCP

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import resolve_repo_path, run_cmd, truncate_output

logger = logging.getLogger(__name__)


@auto_heal()
async def _make_target_impl(
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
        return f"✅ make {target} completed\n\n{truncate_output(output, 2000, mode='tail')}"
    return f"❌ make {target} failed:\n{truncate_output(output, 2000, mode='tail')}"


def register_tools(server: FastMCP) -> int:
    """
    Register make tools with the MCP server.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    registry = ToolRegistry(server)

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

    return registry.count
