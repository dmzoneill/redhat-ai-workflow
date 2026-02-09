"""AA Konflux MCP Server - Konflux/Tekton CI/CD operations.

Konflux is a cloud-native software factory using Kubernetes and Tekton.
Authentication: Uses ~/.kube/config.k for Konflux cluster access.
"""

import json
import os
import tempfile

from fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization


from server.auto_heal_decorator import auto_heal_konflux
from server.tool_registry import ToolRegistry
from server.utils import truncate_output

from .common import DEFAULT_NAMESPACE, run_cmd

# ==================== PIPELINE RUNS ====================


# ==================== TOOL IMPLEMENTATIONS ====================


async def _konflux_get_application_impl(name: str, namespace: str) -> str:
    """Implementation of konflux_get_application tool."""
    success, output = await run_cmd(
        ["kubectl", "get", "application", name, "-n", namespace, "-o", "yaml"]
    )
    if not success:
        return f"❌ Failed: {output}"
    return f"## Application: {name}\n\n```yaml\n{truncate_output(output, max_length=10000)}\n```"


async def _konflux_get_pipeline_impl(name: str, namespace: str) -> str:
    """Implementation of konflux_get_pipeline tool."""
    success, output = await run_cmd(
        ["kubectl", "get", "pipelinerun", name, "-n", namespace, "-o", "yaml"]
    )
    if not success:
        return f"❌ Failed: {output}"
    return f"## Pipeline: {name}\n\n```yaml\n{truncate_output(output, max_length=10000)}\n```"


async def _konflux_list_environments_impl(namespace: str) -> str:
    """Implementation of konflux_list_environments tool."""
    success, output = await run_cmd(
        ["kubectl", "get", "environments", "-n", namespace, "-o", "wide"]
    )
    if not success:
        # Try snapshotenvironmentbindings as fallback
        success, output = await run_cmd(
            [
                "kubectl",
                "get",
                "snapshotenvironmentbindings",
                "-n",
                namespace,
                "-o",
                "wide",
            ]
        )
        if not success:
            return f"❌ Failed: {output}"
    return f"## Environments: {namespace}\n\n```\n{output}\n```"


async def _konflux_list_release_plans_impl(namespace: str) -> str:
    """Implementation of konflux_list_release_plans tool."""
    success, output = await run_cmd(
        ["kubectl", "get", "releaseplans", "-n", namespace, "-o", "wide"]
    )
    if not success:
        return f"❌ Failed: {output}"
    return f"## Release Plans: {namespace}\n\n```\n{output}\n```"


async def _tkn_describe_pipelinerun_impl(name: str, namespace: str) -> str:
    """Implementation of tkn_describe_pipelinerun tool."""
    success, output = await run_cmd(
        ["tkn", "pipelinerun", "describe", name, "-n", namespace]
    )
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
    success, output = await run_cmd(
        ["tkn", "pipeline", "describe", pipeline_name, "-n", namespace]
    )
    if not success:
        return f"❌ Failed: {output}"
    return f"## Pipeline: {pipeline_name}\n\n```\n{output}\n```"


async def _tkn_pipeline_list_impl(namespace: str) -> str:
    """Implementation of tkn_pipeline_list tool."""
    success, output = await run_cmd(["tkn", "pipeline", "list", "-n", namespace])
    if not success:
        return f"❌ Failed: {output}"
    return f"## Pipelines: {namespace}\n\n```\n{output}\n```"


async def _tkn_pipeline_start_impl(
    pipeline_name: str, namespace: str, params: str
) -> str:
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
    success, output = await run_cmd(
        ["tkn", "task", "describe", task_name, "-n", namespace]
    )
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
    success, output = await run_cmd(
        ["tkn", "taskrun", "describe", run_name, "-n", namespace]
    )
    if not success:
        return f"❌ Failed: {output}"
    return f"## Task Run: {run_name}\n\n```\n{output}\n```"


async def _tkn_taskrun_logs_impl(run_name: str, namespace: str) -> str:
    """Implementation of tkn_taskrun_logs tool."""
    success, output = await run_cmd(
        ["tkn", "taskrun", "logs", run_name, "-n", namespace], timeout=120
    )
    if not success:
        return f"❌ Failed: {output}"
    return f"## Logs: {run_name}\n\n```\n{truncate_output(output, max_length=15000, mode='tail')}\n```"


async def _konflux_create_release_impl(
    snapshot: str,
    release_plan: str = "",
    namespace: str = DEFAULT_NAMESPACE,
) -> str:
    """Implementation of konflux_create_release tool.

    Creates a Konflux Release CR from a snapshot. If release_plan is not
    provided, auto-detects by listing available ReleasePlans in the namespace.
    """
    # Auto-detect release plan if not provided
    if not release_plan:
        success, output = await run_cmd(
            ["kubectl", "get", "releaseplan", "-n", namespace, "-o", "json"]
        )
        if not success:
            return f"❌ Failed to list release plans: {output}"
        try:
            data = json.loads(output)
            items = data.get("items", [])
            if not items:
                return f"❌ No ReleasePlans found in namespace {namespace}"
            release_plan = items[0]["metadata"]["name"]
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            return f"❌ Failed to parse release plans: {e}"

    # Build the Release CR YAML
    release_yaml = (
        "apiVersion: appstudio.redhat.com/v1alpha1\n"
        "kind: Release\n"
        "metadata:\n"
        f"  generateName: release-\n"
        f"  namespace: {namespace}\n"
        "spec:\n"
        f"  snapshot: {snapshot}\n"
        f"  releasePlan: {release_plan}\n"
    )

    # Write YAML to a temporary file and apply it
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(release_yaml)
            tmp_path = f.name

        success, output = await run_cmd(["kubectl", "apply", "-f", tmp_path])
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    if not success:
        return f"❌ Failed to create release: {output}"

    # Get the most recently created release to confirm
    verify_success, verify_output = await run_cmd(
        [
            "kubectl",
            "get",
            "release",
            "-n",
            namespace,
            "--sort-by=.metadata.creationTimestamp",
            "-o",
            "json",
        ]
    )
    if verify_success:
        try:
            data = json.loads(verify_output)
            items = data.get("items", [])
            if items:
                latest = items[-1]
                name = latest["metadata"]["name"]
                conditions = latest.get("status", {}).get("conditions", [])
                status_str = (
                    conditions[-1].get("reason", "Pending") if conditions else "Pending"
                )
                return (
                    f"✅ Release created successfully\n\n"
                    f"- **Name:** {name}\n"
                    f"- **Snapshot:** {snapshot}\n"
                    f"- **ReleasePlan:** {release_plan}\n"
                    f"- **Status:** {status_str}\n"
                    f"- **Namespace:** {namespace}"
                )
        except (json.JSONDecodeError, KeyError, IndexError):
            pass

    return f"✅ Release created: {output.strip()}\n\nSnapshot: {snapshot}\nReleasePlan: {release_plan}"


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    # ==================== TOOLS NOT USED IN SKILLS ====================
    @auto_heal_konflux()
    @registry.tool()
    async def konflux_get_application(
        name: str, namespace: str = DEFAULT_NAMESPACE
    ) -> str:
        """Get detailed information about a Konflux application."""
        return await _konflux_get_application_impl(name, namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_get_pipeline(
        name: str, namespace: str = DEFAULT_NAMESPACE
    ) -> str:
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
    async def tkn_describe_pipelinerun(
        name: str, namespace: str = DEFAULT_NAMESPACE
    ) -> str:
        """Describe a Tekton pipeline run."""
        return await _tkn_describe_pipelinerun_impl(name, namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_logs(
        name: str, namespace: str = DEFAULT_NAMESPACE, task: str = ""
    ) -> str:
        """Get logs from a Tekton pipeline run."""
        return await _tkn_logs_impl(name, namespace, task)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_pipeline_describe(
        pipeline_name: str, namespace: str = DEFAULT_NAMESPACE
    ) -> str:
        """Describe a pipeline definition."""
        return await _tkn_pipeline_describe_impl(pipeline_name, namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_pipeline_list(namespace: str = DEFAULT_NAMESPACE) -> str:
        """List available pipelines in a namespace."""
        return await _tkn_pipeline_list_impl(namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_pipeline_start(
        pipeline_name: str, namespace: str = DEFAULT_NAMESPACE, params: str = ""
    ) -> str:
        """Start a pipeline run."""
        return await _tkn_pipeline_start_impl(pipeline_name, namespace, params)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_task_describe(
        task_name: str, namespace: str = DEFAULT_NAMESPACE
    ) -> str:
        """Describe a task definition."""
        return await _tkn_task_describe_impl(task_name, namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_task_list(namespace: str = DEFAULT_NAMESPACE) -> str:
        """List available tasks in a namespace."""
        return await _tkn_task_list_impl(namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_taskrun_describe(
        run_name: str, namespace: str = DEFAULT_NAMESPACE
    ) -> str:
        """Describe a task run in detail."""
        return await _tkn_taskrun_describe_impl(run_name, namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_taskrun_logs(
        run_name: str, namespace: str = DEFAULT_NAMESPACE
    ) -> str:
        """Get logs from a task run."""
        return await _tkn_taskrun_logs_impl(run_name, namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_create_release(
        snapshot: str,
        release_plan: str = "",
        namespace: str = DEFAULT_NAMESPACE,
    ) -> str:
        """Create a Konflux release from a snapshot.

        Args:
            snapshot: Name of the snapshot to release
            release_plan: Name of the ReleasePlan to use (auto-detected if empty)
            namespace: Konflux namespace

        Returns:
            Release creation confirmation with name and status.
        """
        return await _konflux_create_release_impl(snapshot, release_plan, namespace)

    return registry.count
