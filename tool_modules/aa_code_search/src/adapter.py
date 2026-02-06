"""
Code Search Adapter - Memory source for semantic code search.

This adapter exposes the code search functionality as a memory source,
allowing the memory abstraction layer to query code semantically.

It wraps the existing code search tool implementations.
"""

import logging
from typing import Any

from services.memory_abstraction.models import (
    AdapterResult,
    HealthStatus,
    MemoryItem,
    SourceFilter,
)
from services.memory_abstraction.registry import memory_adapter

logger = logging.getLogger(__name__)


@memory_adapter(
    name="code",
    display_name="Code Search",
    capabilities={"query", "search"},
    intent_keywords=[
        "function",
        "class",
        "method",
        "implementation",
        "code",
        "where is",
        "how does",
        "show me",
        "find",
        "search code",
        "definition",
        "usage",
        "import",
    ],
    priority=60,
    latency_class="fast",  # Local vector search
)
class CodeSearchAdapter:
    """
    Adapter for semantic code search.

    Wraps the existing code_search tool functionality for use
    by the memory abstraction layer.
    """

    async def query(
        self,
        question: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """
        Query code using semantic search.

        Args:
            question: Natural language question about code
            filter: Optional filter with project and limit

        Returns:
            AdapterResult with matching code snippets
        """
        try:
            # Import the existing code search implementation
            from tool_modules.aa_code_search.src.tools_basic import (
                _get_index_stats,
                _search_code,
            )

            # Get parameters from filter
            project = filter.project if filter else None
            limit = (filter.limit if filter and filter.limit else None) or 5

            # Default project
            if not project:
                project = "automation-analytics-backend"

            # Check if project is indexed
            stats = _get_index_stats(project)
            if not stats.get("indexed"):
                return AdapterResult(
                    source="code",
                    found=False,
                    items=[],
                    error=f"Project '{project}' is not indexed. Run code_index first.",
                )

            # Perform search
            results = _search_code(
                query=question,
                project=project,
                limit=limit,
                auto_update=False,
            )

            if not results or (results and "error" in results[0]):
                error = results[0].get("error") if results else "No results"
                return AdapterResult(
                    source="code",
                    found=False,
                    items=[],
                    error=error,
                )

            # Convert to MemoryItems
            items = [self._to_memory_item(r) for r in results]

            return AdapterResult(
                source="code",
                found=True,
                items=items,
            )

        except ImportError as e:
            logger.error(f"Code search module not available: {e}")
            return AdapterResult(
                source="code",
                found=False,
                items=[],
                error="Code search module not available",
            )
        except Exception as e:
            logger.error(f"Code search failed: {e}")
            return AdapterResult(
                source="code",
                found=False,
                items=[],
                error=str(e),
            )

    async def search(
        self,
        query: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Semantic search (same as query for code)."""
        return await self.query(query, filter)

    async def store(
        self,
        key: str,
        value: Any,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Code search is read-only."""
        return AdapterResult(
            source="code",
            found=False,
            items=[],
            error="Code search is read-only. Use code_index to update the index.",
        )

    async def health_check(self) -> HealthStatus:
        """Check if code search is healthy."""
        try:
            from tool_modules.aa_code_search.src.tools_basic import _get_index_stats

            # Check default project
            stats = _get_index_stats("automation-analytics-backend")

            return HealthStatus(
                healthy=True,
                details={
                    "indexed": stats.get("indexed", False),
                    "vector_count": stats.get("vector_count", 0),
                    "last_updated": stats.get("last_updated"),
                },
            )
        except ImportError:
            return HealthStatus(
                healthy=False,
                error="Code search module not available",
            )
        except Exception as e:
            return HealthStatus(healthy=False, error=str(e))

    def _to_memory_item(self, result: dict) -> MemoryItem:
        """Convert code search result to MemoryItem."""
        file_path = result.get("file_path", "")
        name = result.get("name", "unknown")
        start_line = result.get("start_line", 0)
        end_line = result.get("end_line", 0)

        # Build summary
        if start_line and end_line:
            summary = f"{name} in {file_path}:{start_line}-{end_line}"
        else:
            summary = f"{name} in {file_path}"

        return MemoryItem(
            source="code",
            type="code_snippet",
            relevance=result.get("similarity", 0.0),
            summary=summary,
            content=result.get("content", ""),
            metadata={
                "file_path": file_path,
                "start_line": start_line,
                "end_line": end_line,
                "type": result.get("type", "unknown"),
                "name": name,
                "language": self._infer_language(file_path),
            },
        )

    def _infer_language(self, file_path: str) -> str:
        """Infer programming language from file path."""
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".rb": "ruby",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".json": "json",
            ".md": "markdown",
            ".sh": "bash",
            ".sql": "sql",
        }

        for ext, lang in ext_map.items():
            if file_path.endswith(ext):
                return lang

        return ""
