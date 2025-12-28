"""Dynamic Agent Loader - Switch tools at runtime.

Enables loading different agent toolsets mid-session by:
1. Removing current tools (except core workflow tools)
2. Loading new agent's tool modules
3. Notifying the client that tools changed

Usage:
    from .agent_loader import AgentLoader

    loader = AgentLoader(server)
    await loader.switch_agent("devops", ctx)
"""

import importlib.util
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context, FastMCP

logger = logging.getLogger(__name__)

# Paths
SERVERS_DIR = Path(__file__).parent.parent.parent  # mcp-servers/
PROJECT_DIR = SERVERS_DIR.parent  # ai-workflow root
AGENTS_DIR = PROJECT_DIR / "agents"

# Tool counts per module
TOOL_MODULES = {
    "git": 15,
    "jira": 24,
    "gitlab": 35,
    "k8s": 26,
    "prometheus": 13,
    "alertmanager": 6,
    "kibana": 9,
    "konflux": 40,
    "bonfire": 21,
    "quay": 8,
    "appinterface": 6,
    "workflow": 26,
    "slack": 15,
    "google-calendar": 6,
}

# Core tools that should never be removed
CORE_TOOLS = {
    "agent_load",
    "agent_list",
    "session_start",
    "debug_tool",
}


class AgentLoader:
    """Manages dynamic agent/tool loading."""

    def __init__(self, server: "FastMCP"):
        self.server = server
        self.current_agent: str = ""
        self.loaded_modules: set[str] = set()
        self._tool_to_module: dict[str, str] = {}  # tool_name -> module_name

    def load_agent_config(self, agent_name: str) -> dict | None:
        """Load agent configuration from YAML file."""
        agent_file = AGENTS_DIR / f"{agent_name}.yaml"
        if not agent_file.exists():
            return None

        try:
            with open(agent_file) as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load agent config {agent_name}: {e}")
            return None

    def _load_tool_module(self, module_name: str) -> list[str]:
        """Load a tool module and return list of tool names added."""
        module_dir = SERVERS_DIR / f"aa-{module_name}"
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
            tools_before = set(self.server.list_tools())

            # Load the module (registers tools with server)
            spec.loader.exec_module(module)

            if hasattr(module, "register_tools"):
                module.register_tools(self.server)

            # Get tools after loading
            tools_after = set(self.server.list_tools())
            new_tools = tools_after - tools_before

            # Track which tools came from this module
            for tool_name in new_tools:
                self._tool_to_module[tool_name] = module_name

            self.loaded_modules.add(module_name)
            logger.info(f"Loaded {module_name}: {len(new_tools)} tools")

            return list(new_tools)

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

    def _clear_non_core_tools(self) -> int:
        """Remove all tools except core ones."""
        all_tools = list(self.server.list_tools())
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

    async def switch_agent(
        self,
        agent_name: str,
        ctx: "Context",
    ) -> dict:
        """
        Switch to a different agent, loading its tools.

        Args:
            agent_name: Agent to switch to (e.g., "devops", "developer")
            ctx: MCP Context for sending notifications

        Returns:
            dict with status, tools loaded, and agent info
        """
        # Load agent config
        config = self.load_agent_config(agent_name)
        if not config:
            return {
                "success": False,
                "error": f"Agent not found: {agent_name}",
                "available": [f.stem for f in AGENTS_DIR.glob("*.yaml")],
            }

        tool_modules = config.get("tools", [])

        # Clear existing tools (except core)
        removed = self._clear_non_core_tools()
        logger.info(f"Removed {removed} tools from previous agent")

        # Load new agent's tools
        loaded_tools = []
        for module_name in tool_modules:
            if module_name not in TOOL_MODULES:
                logger.warning(f"Unknown module: {module_name}")
                continue

            new_tools = self._load_tool_module(module_name)
            loaded_tools.extend(new_tools)

        self.current_agent = agent_name

        # Notify client that tools changed
        try:
            if ctx.session:
                await ctx.session.send_tool_list_changed()
                logger.info("Sent tool_list_changed notification")
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")

        # Load persona
        persona_file = AGENTS_DIR / f"{agent_name}.md"
        persona = ""
        if persona_file.exists():
            persona = persona_file.read_text()

        return {
            "success": True,
            "agent": agent_name,
            "description": config.get("description", ""),
            "modules_loaded": list(self.loaded_modules),
            "tool_count": len(loaded_tools),
            "persona": persona,
        }

    def get_status(self) -> dict:
        """Get current agent loader status."""
        return {
            "current_agent": self.current_agent,
            "loaded_modules": list(self.loaded_modules),
            "tool_count": len(self._tool_to_module),
            "tools": list(self._tool_to_module.keys()),
        }


# Global instance (set by server on startup)
_loader: AgentLoader | None = None


def get_loader() -> AgentLoader | None:
    """Get the global agent loader instance."""
    return _loader


def init_loader(server: "FastMCP") -> AgentLoader:
    """Initialize the global agent loader."""
    global _loader
    _loader = AgentLoader(server)
    return _loader
