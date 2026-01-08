"""Dynamic Persona Loader - Switch tools at runtime.

Enables loading different persona toolsets mid-session by:
1. Removing current tools (except core workflow tools)
2. Loading new persona's tool modules
3. Notifying the client that tools changed

Usage:
    from .persona_loader import PersonaLoader

    loader = PersonaLoader(server)
    await loader.switch_persona("devops", ctx)
"""

import importlib.util
import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast

import yaml

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context, FastMCP

logger = logging.getLogger(__name__)

# Paths - server/ is at project root level
PROJECT_DIR = Path(__file__).parent.parent  # ai-workflow root
TOOL_MODULES_DIR = PROJECT_DIR / "tool_modules"
PERSONAS_DIR = PROJECT_DIR / "personas"

# Tool counts per module
# Removed duplicates, low-value, and interactive-only tools
TOOL_MODULES = {
    "git": 15,
    "jira": 23,  # Removed: jira_open_browser (interactive)
    "gitlab": 29,  # Removed: 2 interactive + 4 duplicates/low-value
    "k8s": 26,
    "prometheus": 13,
    "alertmanager": 6,
    "kibana": 9,
    "konflux": 35,  # Removed: 5 duplicate/low-value tkn tools
    "bonfire": 20,  # Removed: bonfire_version (low value)
    "quay": 7,  # Removed: quay_check_aa_image (duplicate)
    "appinterface": 6,
    "workflow": 16,  # Core only (memory, persona, session, skill, infra, meta)
    "lint": 7,  # Developer-specific linting/testing tools
    "dev-workflow": 9,  # Developer-specific workflow tools
    "slack": 8,  # Removed: 7 daemon/internal tools
    "google-calendar": 6,
}

# Core tools that should never be removed
CORE_TOOLS = {
    "persona_load",
    "persona_list",
    "session_start",
    "debug_tool",
}


class PersonaLoader:
    """Manages dynamic persona/tool loading."""

    def __init__(self, server: "FastMCP"):
        self.server = server
        self.current_persona: str = ""
        self.loaded_modules: set[str] = set()
        self._tool_to_module: dict[str, str] = {}  # tool_name -> module_name

    def load_persona_config(self, persona_name: str) -> dict | None:
        """Load persona configuration from YAML file."""
        persona_file = PERSONAS_DIR / f"{persona_name}.yaml"
        if not persona_file.exists():
            return None

        try:
            with open(persona_file) as f:
                return cast(dict, yaml.safe_load(f))
        except Exception as e:
            logger.error(f"Failed to load persona config {persona_name}: {e}")
            return None

    async def _load_tool_module(self, module_name: str) -> list[str]:
        """Load a tool module and return list of tool names added."""
        module_dir = TOOL_MODULES_DIR / f"aa-{module_name}"
        tools_file = module_dir / "src" / "tools.py"

        if not tools_file.exists():
            logger.warning(f"Tools file not found: {tools_file}")
            return []

        try:
            spec = importlib.util.spec_from_file_location(f"aa_{module_name}_tools_dynamic", tools_file)
            if spec is None or spec.loader is None:
                return []

            module = importlib.util.module_from_spec(spec)

            # Get tools before loading
            tools_before = set(await self.server.list_tools())

            # Load the module (registers tools with server)
            spec.loader.exec_module(module)

            if hasattr(module, "register_tools"):
                module.register_tools(self.server)

            # Get tools after loading
            tools_after = set(await self.server.list_tools())
            new_tools = tools_after - tools_before

            # Track which tools came from this module and extract names
            new_tool_names = []
            for tool in new_tools:
                tool_name = tool.name if hasattr(tool, "name") else str(tool)
                self._tool_to_module[tool_name] = module_name
                new_tool_names.append(tool_name)

            self.loaded_modules.add(module_name)
            logger.info(f"Loaded {module_name}: {len(new_tool_names)} tools")

            return new_tool_names

        except Exception as e:
            logger.error(f"Error loading {module_name}: {e}")
            return []

    def _unload_module_tools(self, module_name: str) -> int:
        """Remove all tools from a specific module."""
        tools_to_remove = [
            name for name, mod in self._tool_to_module.items() if mod == module_name and name not in CORE_TOOLS
        ]

        for tool_name in tools_to_remove:
            try:
                self.server.remove_tool(tool_name)
                del self._tool_to_module[tool_name]
            except Exception as e:
                logger.warning(f"Failed to remove tool {tool_name}: {e}")

        self.loaded_modules.discard(module_name)
        return len(tools_to_remove)

    async def _clear_non_core_tools(self) -> int:
        """Remove all tools except core ones."""
        all_tools = list(await self.server.list_tools())
        removed = 0

        for tool in all_tools:
            tool_name = tool.name if hasattr(tool, "name") else str(tool)
            if tool_name not in CORE_TOOLS:
                try:
                    self.server.remove_tool(tool_name)
                    removed += 1
                except Exception as e:
                    logger.warning(f"Failed to remove {tool_name}: {e}")

        self._tool_to_module.clear()
        self.loaded_modules.clear()

        return removed

    async def switch_persona(
        self,
        persona_name: str,
        ctx: "Context",
    ) -> dict:
        """
        Switch to a different persona, loading its tools.

        Args:
            persona_name: Persona to switch to (e.g., "devops", "developer")
            ctx: MCP Context for sending notifications

        Returns:
            dict with status, tools loaded, and persona info
        """
        # Load persona config
        config = self.load_persona_config(persona_name)
        if not config:
            return {
                "success": False,
                "error": f"Persona not found: {persona_name}",
                "available": [f.stem for f in PERSONAS_DIR.glob("*.yaml")],
            }

        tool_modules = config.get("tools", [])

        # Clear existing tools (except core)
        removed = await self._clear_non_core_tools()
        logger.info(f"Removed {removed} tools from previous persona")

        # Load new persona's tools
        loaded_tools = []
        for module_name in tool_modules:
            if module_name not in TOOL_MODULES:
                logger.warning(f"Unknown module: {module_name}")
                continue

            new_tools = await self._load_tool_module(module_name)
            loaded_tools.extend(new_tools)

        self.current_persona = persona_name

        # Notify client that tools changed
        try:
            if ctx.session:
                await ctx.session.send_tool_list_changed()
                logger.info("Sent tool_list_changed notification")
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")

        # Load persona description
        persona_file = PERSONAS_DIR / f"{persona_name}.md"
        persona = ""
        if persona_file.exists():
            persona = persona_file.read_text()

        return {
            "success": True,
            "persona": persona_name,
            "description": config.get("description", ""),
            "modules_loaded": list(self.loaded_modules),
            "tool_count": len(loaded_tools),
            "persona_context": persona,
        }

    def get_status(self) -> dict:
        """Get current persona loader status."""
        return {
            "current_persona": self.current_persona,
            "loaded_modules": list(self.loaded_modules),
            "tool_count": len(self._tool_to_module),
            "tools": list(self._tool_to_module.keys()),
        }


# Global instance (set by server on startup)
_loader: PersonaLoader | None = None


def get_loader() -> PersonaLoader | None:
    """Get the global persona loader instance."""
    return _loader


def init_loader(server: "FastMCP") -> PersonaLoader:
    """Initialize the global persona loader."""
    global _loader
    _loader = PersonaLoader(server)
    return _loader
