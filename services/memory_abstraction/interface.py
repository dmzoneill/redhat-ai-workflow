"""
Memory Interface - Unified interface for all memory operations.

This is the main entry point for the memory abstraction layer.
It provides a single interface for querying, searching, and storing
data across all registered memory adapters.

Usage:
    from services.memory_abstraction import MemoryInterface

    memory = MemoryInterface()

    # Query with auto-routing
    result = await memory.query("What am I working on?")

    # Query specific sources
    result = await memory.query(
        "Show billing code",
        sources=[SourceFilter(name="code", project="backend")]
    )

    # Get formatted output for LLM
    markdown = result.to_markdown()
"""

import logging
import time
import uuid
from typing import Any

from .discovery import discover_and_load_all_adapters
from .formatter import ResultFormatter
from .merger import ResultMerger
from .models import AdapterResult, IntentClassification, QueryResult, SourceFilter
from .registry import ADAPTER_MANIFEST, AdapterInfo
from .router import ParallelExecutor, QueryRouter

logger = logging.getLogger(__name__)


class MemoryInterface:
    """
    Unified interface for all memory operations.

    This is the main entry point for the memory abstraction layer.
    It handles:
    - Query routing to appropriate adapters
    - Parallel execution of adapter queries
    - Result merging and formatting
    - WebSocket event emission (optional)
    """

    def __init__(
        self,
        adapters: dict[str, AdapterInfo] | None = None,
        auto_discover: bool = True,
        websocket_server: Any = None,
    ):
        """
        Initialize the memory interface.

        Args:
            adapters: Pre-loaded adapters (if None, will discover)
            auto_discover: Whether to auto-discover adapters
            websocket_server: Optional WebSocket server for events
        """
        self.router = QueryRouter()
        self.merger = ResultMerger()
        self.formatter = ResultFormatter()
        self.executor = ParallelExecutor(timeout=30.0)
        self.websocket_server = websocket_server

        # Discover adapters if not provided
        if adapters is None and auto_discover:
            self._adapters = discover_and_load_all_adapters()
        else:
            self._adapters = adapters or {}

        logger.info(f"MemoryInterface initialized with {len(self._adapters)} adapters")

    async def query(
        self,
        question: str,
        sources: list[SourceFilter | str | dict] | None = None,
        thread_context: list[dict] | None = None,
    ) -> QueryResult:
        """
        Query memory across sources.

        Args:
            question: Natural language question
            sources: Optional source filters. If None, auto-selects based on intent.
            thread_context: Optional thread context for better classification

        Returns:
            QueryResult with items from all queried sources

        Examples:
            # Auto-select sources
            result = await memory.query("What am I working on?")

            # Explicit sources
            result = await memory.query(
                "billing code",
                sources=["code", "slack"]
            )

            # Sources with filters
            result = await memory.query(
                "billing code",
                sources=[
                    SourceFilter(name="code", project="backend"),
                    {"name": "slack", "limit": 3}
                ]
            )
        """
        query_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        # Normalize sources
        normalized_sources = self._normalize_sources(sources)

        # Emit query started event
        await self._emit_query_started(query_id, question, normalized_sources)

        try:
            # Route query to adapters
            intent, adapter_filters = await self.router.route(
                query=question,
                sources=normalized_sources,
                capability="query",
            )

            if not adapter_filters:
                # No adapters available
                result = QueryResult(
                    query=question,
                    intent=intent,
                    sources_queried=[],
                    items=[],
                    total_count=0,
                    latency_ms=(time.time() - start_time) * 1000,
                    errors={"routing": "No adapters available for this query"},
                )
            else:
                # Get adapter instances
                adapters_with_instances = []
                for info, filter in adapter_filters:
                    instance = ADAPTER_MANIFEST.get_instance(info.name)
                    if instance:
                        adapters_with_instances.append((info, filter, instance))

                # Execute queries in parallel
                results = await self.executor.execute(
                    adapters_with_instances,
                    method="query",
                    query=question,
                )

                # Merge results
                result = self.merger.merge(
                    query=question,
                    intent=intent,
                    adapter_results=results,
                )

                result.latency_ms = (time.time() - start_time) * 1000

            # Emit query completed event
            await self._emit_query_completed(query_id, result)

            return result

        except Exception as e:
            logger.error(f"Query failed: {e}", exc_info=True)

            # Return error result
            return QueryResult(
                query=question,
                intent=IntentClassification(
                    intent="error",
                    confidence=0.0,
                    sources_suggested=[],
                ),
                sources_queried=[],
                items=[],
                total_count=0,
                latency_ms=(time.time() - start_time) * 1000,
                errors={"query": str(e)},
            )

    async def search(
        self,
        query: str,
        sources: list[SourceFilter | str | dict] | None = None,
        limit: int = 10,
    ) -> QueryResult:
        """
        Semantic search across sources.

        Similar to query() but uses the "search" capability of adapters.

        Args:
            query: Search query
            sources: Optional source filters
            limit: Maximum results per source

        Returns:
            QueryResult with search results
        """
        # Add limit to all sources
        normalized = self._normalize_sources(sources)
        for source in normalized:
            if source.limit is None:
                source.limit = limit

        # Use search capability
        start_time = time.time()

        intent, adapter_filters = await self.router.route(
            query=query,
            sources=normalized,
            capability="search",
        )

        if not adapter_filters:
            return QueryResult(
                query=query,
                intent=intent,
                sources_queried=[],
                items=[],
                total_count=0,
                latency_ms=(time.time() - start_time) * 1000,
            )

        # Get instances and execute
        adapters_with_instances = []
        for info, filter in adapter_filters:
            instance = ADAPTER_MANIFEST.get_instance(info.name)
            if instance:
                adapters_with_instances.append((info, filter, instance))

        results = await self.executor.execute(
            adapters_with_instances,
            method="search",
            query=query,
        )

        result = self.merger.merge(
            query=query,
            intent=intent,
            adapter_results=results,
        )
        result.latency_ms = (time.time() - start_time) * 1000

        return result

    async def store(
        self,
        key: str,
        value: Any,
        source: str = "yaml",
    ) -> AdapterResult:
        """
        Store data in a memory source.

        Args:
            key: Storage key or path
            value: Data to store
            source: Target source (default "yaml")

        Returns:
            AdapterResult indicating success or error
        """
        instance = ADAPTER_MANIFEST.get_instance(source)
        if not instance:
            return AdapterResult(
                source=source,
                found=False,
                items=[],
                error=f"Adapter not found: {source}",
            )

        info = ADAPTER_MANIFEST.get_adapter(source)
        if not info or "store" not in info.capabilities:
            return AdapterResult(
                source=source,
                found=False,
                items=[],
                error=f"Adapter {source} does not support storage",
            )

        filter = SourceFilter(name=source, key=key)
        return await instance.store(key, value, filter)

    async def learn(
        self,
        learning: str,
        category: str,
        context: dict | None = None,
    ) -> bool:
        """
        Record a learning for future use.

        Args:
            learning: What was learned
            category: Category ("pattern", "fix", "gotcha", "preference")
            context: Optional context (issue key, file path, etc.)

        Returns:
            True if learning was recorded
        """
        # Store in YAML memory
        from datetime import datetime

        entry = {
            "learning": learning,
            "category": category,
            "context": context or {},
            "timestamp": datetime.now().isoformat(),
        }

        # Append to learned patterns
        result = await self.store(
            key="learned/patterns",
            value=entry,
            source="yaml",
        )

        return result.found or not result.error

    def format(self, result: QueryResult) -> str:
        """
        Format QueryResult as LLM-friendly markdown.

        Args:
            result: QueryResult to format

        Returns:
            Markdown string
        """
        return self.formatter.format(result)

    def format_compact(self, result: QueryResult) -> str:
        """
        Format QueryResult in compact form.

        Args:
            result: QueryResult to format

        Returns:
            Compact markdown string
        """
        return self.formatter.format_compact(result)

    def _normalize_sources(
        self,
        sources: list[SourceFilter | str | dict] | None,
    ) -> list[SourceFilter]:
        """Normalize sources to SourceFilter objects."""
        if not sources:
            return []

        result = []
        for source in sources:
            if isinstance(source, str):
                result.append(SourceFilter(name=source))
            elif isinstance(source, dict):
                result.append(SourceFilter.from_dict(source))
            elif isinstance(source, SourceFilter):
                result.append(source)

        return result

    async def _emit_query_started(
        self,
        query_id: str,
        query: str,
        sources: list[SourceFilter],
    ) -> None:
        """Emit WebSocket event when query starts."""
        if not self.websocket_server:
            return

        try:
            await self.websocket_server.broadcast(
                {
                    "type": "memory_query_started",
                    "query_id": query_id,
                    "query": query,
                    "sources": [s.name for s in sources],
                }
            )
        except Exception as e:
            logger.debug(f"Failed to emit query_started: {e}")

    async def _emit_query_completed(
        self,
        query_id: str,
        result: QueryResult,
    ) -> None:
        """Emit WebSocket event when query completes."""
        if not self.websocket_server:
            return

        try:
            await self.websocket_server.broadcast(
                {
                    "type": "memory_query_completed",
                    "query_id": query_id,
                    "intent": result.intent.to_dict(),
                    "sources_queried": result.sources_queried,
                    "result_count": result.total_count,
                    "latency_ms": result.latency_ms,
                }
            )
        except Exception as e:
            logger.debug(f"Failed to emit query_completed: {e}")

    async def health_check(self) -> dict[str, Any]:
        """
        Check health of all adapters.

        Returns:
            Dict with adapter health status
        """
        results = {}

        for name in ADAPTER_MANIFEST.list_adapters():
            instance = ADAPTER_MANIFEST.get_instance(name)
            if not instance:
                results[name] = {"healthy": False, "error": "No instance"}
                continue

            try:
                status = await instance.health_check()
                results[name] = status.to_dict()
            except Exception as e:
                results[name] = {"healthy": False, "error": str(e)}

        return results

    def list_adapters(self) -> list[str]:
        """List all available adapters."""
        return ADAPTER_MANIFEST.list_adapters()

    def get_adapter_info(self, name: str) -> AdapterInfo | None:
        """Get info about a specific adapter."""
        return ADAPTER_MANIFEST.get_adapter(name)


# Singleton instance for easy access
_memory_interface: MemoryInterface | None = None


def get_memory_interface() -> MemoryInterface:
    """
    Get the global MemoryInterface instance.

    Creates one if it doesn't exist.
    """
    global _memory_interface

    if _memory_interface is None:
        _memory_interface = MemoryInterface()

    return _memory_interface


def set_memory_interface(interface: MemoryInterface) -> None:
    """
    Set the global MemoryInterface instance.

    Used by server/main.py to set up the interface with WebSocket.
    """
    global _memory_interface
    _memory_interface = interface
