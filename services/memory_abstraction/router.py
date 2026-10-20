# pylint: disable=cyclic-import,duplicate-code
"""
Query Router - Route queries to appropriate memory adapters.

This module handles the routing of queries to the appropriate memory
source adapters based on:

1. Explicit source filters (user-specified)
2. Intent classification (automatic routing)
3. Adapter capabilities and priorities

Usage:
    from services.memory_abstraction.router import QueryRouter

    router = QueryRouter()

    # Route with explicit sources
    adapters = await router.route(
        query="billing code",
        sources=[SourceFilter(name="code", project="backend")]
    )

    # Route with auto-detection
    adapters = await router.route(query="What am I working on?")
"""

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

from .classifier import IntentClassifier
from .models import IntentClassification, SourceFilter
from .registry import ADAPTER_MANIFEST, AdapterInfo

logger = logging.getLogger(__name__)


class QueryRouter:
    """
    Route queries to appropriate memory adapters.

    The router determines which adapters should handle a query based on:
    1. Explicit source filters provided by the user
    2. Intent classification for automatic routing
    3. Adapter capabilities and health status
    """

    def __init__(self):
        self.classifier = IntentClassifier()
        self._health_cache: dict[str, bool] = {}
        self._health_cache_ttl = 60  # seconds
        self._last_health_check = 0.0

    async def route(
        self,
        query: str,
        sources: Sequence[SourceFilter | str] | None = None,
        capability: str = "query",
    ) -> tuple[IntentClassification, list[tuple[AdapterInfo, SourceFilter]]]:
        """
        Route a query to appropriate adapters.

        Args:
            query: The query to route
            sources: Optional explicit source filters. If None, auto-detect.
            capability: Required capability ("query", "search", "store")

        Returns:
            Tuple of (IntentClassification, list of (AdapterInfo, SourceFilter) pairs)
        """
        # Classify intent (always done for context)
        intent = await self.classifier.classify(query)

        # Normalize sources to SourceFilter objects
        if sources:
            filters = self._normalize_sources(sources)
            adapters = await self._route_explicit(filters, capability)
        else:
            adapters = await self._route_by_intent(intent, capability)

        logger.debug(
            "Routed query to %s adapters: %s",
            len(adapters),
            [a[0].name for a in adapters],
        )

        return intent, adapters

    async def _route_explicit(
        self,
        filters: list[SourceFilter],
        capability: str,
    ) -> list[tuple[AdapterInfo, SourceFilter]]:
        """Route to explicitly specified sources."""
        result = []

        for source_filter in filters:
            info = ADAPTER_MANIFEST.get_adapter(source_filter.name)
            if not info:
                logger.warning("Unknown adapter: %s", source_filter.name)
                continue

            if capability not in info.capabilities:
                logger.warning(
                    "Adapter %s doesn't support %s", source_filter.name, capability
                )
                continue

            # Check health (cached)
            if not await self._is_healthy(source_filter.name):
                logger.warning("Adapter %s is unhealthy, skipping", source_filter.name)
                continue

            result.append((info, source_filter))

        return result

    async def _route_by_intent(
        self,
        intent: IntentClassification,
        capability: str,
    ) -> list[tuple[AdapterInfo, SourceFilter]]:
        """Route based on intent classification."""
        result = []

        # Get suggested sources from intent
        suggested = intent.sources_suggested

        if not suggested:
            # Fall back to all adapters with the capability
            suggested = ADAPTER_MANIFEST.list_by_capability(capability)

        for source_name in suggested:
            info = ADAPTER_MANIFEST.get_adapter(source_name)
            if not info:
                continue

            if capability not in info.capabilities:
                continue

            # Check health (cached)
            if not await self._is_healthy(source_name):
                continue

            # Create default filter for this source
            source_filter = SourceFilter(name=source_name)
            result.append((info, source_filter))

        # Sort by priority (highest first)
        result.sort(key=lambda x: x[0].priority, reverse=True)

        return result

    def _normalize_sources(
        self,
        sources: Sequence[SourceFilter | str],
    ) -> list[SourceFilter]:
        """Normalize sources to SourceFilter objects."""
        result = []

        for source in sources:
            if isinstance(source, str):
                result.append(SourceFilter(name=source))
            elif isinstance(source, dict):
                result.append(SourceFilter.from_dict(source))
            elif isinstance(source, SourceFilter):
                result.append(source)
            else:
                logger.warning("Unknown source type: %s", type(source))

        return result

    async def _is_healthy(self, adapter_name: str) -> bool:
        """
        Check if an adapter is healthy (cached).

        Health checks are cached to avoid repeated checks.
        """
        # pylint: disable-next=import-outside-toplevel
        import time

        now = time.time()

        # Refresh cache if expired
        if now - self._last_health_check > self._health_cache_ttl:
            self._health_cache.clear()
            self._last_health_check = now

        # Check cache
        if adapter_name in self._health_cache:
            return self._health_cache[adapter_name]

        # Perform health check
        instance = ADAPTER_MANIFEST.get_instance(adapter_name)
        if not instance:
            self._health_cache[adapter_name] = False
            return False

        try:
            status = await instance.health_check()
            healthy = status.healthy
        # Best-effort: log and continue.
        # pylint: disable-next=broad-exception-caught
        except Exception as e:
            logger.warning("Health check failed for %s: %s", adapter_name, e)
            healthy = False

        self._health_cache[adapter_name] = healthy
        return healthy

    async def get_all_healthy_adapters(
        self,
        capability: str = "query",
    ) -> list[AdapterInfo]:
        """Get all healthy adapters with a specific capability."""
        adapters = []

        for name in ADAPTER_MANIFEST.list_by_capability(capability):
            if await self._is_healthy(name):
                info = ADAPTER_MANIFEST.get_adapter(name)
                if info:
                    adapters.append(info)

        return adapters

    def clear_health_cache(self) -> None:
        """Clear the health check cache."""
        self._health_cache.clear()
        self._last_health_check = 0.0


# pylint: disable-next=too-few-public-methods
class ParallelExecutor:
    """
    Execute adapter queries in parallel.

    Handles concurrent execution of multiple adapter queries
    with timeout and error handling.
    """

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    async def execute(
        self,
        adapters: list[tuple[AdapterInfo, SourceFilter, Any]],
        method: str,
        query: str,
    ) -> list[tuple[str, Any]]:
        """
        Execute a method on multiple adapters in parallel.

        Args:
            adapters: List of (AdapterInfo, SourceFilter, adapter_instance) tuples
            method: Method to call ("query", "search", "store")
            query: Query string to pass

        Returns:
            List of (adapter_name, result) tuples
        """
        if not adapters:
            return []

        tasks = []
        for info, source_filter, instance in adapters:
            task = self._execute_one(info.name, instance, method, query, source_filter)
            tasks.append(task)

        # Execute with timeout
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            logger.warning("Parallel execution timed out after %ss", self.timeout)
            results = [TimeoutError(f"Timeout after {self.timeout}s")] * len(tasks)

        # Pair results with adapter names
        output: list[tuple[str, Any]] = []
        for i, result in enumerate(results):
            name = adapters[i][0].name
            if isinstance(result, Exception):
                logger.warning("Adapter %s failed: %s", name, result)
                output.append((name, result))
            else:
                output.append((name, result))

        return output

    async def _execute_one(
        self,
        name: str,
        instance: Any,
        method: str,
        query: str,
        source_filter: SourceFilter,
    ) -> Any:
        """Execute a single adapter query."""
        # pylint: disable-next=import-outside-toplevel
        import time

        start = time.time()

        try:
            func = getattr(instance, method)
            result = await func(query, source_filter)

            # Add latency to result if it's an AdapterResult
            if hasattr(result, "latency_ms"):
                result.latency_ms = (time.time() - start) * 1000

            return result

        except Exception as e:
            logger.error("Adapter %s.%s() failed: %s", name, method, e)
            raise
