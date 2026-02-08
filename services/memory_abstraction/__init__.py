"""
Memory Abstraction Layer - Unified interface for all memory sources.

This package provides a single interface for querying multiple data sources:
- YAML memory files (state, learned, knowledge)
- Vector databases (code search, Slack messages)
- External APIs (InScope AI, Jira)
- Future sources (NPU classifiers, AI agents)

Architecture:
    ┌─────────────────────────────────────────────────────────────┐
    │                    MemoryInterface                          │
    │  query() / search() / store() / learn()                     │
    └─────────────────────┬───────────────────────────────────────┘
                          │
    ┌─────────────────────▼───────────────────────────────────────┐
    │                    QueryRouter                               │
    │  Intent classification → Source selection                    │
    └─────────────────────┬───────────────────────────────────────┘
                          │
    ┌─────────────────────▼───────────────────────────────────────┐
    │                 Source Adapters                              │
    │  YamlAdapter │ CodeAdapter │ SlackAdapter │ InScopeAdapter  │
    └─────────────────────┬───────────────────────────────────────┘
                          │
    ┌─────────────────────▼───────────────────────────────────────┐
    │                  ResultMerger                                │
    │  Combine, deduplicate, rank by relevance                     │
    └─────────────────────────────────────────────────────────────┘

Usage:
    from services.memory_abstraction import MemoryInterface, memory_adapter

    # Query memory (auto-selects sources based on intent)
    memory = MemoryInterface()
    result = await memory.query("What am I working on?")

    # Query specific sources
    result = await memory.query(
        "Show billing code",
        sources=[SourceFilter(name="code", project="backend")]
    )

    # Create a new adapter
    @memory_adapter(
        name="my_source",
        display_name="My Source",
        capabilities={"query", "search"},
        intent_keywords=["my", "source"],
    )
    class MySourceAdapter:
        async def query(self, question, filter): ...
"""

from .adapter_protocol import BaseAdapter, SourceAdapter
from .classifier import IntentClassifier
from .discovery import (
    discover_adapter_modules,
    discover_and_load_all_adapters,
    get_adapter_info,
    list_adapters,
)
from .formatter import ResultFormatter
from .interface import MemoryInterface, get_memory_interface, set_memory_interface
from .merger import ResultMerger
from .models import (  # noqa: F401
    LATENCY_FAST,
    LATENCY_SLOW,
    AdapterInfo,
    AdapterResult,
    HealthStatus,
    IntentClassification,
    MemoryItem,
    QueryResult,
    SourceFilter,
)
from .registry import ADAPTER_MANIFEST, memory_adapter
from .router import QueryRouter

__all__ = [
    # Main interface
    "MemoryInterface",
    "get_memory_interface",
    "set_memory_interface",
    # Decorator and protocol
    "memory_adapter",
    "SourceAdapter",
    "BaseAdapter",
    # Models
    "MemoryItem",
    "QueryResult",
    "IntentClassification",
    "AdapterResult",
    "HealthStatus",
    "SourceFilter",
    "AdapterInfo",
    # Discovery
    "discover_adapter_modules",
    "discover_and_load_all_adapters",
    "get_adapter_info",
    "list_adapters",
    # Components
    "IntentClassifier",
    "QueryRouter",
    "ResultMerger",
    "ResultFormatter",
    # Registry
    "ADAPTER_MANIFEST",
]
