"""
Result Merger - Combine results from multiple memory adapters.

This module handles merging results from multiple adapter queries
into a single QueryResult, with:

1. Deduplication of similar items
2. Relevance-based ranking
3. Source attribution
4. Error aggregation

Usage:
    from services.memory_abstraction.merger import ResultMerger

    merger = ResultMerger()
    result = merger.merge(
        query="billing code",
        intent=intent_classification,
        adapter_results=[result1, result2, result3]
    )
"""

import logging

from .models import AdapterResult, IntentClassification, MemoryItem, QueryResult

logger = logging.getLogger(__name__)


class ResultMerger:
    """
    Merge results from multiple adapters into a single QueryResult.

    Handles deduplication, ranking, and error aggregation.
    """

    def __init__(
        self,
        max_items: int = 20,
        dedup_threshold: float = 0.9,
    ):
        """
        Initialize the merger.

        Args:
            max_items: Maximum items to include in result
            dedup_threshold: Similarity threshold for deduplication (0-1)
        """
        self.max_items = max_items
        self.dedup_threshold = dedup_threshold

    def merge(
        self,
        query: str,
        intent: IntentClassification,
        adapter_results: list[tuple[str, AdapterResult | Exception]],
        strategy: str = "relevance",
    ) -> QueryResult:
        """
        Merge results from multiple adapters.

        Args:
            query: Original query
            intent: Intent classification
            adapter_results: List of (adapter_name, AdapterResult or Exception)
            strategy: Merge strategy ("relevance", "recency", "source_priority")

        Returns:
            Merged QueryResult
        """
        all_items: list[MemoryItem] = []
        sources_queried: list[str] = []
        errors: dict[str, str] = {}
        total_latency = 0.0

        for name, result in adapter_results:
            sources_queried.append(name)

            if isinstance(result, Exception):
                errors[name] = str(result)
                continue

            if result.error:
                errors[name] = result.error
                continue

            total_latency += result.latency_ms
            all_items.extend(result.items)

        # Deduplicate
        deduped_items = self._deduplicate(all_items)

        # Sort by strategy
        sorted_items = self._sort_items(deduped_items, strategy, intent)

        # Truncate to max items
        final_items = sorted_items[: self.max_items]

        return QueryResult(
            query=query,
            intent=intent,
            sources_queried=sources_queried,
            items=final_items,
            total_count=len(deduped_items),
            latency_ms=total_latency,
            errors=errors,
        )

    def _deduplicate(self, items: list[MemoryItem]) -> list[MemoryItem]:
        """
        Remove duplicate or very similar items.

        Uses content similarity to detect duplicates.
        """
        if not items:
            return []

        unique: list[MemoryItem] = []
        seen_hashes: set[str] = set()

        for item in items:
            # Create a simple hash of the content
            content_hash = self._content_hash(item)

            if content_hash in seen_hashes:
                continue

            # Check for similar content (more expensive)
            is_duplicate = False
            for existing in unique:
                if self._is_similar(item, existing):
                    # Keep the one with higher relevance
                    if item.relevance > existing.relevance:
                        unique.remove(existing)
                        unique.append(item)
                    is_duplicate = True
                    break

            if not is_duplicate:
                unique.append(item)
                seen_hashes.add(content_hash)

        return unique

    def _content_hash(self, item: MemoryItem) -> str:
        """Create a simple hash of item content."""
        import hashlib

        # Use summary + first 100 chars of content
        key = f"{item.source}:{item.summary}:{item.content[:100]}"
        return hashlib.md5(key.encode()).hexdigest()[:16]

    def _is_similar(self, item1: MemoryItem, item2: MemoryItem) -> bool:
        """
        Check if two items are similar enough to be duplicates.

        Uses simple string similarity for now.
        """
        # Different sources are not duplicates
        if item1.source != item2.source:
            return False

        # Same type required
        if item1.type != item2.type:
            return False

        # Check content similarity
        content1 = item1.content[:200].lower()
        content2 = item2.content[:200].lower()

        # Simple overlap check
        words1 = set(content1.split())
        words2 = set(content2.split())

        if not words1 or not words2:
            return False

        overlap = len(words1 & words2) / max(len(words1), len(words2))
        return overlap >= self.dedup_threshold

    def _sort_items(
        self,
        items: list[MemoryItem],
        strategy: str,
        intent: IntentClassification,
    ) -> list[MemoryItem]:
        """
        Sort items by the specified strategy.

        Strategies:
        - relevance: Sort by relevance score (default)
        - recency: Sort by timestamp (newest first)
        - source_priority: Sort by source priority, then relevance
        """
        if strategy == "recency":
            return sorted(
                items, key=lambda x: (x.timestamp or 0, x.relevance), reverse=True
            )

        elif strategy == "source_priority":
            # Boost items from sources suggested by intent
            suggested = set(intent.sources_suggested)

            def priority_key(item: MemoryItem) -> tuple:
                source_boost = 1.0 if item.source in suggested else 0.0
                return (source_boost, item.relevance)

            return sorted(items, key=priority_key, reverse=True)

        else:  # relevance (default)
            return sorted(items, key=lambda x: x.relevance, reverse=True)

    def merge_single(
        self,
        query: str,
        intent: IntentClassification,
        result: AdapterResult,
    ) -> QueryResult:
        """
        Convenience method to wrap a single adapter result.

        Useful when only one adapter is queried.
        """
        return self.merge(
            query=query,
            intent=intent,
            adapter_results=[(result.source, result)],
        )
