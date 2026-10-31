"""
Semantic code search tools using local vector embeddings.

This module provides tools for:
- Indexing code into a local vector database (LanceDB)
- Semantic search across indexed code
- Deep knowledge scanning with Claude analysis
- Automatic index updates via file watcher

Uses LanceDB (embedded, serverless) + sentence-transformers (local embeddings).

Performance Optimizations:
- IVF-PQ indexing for fast approximate nearest neighbor search
- Query embedding cache with LRU + TTL
- Configurable nprobes for speed/accuracy tradeoff
- Optional OpenVINO/NPU acceleration

The implementation lives in the ``cs_*`` modules; this module registers the MCP
tools and re-exports the helpers other modules import from here.
"""

from typing import Any

from mcp.types import TextContent

from tool_modules.aa_code_search.src.cs_chunking import (
    _chunk_by_size,
    _chunk_code_simple,
    _chunk_python_code,
    _get_language,
    _should_index_file,
)
from tool_modules.aa_code_search.src.cs_config import (
    _INDEX_ERRORS,
    AUTO_UPDATE_ON_SEARCH,
    CACHE_ENABLED,
    CACHE_MAX_SIZE,
    CACHE_TTL_SECONDS,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_NPROBES,
    EMBEDDING_DIM,
    INDEX_STALE_MINUTES,
    INDEX_TYPE,
    NUM_PARTITIONS,
    NUM_SUB_VECTORS,
    VECTOR_DB_PATH,
    _compute_file_hash,
    _get_project_path,
    _get_table_name,
    _get_vector_search_config,
    _load_config,
    _now,
    _parse_timestamp,
)
from tool_modules.aa_code_search.src.cs_embeddings import (
    EmbeddingCache,
    _embedding_cache,
    _get_cached_embedding,
    _get_embedding_model,
    _get_lance_db,
    _get_lancedb,
)
from tool_modules.aa_code_search.src.cs_index import _auto_update_if_stale, _index_project, _is_index_stale
from tool_modules.aa_code_search.src.cs_search import (
    _get_index_stats,
    _search_code,
    _update_search_stats,
    get_all_vector_stats,
    get_vector_health,
)
from tool_modules.aa_code_search.src.cs_tool_impls import (
    _code_cache_impl,
    _code_compact_impl,
    _code_health_impl,
    _code_index_impl,
    _code_search_impl,
    _code_stats_impl,
    _code_watch_all_impl,
    _code_watch_impl,
    _knowledge_deep_scan_impl,
)

__all__ = [
    "AUTO_UPDATE_ON_SEARCH",
    "CACHE_ENABLED",
    "CACHE_MAX_SIZE",
    "CACHE_TTL_SECONDS",
    "CHUNK_OVERLAP",
    "CHUNK_SIZE",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_NPROBES",
    "EMBEDDING_DIM",
    "INDEX_STALE_MINUTES",
    "INDEX_TYPE",
    "NUM_PARTITIONS",
    "NUM_SUB_VECTORS",
    "VECTOR_DB_PATH",
    "_INDEX_ERRORS",
    "EmbeddingCache",
    "_auto_update_if_stale",
    "_chunk_by_size",
    "_chunk_code_simple",
    "_chunk_python_code",
    "_code_cache_impl",
    "_code_compact_impl",
    "_code_health_impl",
    "_code_index_impl",
    "_code_search_impl",
    "_code_stats_impl",
    "_code_watch_all_impl",
    "_code_watch_impl",
    "_compute_file_hash",
    "_embedding_cache",
    "_get_cached_embedding",
    "_get_embedding_model",
    "_get_index_stats",
    "_get_lance_db",
    "_get_lancedb",
    "_get_language",
    "_get_project_path",
    "_get_table_name",
    "_get_vector_search_config",
    "_index_project",
    "_is_index_stale",
    "_knowledge_deep_scan_impl",
    "_load_config",
    "_now",
    "_parse_timestamp",
    "_search_code",
    "_should_index_file",
    "_update_search_stats",
    "get_all_vector_stats",
    "get_vector_health",
    "register_tools",
]


def register_tools(registry: Any) -> None:
    """Register code search tools with the MCP registry."""

    @registry.tool()
    async def code_index(
        project: str = "",
        force: bool = False,
    ) -> list[TextContent]:
        """
        Index a project's code into the vector database for semantic search.

        This creates embeddings for all code files and stores them locally.
        Subsequent searches will be fast and semantic (meaning-based).

        Args:
            project: Project name from config.json. Auto-detects if empty.
            force: If True, re-index all files. Otherwise only index changed files.

        Returns:
            Indexing statistics.

        Example:
            code_index("automation-analytics-backend")
            code_index("automation-analytics-backend", force=True)  # Full re-index
        """
        return await _code_index_impl(project=project, force=force)

    @registry.tool()
    async def code_search(
        query: str,
        project: str = "",
        limit: int = 10,
        file_filter: str = "",
        type_filter: str = "",
    ) -> list[TextContent]:
        """
        Semantic search across indexed code.

        Finds code by meaning, not just exact text matches. Great for questions like:
        - "Where do we handle billing calculations?"
        - "How is user authentication implemented?"
        - "What validates API input?"

        Args:
            query: Natural language query describing what you're looking for.
            project: Project name. Auto-detects if only one project configured.
            limit: Maximum results to return (default 10).
            file_filter: Filter to specific file path pattern (e.g., "billing/").
            type_filter: Filter by code type: "function", "class", "module".

        Returns:
            Matching code chunks ranked by relevance.

        Example:
            code_search("How does billing calculate vCPU hours?", "automation-analytics-backend")
            code_search("error handling", project="backend", file_filter="api/")
        """
        return await _code_search_impl(
            query=query, project=project, limit=limit, file_filter=file_filter, type_filter=type_filter
        )

    @registry.tool()
    async def code_stats(
        project: str = "",
    ) -> list[TextContent]:
        """
        Get comprehensive statistics about indexed code.

        Shows indexing status, disk usage, search stats, and watcher status.

        Args:
            project: Project name. Lists all if empty.

        Returns:
            Detailed indexing and search statistics.
        """
        return await _code_stats_impl(project=project)

    @registry.tool()
    async def code_compact(
        project: str = "",
    ) -> list[TextContent]:
        """
        Optimize vector database files to reduce disk usage.

        LanceDB creates new fragment files on each write/update. Over time this
        causes significant disk bloat (can grow to GB). This tool merges fragments
        and removes old versions.

        Args:
            project: Project name. If empty, optimizes all projects.

        Returns:
            Optimization statistics showing space saved.

        Example:
            code_compact("redhat-ai-workflow")  # Optimize single project
            code_compact()  # Optimize all projects
        """
        return await _code_compact_impl(project=project)

    @registry.tool()
    async def knowledge_deep_scan(
        project: str,
        update_memory: bool = True,
    ) -> list[TextContent]:
        """
        Deep scan a project using vector search + Claude analysis.

        This tool:
        1. Ensures the project is indexed
        2. Uses semantic search to find key patterns
        3. Returns structured findings for Claude to analyze
        4. Optionally updates knowledge memory with findings

        Args:
            project: Project name from config.json.
            update_memory: If True, update knowledge memory with findings.

        Returns:
            Deep scan results with architecture, patterns, and gotchas.

        Example:
            knowledge_deep_scan("automation-analytics-backend")
        """
        return await _knowledge_deep_scan_impl(project=project, update_memory=update_memory)

    @registry.tool()
    async def code_watch(
        project: str = "",
        action: str = "start",
        debounce_seconds: float = 5.0,
    ) -> list[TextContent]:
        """
        Start or stop automatic index updates for a project.

        The watcher monitors file changes and automatically re-indexes
        after a quiet period (debounce). This keeps the index fresh
        without manual intervention.

        Args:
            project: Project name from config.json. Required for start/stop.
            action: "start", "stop", or "status"
            debounce_seconds: Wait this long after last change before re-indexing (default 5s)

        Returns:
            Watcher status.

        Example:
            code_watch("automation-analytics-backend", "start")
            code_watch("automation-analytics-backend", "stop")
            code_watch(action="status")  # Show all watchers
        """
        return await _code_watch_impl(project=project, action=action, debounce_seconds=debounce_seconds)

    @registry.tool()
    async def code_watch_all(
        action: str = "start",
        debounce_seconds: float = 5.0,
    ) -> list[TextContent]:
        """
        Start or stop watchers for all configured projects.

        Args:
            action: "start" or "stop"
            debounce_seconds: Wait time before re-indexing (default 5s)

        Returns:
            Status of all watchers.
        """
        return await _code_watch_all_impl(action=action, debounce_seconds=debounce_seconds)

    @registry.tool()
    async def code_health() -> list[TextContent]:
        """
        Get health status and performance metrics for vector search.

        Shows:
        - Overall health status
        - Performance metrics (search times, cache hit rates)
        - Issues and recommendations
        - Index configuration

        Returns:
            Health dashboard with actionable recommendations.

        Example:
            code_health()
        """
        return await _code_health_impl()

    @registry.tool()
    async def code_cache(
        action: str = "stats",
    ) -> list[TextContent]:
        """
        Manage the query embedding cache.

        The cache stores query embeddings to speed up repeated searches.

        Args:
            action: "stats" (show cache stats) or "clear" (clear the cache)

        Returns:
            Cache status or confirmation of clear.

        Example:
            code_cache()  # Show stats
            code_cache("clear")  # Clear cache
        """
        return await _code_cache_impl(action=action)
