"""Docker tool definitions - Container management tools.

Provides:
- docker_compose_status: Check container status
- docker_compose_up: Start docker-compose services
- docker_cp: Copy files to/from containers
- docker_exec: Execute commands in containers
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
async def _docker_compose_status_impl(
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
    resolve_repo_path(repo)

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


@auto_heal()
async def _docker_compose_up_impl(
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
        return f"✅ docker-compose up completed\n\n{truncate_output(output, max_length=1000, mode='tail')}"
    return f"❌ docker-compose up failed:\n{output}"


@auto_heal()
async def _docker_cp_impl(
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


@auto_heal()
async def _docker_exec_impl(
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


def register_tools(server: FastMCP) -> int:
    """
    Register docker tools with the MCP server.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    registry = ToolRegistry(server)

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

    return registry.count
