"""Tool Discovery System.

Provides decorator-based tool registration with automatic discovery.
Tools register themselves at import time, eliminating hardcoded tool lists.

## Architecture

1. Modules use `@register_tool(tier="basic")` decorator on each tool
2. Decorator adds tool to global TOOL_MANIFEST at import time
3. `tool_list()` queries the manifest dynamically
4. `tool_exec()` looks up module from manifest

## Usage in tool modules:

    from server.tool_discovery import register_tool, get_module_tools

    def register_tools(server: FastMCP) -> int:
        registry = ToolRegistry(server)

        @register_tool(module="quay", tier="basic")
        @registry.tool()
        async def quay_get_tag(...):
            ...

        return registry.count
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# Project root for module discovery
PROJECT_ROOT = Path(__file__).parent.parent
TOOL_MODULES_DIR = PROJECT_ROOT / "tool_modules"


class ToolTier(str, Enum):
    """Tool tier classification.

    Three-tier system for managing tool context limits (~80 tools max):
    - CORE: Essential tools loaded by default with persona (5-10 per module)
    - BASIC: Common tools, available via explicit _basic suffix or tool_exec()
    - EXTRA: Advanced tools, available via tool_exec() only
    """

    CORE = "core"  # Essential tools, loaded by default with persona
    BASIC = "basic"  # Common tools, loaded with _basic suffix
    EXTRA = "extra"  # Additional tools, available via tool_exec


@dataclass
class ToolInfo:
    """Metadata about a registered tool."""

    name: str
    module: str
    tier: ToolTier
    description: str = ""
    source_file: str = ""
    line_number: int = 0


@dataclass
class ToolManifest:
    """Global registry of all discovered tools."""

    tools: dict[str, ToolInfo] = field(default_factory=dict)
    modules: dict[str, list[str]] = field(
        default_factory=dict
    )  # module -> [tool_names]
    _frozen: bool = False

    def register(self, info: ToolInfo) -> None:
        """Register a tool in the manifest."""
        if self._frozen:
            logger.warning(f"Manifest frozen, cannot register: {info.name}")
            return

        self.tools[info.name] = info

        # Track by module
        if info.module not in self.modules:
            self.modules[info.module] = []
        if info.name not in self.modules[info.module]:
            self.modules[info.module].append(info.name)

        logger.debug(
            f"Registered tool: {info.name} (module={info.module}, tier={info.tier})"
        )

    def get_module_tools(self, module: str, tier: ToolTier | None = None) -> list[str]:
        """Get tools for a module, optionally filtered by tier."""
        tools = self.modules.get(module, [])
        if tier is None:
            return tools
        return [t for t in tools if self.tools[t].tier == tier]

    def get_tool_module(self, tool_name: str) -> str | None:
        """Get the module a tool belongs to."""
        info = self.tools.get(tool_name)
        return info.module if info else None

    def list_modules(self) -> list[str]:
        """List all modules with registered tools."""
        return list(self.modules.keys())

    def freeze(self) -> None:
        """Freeze the manifest to prevent further registration."""
        self._frozen = True

    def clear(self) -> None:
        """Clear all registrations (for testing)."""
        self.tools.clear()
        self.modules.clear()
        self._frozen = False


# Global manifest instance
TOOL_MANIFEST = ToolManifest()


def register_tool(
    module: str,
    tier: str | ToolTier = ToolTier.BASIC,
    description: str = "",
) -> Callable:
    """Decorator to register a tool in the global manifest.

    Use this decorator BEFORE @registry.tool() to register the tool
    in the discovery system.

    Args:
        module: Module name (e.g., "quay", "gitlab", "git")
        tier: Tool tier - "core", "basic", or "extra"
        description: Optional description override

    Returns:
        Decorator function

    Example:
        @register_tool(module="quay", tier="core")
        @registry.tool()
        async def quay_get_tag(...):
            ...
    """
    tier_enum = ToolTier(tier) if isinstance(tier, str) else tier

    def decorator(func: Callable) -> Callable:
        import inspect

        # Get source info
        try:
            source_file = inspect.getfile(func)
            _, start_line = inspect.getsourcelines(func)
        except (TypeError, OSError):
            source_file = ""
            start_line = 0

        # Create tool info
        info = ToolInfo(
            name=func.__name__,
            module=module,
            tier=tier_enum,
            description=description or (func.__doc__ or "").split("\n")[0].strip(),
            source_file=source_file,
            line_number=start_line,
        )

        # Register in global manifest
        TOOL_MANIFEST.register(info)

        return func

    return decorator


# Convenience decorators for common patterns
def core_tool(module: str, description: str = "") -> Callable:
    """Shorthand for @register_tool(module=..., tier="core")."""
    return register_tool(module=module, tier=ToolTier.CORE, description=description)


def basic_tool(module: str, description: str = "") -> Callable:
    """Shorthand for @register_tool(module=..., tier="basic")."""
    return register_tool(module=module, tier=ToolTier.BASIC, description=description)


def extra_tool(module: str, description: str = "") -> Callable:
    """Shorthand for @register_tool(module=..., tier="extra")."""
    return register_tool(module=module, tier=ToolTier.EXTRA, description=description)


# ============== Query Functions ==============


def get_module_tools(module: str, tier: str | None = None) -> list[str]:
    """Get all tools for a module.

    Args:
        module: Module name (e.g., "quay", "gitlab")
        tier: Optional tier filter ("basic" or "extra")

    Returns:
        List of tool names
    """
    tier_enum = ToolTier(tier) if tier else None
    return TOOL_MANIFEST.get_module_tools(module, tier_enum)


def get_tool_module(tool_name: str) -> str | None:
    """Get the module a tool belongs to.

    Args:
        tool_name: Name of the tool

    Returns:
        Module name or None if not found
    """
    return TOOL_MANIFEST.get_tool_module(tool_name)


def get_all_tools() -> dict[str, list[str]]:
    """Get all registered tools grouped by module.

    Returns:
        Dict of {module: [tool_names]}
    """
    return dict(TOOL_MANIFEST.modules)


def get_tool_info(tool_name: str) -> ToolInfo | None:
    """Get full info for a tool.

    Args:
        tool_name: Name of the tool

    Returns:
        ToolInfo or None if not found
    """
    return TOOL_MANIFEST.tools.get(tool_name)


def list_modules() -> list[str]:
    """List all modules with registered tools."""
    return TOOL_MANIFEST.list_modules()


# ============== Fallback Discovery ==============


def discover_tools_from_file(filepath: Path, module: str) -> list[ToolInfo]:
    """Scan a Python file for tool registrations (fallback method).

    This is used when tools haven't been loaded yet but we need to know
    what's available. It parses the file looking for @registry.tool() decorators.

    Args:
        filepath: Path to the tools file
        module: Module name

    Returns:
        List of discovered ToolInfo objects
    """
    import ast

    if not filepath.exists():
        return []

    try:
        with open(filepath, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
    except (SyntaxError, OSError) as e:
        logger.warning(f"Could not parse {filepath}: {e}")
        return []

    tools = []
    # Determine tier from filename
    if "core" in filepath.name:
        tier = ToolTier.CORE
    elif "extra" in filepath.name:
        tier = ToolTier.EXTRA
    else:
        tier = ToolTier.BASIC

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            # Check if this function has @registry.tool() decorator
            for decorator in node.decorator_list:
                decorator_name = ""
                if isinstance(decorator, ast.Call):
                    if isinstance(decorator.func, ast.Attribute):
                        decorator_name = decorator.func.attr
                    elif isinstance(decorator.func, ast.Name):
                        decorator_name = decorator.func.id
                elif isinstance(decorator, ast.Attribute):
                    decorator_name = decorator.attr
                elif isinstance(decorator, ast.Name):
                    decorator_name = decorator.id

                if decorator_name == "tool":
                    # Get docstring
                    docstring = ast.get_docstring(node) or ""
                    first_line = docstring.split("\n")[0].strip() if docstring else ""

                    tools.append(
                        ToolInfo(
                            name=node.name,
                            module=module,
                            tier=tier,
                            description=first_line,
                            source_file=str(filepath),
                            line_number=node.lineno,
                        )
                    )
                    break  # Found the decorator, move to next function

    return tools


def discover_module_tools(module: str) -> dict[str, list[str]]:
    """Discover all tools in a module by scanning files.

    This is a fallback for when modules haven't been loaded yet.

    Args:
        module: Module name (e.g., "quay", "gitlab")

    Returns:
        Dict with "core", "basic" and "extra" tool lists
    """
    base_name = module.replace("_core", "").replace("_basic", "").replace("_extra", "")
    module_dir = TOOL_MODULES_DIR / f"aa_{base_name}" / "src"

    result = {"core": [], "basic": [], "extra": []}

    # Scan core tools (highest priority, smallest set)
    core_file = module_dir / "tools_core.py"
    if core_file.exists():
        for info in discover_tools_from_file(core_file, base_name):
            result["core"].append(info.name)

    # Scan basic tools
    basic_file = module_dir / "tools_basic.py"
    if basic_file.exists():
        for info in discover_tools_from_file(basic_file, base_name):
            result["basic"].append(info.name)

    # Scan extra tools
    extra_file = module_dir / "tools_extra.py"
    if extra_file.exists():
        for info in discover_tools_from_file(extra_file, base_name):
            result["extra"].append(info.name)

    # Fallback to legacy tools.py (treat as basic)
    if not result["core"] and not result["basic"] and not result["extra"]:
        legacy_file = module_dir / "tools.py"
        if legacy_file.exists():
            for info in discover_tools_from_file(legacy_file, base_name):
                result["basic"].append(info.name)

    # Special case: workflow module has tools split across multiple files
    # Scan all *_tools.py files in the module directory
    if (
        not result["core"]
        and not result["basic"]
        and not result["extra"]
        and module_dir.exists()
    ):
        for py_file in module_dir.glob("*_tools.py"):
            for info in discover_tools_from_file(py_file, base_name):
                result["basic"].append(info.name)
        # Also scan skill_engine.py for skill tools
        skill_engine = module_dir / "skill_engine.py"
        if skill_engine.exists():
            for info in discover_tools_from_file(skill_engine, base_name):
                result["basic"].append(info.name)

    return result


def build_full_manifest() -> dict[str, list[str]]:
    """Build a complete manifest by scanning all tool modules.

    This is used by tool_list() when no tools have been loaded yet.

    Returns:
        Dict of {module: [tool_names]}
    """
    # If manifest already populated, use it
    if TOOL_MANIFEST.modules:
        return dict(TOOL_MANIFEST.modules)

    # Otherwise, scan all modules
    manifest = {}

    for module_dir in TOOL_MODULES_DIR.iterdir():
        if not module_dir.is_dir() or not module_dir.name.startswith("aa_"):
            continue

        module_name = module_dir.name[3:]  # Remove "aa_" prefix
        discovered = discover_module_tools(module_name)

        # Combine core, basic and extra
        all_tools = discovered["core"] + discovered["basic"] + discovered["extra"]
        if all_tools:
            manifest[module_name] = all_tools

    return manifest


def get_module_tool_counts(module: str) -> dict[str, int]:
    """Get tool counts per tier for a module.

    Args:
        module: Module name (e.g., "quay", "gitlab")

    Returns:
        Dict with "core", "basic", "extra" counts
    """
    discovered = discover_module_tools(module)
    return {
        "core": len(discovered["core"]),
        "basic": len(discovered["basic"]),
        "extra": len(discovered["extra"]),
        "total": len(discovered["core"])
        + len(discovered["basic"])
        + len(discovered["extra"]),
    }


# ============== Module Prefix Mapping ==============

# Auto-detect module from tool name prefix
_MODULE_PREFIXES: dict[str, str] | None = None


def _build_prefix_map() -> dict[str, str]:
    """Build a mapping of tool prefixes to modules."""
    prefixes = {}

    # Get all tools from manifest or discovery
    all_tools = build_full_manifest()

    for module, tools in all_tools.items():
        for tool_name in tools:
            # Extract prefix (e.g., "quay_" from "quay_get_tag")
            parts = tool_name.split("_")
            if len(parts) >= 2:
                prefix = f"{parts[0]}_"
                if prefix not in prefixes:
                    prefixes[prefix] = module

    return prefixes


def get_module_for_tool(tool_name: str) -> str | None:
    """Get the module a tool belongs to, using prefix matching as fallback.

    Args:
        tool_name: Name of the tool

    Returns:
        Module name or None
    """
    global _MODULE_PREFIXES

    # First check the manifest (tools that have been loaded)
    module = TOOL_MANIFEST.get_tool_module(tool_name)
    if module:
        return module

    # Check the full discovered manifest (scans files without loading)
    # This is more accurate than prefix matching
    full_manifest = build_full_manifest()
    for mod_name, tools in full_manifest.items():
        if tool_name in tools:
            return mod_name

    # Build prefix map if needed (last resort fallback)
    if _MODULE_PREFIXES is None:
        _MODULE_PREFIXES = _build_prefix_map()

    # Try prefix matching - but verify the tool exists in that module
    for prefix, module in _MODULE_PREFIXES.items():
        if tool_name.startswith(prefix):
            # Verify the tool actually exists in this module
            if module in full_manifest and tool_name in full_manifest[module]:
                return module

    return None
