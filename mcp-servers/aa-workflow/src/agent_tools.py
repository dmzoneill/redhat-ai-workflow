"""Agent Tools - Load specialized AI personas with different toolsets.

Provides tools for managing agent personas:
- agent_list: List available agents
- agent_load: Load an agent with its tools and persona
"""

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.types import TextContent

from .constants import AGENTS_DIR

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_agent_tools(server: "FastMCP") -> int:
    """Register agent tools with the MCP server."""
    tool_count = 0

    @server.tool()
    async def agent_list() -> list[TextContent]:
        """
        List all available agent personas.

        Agents are specialized AI personas with specific expertise, tools, and workflows.
        Use agent_load() to get an agent's full context.

        Returns:
            List of available agents with their focus areas.
        """
        agents = []
        if AGENTS_DIR.exists():
            for f in AGENTS_DIR.glob("*.md"):
                if f.name == "README.md":
                    continue
                try:
                    content = f.read_text()
                    # Extract first heading and first paragraph
                    lines = content.split("\n")
                    name = f.stem
                    role = ""
                    for line in lines:
                        if line.startswith("# "):
                            name = line[2:].strip()
                        elif line.startswith("## Your Role"):
                            idx = lines.index(line)
                            if idx + 1 < len(lines):
                                role = lines[idx + 1].strip("- ")
                            break
                    agents.append({"name": f.stem, "title": name, "role": role})
                except Exception as e:
                    agents.append({"name": f.stem, "title": f.stem, "role": f"Error: {e}"})

        if not agents:
            return [TextContent(type="text", text="No agents found. Create .md files in agents/ directory.")]

        lines = ["## Available Agents\n"]
        for a in agents:
            lines.append(f"### {a['title']} (`{a['name']}`)")
            lines.append(f"{a['role']}\n")

        lines.append("\nUse `agent_load(agent_name)` to load an agent's full context.")

        return [TextContent(type="text", text="\n".join(lines))]

    tool_count += 1

    @server.tool()
    async def agent_load(agent_name: str, ctx=None) -> list[TextContent]:
        """
        Load an agent with its full toolset and persona.

        This dynamically switches to the specified agent by:
        1. Unloading current tools (except core tools)
        2. Loading the agent's tool modules
        3. Notifying Cursor of the tool change
        4. Returning the agent's persona for adoption

        Args:
            agent_name: Agent to load (e.g., "devops", "developer", "incident", "release")

        Returns:
            Agent context with confirmation of tools loaded.
        """
        # Try dynamic loading first
        try:
            # Add aa-common to path if needed
            common_path = str(Path(__file__).parent.parent.parent / "aa-common")
            if common_path not in sys.path:
                sys.path.insert(0, common_path)

            from src.agent_loader import get_loader

            loader = get_loader()
            if loader and ctx:
                # Dynamic mode - switch tools
                result = await loader.switch_agent(agent_name, ctx)

                if result["success"]:
                    lines = [
                        f"## 🔄 Agent Switched: {agent_name}",
                        "",
                        f"**Description:** {result['description']}",
                        f"**Modules:** {', '.join(result['modules_loaded'])}",
                        f"**Tools loaded:** {result['tool_count']}",
                        "",
                        "---",
                        "",
                        "⚠️ **IMPORTANT:** Call tools DIRECTLY by name now!",
                        "   ✅ `bonfire_namespace_list(mine_only=True)`",
                        "   ❌ `tool_exec('bonfire_namespace_list', ...)`",
                        "",
                        "This way Cursor shows the actual tool name instead of 'tool_exec'.",
                        "",
                        "---",
                        "",
                        result["persona"],
                    ]
                    return [TextContent(type="text", text="\n".join(lines))]
                else:
                    return [
                        TextContent(
                            type="text",
                            text=f"❌ {result['error']}\n\n" f"Available: {', '.join(result.get('available', []))}",
                        )
                    ]
        except Exception as e:
            logger.warning(f"Dynamic loading not available: {e}")

        # Fallback: just load persona (static mode)
        agent_file = AGENTS_DIR / f"{agent_name}.md"
        if not agent_file.exists():
            return [
                TextContent(
                    type="text",
                    text=f"❌ Agent not found: {agent_name}\n\n" "Use agent_list() to see available agents.",
                )
            ]

        try:
            content = agent_file.read_text()
            return [
                TextContent(
                    type="text",
                    text=f"## Loading Agent: {agent_name}\n\n"
                    "*(Static mode - tools unchanged)*\n\n---\n\n"
                    f"{content}",
                )
            ]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Error loading agent: {e}")]

    tool_count += 1

    return tool_count
