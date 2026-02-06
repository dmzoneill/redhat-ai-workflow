"""
Data models for the memory abstraction layer.

These models define the data structures used throughout the memory system:
- SourceFilter: Filter for source-specific queries
- MemoryItem: Single result item from any source
- IntentClassification: Classification of query intent
- AdapterResult: Result from a single adapter
- QueryResult: Combined result from all sources
- HealthStatus: Health check result for an adapter
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SourceFilter:
    """
    Filter for source-specific queries.

    Allows specifying which source to query and with what parameters.

    Examples:
        # Simple name-only filter
        SourceFilter(name="code")

        # Filter with project context
        SourceFilter(name="code", project="automation-analytics-backend")

        # Filter with limit
        SourceFilter(name="slack", limit=5)

        # Filter with extra parameters
        SourceFilter(name="inscope", extra={"assistant": "app-interface"})
    """

    name: str  # Adapter name: "code", "slack", "yaml", etc.
    project: str | None = None  # Project context
    namespace: str | None = None  # Kubernetes namespace context
    limit: int | None = None  # Max results to return
    key: str | None = None  # Specific key for YAML adapter
    extra: dict[str, Any] | None = None  # Source-specific parameters

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceFilter":
        """Create SourceFilter from dictionary."""
        return cls(
            name=data.get("name", ""),
            project=data.get("project"),
            namespace=data.get("namespace"),
            limit=data.get("limit"),
            key=data.get("key"),
            extra=data.get("extra"),
        )

    @classmethod
    def from_string(cls, name: str) -> "SourceFilter":
        """Create SourceFilter from simple string name."""
        return cls(name=name)


@dataclass
class MemoryItem:
    """
    Single result item from any source.

    Represents a piece of information retrieved from a memory source,
    with metadata about its origin and relevance.
    """

    source: str  # Source adapter: "code", "slack", "yaml", etc.
    type: str  # Item type: "code_snippet", "message", "state", etc.
    relevance: float  # Relevance score: 0.0 - 1.0
    summary: str  # One-line summary for quick scanning
    content: str  # Full content (may be truncated)
    metadata: dict[str, Any] = field(default_factory=dict)  # Source-specific metadata
    timestamp: datetime | None = None  # When the item was created/modified

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source": self.source,
            "type": self.type,
            "relevance": self.relevance,
            "summary": self.summary,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


@dataclass
class IntentClassification:
    """
    Classification of query intent.

    Used to determine which sources to query and how to interpret results.
    Always included in QueryResult to help LLM understand context.
    """

    intent: str  # Intent type: "code_lookup", "troubleshooting", etc.
    confidence: float  # Confidence score: 0.0 - 1.0
    sources_suggested: list[str] = field(default_factory=list)  # Recommended sources

    # Known intent types
    INTENTS = {
        "code_lookup": "Find code, implementation, function",
        "troubleshooting": "Debug issue, find error cause",
        "status_check": "Current work, active issues, environment",
        "documentation": "How-to, configuration, setup",
        "history": "Past conversations, decisions",
        "pattern_lookup": "Known fixes, learned patterns",
        "issue_context": "Jira issue details",
        "general": "General query, no specific intent",
    }

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "sources_suggested": self.sources_suggested,
        }


@dataclass
class AdapterResult:
    """
    Result from a single adapter query.

    Each adapter returns this structure, which is then merged
    by the ResultMerger into the final QueryResult.
    """

    source: str  # Adapter name
    items: list[MemoryItem] = field(default_factory=list)  # Result items
    error: str | None = None  # Error message if query failed
    latency_ms: float = 0.0  # Query latency in milliseconds
    _found: bool | None = field(default=None, repr=False)  # Optional explicit found flag

    @property
    def found(self) -> bool:
        """Whether any results were found (derived from items if not set)."""
        if self._found is not None:
            return self._found
        return len(self.items) > 0

    def __init__(
        self,
        source: str,
        items: list[MemoryItem] | None = None,
        error: str | None = None,
        latency_ms: float = 0.0,
        found: bool | None = None,  # Accept but ignore - derived from items
    ):
        self.source = source
        self.items = items if items is not None else []
        self.error = error
        self.latency_ms = latency_ms
        self._found = found  # Store for backward compat but prefer deriving

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source": self.source,
            "found": self.found,
            "items": [item.to_dict() for item in self.items],
            "error": self.error,
            "latency_ms": self.latency_ms,
        }


@dataclass
class QueryResult:
    """
    Combined result from memory query/search.

    Contains results from all queried sources, merged and ranked,
    along with intent classification for LLM context.
    """

    query: str  # Original query
    intent: IntentClassification  # Intent classification (always included)
    sources_queried: list[str] = field(default_factory=list)  # Sources that were searched
    items: list[MemoryItem] = field(default_factory=list)  # Results, sorted by relevance
    total_count: int = 0  # Total matches (items may be truncated)
    latency_ms: float = 0.0  # Total query time
    errors: dict[str, str] = field(default_factory=dict)  # Source -> error message

    def has_results(self) -> bool:
        """Check if any results were found."""
        return len(self.items) > 0

    def get_items_by_source(self, source: str) -> list[MemoryItem]:
        """Get items from a specific source."""
        return [item for item in self.items if item.source == source]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query": self.query,
            "intent": self.intent.to_dict(),
            "sources_queried": self.sources_queried,
            "items": [item.to_dict() for item in self.items],
            "total_count": self.total_count,
            "latency_ms": self.latency_ms,
            "errors": self.errors,
        }


@dataclass
class HealthStatus:
    """
    Health check result for an adapter.

    Used to determine if an adapter is available and functioning.
    """

    healthy: bool  # Whether the adapter is healthy
    error: str | None = None  # Error message if unhealthy
    details: dict[str, Any] = field(default_factory=dict)  # Additional health info

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "healthy": self.healthy,
            "error": self.error,
            "details": self.details,
        }


@dataclass
class AdapterInfo:
    """
    Metadata about a registered adapter.

    Stored in ADAPTER_MANIFEST when an adapter is registered
    via the @memory_adapter decorator.
    """

    name: str  # Unique ID: "code", "slack", "yaml"
    module: str  # Source module: "code_search", "slack_persona"
    display_name: str  # Human readable: "Code Search"
    capabilities: set[str]  # {"query", "store", "search"}
    intent_keywords: list[str]  # For routing: ["function", "class"]
    priority: int = 50  # Higher = preferred when multiple match
    source_file: str = ""  # Path to adapter source file
    adapter_class: type | None = None  # The adapter class itself

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary (excluding class reference)."""
        return {
            "name": self.name,
            "module": self.module,
            "display_name": self.display_name,
            "capabilities": list(self.capabilities),
            "intent_keywords": self.intent_keywords,
            "priority": self.priority,
            "source_file": self.source_file,
        }
