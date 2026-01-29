"""Podman tool definitions - Container management tools using Podman.

Provides:
- podman_ps: List running containers
- podman_compose_status: Check podman-compose container status
- podman_compose_up: Start podman-compose services
- podman_compose_down: Stop podman-compose services
- podman_cp: Copy files to/from containers
- podman_exec: Execute commands in containers
- podman_logs: View container logs
- podman_images: List container images
- podman_pull: Pull a container image
- podman_build: Build a container image
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
async def _podman_ps_impl(
    all_containers: bool = False,
    filter_name: str = "",
) -> str:
    """
    List podman containers.

    Args:
        all_containers: Show all containers (including stopped)
        filter_name: Filter containers by name

    Returns:
        Container list.
    """
    cmd = ["podman", "ps", "--format", "{{.Names}}|{{.Status}}|{{.Ports}}|{{.Image}}"]
    if all_containers:
        cmd.append("-a")
    if filter_name:
        cmd.extend(["--filter", f"name={filter_name}"])

    success, output = await run_cmd(cmd, timeout=30)

    if not success:
        return f"❌ Podman not running or not available: {output}"

    if not output.strip():
        msg = "No containers"
        if not all_containers:
            msg += " running"
        if filter_name:
            msg += f" matching '{filter_name}'"
        return msg

    lines = ["## Podman Containers", ""]
    for line in output.strip().split("\n"):
        parts = line.split("|")
        if len(parts) >= 2:
            name, status = parts[0], parts[1]
            ports = parts[2] if len(parts) > 2 else ""
            image = parts[3] if len(parts) > 3 else ""
            icon = "🟢" if "Up" in status else "🔴"
            lines.append(f"{icon} **{name}**: {status}")
            if image:
                lines.append(f"   Image: {image}")
            if ports:
                lines.append(f"   Ports: {ports}")

    return "\n".join(lines)


@auto_heal()
async def _podman_compose_status_impl(
    repo: str,
    filter_name: str = "",
) -> str:
    """
    Check podman-compose container status.

    Args:
        repo: Repository path (where podman-compose.yml or docker-compose.yml is)
        filter_name: Filter containers by name

    Returns:
        Container status.
    """
    path = resolve_repo_path(repo)

    # podman-compose ps shows containers for the project
    cmd = ["podman-compose", "ps"]

    success, output = await run_cmd(cmd, cwd=path, timeout=30)

    if not success:
        return f"❌ podman-compose not available or no compose file found: {output}"

    if not output.strip() or "no containers" in output.lower():
        return "No containers running" + (f" matching '{filter_name}'" if filter_name else "")

    # Filter output if filter_name provided
    if filter_name:
        filtered_lines = []
        for line in output.strip().split("\n"):
            if filter_name.lower() in line.lower() or line.startswith("CONTAINER") or line.startswith("NAME"):
                filtered_lines.append(line)
        output = "\n".join(filtered_lines)

    return f"## Podman Compose Status\n\n```\n{output}\n```"


@auto_heal()
async def _podman_compose_up_impl(
    repo: str,
    detach: bool = True,
    services: str = "",
    build: bool = False,
    timeout: int = 180,
) -> str:
    """
    Start podman-compose services.

    Args:
        repo: Repository path (where podman-compose.yml or docker-compose.yml is)
        detach: Run in background
        services: Specific services to start (space-separated, empty = all)
        build: Build images before starting
        timeout: Timeout in seconds

    Returns:
        Startup result.
    """
    path = resolve_repo_path(repo)

    cmd = ["podman-compose", "up"]
    if detach:
        cmd.append("-d")
    if build:
        cmd.append("--build")
    if services:
        cmd.extend(services.split())

    success, output = await run_cmd(cmd, cwd=path, timeout=timeout)

    if success:
        return f"✅ podman-compose up completed\n\n{truncate_output(output, max_length=1000, mode='tail')}"
    return f"❌ podman-compose up failed:\n{output}"


@auto_heal()
async def _podman_compose_down_impl(
    repo: str,
    volumes: bool = False,
    remove_orphans: bool = False,
    timeout: int = 60,
) -> str:
    """
    Stop podman-compose services.

    Args:
        repo: Repository path (where podman-compose.yml or docker-compose.yml is)
        volumes: Remove named volumes
        remove_orphans: Remove containers for services not defined in compose file
        timeout: Timeout in seconds

    Returns:
        Shutdown result.
    """
    path = resolve_repo_path(repo)

    cmd = ["podman-compose", "down"]
    if volumes:
        cmd.append("-v")
    if remove_orphans:
        cmd.append("--remove-orphans")

    success, output = await run_cmd(cmd, cwd=path, timeout=timeout)

    if success:
        return f"✅ podman-compose down completed\n\n{truncate_output(output, max_length=500, mode='tail')}"
    return f"❌ podman-compose down failed:\n{output}"


@auto_heal()
async def _podman_cp_impl(
    source: str,
    destination: str,
    to_container: bool = True,
) -> str:
    """
    Copy files to/from a Podman container.

    Args:
        source: Source path (local path or container:path)
        destination: Destination path (container:path or local path)
        to_container: If True, copy from local to container

    Returns:
        Copy result.

    Examples:
        podman_cp("/tmp/script.sh", "my_container:/tmp/script.sh", to_container=True)
        podman_cp("my_container:/var/log/app.log", "/tmp/app.log", to_container=False)
    """
    cmd = ["podman", "cp", source, destination]

    success, output = await run_cmd(cmd, timeout=60)

    if success:
        direction = "to container" if to_container else "from container"
        return f"✅ Copied {direction}: {source} → {destination}"
    return f"❌ Copy failed: {output}"


@auto_heal()
async def _podman_exec_impl(
    container: str,
    command: str,
    workdir: str = "",
    user: str = "",
    timeout: int = 300,
) -> str:
    """
    Execute a command in a running Podman container.

    Args:
        container: Container name or ID
        command: Command to execute
        workdir: Working directory inside container
        user: User to run command as
        timeout: Timeout in seconds

    Returns:
        Command output.
    """
    cmd = ["podman", "exec"]
    if workdir:
        cmd.extend(["-w", workdir])
    if user:
        cmd.extend(["-u", user])
    cmd.extend([container, "bash", "-c", command])

    success, output = await run_cmd(cmd, timeout=timeout)

    if success:
        return f"## Podman exec: {command[:50]}...\n\n```\n{output}\n```"
    return f"❌ Podman exec failed:\n{output}"


@auto_heal()
async def _podman_logs_impl(
    container: str,
    tail: int = 100,
    follow: bool = False,
    since: str = "",
    timestamps: bool = False,
) -> str:
    """
    View container logs.

    Args:
        container: Container name or ID
        tail: Number of lines to show from end (0 for all)
        follow: Follow log output (not recommended for automation)
        since: Show logs since timestamp (e.g., "2024-01-01", "10m", "1h")
        timestamps: Show timestamps

    Returns:
        Container logs.
    """
    cmd = ["podman", "logs"]
    if tail > 0:
        cmd.extend(["--tail", str(tail)])
    if since:
        cmd.extend(["--since", since])
    if timestamps:
        cmd.append("-t")
    # Note: follow=True would hang, so we ignore it for safety
    cmd.append(container)

    success, output = await run_cmd(cmd, timeout=30)

    if success:
        return f"## Logs: {container}\n\n```\n{truncate_output(output, max_length=3000, mode='tail')}\n```"
    return f"❌ Failed to get logs: {output}"


@auto_heal()
async def _podman_images_impl(
    filter_name: str = "",
    all_images: bool = False,
) -> str:
    """
    List container images.

    Args:
        filter_name: Filter images by name/reference
        all_images: Show all images (including intermediate)

    Returns:
        Image list.
    """
    cmd = ["podman", "images", "--format", "{{.Repository}}:{{.Tag}}|{{.ID}}|{{.Size}}|{{.Created}}"]
    if all_images:
        cmd.append("-a")
    if filter_name:
        cmd.append(filter_name)

    success, output = await run_cmd(cmd, timeout=30)

    if not success:
        return f"❌ Failed to list images: {output}"

    if not output.strip():
        return "No images found" + (f" matching '{filter_name}'" if filter_name else "")

    lines = ["## Podman Images", "", "| Image | ID | Size | Created |", "|-------|-----|------|---------|"]
    for line in output.strip().split("\n"):
        parts = line.split("|")
        if len(parts) >= 4:
            image, img_id, size, created = parts[0], parts[1][:12], parts[2], parts[3]
            lines.append(f"| {image} | {img_id} | {size} | {created} |")

    return "\n".join(lines)


@auto_heal()
async def _podman_pull_impl(
    image: str,
    quiet: bool = False,
) -> str:
    """
    Pull a container image.

    Args:
        image: Image name with optional tag (e.g., "nginx:latest", "quay.io/myorg/myimage:v1")
        quiet: Suppress progress output

    Returns:
        Pull result.
    """
    cmd = ["podman", "pull"]
    if quiet:
        cmd.append("-q")
    cmd.append(image)

    success, output = await run_cmd(cmd, timeout=300)

    if success:
        return f"✅ Pulled image: {image}\n\n{truncate_output(output, max_length=500, mode='tail')}"
    return f"❌ Failed to pull image: {output}"


@auto_heal()
async def _podman_build_impl(
    repo: str,
    tag: str,
    dockerfile: str = "Dockerfile",
    no_cache: bool = False,
    build_args: str = "",
    timeout: int = 600,
) -> str:
    """
    Build a container image.

    Args:
        repo: Repository path (build context)
        tag: Image tag (e.g., "myapp:latest")
        dockerfile: Dockerfile path relative to repo
        no_cache: Don't use cache when building
        build_args: Build arguments as KEY=VALUE pairs, space-separated
        timeout: Timeout in seconds

    Returns:
        Build result.
    """
    path = resolve_repo_path(repo)

    cmd = ["podman", "build", "-t", tag, "-f", dockerfile]
    if no_cache:
        cmd.append("--no-cache")
    if build_args:
        for arg in build_args.split():
            cmd.extend(["--build-arg", arg])
    cmd.append(".")

    success, output = await run_cmd(cmd, cwd=path, timeout=timeout)

    if success:
        return f"✅ Built image: {tag}\n\n{truncate_output(output, max_length=1000, mode='tail')}"
    return f"❌ Build failed:\n{truncate_output(output, max_length=2000, mode='tail')}"


@auto_heal()
async def _podman_run_impl(
    image: str,
    name: str = "",
    command: str = "",
    detach: bool = True,
    rm: bool = False,
    ports: str = "",
    volumes: str = "",
    env_vars: str = "",
    network: str = "",
    timeout: int = 60,
) -> str:
    """
    Run a container from an image.

    Args:
        image: Image name with optional tag
        name: Container name
        command: Command to run in container
        detach: Run in background
        rm: Remove container when it exits
        ports: Port mappings (e.g., "8080:80 9090:90")
        volumes: Volume mounts (e.g., "/host/path:/container/path:Z")
        env_vars: Environment variables (e.g., "FOO=bar BAZ=qux")
        network: Network to connect to
        timeout: Timeout in seconds

    Returns:
        Run result with container ID.
    """
    cmd = ["podman", "run"]
    if detach:
        cmd.append("-d")
    if rm:
        cmd.append("--rm")
    if name:
        cmd.extend(["--name", name])
    if network:
        cmd.extend(["--network", network])

    # Parse ports
    if ports:
        for port in ports.split():
            cmd.extend(["-p", port])

    # Parse volumes
    if volumes:
        for vol in volumes.split():
            cmd.extend(["-v", vol])

    # Parse env vars
    if env_vars:
        for env in env_vars.split():
            cmd.extend(["-e", env])

    cmd.append(image)

    if command:
        cmd.extend(command.split())

    success, output = await run_cmd(cmd, timeout=timeout)

    if success:
        container_id = output.strip()[:12] if output.strip() else "unknown"
        return f"✅ Started container: {name or container_id}\n\nContainer ID: {output.strip()}"
    return f"❌ Failed to run container:\n{output}"


@auto_heal()
async def _podman_stop_impl(
    container: str,
    timeout_seconds: int = 10,
) -> str:
    """
    Stop a running container.

    Args:
        container: Container name or ID
        timeout_seconds: Seconds to wait before killing

    Returns:
        Stop result.
    """
    cmd = ["podman", "stop", "-t", str(timeout_seconds), container]

    success, output = await run_cmd(cmd, timeout=timeout_seconds + 30)

    if success:
        return f"✅ Stopped container: {container}"
    return f"❌ Failed to stop container: {output}"


@auto_heal()
async def _podman_rm_impl(
    container: str,
    force: bool = False,
    volumes: bool = False,
) -> str:
    """
    Remove a container.

    Args:
        container: Container name or ID
        force: Force removal of running container
        volumes: Remove associated volumes

    Returns:
        Remove result.
    """
    cmd = ["podman", "rm"]
    if force:
        cmd.append("-f")
    if volumes:
        cmd.append("-v")
    cmd.append(container)

    success, output = await run_cmd(cmd, timeout=30)

    if success:
        return f"✅ Removed container: {container}"
    return f"❌ Failed to remove container: {output}"


def register_tools(server: FastMCP) -> int:
    """
    Register podman tools with the MCP server.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def podman_ps(
        all_containers: bool = False,
        filter_name: str = "",
    ) -> str:
        """
        List podman containers.

        Args:
            all_containers: Show all containers (including stopped)
            filter_name: Filter containers by name

        Returns:
            Container list.
        """
        return await _podman_ps_impl(all_containers, filter_name)

    @auto_heal()
    @registry.tool()
    async def podman_compose_status(
        repo: str,
        filter_name: str = "",
    ) -> str:
        """
        Check podman-compose container status.

        Args:
            repo: Repository path (where podman-compose.yml or docker-compose.yml is)
            filter_name: Filter containers by name

        Returns:
            Container status.
        """
        return await _podman_compose_status_impl(repo, filter_name)

    @auto_heal()
    @registry.tool()
    async def podman_compose_up(
        repo: str,
        detach: bool = True,
        services: str = "",
        build: bool = False,
        timeout: int = 180,
    ) -> str:
        """
        Start podman-compose services.

        Args:
            repo: Repository path (where podman-compose.yml or docker-compose.yml is)
            detach: Run in background
            services: Specific services to start (space-separated, empty = all)
            build: Build images before starting
            timeout: Timeout in seconds

        Returns:
            Startup result.
        """
        return await _podman_compose_up_impl(repo, detach, services, build, timeout)

    @auto_heal()
    @registry.tool()
    async def podman_compose_down(
        repo: str,
        volumes: bool = False,
        remove_orphans: bool = False,
        timeout: int = 60,
    ) -> str:
        """
        Stop podman-compose services.

        Args:
            repo: Repository path (where podman-compose.yml or docker-compose.yml is)
            volumes: Remove named volumes
            remove_orphans: Remove containers for services not defined in compose file
            timeout: Timeout in seconds

        Returns:
            Shutdown result.
        """
        return await _podman_compose_down_impl(repo, volumes, remove_orphans, timeout)

    @auto_heal()
    @registry.tool()
    async def podman_cp(
        source: str,
        destination: str,
        to_container: bool = True,
    ) -> str:
        """
        Copy files to/from a Podman container.

        Args:
            source: Source path (local path or container:path)
            destination: Destination path (container:path or local path)
            to_container: If True, copy from local to container

        Returns:
            Copy result.

        Examples:
            podman_cp("/tmp/script.sh", "my_container:/tmp/script.sh", to_container=True)
            podman_cp("my_container:/var/log/app.log", "/tmp/app.log", to_container=False)
        """
        return await _podman_cp_impl(source, destination, to_container)

    @auto_heal()
    @registry.tool()
    async def podman_exec(
        container: str,
        command: str,
        workdir: str = "",
        user: str = "",
        timeout: int = 300,
    ) -> str:
        """
        Execute a command in a running Podman container.

        Args:
            container: Container name or ID
            command: Command to execute
            workdir: Working directory inside container
            user: User to run command as
            timeout: Timeout in seconds

        Returns:
            Command output.
        """
        return await _podman_exec_impl(container, command, workdir, user, timeout)

    @auto_heal()
    @registry.tool()
    async def podman_logs(
        container: str,
        tail: int = 100,
        follow: bool = False,
        since: str = "",
        timestamps: bool = False,
    ) -> str:
        """
        View container logs.

        Args:
            container: Container name or ID
            tail: Number of lines to show from end (0 for all)
            follow: Follow log output (not recommended for automation)
            since: Show logs since timestamp (e.g., "2024-01-01", "10m", "1h")
            timestamps: Show timestamps

        Returns:
            Container logs.
        """
        return await _podman_logs_impl(container, tail, follow, since, timestamps)

    @auto_heal()
    @registry.tool()
    async def podman_images(
        filter_name: str = "",
        all_images: bool = False,
    ) -> str:
        """
        List container images.

        Args:
            filter_name: Filter images by name/reference
            all_images: Show all images (including intermediate)

        Returns:
            Image list.
        """
        return await _podman_images_impl(filter_name, all_images)

    @auto_heal()
    @registry.tool()
    async def podman_pull(
        image: str,
        quiet: bool = False,
    ) -> str:
        """
        Pull a container image.

        Args:
            image: Image name with optional tag (e.g., "nginx:latest", "quay.io/myorg/myimage:v1")
            quiet: Suppress progress output

        Returns:
            Pull result.
        """
        return await _podman_pull_impl(image, quiet)

    @auto_heal()
    @registry.tool()
    async def podman_build(
        repo: str,
        tag: str,
        dockerfile: str = "Dockerfile",
        no_cache: bool = False,
        build_args: str = "",
        timeout: int = 600,
    ) -> str:
        """
        Build a container image.

        Args:
            repo: Repository path (build context)
            tag: Image tag (e.g., "myapp:latest")
            dockerfile: Dockerfile path relative to repo
            no_cache: Don't use cache when building
            build_args: Build arguments as KEY=VALUE pairs, space-separated
            timeout: Timeout in seconds

        Returns:
            Build result.
        """
        return await _podman_build_impl(repo, tag, dockerfile, no_cache, build_args, timeout)

    @auto_heal()
    @registry.tool()
    async def podman_run(
        image: str,
        name: str = "",
        command: str = "",
        detach: bool = True,
        rm: bool = False,
        ports: str = "",
        volumes: str = "",
        env_vars: str = "",
        network: str = "",
        timeout: int = 60,
    ) -> str:
        """
        Run a container from an image.

        Args:
            image: Image name with optional tag
            name: Container name
            command: Command to run in container
            detach: Run in background
            rm: Remove container when it exits
            ports: Port mappings (e.g., "8080:80 9090:90")
            volumes: Volume mounts (e.g., "/host/path:/container/path:Z")
            env_vars: Environment variables (e.g., "FOO=bar BAZ=qux")
            network: Network to connect to
            timeout: Timeout in seconds

        Returns:
            Run result with container ID.
        """
        return await _podman_run_impl(image, name, command, detach, rm, ports, volumes, env_vars, network, timeout)

    @auto_heal()
    @registry.tool()
    async def podman_stop(
        container: str,
        timeout_seconds: int = 10,
    ) -> str:
        """
        Stop a running container.

        Args:
            container: Container name or ID
            timeout_seconds: Seconds to wait before killing

        Returns:
            Stop result.
        """
        return await _podman_stop_impl(container, timeout_seconds)

    @auto_heal()
    @registry.tool()
    async def podman_rm(
        container: str,
        force: bool = False,
        volumes: bool = False,
    ) -> str:
        """
        Remove a container.

        Args:
            container: Container name or ID
            force: Force removal of running container
            volumes: Remove associated volumes

        Returns:
            Remove result.
        """
        return await _podman_rm_impl(container, force, volumes)

    return registry.count
