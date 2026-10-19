# pylint: disable=duplicate-code,cyclic-import
"""Split from skill_engine.py so the public module stays importable."""

import json
import logging
from typing import Optional

import yaml
from fastmcp import Context, FastMCP
from mcp.types import TextContent

from server.tool_registry import ToolRegistry

from .skill_paths import skills_dir

logger = logging.getLogger(__name__)


def _skill_list_impl() -> list[TextContent]:
    """Implementation of skill_list tool."""
    skills = []
    if skills_dir().exists():
        for f in skills_dir().glob("*.yaml"):
            if f.name == "README.md":
                continue
            try:
                with open(f, encoding="utf-8") as fp:
                    data = yaml.safe_load(fp)
                skills.append(
                    {
                        "name": data.get("name", f.stem),
                        "description": data.get("description", "No description"),
                        "inputs": [i["name"] for i in data.get("inputs", [])],
                    }
                )
            except Exception as e:  # pylint: disable=broad-exception-caught
                skills.append(
                    {"name": f.stem, "description": f"Error loading: {e}", "inputs": []}
                )

    if not skills:
        return [
            TextContent(
                type="text",
                text="No skills found. Create .yaml files in skills/ directory.",
            )
        ]

    lines = ["## Available Skills\n"]
    for s in skills:
        inputs = ", ".join(s["inputs"]) if s["inputs"] else "none"
        lines.append(f"### {s['name']}")
        lines.append(f"{s['description']}")
        lines.append(f"**Inputs:** {inputs}\n")

    return [TextContent(type="text", text="\n".join(lines))]


def _validate_skill_inputs(skill: dict, input_data: dict) -> list[str]:
    """Validate required skill inputs and return list of missing inputs."""
    missing = []
    for inp in skill.get("inputs", []):
        if inp.get("required", False) and inp["name"] not in input_data:
            if "default" not in inp:
                missing.append(inp["name"])
    return missing


def _format_skill_plan(
    skill: dict, skill_name: str, input_data: dict
) -> list[TextContent]:
    """Format skill execution plan (preview mode)."""
    lines = [f"## 📋 Skill Plan: {skill.get('name', skill_name)}\n"]
    lines.append(f"*{skill.get('description', '')}*\n")
    lines.append("### Inputs")
    for k, v in input_data.items():
        lines.append(f"- `{k}`: {v}")
    lines.append("\n### Steps to Execute\n")

    step_num = 0
    for step in skill.get("steps", []):
        step_num += 1
        name = step.get("name", f"step_{step_num}")

        if "tool" in step:
            lines.append(f"{step_num}. **{name}** → `{step['tool']}`")
            if step.get("condition"):
                lines.append(f"   *Condition: {step['condition']}*")
        elif "compute" in step:
            lines.append(f"{step_num}. **{name}** → compute")
        elif "description" in step:
            lines.append(f"{step_num}. **{name}** → manual step")

    lines.append("\n*Run with `execute=True` to execute this plan*")
    return [TextContent(type="text", text="\n".join(lines))]


async def _skill_run_impl(  # pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,too-many-return-statements
    skill_name: str,
    inputs: str,
    execute: bool,
    debug: bool,
    server: "FastMCP",
    create_issue_fn=None,
    ask_question_fn=None,
    ctx: Optional["Context"] = None,
    source: str = "chat",
    source_details: str | None = None,
) -> list[TextContent]:
    """Implementation of skill_run tool.

    Args:
        skill_name: Name of the skill to run.
        inputs: JSON string of input parameters.
        execute: Whether to execute (True) or just preview (False).
        debug: Whether to show debug output.
        server: FastMCP server instance.
        create_issue_fn: Function to create Jira issues.
        ask_question_fn: Function to ask user questions.
        ctx: MCP Context for workspace/session info.
        source: Source of execution ("chat", "cron", "slack", "api").
        source_details: Additional source info (e.g., cron job name).
    """
    skill_file = skills_dir() / f"{skill_name}.yaml"
    if not skill_file.exists():
        available = (
            [f.stem for f in skills_dir().glob("*.yaml")]
            if skills_dir().exists()
            else []
        )
        return [
            TextContent(
                type="text",
                text=f"❌ Skill not found: {skill_name}\n\nAvailable: {', '.join(available) or 'none'}",  # pylint: disable=line-too-long
            )
        ]

    try:
        with open(skill_file, encoding="utf-8") as f:
            skill = yaml.safe_load(f)

        try:
            input_data = json.loads(inputs) if inputs else {}
        except json.JSONDecodeError:
            return [TextContent(type="text", text=f"❌ Invalid inputs JSON: {inputs}")]

        # Validate inputs
        missing = _validate_skill_inputs(skill, input_data)
        if missing:
            lines = [f"❌ Missing required inputs: {', '.join(missing)}\n"]
            lines.append("### Required Inputs\n")
            for inp in skill.get("inputs", []):
                req = "**required**" if inp.get("required") else "optional"
                default = f" (default: {inp['default']})" if "default" in inp else ""
                lines.append(
                    f"- `{inp['name']}` ({inp.get('type', 'string')}) - {req}{default}"
                )
                if inp.get("description"):
                    lines.append(f"  {inp['description']}")
            return [TextContent(type="text", text="\n".join(lines))]

        # Preview mode: just show the plan
        if not execute:
            return _format_skill_plan(skill, skill_name, input_data)

        # Get session context from workspace if available
        workspace_uri = "default"
        session_id = None
        session_name = None

        if ctx:
            try:
                from server.workspace_state import (  # pylint: disable=import-outside-toplevel
                    WorkspaceRegistry,
                )  # pylint: disable=import-outside-toplevel

                workspace = await WorkspaceRegistry.get_for_ctx(ctx)
                workspace_uri = workspace.workspace_uri
                session = workspace.get_active_session()
                if session:
                    session_id = session.session_id
                    session_name = session.name
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.debug("Could not get session context: %s", e)

        # Execute mode: run the skill. Imported here to avoid a cycle with skill_executor.
        from .skill_executor import (  # pylint: disable=import-outside-toplevel
            SkillExecutor,
        )

        executor = SkillExecutor(
            skill,
            input_data,
            debug=debug,
            server=server,
            create_issue_fn=create_issue_fn,
            ask_question_fn=ask_question_fn,
            enable_interactive_recovery=True,
            emit_events=True,  # Enable VS Code extension events
            workspace_uri=workspace_uri,
            ctx=ctx,
            session_id=session_id,
            session_name=session_name,
            source=source,
            source_details=source_details,
        )
        result = await executor.execute()

        return [TextContent(type="text", text=result)]

    except Exception as e:  # pylint: disable=broad-exception-caught
        import traceback  # pylint: disable=import-outside-toplevel

        if debug:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Error: {e}\n\n```\n{traceback.format_exc()}\n```",
                )
            ]
        return [TextContent(type="text", text=f"❌ Error loading skill: {e}")]


def register_skill_tools(
    server: "FastMCP", create_issue_fn=None, ask_question_fn=None
) -> int:
    """Register skill tools with the MCP server."""
    registry = ToolRegistry(server)

    @registry.tool()
    async def skill_list() -> list[TextContent]:
        """
        List all available skills (reusable workflows).

        Skills are multi-step workflows that combine MCP tools with logic.
        Use skill_run() to execute a skill.

        Returns:
            List of available skills with descriptions.
        """
        return _skill_list_impl()

    @registry.tool()
    async def skill_run(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        ctx: "Context",
        skill_name: str,
        inputs: str = "{}",
        args: str = "",
        execute: bool = True,
        debug: bool = False,
    ) -> list[TextContent]:
        """
        Execute a skill (multi-step workflow).

        Skills chain multiple MCP tools together with logic and conditions.

        Args:
            skill_name: Name of the skill (e.g., "start_work", "investigate_alert")
            inputs: JSON object with input parameters (preferred)
            args: Alias for inputs (for convenience)
            execute: If True (default), run the tools. If False, just show the plan.
            debug: If True, show detailed execution trace with timing.

        Returns:
            Execution results or plan preview.
        """
        # Support both 'inputs' and 'args' parameter names
        actual_inputs = args if args else inputs
        return await _skill_run_impl(
            skill_name,
            actual_inputs,
            execute,
            debug,
            server,
            create_issue_fn,
            ask_question_fn,
            ctx=ctx,
            source="chat",
        )

    return registry.count
