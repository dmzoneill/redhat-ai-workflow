"""Meta Tools - Dynamic tool discovery and execution.

Provides tools for:
- tool_list: List all available tools across modules
- tool_exec: Execute any tool from any module dynamically
- context_filter: Get context-aware tool recommendations for a message
"""

import importlib.util
import json
import logging
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from server.tool_discovery import build_full_manifest, get_module_for_tool
from server.tool_registry import ToolRegistry

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT

# Import tool filtering for context-aware recommendations
try:
    from tool_modules.aa_ollama.src.skill_discovery import detect_skill
    from tool_modules.aa_ollama.src.tool_filter import filter_tools_detailed

    TOOL_FILTER_AVAILABLE = True
except ImportError:
    TOOL_FILTER_AVAILABLE = False
    filter_tools_detailed = None
    detect_skill = None

TOOL_MODULES_DIR = PROJECT_ROOT / "tool_modules"

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# Known issues checking - loads patterns from memory
def _check_known_issues_sync(tool_name: str = "", error_text: str = "") -> list:
    """Check memory for known issues matching this tool/error."""
    import yaml

    matches = []
    error_lower = error_text.lower() if error_text else ""
    tool_lower = tool_name.lower() if tool_name else ""

    try:
        memory_dir = PROJECT_ROOT / "memory" / "learned"

        patterns_file = memory_dir / "patterns.yaml"
        if patterns_file.exists():
            with open(patterns_file) as f:
                patterns = yaml.safe_load(f) or {}

            # Check all pattern categories
            for category in [
                "error_patterns",
                "auth_patterns",
                "bonfire_patterns",
                "pipeline_patterns",
            ]:
                for pattern in patterns.get(category, []):
                    pattern_text = pattern.get("pattern", "").lower()
                    if pattern_text and (pattern_text in error_lower or pattern_text in tool_lower):
                        matches.append(
                            {
                                "source": category,
                                "pattern": pattern.get("pattern"),
                                "meaning": pattern.get("meaning", ""),
                                "fix": pattern.get("fix", ""),
                                "commands": pattern.get("commands", []),
                            }
                        )

        # Check tool_fixes.yaml
        fixes_file = memory_dir / "tool_fixes.yaml"
        if fixes_file.exists():
            with open(fixes_file) as f:
                fixes = yaml.safe_load(f) or {}

            for fix in fixes.get("tool_fixes", []):
                if tool_name and fix.get("tool_name", "").lower() == tool_lower:
                    matches.append(
                        {
                            "source": "tool_fixes",
                            "tool_name": fix.get("tool_name"),
                            "pattern": fix.get("error_pattern", ""),
                            "fix": fix.get("fix_applied", ""),
                        }
                    )
                elif error_text:
                    fix_pattern = fix.get("error_pattern", "").lower()
                    if fix_pattern and fix_pattern in error_lower:
                        matches.append(
                            {
                                "source": "tool_fixes",
                                "tool_name": fix.get("tool_name"),
                                "pattern": fix.get("error_pattern", ""),
                                "fix": fix.get("fix_applied", ""),
                            }
                        )

    except Exception:
        pass

    return matches


def _format_known_issues(matches: list) -> str:
    """Format known issues for display."""
    if not matches:
        return ""

    lines = ["\n## 💡 Known Issues Found!\n"]
    for match in matches[:3]:  # Limit to 3
        lines.append(f"**Pattern:** `{match.get('pattern', '?')}`")
        if match.get("meaning"):
            lines.append(f"*{match.get('meaning')}*")
        if match.get("fix"):
            lines.append(f"**Fix:** {match.get('fix')}")
        if match.get("commands"):
            lines.append("**Try:**")
            for cmd in match.get("commands", [])[:2]:
                lines.append(f"- `{cmd}`")
        lines.append("")

    return "\n".join(lines)


# ============== Dynamic Tool Discovery ==============
# Tools are discovered by scanning module files at runtime.
# No more hardcoded lists to maintain!


def _get_tool_registry() -> dict[str, list[str]]:
    """Get the tool registry by discovering tools from modules.

    This replaces the old hardcoded TOOL_REGISTRY dict.
    Tools are discovered by parsing @registry.tool() decorators in module files.
    """
    return build_full_manifest()


def _get_module_for_tool(tool_name: str) -> str | None:
    """Get the module a tool belongs to.

    This replaces the old MODULE_PREFIXES dict.
    Uses the discovery system with prefix-based fallback.
    """
    return get_module_for_tool(tool_name)


async def _tool_list_impl(module: str) -> list[TextContent]:
    """Implementation of tool_list tool."""
    # Get tools dynamically from discovery system
    tool_registry = _get_tool_registry()

    if module:
        if module not in tool_registry:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Unknown module: {module}\n\n" f"Available: {', '.join(tool_registry.keys())}",
                )
            ]

        tools = tool_registry[module]
        lines = [f"## Module: {module}\n", f"**{len(tools)} tools available:**\n"]
        for t in tools:
            lines.append(f"- `{t}`")
        if tools:
            lines.append(f"\n*Use `tool_exec('{tools[0]}', '{{}}')` to run*")
        return [TextContent(type="text", text="\n".join(lines))]

    # List all modules
    lines = ["## Available Tool Modules\n"]
    total = 0
    for mod, tools in tool_registry.items():
        lines.append(f"- **{mod}**: {len(tools)} tools")
        total += len(tools)
    lines.append(f"\n**Total: {total} tools**")
    lines.append("\nUse `tool_list(module='git')` to see tools in a module")
    lines.append("\n**💡 TIP:** After loading an agent, call tools DIRECTLY by name:")
    lines.append("   `bonfire_namespace_list(mine_only=True)`  ← Cursor shows actual name")
    lines.append("   NOT: `tool_exec('bonfire_namespace_list', ...)`  ← Shows as 'tool_exec'")
    lines.append("\nUse `tool_exec()` only for tools from non-loaded agents.")

    return [TextContent(type="text", text="\n".join(lines))]


def _extract_tool_result(result) -> list[TextContent]:
    """Extract text content from tool execution result.

    Args:
        result: Tool execution result (various types)

    Returns:
        TextContent list
    """
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, list) and len(result) > 0:
        if hasattr(result[0], "text"):
            return [TextContent(type="text", text=result[0].text)]
        return [TextContent(type="text", text=str(result[0]))]

    return [TextContent(type="text", text=str(result))]


async def _handle_tool_exec_error(tool_name: str, error_msg: str, args: str, create_issue_fn) -> list[TextContent]:
    """Handle tool execution error with known issues check and GitHub issue creation.

    Args:
        tool_name: Name of the tool that failed
        error_msg: Error message
        args: Tool arguments (JSON string)
        create_issue_fn: Function to create GitHub issues

    Returns:
        Error message with hints and issue link
    """
    lines = [f"❌ Error executing {tool_name}: {error_msg}"]

    # Check for known issues from memory
    matches = _check_known_issues_sync(tool_name=tool_name, error_text=error_msg)
    known_text = _format_known_issues(matches)
    if known_text:
        lines.append(known_text)
    else:
        lines.append("")
        lines.append(f"💡 **Auto-fix:** `debug_tool('{tool_name}')`")
        lines.append(f"📚 **After fixing:** `learn_tool_fix('{tool_name}', '<pattern>', '<cause>', '<fix>')`")

    # Auto-create GitHub issue for all tool failures
    if create_issue_fn:
        try:
            issue_result = await create_issue_fn(tool=tool_name, error=error_msg, context=f"Args: {args}")

            if issue_result["success"]:
                lines.append("")
                lines.append(f"🐛 **Issue created:** {issue_result['issue_url']}")
            elif issue_result["issue_url"]:
                lines.append("")
                lines.append("💡 **Report this error:**")
                lines.append(f"📝 [Create GitHub Issue]({issue_result['issue_url']})")
        except Exception as issue_err:
            logger.debug(f"Failed to create GitHub issue: {issue_err}")

    return [TextContent(type="text", text="\n".join(lines))]


async def _tool_exec_impl(tool_name: str, args: str, create_issue_fn) -> list[TextContent]:
    """Implementation of tool_exec tool."""
    # Determine which module the tool belongs to using discovery system
    module = _get_module_for_tool(tool_name)

    if not module:
        return [
            TextContent(
                type="text",
                text=f"❌ Unknown tool: {tool_name}\n\nUse tool_list() to see available tools.",
            )
        ]

    # Parse arguments
    try:
        tool_args = json.loads(args) if args else {}
    except json.JSONDecodeError as e:
        return [TextContent(type="text", text=f"❌ Invalid JSON args: {e}")]

    # Load and execute the tool module (try tools_basic.py first, then tools.py)
    tools_file = TOOL_MODULES_DIR / f"aa_{module}" / "src" / "tools_basic.py"
    if not tools_file.exists():
        tools_file = TOOL_MODULES_DIR / f"aa_{module}" / "src" / "tools.py"

    if not tools_file.exists():
        return [TextContent(type="text", text=f"❌ Module not found: {module}")]

    try:
        # Create a temporary server to register tools
        temp_server = FastMCP(f"temp-{module}")

        # Load the module
        spec = importlib.util.spec_from_file_location(f"aa_{module}_tools_exec", tools_file)
        if spec is None or spec.loader is None:
            return [TextContent(type="text", text=f"❌ Could not load module: {module}")]

        loaded_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded_module)

        # Register tools with temp server
        if hasattr(loaded_module, "register_tools"):
            loaded_module.register_tools(temp_server)

        # Execute the tool
        result = await temp_server.call_tool(tool_name, tool_args)

        # Extract text from result
        return _extract_tool_result(result)

    except Exception as e:
        return await _handle_tool_exec_error(tool_name, str(e), args, create_issue_fn)


def register_meta_tools(server: "FastMCP", create_issue_fn=None) -> int:
    """Register meta tools with the MCP server."""
    registry = ToolRegistry(server)

    @registry.tool()
    async def tool_list(module: str = "") -> list[TextContent]:
        """
        List all available tools across all modules.

        Use this to discover tools that aren't directly loaded.
        Then use tool_exec() to run them.

        Args:
            module: Filter by module (git, jira, gitlab, k8s, etc.)
                   Leave empty to list all modules.

        Returns:
            List of available tools and their descriptions.
        """
        return await _tool_list_impl(module)

    @registry.tool()
    async def tool_exec(tool_name: str, args: str = "{}") -> list[TextContent]:
        """
        Execute ANY tool from ANY module dynamically.

        This is a meta-tool that can run tools not directly loaded.
        First use tool_list() to see available tools.

        Args:
            tool_name: Full tool name (e.g., "gitlab_mr_list", "kibana_search_logs")
            args: JSON string of arguments (e.g., '{"project": "backend", "state": "opened"}')

        Returns:
            Tool execution result.

        Example:
            tool_exec("gitlab_mr_list", '{"project": "your-backend"}')
        """
        return await _tool_exec_impl(tool_name, args, create_issue_fn)

    @registry.tool()
    async def context_filter(
        message: str,
        persona: str = "developer",
    ) -> list[TextContent]:
        """
        Get context-aware tool recommendations for a message.

        Uses the 4-layer HybridToolFilter to analyze your message and return:
        - Recommended tools for this task
        - Detected skill (if any)
        - Memory context (active issues, repo, branch)
        - Learned patterns (known fixes)
        - Semantic knowledge (relevant code)

        Call this FIRST when starting a complex task to understand what tools
        and context are available.

        Args:
            message: The task or question you want to accomplish
            persona: Current persona (developer, devops, incident, release)

        Returns:
            Context-aware recommendations including tools, skill, and enriched context.

        Example:
            context_filter("deploy MR 1459 to ephemeral")
            # Returns: detected skill, recommended tools, memory state, etc.
        """
        if not TOOL_FILTER_AVAILABLE:
            return [
                TextContent(
                    type="text",
                    text="⚠️ Tool filtering not available. Install: pip install sentence-transformers lancedb",
                )
            ]

        try:
            # Detect skill first
            detected_skill = detect_skill(message) if detect_skill else None

            # Run the 4-layer filter
            result = filter_tools_detailed(
                message=message,
                persona=persona,
                detected_skill=detected_skill,
            )

            # Format the response
            ctx = result.get("context", {})
            lines = []

            # Header
            lines.append(f'## 🎯 Context Analysis for: "{message[:50]}..."')
            lines.append("")

            # Persona
            persona_icon = {"developer": "👨‍💻", "devops": "🔧", "incident": "🚨", "release": "📦"}.get(
                result["persona"], "👤"
            )
            if result.get("persona_auto_detected"):
                lines.append(
                    f"**Persona**: {persona_icon} {result['persona']} "
                    f"(auto-detected via {result.get('persona_detection_reason', 'keyword')})"
                )
            else:
                lines.append(f"**Persona**: {persona_icon} {result['persona']}")

            # Skill
            skill = ctx.get("skill", {})
            if skill.get("name"):
                lines.append(f"**Detected Skill**: 🎯 {skill['name']}")
                if skill.get("description"):
                    lines.append(f"  - {skill['description'][:100]}")
                if skill.get("tools"):
                    lines.append(f"  - Tools: {', '.join(skill['tools'][:10])}")
                if skill.get("memory_ops"):
                    mem_ops = skill["memory_ops"]
                    if mem_ops.get("reads"):
                        lines.append(f"  - Memory reads: {len(mem_ops['reads'])}")
                    if mem_ops.get("writes"):
                        lines.append(f"  - Memory writes: {len(mem_ops['writes'])}")
            else:
                lines.append("**Detected Skill**: None (will use general tools)")

            lines.append("")

            # Memory state
            mem = ctx.get("memory_state", {})
            lines.append("### 🧠 Memory State")
            if mem.get("current_repo"):
                lines.append(f"- Active repo: `{mem['current_repo']}`")
            if mem.get("current_branch"):
                lines.append(f"- Branch: `{mem['current_branch']}`")
            active_issues = mem.get("active_issues", [])
            if active_issues:
                issue_keys = [i.get("key", str(i)) for i in active_issues[:3]]
                lines.append(f"- Active issues: {', '.join(issue_keys)}")
            if not any([mem.get("current_repo"), mem.get("current_branch"), active_issues]):
                lines.append("- No active work context")

            lines.append("")

            # Learned patterns
            patterns = ctx.get("learned_patterns", [])
            if patterns:
                lines.append("### 💡 Relevant Learned Patterns")
                for p in patterns[:3]:
                    lines.append(f"- **{p.get('pattern', 'Unknown')[:40]}**")
                    if p.get("fix"):
                        lines.append(f"  Fix: {p['fix'][:60]}")

            # Semantic knowledge
            semantic = ctx.get("semantic_knowledge", [])
            if semantic:
                lines.append("")
                lines.append("### 🔍 Relevant Code (Semantic Search)")
                for s in semantic[:3]:
                    lines.append(f"- `{s.get('file', 'unknown')}`")
                    if s.get("content"):
                        lines.append(f"  ```\n  {s['content'][:100]}...\n  ```")

            lines.append("")

            # Recommended tools
            tools = result.get("tools", [])
            lines.append(f"### 📋 Recommended Tools ({len(tools)} tools)")
            lines.append(f"Reduction: {result.get('reduction_pct', 0):.1f}% | Latency: {result.get('latency_ms', 0)}ms")
            lines.append("")

            # Group tools by category
            tool_groups = {}
            for t in tools:
                prefix = t.split("_")[0] if "_" in t else "other"
                if prefix not in tool_groups:
                    tool_groups[prefix] = []
                tool_groups[prefix].append(t)

            for group, group_tools in sorted(tool_groups.items()):
                lines.append(
                    f"**{group}**: {', '.join(group_tools[:5])}"
                    + (f" +{len(group_tools)-5} more" if len(group_tools) > 5 else "")
                )

            return [TextContent(type="text", text="\n".join(lines))]

        except Exception as e:
            logger.error(f"Context filter error: {e}")
            return [TextContent(type="text", text=f"❌ Error running context filter: {e}")]

    return registry.count
