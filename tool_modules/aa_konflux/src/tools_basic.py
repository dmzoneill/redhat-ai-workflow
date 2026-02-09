"""AA Konflux MCP Server - Konflux/Tekton CI/CD operations.

Konflux is a cloud-native software factory using Kubernetes and Tekton.
Authentication: Uses ~/.kube/config.k for Konflux cluster access.
"""

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


@auto_heal_konflux()
async def _konflux_failed_pipelines_impl(
    namespace: str = DEFAULT_NAMESPACE, limit: int = 5
) -> str:
    """Get recent failed pipelines."""
    success, output = await run_cmd(
        ["kubectl", "get", "pipelineruns", "-n", namespace, "-o", "wide"]
    )
    if not success:
        return f"❌ Failed: {output}"

    lines = output.strip().split("\n")
    header = lines[0] if lines else ""
    failed = [ln for ln in lines[1:] if "Failed" in ln][:limit]

    if not failed:
        return f"No failed pipelines in {namespace}"

    return (
        f"## Failed Pipelines: {namespace}\n\n```\n{header}\n"
        + "\n".join(failed)
        + "\n```"
    )


@auto_heal_konflux()
async def _konflux_get_build_logs_impl(
    build_name: str, namespace: str = DEFAULT_NAMESPACE, task: str = ""
) -> str:
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
        output,
        max_length=20000,
        mode="tail",
        suffix="... (truncated, showing last 20000 chars)",
    )
    return f"## Build Logs: {build_name}\n\n```\n{output}\n```"


@auto_heal_konflux()
async def _konflux_get_component_impl(
    name: str, namespace: str = DEFAULT_NAMESPACE
) -> str:
    """Get detailed information about a Konflux component."""
    success, output = await run_cmd(
        ["kubectl", "get", "component", name, "-n", namespace, "-o", "yaml"]
    )
    if not success:
        return f"❌ Failed: {output}"
    return f"## Component: {name}\n\n```yaml\n{truncate_output(output, max_length=10000)}\n```"


@auto_heal_konflux()
async def _konflux_get_release_impl(
    name: str, namespace: str = DEFAULT_NAMESPACE
) -> str:
    """Get detailed information about a Konflux release."""
    success, output = await run_cmd(
        ["kubectl", "get", "release", name, "-n", namespace, "-o", "yaml"]
    )
    if not success:
        return f"❌ Failed: {output}"
    return f"## Release: {name}\n\n```yaml\n{truncate_output(output, max_length=10000)}\n```"


@auto_heal_konflux()
async def _konflux_get_snapshot_impl(
    name: str, namespace: str = DEFAULT_NAMESPACE
) -> str:
    """Get details of a specific snapshot."""
    success, output = await run_cmd(
        ["kubectl", "get", "snapshot", name, "-n", namespace, "-o", "yaml"]
    )
    if not success:
        return f"❌ Failed: {output}"
    return f"## Snapshot: {name}\n\n```yaml\n{output}\n```"


@auto_heal_konflux()
async def _konflux_get_test_results_impl(
    namespace: str = DEFAULT_NAMESPACE, snapshot: str = "", limit: int = 10
) -> str:
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


@auto_heal_konflux()
async def _konflux_list_applications_impl(namespace: str = DEFAULT_NAMESPACE) -> str:
    """List Konflux applications."""
    success, output = await run_cmd(
        ["kubectl", "get", "applications", "-n", namespace, "-o", "wide"]
    )
    if not success:
        return f"❌ Failed: {output}"
    return f"## Applications: {namespace}\n\n```\n{output}\n```"


@auto_heal_konflux()
async def _konflux_list_builds_impl(
    namespace: str = DEFAULT_NAMESPACE, component: str = "", limit: int = 10
) -> str:
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
async def _konflux_list_components_impl(namespace: str = DEFAULT_NAMESPACE) -> str:
    """List Konflux components."""
    success, output = await run_cmd(
        ["kubectl", "get", "components", "-n", namespace, "-o", "wide"]
    )
    if not success:
        return f"❌ Failed: {output}"
    return f"## Components: {namespace}\n\n```\n{output}\n```"


@auto_heal_konflux()
async def _konflux_list_integration_tests_impl(
    namespace: str = DEFAULT_NAMESPACE, application: str = ""
) -> str:
    """List IntegrationTestScenarios in a namespace."""
    args = ["kubectl", "get", "integrationtestscenarios", "-n", namespace, "-o", "wide"]
    if application:
        args.extend(["-l", f"appstudio.openshift.io/application={application}"])
    success, output = await run_cmd(args)
    if not success:
        return f"❌ Failed: {output}"
    return f"## Integration Tests: {namespace}\n\n```\n{output}\n```"


@auto_heal_konflux()
async def _konflux_list_pipelines_impl(
    namespace: str = DEFAULT_NAMESPACE, limit: int = 10
) -> str:
    """List recent pipeline runs in a Konflux namespace."""
    success, output = await run_cmd(
        [
            "kubectl",
            "get",
            "pipelineruns",
            "-n",
            namespace,
            "-o",
            "wide",
            "--sort-by=.metadata.creationTimestamp",
        ]
    )
    if not success:
        return f"❌ Failed: {output}\n\nRun: `kube k` to authenticate"

    lines = output.strip().split("\n")
    if len(lines) > limit + 1:
        lines = lines[:1] + lines[-(limit):]
    return f"## Konflux Pipelines: {namespace}\n\n```\n" + "\n".join(lines) + "\n```"


@auto_heal_konflux()
async def _konflux_list_releases_impl(
    namespace: str = DEFAULT_NAMESPACE, limit: int = 10
) -> str:
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
async def _konflux_list_snapshots_impl(
    namespace: str = DEFAULT_NAMESPACE, limit: int = 10
) -> str:
    """List Konflux snapshots."""
    success, output = await run_cmd(
        [
            "kubectl",
            "get",
            "snapshots",
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

    return f"## Snapshots: {namespace}\n\n```\n" + "\n".join(lines) + "\n```"


@auto_heal_konflux()
async def _konflux_namespace_summary_impl(namespace: str = DEFAULT_NAMESPACE) -> str:
    """Get a summary of all Konflux resources in a namespace."""
    lines = [f"## Konflux Summary: {namespace}", ""]
    resources = [
        ("Applications", "applications"),
        ("Components", "components"),
        ("Snapshots", "snapshots"),
        ("IntegrationTests", "integrationtestscenarios"),
        ("Releases", "releases"),
        ("ReleasePlans", "releaseplans"),
    ]
    for display, resource in resources:
        success, output = await run_cmd(
            ["kubectl", "get", resource, "-n", namespace, "--no-headers"]
        )
        if success:
            count = len([ln for ln in output.strip().split("\n") if ln.strip()])
            lines.append(f"- **{display}:** {count}")
        else:
            lines.append(f"- **{display}:** ❌ Error")

    # Get recent pipeline runs summary
    success, output = await run_cmd(
        ["kubectl", "get", "pipelineruns", "-n", namespace, "--no-headers"]
    )
    if success:
        pr_lines = [ln for ln in output.strip().split("\n") if ln.strip()]
        running = len([ln for ln in pr_lines if "Running" in ln or "Unknown" in ln])
        succeeded = len([ln for ln in pr_lines if "Succeeded" in ln])
        failed = len([ln for ln in pr_lines if "Failed" in ln])
        lines.append("")
        lines.append("### Pipeline Runs")
        lines.append(f"- ✅ Succeeded: {succeeded}")
        lines.append(f"- ❌ Failed: {failed}")
        lines.append(f"- ⏳ Running: {running}")

    return "\n".join(lines)


@auto_heal_konflux()
async def _konflux_running_pipelines_impl(namespace: str = DEFAULT_NAMESPACE) -> str:
    """Get currently running pipelines."""
    success, output = await run_cmd(
        [
            "kubectl",
            "get",
            "pipelineruns",
            "-n",
            namespace,
            "--field-selector=status.conditions[0].reason=Running",
            "-o",
            "wide",
        ]
    )
    if not success:
        # Try without field selector
        success, output = await run_cmd(
            ["kubectl", "get", "pipelineruns", "-n", namespace, "-o", "wide"]
        )
        if success:
            # Filter to running only
            lines = output.strip().split("\n")
            header = lines[0] if lines else ""
            running = [ln for ln in lines[1:] if "Running" in ln or "Unknown" in ln]
            if not running:
                return f"No running pipelines in {namespace}"
            output = header + "\n" + "\n".join(running)

    return f"## Running Pipelines: {namespace}\n\n```\n{output}\n```"


@auto_heal_konflux()
async def _konflux_status_impl() -> str:
    """Check Konflux cluster connectivity."""
    success, output = await run_cmd(["kubectl", "cluster-info"])
    if not success:
        return (
            f"❌ Not connected to Konflux\n\n{output}\n\nRun: `kube k` to authenticate"
        )
    return f"✅ Connected to Konflux\n\n```\n{output}\n```"


@auto_heal_konflux()
async def _tkn_pipelinerun_cancel_impl(
    run_name: str, namespace: str = DEFAULT_NAMESPACE
) -> str:
    """Cancel a running pipeline."""
    success, output = await run_cmd(
        ["tkn", "pipelinerun", "cancel", run_name, "-n", namespace]
    )
    if not success:
        return f"❌ Failed: {output}"
    return f"✅ Pipeline run cancelled: {run_name}\n\n{output}"


@auto_heal_konflux()
async def _tkn_pipelinerun_delete_impl(
    run_name: str, namespace: str = DEFAULT_NAMESPACE
) -> str:
    """Delete a pipeline run."""
    success, output = await run_cmd(
        ["tkn", "pipelinerun", "delete", run_name, "-n", namespace, "-f"]
    )
    if not success:
        return f"❌ Failed: {output}"
    return f"✅ Pipeline run deleted: {run_name}"


@auto_heal_konflux()
async def _tkn_pipelinerun_describe_impl(
    run_name: str, namespace: str = DEFAULT_NAMESPACE
) -> str:
    """Describe a pipeline run in detail."""
    success, output = await run_cmd(
        ["tkn", "pipelinerun", "describe", run_name, "-n", namespace]
    )
    if not success:
        return f"❌ Failed: {output}"
    return f"## Pipeline Run: {run_name}\n\n```\n{truncate_output(output, max_length=10000)}\n```"


@auto_heal_konflux()
async def _tkn_pipelinerun_list_impl(
    namespace: str = DEFAULT_NAMESPACE, limit: int = 10, label: str = ""
) -> str:
    """List pipeline runs in a namespace."""
    args = ["tkn", "pipelinerun", "list", "-n", namespace, f"--limit={limit}"]
    if label:
        args.extend(["--label", label])
    success, output = await run_cmd(args)
    if not success:
        return f"❌ Failed: {output}"
    return f"## Pipeline Runs: {namespace}\n\n```\n{output}\n```"


@auto_heal_konflux()
async def _tkn_pipelinerun_logs_impl(
    run_name: str,
    namespace: str = DEFAULT_NAMESPACE,
    task: str = "",
    all_tasks: bool = True,
) -> str:
    """Get logs from a pipeline run."""
    args = ["tkn", "pipelinerun", "logs", run_name, "-n", namespace]
    if task:
        args.extend(["--task", task])
    elif all_tasks:
        args.append("--all")
    success, output = await run_cmd(args, timeout=120)
    if not success:
        return f"❌ Failed: {output}"
    return f"## Logs: {run_name}\n\n```\n{truncate_output(output, max_length=20000, mode='tail')}\n```"


@auto_heal_konflux()
async def _tkn_taskrun_list_impl(
    namespace: str = DEFAULT_NAMESPACE, limit: int = 10
) -> str:
    """List task runs in a namespace."""
    success, output = await run_cmd(
        ["tkn", "taskrun", "list", "-n", namespace, f"--limit={limit}"]
    )
    if not success:
        return f"❌ Failed: {output}"
    return f"## Task Runs: {namespace}\n\n```\n{output}\n```"


def _register_status_tools(registry: ToolRegistry) -> None:
    """Register status tools."""

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_failed_pipelines(
        namespace: str = DEFAULT_NAMESPACE, limit: int = 5
    ) -> str:
        """Get recent failed pipelines."""
        return await _konflux_failed_pipelines_impl(namespace, limit)

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_running_pipelines(namespace: str = DEFAULT_NAMESPACE) -> str:
        """Get currently running pipelines."""
        return await _konflux_running_pipelines_impl(namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_status() -> str:
        """Check Konflux cluster connectivity."""
        return await _konflux_status_impl()

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_namespace_summary(namespace: str = DEFAULT_NAMESPACE) -> str:
        """Get a summary of all Konflux resources in a namespace."""
        return await _konflux_namespace_summary_impl(namespace)


def _register_list_tools(registry: ToolRegistry) -> None:
    """Register list tools."""

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_list_applications(namespace: str = DEFAULT_NAMESPACE) -> str:
        """List Konflux applications."""
        return await _konflux_list_applications_impl(namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_list_builds(
        namespace: str = DEFAULT_NAMESPACE, component: str = "", limit: int = 10
    ) -> str:
        """List build PipelineRuns for components."""
        return await _konflux_list_builds_impl(namespace, component, limit)

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_list_components(namespace: str = DEFAULT_NAMESPACE) -> str:
        """List Konflux components."""
        return await _konflux_list_components_impl(namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_list_integration_tests(
        namespace: str = DEFAULT_NAMESPACE, application: str = ""
    ) -> str:
        """List IntegrationTestScenarios in a namespace."""
        return await _konflux_list_integration_tests_impl(namespace, application)

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_list_pipelines(
        namespace: str = DEFAULT_NAMESPACE, limit: int = 10
    ) -> str:
        """List recent pipeline runs in a Konflux namespace."""
        return await _konflux_list_pipelines_impl(namespace, limit)

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_list_releases(
        namespace: str = DEFAULT_NAMESPACE, limit: int = 10
    ) -> str:
        """List Konflux releases."""
        return await _konflux_list_releases_impl(namespace, limit)

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_list_snapshots(
        namespace: str = DEFAULT_NAMESPACE, limit: int = 10
    ) -> str:
        """List Konflux snapshots."""
        return await _konflux_list_snapshots_impl(namespace, limit)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_pipelinerun_list(
        namespace: str = DEFAULT_NAMESPACE, limit: int = 10, label: str = ""
    ) -> str:
        """List pipeline runs in a namespace."""
        return await _tkn_pipelinerun_list_impl(namespace, limit, label)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_taskrun_list(
        namespace: str = DEFAULT_NAMESPACE, limit: int = 10
    ) -> str:
        """List task runs in a namespace."""
        return await _tkn_taskrun_list_impl(namespace, limit)


def _register_get_tools(registry: ToolRegistry) -> None:
    """Register get tools."""

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_get_build_logs(
        build_name: str, namespace: str = DEFAULT_NAMESPACE, task: str = ""
    ) -> str:
        """Get logs from a build PipelineRun using tkn CLI."""
        return await _konflux_get_build_logs_impl(build_name, namespace, task)

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_get_component(
        name: str, namespace: str = DEFAULT_NAMESPACE
    ) -> str:
        """Get detailed information about a Konflux component."""
        return await _konflux_get_component_impl(name, namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_get_release(name: str, namespace: str = DEFAULT_NAMESPACE) -> str:
        """Get detailed information about a Konflux release."""
        return await _konflux_get_release_impl(name, namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_get_snapshot(
        name: str, namespace: str = DEFAULT_NAMESPACE
    ) -> str:
        """Get details of a specific snapshot."""
        return await _konflux_get_snapshot_impl(name, namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def konflux_get_test_results(
        namespace: str = DEFAULT_NAMESPACE, snapshot: str = "", limit: int = 10
    ) -> str:
        """Get integration test results from test pipelineruns."""
        return await _konflux_get_test_results_impl(namespace, snapshot, limit)


def _register_tekton_mgmt_tools(registry: ToolRegistry) -> None:
    """Register tekton mgmt tools."""

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_pipelinerun_cancel(
        run_name: str, namespace: str = DEFAULT_NAMESPACE
    ) -> str:
        """Cancel a running pipeline."""
        return await _tkn_pipelinerun_cancel_impl(run_name, namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_pipelinerun_delete(
        run_name: str, namespace: str = DEFAULT_NAMESPACE
    ) -> str:
        """Delete a pipeline run."""
        return await _tkn_pipelinerun_delete_impl(run_name, namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_pipelinerun_describe(
        run_name: str, namespace: str = DEFAULT_NAMESPACE
    ) -> str:
        """Describe a pipeline run in detail."""
        return await _tkn_pipelinerun_describe_impl(run_name, namespace)

    @auto_heal_konflux()
    @registry.tool()
    async def tkn_pipelinerun_logs(
        run_name: str,
        namespace: str = DEFAULT_NAMESPACE,
        task: str = "",
        all_tasks: bool = True,
    ) -> str:
        """Get logs from a pipeline run."""
        return await _tkn_pipelinerun_logs_impl(run_name, namespace, task, all_tasks)


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""
    registry = ToolRegistry(server)

    _register_status_tools(registry)
    _register_list_tools(registry)
    _register_get_tools(registry)
    _register_tekton_mgmt_tools(registry)

    return registry.count
