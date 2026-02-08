"""Dynamic Persona Loader - Switch tools at runtime.

Enables loading different persona toolsets mid-session by:
1. Removing current tools (except core workflow tools)
2. Loading new persona's tool modules
3. Notifying the client that tools changed

This module is workspace-aware: persona state is stored per-workspace
in the WorkspaceRegistry, allowing different Cursor chats to have
different active personas.

Usage:
    from .persona_loader import PersonaLoader

    loader = PersonaLoader(server)
    await loader.switch_persona("devops", ctx)  # ctx provides workspace context
"""

import asyncio
import importlib.util
import logging
from typing import TYPE_CHECKING, cast

import yaml

if TYPE_CHECKING:
    from fastmcp import Context, FastMCP

logger = logging.getLogger(__name__)

# Import protocol for validation
from .protocols import is_tool_module, validate_tool_module  # noqa: E402

# Import shared path resolution utilities
from .tool_paths import (  # noqa: E402
    PROJECT_DIR,
    TOOL_MODULES_DIR,
    TOOLS_BASIC_FILE,
    TOOLS_CORE_FILE,
    TOOLS_EXTRA_FILE,
    TOOLS_FILE,
    TOOLS_STYLE_FILE,
    get_tools_file_path,
)

PERSONAS_DIR = PROJECT_DIR / "personas"


def discover_tool_modules() -> set[str]:
    """
    Dynamically discover available tool modules from the tool_modules directory.

    Scans for:
    - Base modules: aa_*/src/tools.py or aa_*/src/tools_basic.py or aa_*/src/tools_core.py
    - Core variants: aa_*/src/tools_core.py -> module_core
    - Basic variants: aa_*/src/tools_basic.py -> module_basic
    - Extra variants: aa_*/src/tools_extra.py -> module_extra
    - Style variants: aa_*/src/tools_style.py -> module_style

    Returns:
        Set of available module names (e.g., {'git', 'git_core', 'git_basic', 'git_extra', ...})
    """
    modules = set()

    if not TOOL_MODULES_DIR.exists():
        logger.warning(f"Tool modules directory not found: {TOOL_MODULES_DIR}")
        return modules

    for module_dir in TOOL_MODULES_DIR.iterdir():
        if not module_dir.is_dir() or not module_dir.name.startswith("aa_"):
            continue

        # Extract base name (e.g., "aa_git" -> "git")
        base_name = module_dir.name[3:]  # Remove "aa_" prefix
        src_dir = module_dir / "src"

        if not src_dir.exists():
            continue

        # Check for tools files
        tools_py = src_dir / TOOLS_FILE
        tools_core_py = src_dir / TOOLS_CORE_FILE
        tools_basic_py = src_dir / TOOLS_BASIC_FILE
        tools_extra_py = src_dir / TOOLS_EXTRA_FILE
        tools_style_py = src_dir / TOOLS_STYLE_FILE

        # Add base module if any tools file exists
        if tools_py.exists() or tools_core_py.exists() or tools_basic_py.exists():
            modules.add(base_name)

        # Add _core variant if tools_core.py exists
        if tools_core_py.exists():
            modules.add(f"{base_name}_core")

        # Add _basic variant if tools_basic.py exists
        if tools_basic_py.exists():
            modules.add(f"{base_name}_basic")

        # Add _extra variant if tools_extra.py exists
        if tools_extra_py.exists():
            modules.add(f"{base_name}_extra")

        # Add _style variant if tools_style.py exists
        if tools_style_py.exists():
            modules.add(f"{base_name}_style")

    logger.debug(f"Discovered {len(modules)} tool modules: {sorted(modules)}")
    return modules


# Dynamically discovered tool modules (cached on first access)
_discovered_modules: set[str] | None = None


def get_available_modules() -> set[str]:
    """Get available tool modules, discovering them if needed."""
    global _discovered_modules
    if _discovered_modules is None:
        _discovered_modules = discover_tool_modules()
    return _discovered_modules


def is_valid_module(module_name: str) -> bool:
    """Check if a module name is valid (exists in tool_modules)."""
    return module_name in get_available_modules()


# Core tools that should never be removed
CORE_TOOLS = {
    "persona_load",
    "persona_list",
    "session_start",
    "debug_tool",
    # Unified memory abstraction tools
    "memory_ask",
    "memory_search",
    "memory_store",
    "memory_health",
    "memory_list_adapters",
}


class PersonaLoader:
    """Manages dynamic persona/tool loading."""

    def __init__(self, server: "FastMCP"):
        self.server = server
        self.current_persona: str = ""
        self.loaded_modules: set[str] = set()
        self._tool_to_module: dict[str, str] = {}  # tool_name -> module_name
        # Lock for thread-safe access to shared state
        self._state_lock = asyncio.Lock()

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
        tools_file = get_tools_file_path(module_name)

        if not tools_file.exists():
            logger.warning(f"Tools file not found: {tools_file}")
            return []

        try:
            spec = importlib.util.spec_from_file_location(
                f"aa_{module_name}_tools_dynamic", tools_file
            )
            if spec is None or spec.loader is None:
                return []

            module = importlib.util.module_from_spec(spec)

            # Get tool names before loading (Tool objects aren't hashable, so use names)
            tools_before = {t.name for t in await self.server.list_tools()}

            # Load the module (registers tools with server)
            spec.loader.exec_module(module)

            # Validate module structure before calling register_tools
            if not is_tool_module(module):
                logger.warning(
                    f"Module {module_name} does not implement ToolModuleProtocol"
                )
                return []

            # Log any validation warnings (non-fatal)
            validation_errors = validate_tool_module(module, module_name)
            for error in validation_errors:
                logger.warning(f"Tool module validation: {error}")

            module.register_tools(self.server)

            # Get tool names after loading
            tools_after = {t.name for t in await self.server.list_tools()}
            new_tool_names = list(tools_after - tools_before)

            # Track which tools came from this module (with lock for thread safety)
            async with self._state_lock:
                for tool_name in new_tool_names:
                    self._tool_to_module[tool_name] = module_name
                self.loaded_modules.add(module_name)

            logger.info(f"Loaded {module_name}: {len(new_tool_names)} tools")

            return new_tool_names

        except Exception as e:
            logger.error(f"Error loading {module_name}: {e}")
            return []

    async def _unload_module_tools(self, module_name: str) -> int:
        """Remove all tools from a specific module."""
        async with self._state_lock:
            tools_to_remove = [
                name
                for name, mod in self._tool_to_module.items()
                if mod == module_name and name not in CORE_TOOLS
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

        async with self._state_lock:
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

        This method is workspace-aware: it stores the persona in the
        WorkspaceRegistry for the current workspace, allowing different
        Cursor chats to have different active personas.

        Args:
            persona_name: Persona to switch to (e.g., "devops", "developer")
            ctx: MCP Context for sending notifications and workspace identification

        Returns:
            dict with status, tools loaded, and persona info
        """
        # Load persona config
        config = self.load_persona_config(persona_name)
        if not config:
            # Emit failure notification
            try:
                from tool_modules.aa_workflow.src.notification_emitter import (
                    notify_persona_failed,
                )

                notify_persona_failed(persona_name, "Persona not found")
            except Exception as e:
                logger.debug(f"Suppressed error in notify_persona_failed: {e}")
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
            if not is_valid_module(module_name):
                logger.warning(f"Unknown module: {module_name}")
                continue

            new_tools = await self._load_tool_module(module_name)
            loaded_tools.extend(new_tools)

        # Update global persona (for backward compatibility)
        self.current_persona = persona_name

        # Update workspace-specific persona
        try:
            from .workspace_state import WorkspaceRegistry, update_persona_tool_count

            workspace_state = await WorkspaceRegistry.get_for_ctx(ctx)

            # Get or create active session and update it directly
            session = workspace_state.get_active_session()
            if session:
                # Update session directly (not via workspace property)
                old_persona = session.persona
                session.persona = persona_name
                session.static_tool_count = len(loaded_tools)
                logger.info(
                    f"Updated session {session.session_id[:8]}: "
                    f"persona '{old_persona}' -> '{persona_name}', tools: {len(loaded_tools)}"
                )
            else:
                # No active session - create one with the new persona
                session = workspace_state.create_session(persona=persona_name)
                session.static_tool_count = len(loaded_tools)
                logger.info(
                    f"Created session {session.session_id[:8]} with "
                    f"persona '{persona_name}', tools: {len(loaded_tools)}"
                )

            workspace_state.clear_filter_cache()  # Clear NPU cache when persona changes

            # Update the global persona tool count cache
            update_persona_tool_count(persona_name, len(loaded_tools))

            logger.info(
                f"Set persona '{persona_name}' for workspace "
                f"{workspace_state.workspace_uri} with {len(loaded_tools)} tools"
            )

            # Persist to disk so UI can see the change
            WorkspaceRegistry.save_to_disk()
        except Exception as e:
            logger.warning(f"Failed to update workspace state: {e}")
            import traceback

            logger.warning(traceback.format_exc())

        # Notify client that tools changed
        try:
            if ctx.session:
                await ctx.session.send_tool_list_changed()
                logger.info("Sent tool_list_changed notification")
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")

        # Emit toast notification for persona load
        try:
            from tool_modules.aa_workflow.src.notification_emitter import (
                notify_persona_loaded,
            )

            notify_persona_loaded(persona_name, len(loaded_tools))
        except Exception as e:
            logger.debug(f"Failed to emit persona notification: {e}")

        # Load persona description
        # Check if persona points to a file or is inline
        persona_ref = config.get("persona", "")
        persona = ""

        if persona_ref.endswith(".md"):
            # It's a file reference (e.g., "personas/dave.md")
            persona_path = PERSONAS_DIR.parent / persona_ref
            if persona_path.exists():
                persona = persona_path.read_text()
        elif persona_ref:
            # It's inline content
            persona = persona_ref
        else:
            # Fall back to {persona_name}.md
            persona_file = PERSONAS_DIR / f"{persona_name}.md"
            if persona_file.exists():
                persona = persona_file.read_text()

        # Append additional persona instructions if specified
        persona_append = config.get("persona_append", "")
        if persona_append:
            persona = persona + "\n" + persona_append

        return {
            "success": True,
            "persona": persona_name,
            "description": config.get("description", ""),
            "modules_loaded": list(self.loaded_modules),
            "tool_count": len(loaded_tools),
            "persona_context": persona,
        }

    async def get_workspace_persona(self, ctx: "Context") -> str:
        """Get the persona for the current workspace.

        Args:
            ctx: MCP Context for workspace identification

        Returns:
            Persona name for the current workspace
        """
        try:
            from .workspace_state import WorkspaceRegistry

            workspace_state = await WorkspaceRegistry.get_for_ctx(ctx)
            return workspace_state.persona
        except Exception as e:
            logger.debug(f"Suppressed error in get_workspace_persona: {e}")
            if self.current_persona:
                return self.current_persona
            # Fall back to config default
            try:
                from server.utils import load_config

                cfg = load_config()
                return cfg.get("agent", {}).get("default_persona", "researcher")
            except Exception as e2:
                logger.debug(
                    f"Suppressed error in get_workspace_persona config fallback: {e2}"
                )
                return "researcher"

    async def set_workspace_persona(self, ctx: "Context", persona_name: str) -> None:
        """Set the persona for the current workspace without loading tools.

        Use this when you want to track persona per-workspace but not
        reload tools (e.g., when tools are already loaded globally).

        Args:
            ctx: MCP Context for workspace identification
            persona_name: Persona name to set
        """
        try:
            from .workspace_state import WorkspaceRegistry

            workspace_state = await WorkspaceRegistry.get_for_ctx(ctx)
            workspace_state.persona = persona_name
            workspace_state.clear_filter_cache()
            logger.debug(f"Set workspace persona to '{persona_name}'")
        except Exception as e:
            logger.warning(f"Failed to set workspace persona: {e}")

    def get_status(self) -> dict:
        """Get current persona loader status (global)."""
        return {
            "current_persona": self.current_persona,
            "loaded_modules": list(self.loaded_modules),
            "tool_count": len(self._tool_to_module),
            "tools": list(self._tool_to_module.keys()),
        }

    async def get_workspace_status(self, ctx: "Context") -> dict:
        """Get persona loader status for the current workspace.

        Args:
            ctx: MCP Context for workspace identification

        Returns:
            dict with workspace-specific persona status
        """
        try:
            from .workspace_state import WorkspaceRegistry

            workspace_state = await WorkspaceRegistry.get_for_ctx(ctx)
            return {
                "workspace_uri": workspace_state.workspace_uri,
                "persona": workspace_state.persona,
                "project": workspace_state.project,
                "active_tools": list(workspace_state.active_tools),
                "global_persona": self.current_persona,
                "loaded_modules": list(self.loaded_modules),
                "tool_count": len(self._tool_to_module),
            }
        except Exception as e:
            logger.warning(f"Failed to get workspace status: {e}")
            return self.get_status()


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
