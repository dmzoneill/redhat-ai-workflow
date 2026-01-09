"""Konflux Extra Tools - Advanced konflux operations.

For basic operations, see tools_basic.py.

Tools included (~17):
- konflux_list_integration_tests, konflux_get_test_results, konflux_list_releases, ...
"""

import os
from typing import cast

from mcp.server.fastmcp import FastMCP

from server.auto_heal_decorator import auto_heal_konflux
from server.tool_registry import ToolRegistry
from server.utils import get_kubeconfig, load_config
from server.utils import run_cmd as run_cmd_base
from server.utils import truncate_output

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT  # noqa: F401 - side effect: adds to sys.path


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


def register_tools(server: FastMCP) -> int:
    """Register extra konflux tools with the MCP server."""
    registry = ToolRegistry(server)

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_list_integration_tests(namespace: str = DEFAULT_NAMESPACE, application: str = "") -> str:
        """List IntegrationTestScenarios in a namespace."""
        args = ["kubectl", "get", "integrationtestscenarios", "-n", namespace, "-o", "wide"]
        if application:
            args.extend(["-l", f"appstudio.openshift.io/application={application}"])
        success, output = await run_cmd(args)
        if not success:
            return f"❌ Failed: {output}"
        return f"## Integration Tests: {namespace}\n\n```\n{output}\n```"

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_get_test_results(namespace: str = DEFAULT_NAMESPACE, snapshot: str = "", limit: int = 10) -> str:
        """Get integration test results from test pipelineruns."""
        args = [
            "kubectl",
            "get",
            "pipelineruns",
            "-n",
            namespace,
            "-l",
            "test.appstudio.openshift.io/scenario",
            "-o",
            "wide",
            "--sort-by=.metadata.creationTimestamp",
        ]
        if snapshot:
            args = [
                "kubectl",
                "get",
                "pipelineruns",
                "-n",
                namespace,
                "-l",
                f"appstudio.openshift.io/snapshot={snapshot}",
                "-o",
                "wide",
            ]
        success, output = await run_cmd(args)
        if not success:
            return f"❌ Failed: {output}"
        # Limit output to recent results
        lines = output.strip().split("\n")
        if len(lines) > limit + 1:
            lines = lines[:1] + lines[-(limit):]
        return f"## Test Results: {namespace}\n\n```\n" + "\n".join(lines) + "\n```"

    # ==================== RELEASES ====================

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_list_releases(namespace: str = DEFAULT_NAMESPACE, limit: int = 10) -> str:
        """List Konflux releases."""
        success, output = await run_cmd(
            [
                "kubectl",
                "get",
                "releases",
                "-n",
                namespace,
                "-o",
                "wide",
                "--sort-by=.metadata.creationTimestamp",
            ]
        )
        if not success:
            return f"❌ Failed: {output}"
        lines = output.strip().split("\n")
        if len(lines) > limit + 1:
            lines = lines[:1] + lines[-(limit):]
        return f"## Releases: {namespace}\n\n```\n" + "\n".join(lines) + "\n```"

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_get_release(name: str, namespace: str = DEFAULT_NAMESPACE) -> str:
        """Get detailed information about a Konflux release."""
        success, output = await run_cmd(["kubectl", "get", "release", name, "-n", namespace, "-o", "yaml"])
        if not success:
            return f"❌ Failed: {output}"
        return f"## Release: {name}\n\n```yaml\n{truncate_output(output, max_length=10000)}\n```"

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_list_release_plans(namespace: str = DEFAULT_NAMESPACE) -> str:
        """List Konflux release plans."""
        success, output = await run_cmd(["kubectl", "get", "releaseplans", "-n", namespace, "-o", "wide"])
        if not success:
            return f"❌ Failed: {output}"
        return f"## Release Plans: {namespace}\n\n```\n{output}\n```"

    # ==================== BUILDS ====================

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_list_builds(namespace: str = DEFAULT_NAMESPACE, component: str = "", limit: int = 10) -> str:
        """List build PipelineRuns for components."""
        args = [
            "kubectl",
            "get",
            "pipelineruns",
            "-n",
            namespace,
            "-l",
            "pipelines.appstudio.openshift.io/type=build",
            "-o",
            "wide",
            "--sort-by=.metadata.creationTimestamp",
        ]
        if component:
            args = [
                "kubectl",
                "get",
                "pipelineruns",
                "-n",
                namespace,
                "-l",
                f"appstudio.openshift.io/component={component}",
                "-o",
                "wide",
                "--sort-by=.metadata.creationTimestamp",
            ]
        success, output = await run_cmd(args)
        if not success:
            return f"❌ Failed: {output}"
        lines = output.strip().split("\n")
        if len(lines) > limit + 1:
            lines = lines[:1] + lines[-(limit):]
        return f"## Builds: {namespace}\n\n```\n" + "\n".join(lines) + "\n```"

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_get_build_logs(build_name: str, namespace: str = DEFAULT_NAMESPACE, task: str = "") -> str:
        """Get logs from a build PipelineRun using tkn CLI."""
        args = ["tkn", "pipelinerun", "logs", build_name, "-n", namespace]
        if task:
            args.extend(["--task", task])
        else:
            args.append("--all")
        success, output = await run_cmd(args, timeout=120)
        if not success:
            return f"❌ Failed: {output}"
        output = truncate_output(
            output, max_length=20000, mode="tail", suffix="... (truncated, showing last 20000 chars)"
        )
        return f"## Build Logs: {build_name}\n\n```\n{output}\n```"

    # ==================== ENVIRONMENTS ====================

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_list_environments(namespace: str = DEFAULT_NAMESPACE) -> str:
        """List Konflux environments (deployment targets)."""
        success, output = await run_cmd(["kubectl", "get", "environments", "-n", namespace, "-o", "wide"])
        if not success:
            # Try snapshotenvironmentbindings as fallback
            success, output = await run_cmd(
                ["kubectl", "get", "snapshotenvironmentbindings", "-n", namespace, "-o", "wide"]
            )
            if not success:
                return f"❌ Failed: {output}"
        return f"## Environments: {namespace}\n\n```\n{output}\n```"

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_pipelinerun_delete(run_name: str, namespace: str = DEFAULT_NAMESPACE) -> str:
        """Delete a pipeline run."""
        success, output = await run_cmd(["tkn", "pipelinerun", "delete", run_name, "-n", namespace, "-f"])
        if not success:
            return f"❌ Failed: {output}"
        return f"✅ Pipeline run deleted: {run_name}"

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_taskrun_list(namespace: str = DEFAULT_NAMESPACE, limit: int = 10) -> str:
        """List task runs in a namespace."""
        success, output = await run_cmd(["tkn", "taskrun", "list", "-n", namespace, f"--limit={limit}"])
        if not success:
            return f"❌ Failed: {output}"
        return f"## Task Runs: {namespace}\n\n```\n{output}\n```"

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_taskrun_describe(run_name: str, namespace: str = DEFAULT_NAMESPACE) -> str:
        """Describe a task run in detail."""
        success, output = await run_cmd(["tkn", "taskrun", "describe", run_name, "-n", namespace])
        if not success:
            return f"❌ Failed: {output}"
        return f"## Task Run: {run_name}\n\n```\n{output}\n```"

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_taskrun_logs(run_name: str, namespace: str = DEFAULT_NAMESPACE) -> str:
        """Get logs from a task run."""
        success, output = await run_cmd(["tkn", "taskrun", "logs", run_name, "-n", namespace], timeout=120)
        if not success:
            return f"❌ Failed: {output}"
        return f"## Logs: {run_name}\n\n```\n{truncate_output(output, max_length=15000, mode='tail')}\n```"

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_pipeline_list(namespace: str = DEFAULT_NAMESPACE) -> str:
        """List available pipelines in a namespace."""
        success, output = await run_cmd(["tkn", "pipeline", "list", "-n", namespace])
        if not success:
            return f"❌ Failed: {output}"
        return f"## Pipelines: {namespace}\n\n```\n{output}\n```"

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_pipeline_describe(pipeline_name: str, namespace: str = DEFAULT_NAMESPACE) -> str:
        """Describe a pipeline definition."""
        success, output = await run_cmd(["tkn", "pipeline", "describe", pipeline_name, "-n", namespace])
        if not success:
            return f"❌ Failed: {output}"
        return f"## Pipeline: {pipeline_name}\n\n```\n{output}\n```"

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_pipeline_start(pipeline_name: str, namespace: str = DEFAULT_NAMESPACE, params: str = "") -> str:
        """Start a pipeline run."""
        args = ["tkn", "pipeline", "start", pipeline_name, "-n", namespace]
        if params:
            for p in params.split(","):
                args.extend(["--param", p.strip()])
        success, output = await run_cmd(args)
        if not success:
            return f"❌ Failed: {output}"
        return f"✅ Pipeline started: {pipeline_name}\n\n{output}"

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_task_list(namespace: str = DEFAULT_NAMESPACE) -> str:
        """List available tasks in a namespace."""
        success, output = await run_cmd(["tkn", "task", "list", "-n", namespace])
        if not success:
            return f"❌ Failed: {output}"
        return f"## Tasks: {namespace}\n\n```\n{output}\n```"

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_task_describe(task_name: str, namespace: str = DEFAULT_NAMESPACE) -> str:
        """Describe a task definition."""
        success, output = await run_cmd(["tkn", "task", "describe", task_name, "-n", namespace])
        if not success:
            return f"❌ Failed: {output}"
        return f"## Task: {task_name}\n\n```\n{output}\n```"

    # REMOVED: tkn_clustertask_list - low value, rarely used
    # REMOVED: tkn_triggertemplate_list - low value, rarely used
    # REMOVED: tkn_eventlistener_list - low value, rarely used

    return registry.count
