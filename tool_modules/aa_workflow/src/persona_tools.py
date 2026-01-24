"""Persona Tools - Load specialized AI personas with different toolsets.

Provides tools for managing agent personas:
- persona_list: List available personas
- persona_load: Load a persona with its tools and context
"""

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context
from mcp.types import TextContent

from server.tool_registry import ToolRegistry

# Support both package import and direct loading
try:
    from .constants import PERSONAS_DIR
except ImportError:
    TOOL_MODULES_DIR = Path(__file__).parent.parent.parent
    PROJECT_DIR = TOOL_MODULES_DIR.parent
    PERSONAS_DIR = PROJECT_DIR / "personas"

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def _list_personas_impl() -> list[TextContent]:
    """Implementation of persona_list tool."""
    personas = []
    if PERSONAS_DIR.exists():
        for f in PERSONAS_DIR.glob("*.md"):
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
                personas.append({"name": f.stem, "title": name, "role": role})
            except Exception as e:
                personas.append({"name": f.stem, "title": f.stem, "role": f"Error: {e}"})

    if not personas:
        return [
            TextContent(
                type="text",
                text="No personas found. Create .md files in personas/ directory.",
            )
        ]

    lines = ["## Available Personas\n"]
    for p in personas:
        lines.append(f"### {p['title']} (`{p['name']}`)")
        lines.append(f"{p['role']}\n")

    lines.append("\nUse `persona_load(persona_name)` to load a persona's full context.")

    return [TextContent(type="text", text="\n".join(lines))]


async def _load_persona_impl(persona_name: str, ctx: Context) -> list[TextContent]:
    """Implementation of persona_load tool."""
    # Try dynamic loading first
    try:
        # Add project root to path if needed
        project_path = str(Path(__file__).parent.parent.parent.parent)
        if project_path not in sys.path:
            sys.path.insert(0, project_path)

        from server.persona_loader import get_loader

        loader = get_loader()
        if loader and ctx:
            # Dynamic mode - switch tools
            result = await loader.switch_persona(persona_name, ctx)

            if result["success"]:
                lines = [
                    f"## 🔄 Persona Loaded: {persona_name}",
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
    persona_file = PERSONAS_DIR / f"{persona_name}.md"
    if not persona_file.exists():
        return [
            TextContent(
                type="text",
                text=f"❌ Persona not found: {persona_name}\n\n" "Use persona_list() to see available personas.",
            )
        ]

    try:
        content = persona_file.read_text()
        return [
            TextContent(
                type="text",
                text=f"## Loading Persona: {persona_name}\n\n"
                "*(Static mode - tools unchanged)*\n\n---\n\n"
                f"{content}",
            )
        ]
    except Exception as e:
        return [TextContent(type="text", text=f"❌ Error loading persona: {e}")]


def register_persona_tools(server: "FastMCP") -> int:
    """Register persona tools with the MCP server."""
    registry = ToolRegistry(server)

    @registry.tool()
    async def persona_list() -> list[TextContent]:
        """
        List all available personas.

        Personas are specialized AI configurations with specific expertise, tools, and workflows.
        Use persona_load() to load a persona's full context.

        Returns:
            List of available personas with their focus areas.
        """
        return _list_personas_impl()

    @registry.tool()
    async def persona_load(ctx: Context, persona_name: str) -> list[TextContent]:
        """
        Load a persona with its full toolset and context.

        This dynamically switches to the specified persona by:
        1. Unloading current tools (except core tools)
        2. Loading the persona's tool modules
        3. Notifying Cursor of the tool change
        4. Returning the persona's context for adoption

        Args:
            persona_name: Persona to load (e.g., "devops", "developer", "incident", "release")

        Returns:
            Persona context with confirmation of tools loaded.
        """
        return await _load_persona_impl(persona_name, ctx)

    return registry.count
