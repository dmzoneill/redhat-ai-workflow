"""AA Konflux MCP Server - Konflux/Tekton CI/CD operations.

Konflux is a cloud-native software factory using Kubernetes and Tekton.
Authentication: Uses ~/.kube/config.k for Konflux cluster access.
"""

import os
from typing import cast

from mcp.server.fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization


from server.auto_heal_decorator import auto_heal_konflux
from server.tool_registry import ToolRegistry
from server.utils import get_kubeconfig, load_config
from server.utils import run_cmd as run_cmd_base
from server.utils import truncate_output

# Setup project path for server imports


def get_konflux_config() -> dict:
    """Get Konflux configuration."""
    config = load_config()
    return cast(dict, config.get("konflux", {}))


def get_konflux_kubeconfig() -> str:
    """Get kubeconfig for Konflux cluster from config or default."""
    kubeconfig = get_konflux_config().get("kubeconfig")
    if kubeconfig:
        return os.path.expanduser(kubeconfig)
    # Fall back to get_kubeconfig which uses config.json namespaces section
    return get_kubeconfig("konflux")


# Cached kubeconfig for module-level default
KONFLUX_KUBECONFIG = get_konflux_kubeconfig()
DEFAULT_NAMESPACE = os.getenv("KONFLUX_NAMESPACE", "default")


async def run_konflux_cmd(cmd: list[str], kubeconfig: str | None = None, timeout: int = 60) -> tuple[bool, str]:
    """Run command with Konflux kubeconfig.

    Args:
        cmd: Command and arguments
        kubeconfig: Optional kubeconfig path (defaults to Konflux kubeconfig)
        timeout: Timeout in seconds

    Returns:
        Tuple of (success, output)
    """
    kc = kubeconfig or KONFLUX_KUBECONFIG
    env = {"KUBECONFIG": kc}
    return await run_cmd_base(cmd, env=env, timeout=timeout)


# Backward compatibility alias
run_cmd = run_konflux_cmd


# ==================== PIPELINE RUNS ====================


# ==================== TOOL IMPLEMENTATIONS ====================


async def _konflux_get_application_impl(name: str, namespace: str) -> str:
    """Implementation of konflux_get_application tool."""
    success, output = await run_cmd(["kubectl", "get", "application", name, "-n", namespace, "-o", "yaml"])
    if not success:
        return f"❌ Failed: {output}"
    return f"## Application: {name}\n\n```yaml\n{truncate_output(output, max_length=10000)}\n```"


async def _konflux_get_pipeline_impl(name: str, namespace: str) -> str:
    """Implementation of konflux_get_pipeline tool."""
    success, output = await run_cmd(["kubectl", "get", "pipelinerun", name, "-n", namespace, "-o", "yaml"])
    if not success:
        return f"❌ Failed: {output}"
    return f"## Pipeline: {name}\n\n```yaml\n{truncate_output(output, max_length=10000)}\n```"


async def _konflux_list_environments_impl(namespace: str) -> str:
    """Implementation of konflux_list_environments tool."""
    success, output = await run_cmd(["kubectl", "get", "environments", "-n", namespace, "-o", "wide"])
    if not success:
        # Try snapshotenvironmentbindings as fallback
        success, output = await run_cmd(
            ["kubectl", "get", "snapshotenvironmentbindings", "-n", namespace, "-o", "wide"]
        )
        if not success:
            return f"❌ Failed: {output}"
    return f"## Environments: {namespace}\n\n```\n{output}\n```"


async def _konflux_list_release_plans_impl(namespace: str) -> str:
    """Implementation of konflux_list_release_plans tool."""
    success, output = await run_cmd(["kubectl", "get", "releaseplans", "-n", namespace, "-o", "wide"])
    if not success:
        return f"❌ Failed: {output}"
    return f"## Release Plans: {namespace}\n\n```\n{output}\n```"


async def _tkn_describe_pipelinerun_impl(name: str, namespace: str) -> str:
    """Implementation of tkn_describe_pipelinerun tool."""
    success, output = await run_cmd(["tkn", "pipelinerun", "describe", name, "-n", namespace])
    if not success:
        return f"❌ Failed: {output}"
    return f"## Pipeline Run: {name}\n\n```\n{truncate_output(output, max_length=10000)}\n```"


async def _tkn_logs_impl(name: str, namespace: str, task: str) -> str:
    """Implementation of tkn_logs tool."""
    args = ["tkn", "pipelinerun", "logs", name, "-n", namespace]
    if task:
        args.extend(["--task", task])
    success, output = await run_cmd(args, timeout=120)
    if not success:
        return f"❌ Failed: {output}"
    return f"## Logs: {name}\n\n```\n{truncate_output(output, max_length=15000, mode='tail')}\n```"


async def _tkn_pipeline_describe_impl(pipeline_name: str, namespace: str) -> str:
    """Implementation of tkn_pipeline_describe tool."""
    success, output = await run_cmd(["tkn", "pipeline", "describe", pipeline_name, "-n", namespace])
    if not success:
        return f"❌ Failed: {output}"
    return f"## Pipeline: {pipeline_name}\n\n```\n{output}\n```"


async def _tkn_pipeline_list_impl(namespace: str) -> str:
    """Implementation of tkn_pipeline_list tool."""
    success, output = await run_cmd(["tkn", "pipeline", "list", "-n", namespace])
    if not success:
        return f"❌ Failed: {output}"
    return f"## Pipelines: {namespace}\n\n```\n{output}\n```"


async def _tkn_pipeline_start_impl(pipeline_name: str, namespace: str, params: str) -> str:
    """Implementation of tkn_pipeline_start tool."""
    args = ["tkn", "pipeline", "start", pipeline_name, "-n", namespace]
    if params:
        for p in params.split(","):
            args.extend(["--param", p.strip()])
    success, output = await run_cmd(args)
    if not success:
        return f"❌ Failed: {output}"
    return f"✅ Pipeline started: {pipeline_name}\n\n{output}"


async def _tkn_task_describe_impl(task_name: str, namespace: str) -> str:
    """Implementation of tkn_task_describe tool."""
    success, output = await run_cmd(["tkn", "task", "describe", task_name, "-n", namespace])
    if not success:
        return f"❌ Failed: {output}"
    return f"## Task: {task_name}\n\n```\n{output}\n```"


async def _tkn_task_list_impl(namespace: str) -> str:
    """Implementation of tkn_task_list tool."""
    success, output = await run_cmd(["tkn", "task", "list", "-n", namespace])
    if not success:
        return f"❌ Failed: {output}"
    return f"## Tasks: {namespace}\n\n```\n{output}\n```"


async def _tkn_taskrun_describe_impl(run_name: str, namespace: str) -> str:
    """Implementation of tkn_taskrun_describe tool."""
    success, output = await run_cmd(["tkn", "taskrun", "describe", run_name, "-n", namespace])
    if not success:
        return f"❌ Failed: {output}"
    return f"## Task Run: {run_name}\n\n```\n{output}\n```"


async def _tkn_taskrun_logs_impl(run_name: str, namespace: str) -> str:
    """Implementation of tkn_taskrun_logs tool."""
    success, output = await run_cmd(["tkn", "taskrun", "logs", run_name, "-n", namespace], timeout=120)
    if not success:
        return f"❌ Failed: {output}"
    return f"## Logs: {run_name}\n\n```\n{truncate_output(output, max_length=15000, mode='tail')}\n```"


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    # ==================== TOOLS NOT USED IN SKILLS ====================
    @auto_heal_konflux()
    @registry.tool()
    async def konflux_get_application(name: str, namespace: str = DEFAULT_NAMESPACE) -> str:
        """Get detailed information about a Konflux application."""
        return await _konflux_get_application_impl(name, namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_get_pipeline(name: str, namespace: str = DEFAULT_NAMESPACE) -> str:
        """Get details of a specific pipeline run."""
        return await _konflux_get_pipeline_impl(name, namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_list_environments(namespace: str = DEFAULT_NAMESPACE) -> str:
        """List Konflux environments (deployment targets)."""
        return await _konflux_list_environments_impl(namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_list_release_plans(namespace: str = DEFAULT_NAMESPACE) -> str:
        """List Konflux release plans."""
        return await _konflux_list_release_plans_impl(namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_describe_pipelinerun(name: str, namespace: str = DEFAULT_NAMESPACE) -> str:
        """Describe a Tekton pipeline run."""
        return await _tkn_describe_pipelinerun_impl(name, namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_logs(name: str, namespace: str = DEFAULT_NAMESPACE, task: str = "") -> str:
        """Get logs from a Tekton pipeline run."""
        return await _tkn_logs_impl(name, namespace, task)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_pipeline_describe(pipeline_name: str, namespace: str = DEFAULT_NAMESPACE) -> str:
        """Describe a pipeline definition."""
        return await _tkn_pipeline_describe_impl(pipeline_name, namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_pipeline_list(namespace: str = DEFAULT_NAMESPACE) -> str:
        """List available pipelines in a namespace."""
        return await _tkn_pipeline_list_impl(namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_pipeline_start(pipeline_name: str, namespace: str = DEFAULT_NAMESPACE, params: str = "") -> str:
        """Start a pipeline run."""
        return await _tkn_pipeline_start_impl(pipeline_name, namespace, params)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_task_describe(task_name: str, namespace: str = DEFAULT_NAMESPACE) -> str:
        """Describe a task definition."""
        return await _tkn_task_describe_impl(task_name, namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_task_list(namespace: str = DEFAULT_NAMESPACE) -> str:
        """List available tasks in a namespace."""
        return await _tkn_task_list_impl(namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_taskrun_describe(run_name: str, namespace: str = DEFAULT_NAMESPACE) -> str:
        """Describe a task run in detail."""
        return await _tkn_taskrun_describe_impl(run_name, namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_taskrun_logs(run_name: str, namespace: str = DEFAULT_NAMESPACE) -> str:
        """Get logs from a task run."""
        return await _tkn_taskrun_logs_impl(run_name, namespace)

    return registry.count
