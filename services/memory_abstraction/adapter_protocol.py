"""
Source Adapter Protocol - Interface that all memory adapters must implement.

This module defines the protocol (interface) that memory source adapters
must implement to be discoverable and usable by the memory abstraction layer.

Usage:
    from services.memory_abstraction.adapter_protocol import SourceAdapter

    class MyAdapter(SourceAdapter):
        async def query(self, question, filter): ...
        async def search(self, query, filter): ...
        async def store(self, key, value, filter): ...
        async def health_check(self): ...
"""

from typing import Any, Protocol, runtime_checkable

from .models import AdapterResult, HealthStatus, SourceFilter


@runtime_checkable
class SourceAdapter(Protocol):
    """
    Protocol that all memory source adapters must implement.

    Adapters provide access to different data sources (YAML files,
    vector databases, APIs, etc.) through a unified interface.

    Required Methods:
        - query: Answer a question using the source
        - search: Semantic search across the source
        - store: Store data in the source (if supported)
        - health_check: Check if the source is available

    The @memory_adapter decorator automatically registers adapters
    and attaches metadata (_adapter_info attribute).

    Example:
        @memory_adapter(
            name="code",
            display_name="Code Search",
            capabilities={"query", "search"},
            intent_keywords=["function", "class", "code"],
        )
        class CodeSearchAdapter:
            async def query(self, question: str, filter: SourceFilter | None) -> AdapterResult:
                # Implementation
                ...
    """

    async def query(
        self,
        question: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """
        Query the source with a natural language question.

        Args:
            question: Natural language question to answer
            filter: Optional filter with source-specific parameters

        Returns:
            AdapterResult with found items or error

        Example:
            result = await adapter.query(
                "What's the billing calculation?",
                SourceFilter(name="code", project="backend")
            )
        """
        ...

    async def search(
        self,
        query: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """
        Semantic search across the source.

        For many sources, this is the same as query(). For others
        (like vector databases), it may use different search strategies.

        Args:
            query: Search query
            filter: Optional filter with source-specific parameters

        Returns:
            AdapterResult with matching items or error
        """
        ...

    async def store(
        self,
        key: str,
        value: Any,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """
        Store data in the source.

        Not all sources support storage. Read-only sources should
        return an AdapterResult with an error message.

        Args:
            key: Storage key or path
            value: Data to store
            filter: Optional filter with source-specific parameters

        Returns:
            AdapterResult indicating success or error
        """
        ...

    async def health_check(self) -> HealthStatus:
        """
        Check if the source is available and healthy.

        Used to determine if an adapter should be included in queries.

        Returns:
            HealthStatus indicating health and any issues
        """
        ...


class BaseAdapter:
    """
    Base class for adapters with common functionality.

    Provides default implementations and helper methods.
    Adapters can inherit from this class for convenience,
    but it's not required - they just need to implement
    the SourceAdapter protocol.
    """

    async def query(
        self,
        question: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Default query implementation - subclasses should override."""
        return AdapterResult(
            source=getattr(self, "_adapter_info", {}).get("name", "unknown"),
            found=False,
            items=[],
            error="query() not implemented",
        )

    async def search(
        self,
        query: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Default search - delegates to query()."""
        return await self.query(query, filter)

    async def store(
        self,
        key: str,
        value: Any,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Default store - returns not supported error."""
        return AdapterResult(
            source=getattr(self, "_adapter_info", {}).get("name", "unknown"),
            found=False,
            items=[],
            error="This adapter is read-only",
        )

    async def health_check(self) -> HealthStatus:
        """Default health check - returns healthy."""
        return HealthStatus(healthy=True)

    @property
    def name(self) -> str:
        """Get adapter name from metadata."""
        info = getattr(self, "_adapter_info", None)
        return info.name if info else "unknown"

    @property
    def capabilities(self) -> set[str]:
        """Get adapter capabilities from metadata."""
        info = getattr(self, "_adapter_info", None)
        return info.capabilities if info else set()

    def supports(self, capability: str) -> bool:
        """Check if adapter supports a capability."""
        return capability in self.capabilities
