"""
Adapter Registry - Decorator-based registration for memory adapters.

This module provides the @memory_adapter decorator and global ADAPTER_MANIFEST
for registering and discovering memory source adapters.

The pattern mirrors server/tool_discovery.py for consistency:
- Decorators register at import time
- Global manifest tracks all registered adapters
- Discovery functions scan tool_modules for adapters

Usage:
    from services.memory_abstraction.registry import memory_adapter
    
    @memory_adapter(
        name="code",
        display_name="Code Search",
        capabilities={"query", "search"},
        intent_keywords=["function", "class", "code"],
        priority=60,
    )
    class CodeSearchAdapter:
        async def query(self, question, filter): ...
"""

import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# Project root for module discovery
PROJECT_ROOT = Path(__file__).parent.parent.parent
TOOL_MODULES_DIR = PROJECT_ROOT / "tool_modules"
ADAPTER_FILE = "adapter.py"


# Latency class constants
LATENCY_FAST = "fast"       # <2s - local operations, vector DBs
LATENCY_SLOW = "slow"       # >2s - external APIs, AI queries


@dataclass
class AdapterInfo:
    """
    Metadata about a registered adapter.
    
    Stored in ADAPTER_MANIFEST when an adapter is registered
    via the @memory_adapter decorator.
    """
    name: str                           # Unique ID: "code", "slack", "yaml"
    module: str                         # Source module: "code_search", "slack_persona"
    display_name: str                   # Human readable: "Code Search"
    capabilities: set[str]              # {"query", "store", "search"}
    intent_keywords: list[str]          # For routing: ["function", "class"]
    priority: int = 50                  # Higher = preferred when multiple match
    latency_class: str = LATENCY_FAST   # "fast" (<2s) or "slow" (>2s)
    source_file: str = ""               # Path to adapter source file
    adapter_class: type | None = None   # The adapter class itself
    
    def to_dict(self) -> dict:
        """Convert to dictionary (excluding class reference)."""
        return {
            "name": self.name,
            "module": self.module,
            "display_name": self.display_name,
            "capabilities": list(self.capabilities),
            "intent_keywords": self.intent_keywords,
            "priority": self.priority,
            "latency_class": self.latency_class,
            "source_file": self.source_file,
        }
    
    @property
    def is_fast(self) -> bool:
        """Check if this adapter is fast (suitable for bootstrap)."""
        return self.latency_class == LATENCY_FAST


@dataclass
class AdapterManifest:
    """
    Global registry of all discovered adapters.
    
    Mirrors ToolManifest from server/tool_discovery.py.
    """
    
    adapters: dict[str, AdapterInfo] = field(default_factory=dict)
    modules: dict[str, str] = field(default_factory=dict)  # module -> adapter_name
    _frozen: bool = False
    _instances: dict[str, object] = field(default_factory=dict)  # Cached adapter instances
    
    def register(self, info: AdapterInfo) -> None:
        """Register an adapter in the manifest."""
        if self._frozen:
            logger.warning(f"Manifest frozen, cannot register: {info.name}")
            return
        
        if info.name in self.adapters:
            logger.warning(f"Adapter already registered, overwriting: {info.name}")
        
        self.adapters[info.name] = info
        if info.module:
            self.modules[info.module] = info.name
        
        logger.debug(f"Registered adapter: {info.name} (module={info.module}, "
                     f"capabilities={info.capabilities})")
    
    def get_adapter(self, name: str) -> AdapterInfo | None:
        """Get adapter info by name."""
        return self.adapters.get(name)
    
    def get_by_module(self, module: str) -> AdapterInfo | None:
        """Get adapter info by source module name."""
        adapter_name = self.modules.get(module)
        return self.adapters.get(adapter_name) if adapter_name else None
    
    def get_instance(self, name: str) -> object | None:
        """
        Get or create an adapter instance.
        
        Instances are cached for reuse.
        """
        if name in self._instances:
            return self._instances[name]
        
        info = self.adapters.get(name)
        if not info or not info.adapter_class:
            return None
        
        try:
            instance = info.adapter_class()
            self._instances[name] = instance
            return instance
        except Exception as e:
            logger.error(f"Failed to create adapter instance {name}: {e}")
            return None
    
    def list_adapters(self) -> list[str]:
        """List all registered adapter names."""
        return list(self.adapters.keys())
    
    def list_by_capability(self, capability: str) -> list[str]:
        """List adapters that support a specific capability."""
        return [
            name for name, info in self.adapters.items()
            if capability in info.capabilities
        ]
    
    def list_by_latency_class(self, latency_class: str) -> list[str]:
        """List adapters by latency class ('fast' or 'slow')."""
        return [
            name for name, info in self.adapters.items()
            if info.latency_class == latency_class
        ]
    
    def list_fast_adapters(self, capability: str | None = None) -> list[str]:
        """List fast adapters, optionally filtered by capability."""
        return [
            name for name, info in self.adapters.items()
            if info.latency_class == LATENCY_FAST
            and (capability is None or capability in info.capabilities)
        ]
    
    def list_slow_adapters(self, capability: str | None = None) -> list[str]:
        """List slow adapters, optionally filtered by capability."""
        return [
            name for name, info in self.adapters.items()
            if info.latency_class == LATENCY_SLOW
            and (capability is None or capability in info.capabilities)
        ]
    
    def freeze(self) -> None:
        """Freeze the manifest to prevent further registration."""
        self._frozen = True
        logger.info(f"Adapter manifest frozen with {len(self.adapters)} adapters")
    
    def clear(self) -> None:
        """Clear all registrations (for testing)."""
        self.adapters.clear()
        self.modules.clear()
        self._instances.clear()
        self._frozen = False


# Global manifest instance
ADAPTER_MANIFEST = AdapterManifest()


def memory_adapter(
    name: str,
    display_name: str,
    capabilities: set[str],
    intent_keywords: list[str],
    priority: int = 50,
    latency_class: str = LATENCY_FAST,
) -> Callable:
    """
    Decorator to register a memory source adapter.
    
    Mirrors @register_tool() from server/tool_discovery.py.
    
    Args:
        name: Unique adapter identifier (e.g., "code", "slack", "yaml")
        display_name: Human-readable name (e.g., "Code Search")
        capabilities: Set of supported operations {"query", "search", "store"}
        intent_keywords: Keywords for intent-based routing
        priority: Higher priority adapters are preferred (default 50)
        latency_class: "fast" (<2s, local) or "slow" (>2s, external APIs)
                       Fast adapters are used in bootstrap, slow are on-demand.
    
    Returns:
        Decorator function
    
    Example:
        @memory_adapter(
            name="code",
            display_name="Code Search",
            capabilities={"query", "search"},
            intent_keywords=["function", "class", "implementation"],
            priority=60,
            latency_class="fast",  # Local vector search
        )
        class CodeSearchAdapter:
            async def query(self, question, filter): ...
    """
    def decorator(cls: type) -> type:
        # Get source file info - try multiple methods for dynamic loading
        source_file = ""
        try:
            source_file = inspect.getfile(cls)
        except (TypeError, OSError):
            pass
        
        # If inspect.getfile failed, try to get from module
        if not source_file:
            try:
                module = inspect.getmodule(cls)
                if module and hasattr(module, "__file__"):
                    source_file = module.__file__ or ""
            except Exception:
                pass
        
        # Extract module name from path
        # tool_modules/aa_code_search/src/adapter.py -> code_search
        module_name = ""
        if source_file:
            path = Path(source_file)
            if "tool_modules" in path.parts:
                idx = path.parts.index("tool_modules")
                if idx + 1 < len(path.parts):
                    dir_name = path.parts[idx + 1]
                    if dir_name.startswith("aa_"):
                        module_name = dir_name[3:]  # Remove "aa_" prefix
        
        # Fallback: try to extract from class module name
        # e.g., "aa_code_search_adapter_dynamic" -> "code_search"
        if not module_name and hasattr(cls, "__module__"):
            cls_module = cls.__module__
            if cls_module.startswith("aa_") and "_adapter" in cls_module:
                # Extract: aa_code_search_adapter_dynamic -> code_search
                parts = cls_module.split("_adapter")[0]
                if parts.startswith("aa_"):
                    module_name = parts[3:]  # Remove "aa_" prefix
        
        # Create adapter info
        info = AdapterInfo(
            name=name,
            module=module_name,
            display_name=display_name,
            capabilities=set(capabilities),
            intent_keywords=list(intent_keywords),
            priority=priority,
            latency_class=latency_class,
            source_file=source_file,
            adapter_class=cls,
        )
        
        # Register in global manifest
        ADAPTER_MANIFEST.register(info)
        
        # Attach metadata to class for runtime access
        cls._adapter_info = info
        
        return cls
    
    return decorator


# Convenience functions for querying the manifest

def get_adapter_info(name: str) -> AdapterInfo | None:
    """Get adapter info by name."""
    return ADAPTER_MANIFEST.get_adapter(name)


def get_adapter_instance(name: str) -> object | None:
    """Get or create an adapter instance."""
    return ADAPTER_MANIFEST.get_instance(name)


def list_adapters() -> list[str]:
    """List all registered adapter names."""
    return ADAPTER_MANIFEST.list_adapters()


def list_adapters_by_capability(capability: str) -> list[str]:
    """List adapters that support a specific capability."""
    return ADAPTER_MANIFEST.list_by_capability(capability)
