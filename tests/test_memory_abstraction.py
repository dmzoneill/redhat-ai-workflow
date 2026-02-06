"""
Unit tests for the Memory Abstraction Layer.

Tests cover:
- Models (MemoryItem, QueryResult, IntentClassification, etc.)
- Registry (@memory_adapter decorator, ADAPTER_MANIFEST)
- Classifier (IntentClassifier keyword matching)
- Router (QueryRouter source selection)
- Merger (ResultMerger deduplication and ranking)
- Formatter (ResultFormatter markdown output)
- Interface (MemoryInterface query/search/store)
"""

import asyncio

# Add project root to path
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestModels:
    """Test data models."""

    def test_source_filter_from_dict(self):
        """Test SourceFilter.from_dict()."""
        from services.memory_abstraction.models import SourceFilter

        data = {
            "name": "code",
            "project": "backend",
            "limit": 5,
        }
        filter = SourceFilter.from_dict(data)

        assert filter.name == "code"
        assert filter.project == "backend"
        assert filter.limit == 5

    def test_source_filter_from_string(self):
        """Test SourceFilter.from_string()."""
        from services.memory_abstraction.models import SourceFilter

        filter = SourceFilter.from_string("slack")
        assert filter.name == "slack"
        assert filter.project is None

    def test_memory_item_to_dict(self):
        """Test MemoryItem.to_dict()."""
        from services.memory_abstraction.models import MemoryItem

        item = MemoryItem(
            source="code",
            type="code_snippet",
            relevance=0.85,
            summary="Test function",
            content="def test(): pass",
            metadata={"file_path": "test.py"},
            timestamp=datetime(2025, 1, 15, 10, 30),
        )
        d = item.to_dict()

        assert d["source"] == "code"
        assert d["type"] == "code_snippet"
        assert d["relevance"] == 0.85
        assert d["summary"] == "Test function"
        assert d["content"] == "def test(): pass"
        assert d["metadata"]["file_path"] == "test.py"
        assert d["timestamp"] == "2025-01-15T10:30:00"

    def test_intent_classification(self):
        """Test IntentClassification."""
        from services.memory_abstraction.models import IntentClassification

        intent = IntentClassification(
            intent="code_lookup",
            confidence=0.9,
            sources_suggested=["code", "yaml"],
        )

        assert intent.intent == "code_lookup"
        assert intent.confidence == 0.9
        assert "code" in intent.sources_suggested

    def test_query_result_has_results(self):
        """Test QueryResult.has_results()."""
        from services.memory_abstraction.models import IntentClassification, MemoryItem, QueryResult

        intent = IntentClassification(intent="general", confidence=0.5, sources_suggested=[])

        # Empty result
        result = QueryResult(query="test", intent=intent, items=[])
        assert not result.has_results()

        # With results
        item = MemoryItem(
            source="code",
            type="code_snippet",
            relevance=0.8,
            summary="Test",
            content="test",
        )
        result = QueryResult(query="test", intent=intent, items=[item])
        assert result.has_results()


class TestRegistry:
    """Test adapter registry."""

    def test_memory_adapter_decorator(self):
        """Test @memory_adapter decorator registers adapter."""
        from services.memory_abstraction.registry import ADAPTER_MANIFEST, memory_adapter

        # Clear manifest for test
        ADAPTER_MANIFEST.clear()

        @memory_adapter(
            name="test_adapter",
            display_name="Test Adapter",
            capabilities={"query", "search"},
            intent_keywords=["test", "example"],
            priority=50,
        )
        class TestAdapter:
            async def query(self, question, filter):
                pass

        # Check registration
        info = ADAPTER_MANIFEST.get_adapter("test_adapter")
        assert info is not None
        assert info.name == "test_adapter"
        assert info.display_name == "Test Adapter"
        assert "query" in info.capabilities
        assert "search" in info.capabilities
        assert "test" in info.intent_keywords
        assert info.priority == 50

        # Cleanup
        ADAPTER_MANIFEST.clear()

    def test_adapter_manifest_list_by_capability(self):
        """Test AdapterManifest.list_by_capability()."""
        from services.memory_abstraction.registry import ADAPTER_MANIFEST, memory_adapter

        ADAPTER_MANIFEST.clear()

        @memory_adapter(
            name="query_only",
            display_name="Query Only",
            capabilities={"query"},
            intent_keywords=["query"],
        )
        class QueryOnlyAdapter:
            pass

        @memory_adapter(
            name="query_and_store",
            display_name="Query and Store",
            capabilities={"query", "store"},
            intent_keywords=["store"],
        )
        class QueryAndStoreAdapter:
            pass

        # Check capabilities
        query_adapters = ADAPTER_MANIFEST.list_by_capability("query")
        assert "query_only" in query_adapters
        assert "query_and_store" in query_adapters

        store_adapters = ADAPTER_MANIFEST.list_by_capability("store")
        assert "query_only" not in store_adapters
        assert "query_and_store" in store_adapters

        ADAPTER_MANIFEST.clear()


class TestClassifier:
    """Test intent classifier."""

    def test_keyword_classify_code_lookup(self):
        """Test keyword classification for code lookup."""
        from services.memory_abstraction.classifier import IntentClassifier

        classifier = IntentClassifier()
        result = classifier._keyword_classify("Where is the billing function?")

        assert result.intent == "code_lookup"
        assert result.confidence > 0.5
        assert "code" in result.sources_suggested

    def test_keyword_classify_status_check(self):
        """Test keyword classification for status check."""
        from services.memory_abstraction.classifier import IntentClassifier

        classifier = IntentClassifier()
        result = classifier._keyword_classify("What am I working on?")

        assert result.intent == "status_check"
        assert "yaml" in result.sources_suggested

    def test_keyword_classify_troubleshooting(self):
        """Test keyword classification for troubleshooting."""
        from services.memory_abstraction.classifier import IntentClassifier

        classifier = IntentClassifier()
        result = classifier._keyword_classify("Why is the deployment failing?")

        assert result.intent == "troubleshooting"
        assert result.confidence > 0.5

    def test_keyword_classify_general(self):
        """Test keyword classification falls back to general."""
        from services.memory_abstraction.classifier import IntentClassifier

        classifier = IntentClassifier()
        result = classifier._keyword_classify("Hello world")

        assert result.intent == "general"


class TestMerger:
    """Test result merger."""

    def test_merge_empty(self):
        """Test merging empty results."""
        from services.memory_abstraction.merger import ResultMerger
        from services.memory_abstraction.models import IntentClassification

        merger = ResultMerger()
        intent = IntentClassification(intent="general", confidence=0.5, sources_suggested=[])

        result = merger.merge(
            query="test",
            intent=intent,
            adapter_results=[],
        )

        assert result.query == "test"
        assert not result.has_results()

    def test_merge_with_results(self):
        """Test merging results from multiple adapters."""
        from services.memory_abstraction.merger import ResultMerger
        from services.memory_abstraction.models import AdapterResult, IntentClassification, MemoryItem

        merger = ResultMerger()
        intent = IntentClassification(intent="code_lookup", confidence=0.8, sources_suggested=["code"])

        item1 = MemoryItem(
            source="code",
            type="code_snippet",
            relevance=0.9,
            summary="High relevance",
            content="test1",
        )
        item2 = MemoryItem(
            source="yaml",
            type="state",
            relevance=0.5,
            summary="Low relevance",
            content="test2",
        )

        adapter_results = [
            ("code", AdapterResult(source="code", found=True, items=[item1])),
            ("yaml", AdapterResult(source="yaml", found=True, items=[item2])),
        ]

        result = merger.merge(
            query="test",
            intent=intent,
            adapter_results=adapter_results,
        )

        assert result.has_results()
        assert result.total_count == 2
        # Should be sorted by relevance (highest first)
        assert result.items[0].relevance >= result.items[1].relevance

    def test_merge_with_errors(self):
        """Test merging handles errors gracefully."""
        from services.memory_abstraction.merger import ResultMerger
        from services.memory_abstraction.models import AdapterResult, IntentClassification

        merger = ResultMerger()
        intent = IntentClassification(intent="general", confidence=0.5, sources_suggested=[])

        adapter_results = [
            ("code", Exception("Connection failed")),
            ("yaml", AdapterResult(source="yaml", found=False, items=[], error="File not found")),
        ]

        result = merger.merge(
            query="test",
            intent=intent,
            adapter_results=adapter_results,
        )

        assert "code" in result.errors
        assert "yaml" in result.errors


class TestFormatter:
    """Test result formatter."""

    def test_format_empty(self):
        """Test formatting empty results."""
        from services.memory_abstraction.formatter import ResultFormatter
        from services.memory_abstraction.models import IntentClassification, QueryResult

        formatter = ResultFormatter()
        intent = IntentClassification(intent="general", confidence=0.5, sources_suggested=[])
        result = QueryResult(query="test", intent=intent, items=[])

        output = formatter.format(result)

        assert "No results found" in output
        assert "Query Analysis" in output

    def test_format_with_results(self):
        """Test formatting results."""
        from services.memory_abstraction.formatter import ResultFormatter
        from services.memory_abstraction.models import IntentClassification, MemoryItem, QueryResult

        formatter = ResultFormatter()
        intent = IntentClassification(
            intent="code_lookup",
            confidence=0.85,
            sources_suggested=["code"],
        )
        item = MemoryItem(
            source="code",
            type="code_snippet",
            relevance=0.9,
            summary="Test function",
            content="def test(): pass",
            metadata={"file_path": "test.py", "start_line": 1, "end_line": 1},
        )
        result = QueryResult(
            query="test",
            intent=intent,
            sources_queried=["code"],
            items=[item],
            total_count=1,
        )

        output = formatter.format(result)

        assert "Query Analysis" in output
        assert "code_lookup" in output
        assert "Code Search" in output
        assert "Test function" in output

    def test_format_compact(self):
        """Test compact formatting."""
        from services.memory_abstraction.formatter import ResultFormatter
        from services.memory_abstraction.models import IntentClassification, MemoryItem, QueryResult

        formatter = ResultFormatter()
        intent = IntentClassification(intent="general", confidence=0.5, sources_suggested=[])
        item = MemoryItem(
            source="code",
            type="code_snippet",
            relevance=0.8,
            summary="Test",
            content="test",
        )
        result = QueryResult(
            query="test",
            intent=intent,
            items=[item],
            total_count=1,
        )

        output = formatter.format_compact(result)

        assert "Intent" in output
        assert "[code]" in output


class TestInterface:
    """Test MemoryInterface."""

    @pytest.mark.asyncio
    async def test_query_no_adapters(self):
        """Test query with no adapters available."""
        from services.memory_abstraction.interface import MemoryInterface

        # Create interface with no adapters
        memory = MemoryInterface(adapters={}, auto_discover=False)

        result = await memory.query("test query")

        assert not result.has_results()
        assert "routing" in result.errors or len(result.sources_queried) == 0

    @pytest.mark.asyncio
    async def test_format_result(self):
        """Test format() method."""
        from services.memory_abstraction.interface import MemoryInterface
        from services.memory_abstraction.models import IntentClassification, QueryResult

        memory = MemoryInterface(adapters={}, auto_discover=False)

        intent = IntentClassification(intent="general", confidence=0.5, sources_suggested=[])
        result = QueryResult(query="test", intent=intent, items=[])

        output = memory.format(result)
        assert "Query Analysis" in output

    def test_list_adapters_empty(self):
        """Test list_adapters() with no adapters."""
        from services.memory_abstraction.interface import MemoryInterface

        memory = MemoryInterface(adapters={}, auto_discover=False)
        adapters = memory.list_adapters()

        assert adapters == []


class TestDiscovery:
    """Test adapter discovery."""

    def test_discover_adapter_modules(self):
        """Test discovering adapter modules."""
        from services.memory_abstraction.discovery import clear_discovery_cache, discover_adapter_modules

        # Clear cache to force fresh discovery
        clear_discovery_cache()

        modules = discover_adapter_modules()

        # Should find at least the adapters we created
        # (memory_yaml, code_search, slack_persona, inscope, jira)
        assert isinstance(modules, set)
        # Don't assert specific modules since they depend on file system state


class TestAdapterProtocol:
    """Test adapter protocol."""

    def test_base_adapter_defaults(self):
        """Test BaseAdapter default implementations."""
        from services.memory_abstraction.adapter_protocol import BaseAdapter

        adapter = BaseAdapter()

        # Should have default implementations
        assert hasattr(adapter, "query")
        assert hasattr(adapter, "search")
        assert hasattr(adapter, "store")
        assert hasattr(adapter, "health_check")

    @pytest.mark.asyncio
    async def test_base_adapter_store_readonly(self):
        """Test BaseAdapter.store() returns read-only error."""
        from services.memory_abstraction.adapter_protocol import BaseAdapter

        adapter = BaseAdapter()
        result = await adapter.store("key", "value")

        assert result.error is not None
        assert "read-only" in result.error.lower()


# Run tests with: pytest tests/test_memory_abstraction.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
