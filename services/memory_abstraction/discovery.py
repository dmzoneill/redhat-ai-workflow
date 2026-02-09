"""
Adapter Discovery - Scan and load memory adapters from tool_modules.

This module provides functions to discover and load memory adapters
from the tool_modules directory, mirroring the pattern used by
server/persona_loader.py for tool discovery.

Discovery Pattern:
    1. Scan tool_modules/aa_*/src/ for adapter.py files
    2. Import each module using importlib.util
    3. Importing triggers @memory_adapter decorator registration
    4. Return ADAPTER_MANIFEST with all registered adapters

Usage:
    from services.memory_abstraction.discovery import discover_and_load_all_adapters

    # Load all adapters at server startup
    adapters = discover_and_load_all_adapters()

    # Check what's available
    modules = discover_adapter_modules()
"""

import importlib.util
import logging
from pathlib import Path

from .registry import ADAPTER_MANIFEST, AdapterInfo

logger = logging.getLogger(__name__)

# Project root for module discovery
PROJECT_ROOT = Path(__file__).parent.parent.parent
TOOL_MODULES_DIR = PROJECT_ROOT / "tool_modules"
ADAPTER_FILE = "adapter.py"

# Cache for discovered modules
_discovered_modules: set[str] | None = None


def discover_adapter_modules() -> set[str]:
    """
    Discover available adapter modules from tool_modules directory.

    Mirrors discover_tool_modules() from server/persona_loader.py.

    Scans for: tool_modules/aa_*/src/adapter.py

    Returns:
        Set of module names that have adapters (e.g., {'code_search', 'slack_persona'})
    """
    global _discovered_modules

    if _discovered_modules is not None:
        return _discovered_modules

    modules = set()

    if not TOOL_MODULES_DIR.exists():
        logger.warning(f"Tool modules directory not found: {TOOL_MODULES_DIR}")
        return modules

    for module_dir in TOOL_MODULES_DIR.iterdir():
        if not module_dir.is_dir() or not module_dir.name.startswith("aa_"):
            continue

        adapter_file = module_dir / "src" / ADAPTER_FILE
        if adapter_file.exists():
            base_name = module_dir.name[3:]  # Remove "aa_" prefix
            modules.add(base_name)
            logger.debug(f"Found adapter module: {base_name} at {adapter_file}")

    _discovered_modules = modules
    logger.info(f"Discovered {len(modules)} adapter modules: {sorted(modules)}")
    return modules


def load_adapter_module(module_name: str) -> AdapterInfo | None:
    """
    Load an adapter module by name.

    Mirrors PersonaLoader._load_tool_module() pattern.

    Args:
        module_name: Module name (e.g., "code_search", "slack_persona")

    Returns:
        AdapterInfo if loaded successfully, None otherwise
    """
    adapter_file = TOOL_MODULES_DIR / f"aa_{module_name}" / "src" / ADAPTER_FILE

    if not adapter_file.exists():
        logger.warning(f"Adapter file not found: {adapter_file}")
        return None

    try:
        # Same pattern as persona_loader.py
        spec = importlib.util.spec_from_file_location(
            f"aa_{module_name}_adapter_dynamic", adapter_file
        )
        if spec is None or spec.loader is None:
            logger.error(f"Could not create module spec for {adapter_file}")
            return None

        module = importlib.util.module_from_spec(spec)

        # Execute module (triggers @memory_adapter decorator registration)
        spec.loader.exec_module(module)

        # Return the registered adapter info
        info = ADAPTER_MANIFEST.get_by_module(module_name)
        if info:
            logger.info(f"Loaded adapter: {info.name} from {module_name}")
        else:
            logger.warning(f"Module {module_name} loaded but no adapter registered")

        return info

    except Exception as e:
        logger.error(f"Error loading adapter {module_name}: {e}", exc_info=True)
        return None


def discover_and_load_all_adapters() -> dict[str, AdapterInfo]:
    """
    Discover and load all available adapters.

    Called once at server startup (in server/main.py).

    Returns:
        Dict of {adapter_name: AdapterInfo}
    """
    # If already populated, return existing
    if ADAPTER_MANIFEST.adapters:
        logger.debug(
            f"Using existing manifest with {len(ADAPTER_MANIFEST.adapters)} adapters"
        )
        return dict(ADAPTER_MANIFEST.adapters)

    # Discover all modules with adapters
    adapter_modules = discover_adapter_modules()

    # Load each adapter module
    loaded = 0
    for module_name in sorted(adapter_modules):
        info = load_adapter_module(module_name)
        if info:
            loaded += 1

    logger.info(
        f"Loaded {loaded}/{len(adapter_modules)} memory adapters: "
        f"{list(ADAPTER_MANIFEST.adapters.keys())}"
    )

    return dict(ADAPTER_MANIFEST.adapters)


def reload_adapter(module_name: str) -> AdapterInfo | None:
    """
    Reload a specific adapter module.

    Useful for development when adapter code changes.

    Args:
        module_name: Module name to reload

    Returns:
        Updated AdapterInfo or None if failed
    """
    # Clear cached instance
    adapter_name = ADAPTER_MANIFEST.modules.get(module_name)
    if adapter_name and adapter_name in ADAPTER_MANIFEST._instances:
        del ADAPTER_MANIFEST._instances[adapter_name]

    # Reload the module
    return load_adapter_module(module_name)


def get_adapter_info(name: str) -> AdapterInfo | None:
    """Get adapter info by name."""
    return ADAPTER_MANIFEST.get_adapter(name)


def get_adapter_for_module(module: str) -> AdapterInfo | None:
    """Get adapter for a tool module."""
    return ADAPTER_MANIFEST.get_by_module(module)


def list_adapters() -> list[str]:
    """List all registered adapter names."""
    return ADAPTER_MANIFEST.list_adapters()


def get_adapters_for_intent(intent_keywords: list[str]) -> list[AdapterInfo]:
    """
    Get adapters that match given intent keywords.

    Args:
        intent_keywords: Keywords to match against adapter intent_keywords

    Returns:
        List of matching AdapterInfo, sorted by priority (highest first)
    """
    matches = []
    keywords_set = set(kw.lower() for kw in intent_keywords)

    for info in ADAPTER_MANIFEST.adapters.values():
        adapter_keywords = set(kw.lower() for kw in info.intent_keywords)
        if keywords_set & adapter_keywords:  # Any overlap
            matches.append(info)

    # Sort by priority (highest first)
    matches.sort(key=lambda x: x.priority, reverse=True)
    return matches


def clear_discovery_cache() -> None:
    """Clear the discovery cache (for testing)."""
    global _discovered_modules
    _discovered_modules = None
    ADAPTER_MANIFEST.clear()
