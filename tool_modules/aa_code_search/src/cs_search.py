"""Semantic search over a project's index, and index/search statistics."""

import json
import logging
import time
from datetime import timedelta
from typing import Any, TypedDict, Unpack

from tool_modules.aa_code_search.src import cs_config
from tool_modules.aa_code_search.src.cs_config import (
    _INDEX_ERRORS,
    CACHE_ENABLED,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_NPROBES,
    INDEX_STALE_MINUTES,
    INDEX_TYPE,
    _format_size,
    _get_table_name,
    _get_vector_search_config,
    _load_config,
    _now,
    _parse_timestamp,
)
from tool_modules.aa_code_search.src.cs_embeddings import (
    _embedding_cache,
    _get_cached_embedding,
    _get_embedding_model,
    _get_lance_db,
)
from tool_modules.aa_code_search.src.cs_index import _auto_update_if_stale
from tool_modules.aa_code_search.src.watcher import get_watcher

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS = frozenset({"file_path", "type", "content", "start_line", "end_line", "name", "language"})

_EMPTY_SEARCH_STATS = {
    "total_searches": 0,
    "total_search_time_ms": 0,
    "last_search": None,
    "avg_search_time_ms": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "avg_embed_time_ms": 0,
    "avg_vector_search_time_ms": 0,
}


class SearchOptions(TypedDict, total=False):
    """Optional keyword arguments of :func:`_search_code`."""

    file_filter: str  # Filter by file path pattern
    type_filter: str  # Filter by code type (function, class, etc.)
    auto_update: bool  # Auto-update stale indexes (default True)
    nprobes: int | None  # Partitions to search; default from config or DEFAULT_NPROBES


def _run_vector_query(table: Any, query_embedding: list[float], limit: int, nprobes: int) -> Any:
    """Run the ANN query and return a DataFrame (raises on corrupted/empty indexes)."""
    search_query = table.search(query_embedding).limit(limit * 2)
    try:
        search_query = search_query.nprobes(nprobes)
    except (AttributeError, TypeError) as exc:
        # nprobes not supported (FLAT index or old LanceDB version)
        logger.debug("Suppressed error: %s", exc)
    return search_query.to_pandas()


def _apply_filters(results: Any, file_filter: str, type_filter: str) -> Any:
    """Filter results by file path substring and chunk type; unfiltered if filtering fails."""
    try:
        if file_filter:
            results = results[results["file_path"].str.contains(file_filter, case=False)]
        if type_filter:
            results = results[results["type"] == type_filter]
    # Intentional: log the failure and continue at this boundary.
    except _INDEX_ERRORS as e:
        logger.warning("Filter application failed: %s", e)
    return results


def _format_results(results: Any) -> list[dict]:
    """Convert result rows to dicts with a 0-1 similarity score."""
    formatted = []
    for _, row in results.iterrows():
        # For cosine distance, similarity = 1 - distance / 2 (distance is 0-2 for cosine)
        similarity = max(0, 1 - row.get("_distance", 0) / 2)
        formatted.append(
            {
                "content": row["content"],
                "file_path": row["file_path"],
                "start_line": int(row["start_line"]),
                "end_line": int(row["end_line"]),
                "type": row["type"],
                "name": row["name"],
                "language": row["language"],
                "similarity": round(similarity, 3),
            }
        )
    return formatted


def _refresh_if_stale(project: str) -> None:
    """Re-index a stale project before searching it."""
    update_stats = _auto_update_if_stale(project)
    if update_stats and "error" not in update_stats:
        logger.info("Auto-updated index: %s files", update_stats.get("files_indexed", 0))


def _resolve_nprobes(nprobes: int | None) -> int:
    """Explicit nprobes, else the configured value, else DEFAULT_NPROBES."""
    if nprobes is None:
        return _get_vector_search_config().get("nprobes", DEFAULT_NPROBES)
    return nprobes


def _embed_query(query: str, timing: dict[str, Any]) -> list[float]:
    """Embed the query (cached), recording the embed time in ``timing``."""
    embed_start = time.time()
    query_embedding = _get_cached_embedding(query, _get_embedding_model())
    timing["embed_time_ms"] = (time.time() - embed_start) * 1000
    timing["cache_hit"] = timing["embed_time_ms"] < 1  # Cache hits are < 1ms
    return query_embedding


def _search_code(query: str, project: str, limit: int = 10, **options: Unpack[SearchOptions]) -> list[dict]:
    """
    Search indexed code semantically.

    Uses IVF-PQ index for fast approximate nearest neighbor search when available.
    Query embeddings are cached for repeated queries.

    Args:
        query: Natural language query
        project: Project name
        limit: Max results to return
        **options: ``file_filter``, ``type_filter``, ``auto_update`` and ``nprobes``
            (see :class:`SearchOptions`).

    Returns list of matching code chunks with relevance scores.
    """
    start_time = time.time()

    if options.get("auto_update", True):
        _refresh_if_stale(project)

    db = _get_lance_db(project)
    table_name = _get_table_name(project)
    if table_name not in db.table_names():
        return [{"error": f"Project '{project}' not indexed. Run code_index first."}]

    table = db.open_table(table_name)
    timing: dict[str, Any] = {}
    query_embedding = _embed_query(query, timing)

    timing["nprobes"] = _resolve_nprobes(options.get("nprobes"))

    search_start = time.time()
    try:
        results = _run_vector_query(table, query_embedding, limit, timing["nprobes"])
    # Intentional: convert the failure into an error result for the caller.
    except _INDEX_ERRORS as e:
        logger.error("LanceDB search failed for project '%s': %s", project, e)
        return [{"error": (f"Search failed: {e}. Try re-indexing with code_index(project='{project}', force=True)")}]
    timing["search_time_ms"] = (time.time() - search_start) * 1000

    if results is None or results.empty:
        return []

    missing_cols = _REQUIRED_COLUMNS - set(results.columns)
    if missing_cols:
        logger.error("Index schema mismatch for '%s': missing columns %s", project, missing_cols)
        return [{"error": (f"Index schema mismatch. Re-index with code_index(project='{project}', force=True)")}]

    results = _apply_filters(results, options.get("file_filter", ""), options.get("type_filter", ""))
    formatted = _format_results(results.head(limit))
    _update_search_stats(project, (time.time() - start_time) * 1000, timing)
    return formatted


def _table_row_count(project: str) -> int:
    """Number of chunks in the project's table (0 when unavailable)."""
    try:
        db = _get_lance_db(project)
        table_name = _get_table_name(project)
        if table_name in db.table_names():
            return len(db.open_table(table_name))
    # Intentional: log the failure and continue at this boundary.
    except _INDEX_ERRORS as exc:
        logger.debug("Suppressed error: %s", exc)
    return 0


def _disk_usage(project: str) -> int:
    """Total bytes of the project's vector database directory."""
    db_path = cs_config.vector_db_path() / project
    if not db_path.exists():
        return 0
    return sum(entry.stat().st_size for entry in db_path.rglob("*") if entry.is_file())


def _index_age(indexed_at: str) -> tuple[str, bool]:
    """Human-readable age of the index and whether it is stale."""
    if not indexed_at:
        return "", False
    try:
        age = _now() - _parse_timestamp(indexed_at)
    # Intentional: log the failure and continue at this boundary.
    except _INDEX_ERRORS as exc:
        logger.debug("Suppressed error: %s", exc)
        return "", False

    if age.days > 0:
        label = f"{age.days}d ago"
    elif age.seconds >= 3600:
        label = f"{age.seconds // 3600}h ago"
    elif age.seconds >= 60:
        label = f"{age.seconds // 60}m ago"
    else:
        label = "just now"
    return label, age > timedelta(minutes=INDEX_STALE_MINUTES)


def _get_index_stats(project: str) -> dict:
    """Get comprehensive statistics about indexed project."""
    metadata_path = cs_config.metadata_path(project)
    if not metadata_path.exists():
        return {"indexed": False, "project": project}

    with open(metadata_path, encoding="utf-8") as f:
        metadata = json.load(f)

    disk_size_bytes = _disk_usage(project)
    indexed_at = metadata.get("indexed_at", "")
    index_age, is_stale = _index_age(indexed_at)
    search_stats = metadata.get("search_stats", {})
    index_config = metadata.get("index_config", {})
    cache_stats = _embedding_cache.stats()

    return {
        "indexed": True,
        "project": project,
        "indexed_at": indexed_at,
        "index_age": index_age,
        "is_stale": is_stale,
        "files_indexed": metadata.get("stats", {}).get("files_indexed", 0),
        "files_total": len(metadata.get("file_hashes", {})),
        "chunks_count": _table_row_count(project),
        "disk_size": _format_size(disk_size_bytes),
        "disk_size_bytes": disk_size_bytes,
        "search_count": search_stats.get("total_searches", 0),
        "last_search": search_stats.get("last_search", None),
        "avg_search_time_ms": search_stats.get("avg_search_time_ms", 0),
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
        # Index info
        "index_type": index_config.get("type", "FLAT"),
        "num_partitions": index_config.get("num_partitions", 0),
        # Cache info
        "cache_size": cache_stats["size"],
        "cache_hit_rate": cache_stats["hit_rate"],
        # Detailed timing
        "avg_embed_time_ms": search_stats.get("avg_embed_time_ms", 0),
        "avg_vector_search_time_ms": search_stats.get("avg_vector_search_time_ms", 0),
        "cache_hits": search_stats.get("cache_hits", 0),
        "cache_misses": search_stats.get("cache_misses", 0),
    }


def _record_timing(search_stats: dict, details: dict) -> None:
    """Update cache hit/miss counters and running timing averages."""
    if details.get("cache_hit"):
        search_stats["cache_hits"] = search_stats.get("cache_hits", 0) + 1
    else:
        search_stats["cache_misses"] = search_stats.get("cache_misses", 0) + 1

    n = search_stats["total_searches"]
    prev_avg_embed = search_stats.get("avg_embed_time_ms", 0)
    search_stats["avg_embed_time_ms"] = round((prev_avg_embed * (n - 1) + details.get("embed_time_ms", 0)) / n, 2)

    prev_avg_vector = search_stats.get("avg_vector_search_time_ms", 0)
    vector_time = details.get("search_time_ms", 0)
    search_stats["avg_vector_search_time_ms"] = round((prev_avg_vector * (n - 1) + vector_time) / n, 2)


def _update_search_stats(project: str, search_time_ms: float, details: dict | None = None) -> None:
    """Update search statistics in metadata."""
    metadata_path = cs_config.metadata_path(project)
    if not metadata_path.exists():
        return

    try:
        with open(metadata_path, encoding="utf-8") as f:
            metadata = json.load(f)

        search_stats = metadata.get("search_stats", dict(_EMPTY_SEARCH_STATS))
        search_stats["total_searches"] += 1
        search_stats["total_search_time_ms"] += search_time_ms
        search_stats["last_search"] = _now().isoformat()
        search_stats["avg_search_time_ms"] = round(
            search_stats["total_search_time_ms"] / search_stats["total_searches"], 1
        )
        if details:
            _record_timing(search_stats, details)

        metadata["search_stats"] = search_stats
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
    # Intentional: log the failure and continue at this boundary.
    except _INDEX_ERRORS as e:
        logger.debug("Failed to update search stats: %s", e)


def _project_vector_stats(proj: str, stats: dict, watcher_active: bool) -> dict:
    """Per-project entry of :func:`get_all_vector_stats`."""
    return {
        "project": proj,
        "indexed": True,
        "files": stats.get("files_total", 0),
        "chunks": stats.get("chunks_count", 0),
        "disk_size": stats.get("disk_size", "0 B"),
        "disk_size_bytes": stats.get("disk_size_bytes", 0),
        "index_age": stats.get("index_age", "Unknown"),
        "is_stale": stats.get("is_stale", False),
        "searches": stats.get("search_count", 0),
        "avg_search_ms": stats.get("avg_search_time_ms", 0),
        "last_search": stats.get("last_search"),
        "watcher_active": watcher_active,
        "model": stats.get("embedding_model", "unknown"),
        # New index info
        "index_type": stats.get("index_type", "FLAT"),
        "num_partitions": stats.get("num_partitions", 0),
        # Timing breakdown
        "avg_embed_ms": stats.get("avg_embed_time_ms", 0),
        "avg_vector_ms": stats.get("avg_vector_search_time_ms", 0),
        "cache_hits": stats.get("cache_hits", 0),
        "cache_misses": stats.get("cache_misses", 0),
    }


def _add_to_totals(totals: dict, stats: dict, watcher_active: bool) -> None:
    """Accumulate one indexed project's stats into the totals."""
    totals["indexed_count"] += 1
    totals["total_chunks"] += stats.get("chunks_count", 0)
    totals["total_files"] += stats.get("files_total", 0)
    totals["total_size_bytes"] += stats.get("disk_size_bytes", 0)
    totals["total_searches"] += stats.get("search_count", 0)
    totals["total_cache_hits"] += stats.get("cache_hits", 0)
    totals["total_cache_misses"] += stats.get("cache_misses", 0)
    if watcher_active:
        totals["watchers_active"] += 1


def get_all_vector_stats() -> dict:
    """
    Get vector search stats for all indexed projects.
    Used by the VSCode extension to display stats.

    Returns dict with:
    - projects: list of project stats
    - totals: aggregate stats
    - cache: global embedding cache stats
    - config: current vector search config
    """
    config = _load_config()
    projects = list(config.get("repositories", {}).keys())
    vs_config = config.get("vector_search", {})

    totals: dict[str, Any] = {
        "indexed_count": 0,
        "total_chunks": 0,
        "total_files": 0,
        "total_size_bytes": 0,
        "total_size": "0 B",
        "total_searches": 0,
        "watchers_active": 0,
        "total_cache_hits": 0,
        "total_cache_misses": 0,
    }
    result: dict[str, Any] = {
        "projects": [],
        "totals": totals,
        "cache": _embedding_cache.stats(),
        "config": {
            "index_type": vs_config.get("index_type", INDEX_TYPE),
            "nprobes": vs_config.get("search", {}).get("nprobes", DEFAULT_NPROBES),
            "cache_enabled": vs_config.get("cache", {}).get("enabled", CACHE_ENABLED),
            "embedding_model": vs_config.get("embedding", {}).get("model", DEFAULT_EMBEDDING_MODEL),
            "embedding_backend": vs_config.get("embedding", {}).get("backend", "sentence-transformers"),
        },
    }

    for proj in projects:
        stats = _get_index_stats(proj)
        if not stats.get("indexed"):
            result["projects"].append({"project": proj, "indexed": False})
            continue
        watcher = get_watcher(proj)
        watcher_active = watcher.is_running if watcher else False
        result["projects"].append(_project_vector_stats(proj, stats, watcher_active))
        _add_to_totals(totals, stats, watcher_active)

    totals["total_size"] = _format_size(totals["total_size_bytes"])

    total_cache = totals["total_cache_hits"] + totals["total_cache_misses"]
    if total_cache > 0:
        totals["cache_hit_rate"] = f"{totals['total_cache_hits'] / total_cache * 100:.1f}%"
    else:
        totals["cache_hit_rate"] = "N/A"

    return result


def _project_health_findings(proj: dict, health: dict) -> None:
    """Append the issues and recommendations for one project."""
    name = proj["project"]
    if not proj.get("indexed"):
        health["issues"].append(f"Project '{name}' not indexed")
        return

    if proj.get("is_stale"):
        health["issues"].append(f"Project '{name}' index is stale ({proj.get('index_age', 'unknown')})")

    if proj.get("index_type") == "FLAT" and proj.get("chunks", 0) > 1000:
        health["recommendations"].append(
            f"Project '{name}' has {proj['chunks']} vectors but no ANN index. "
            "Re-index to create IVF-PQ index for faster search."
        )

    if proj.get("avg_search_ms", 0) > 500:
        health["issues"].append(f"Project '{name}' search is slow ({proj['avg_search_ms']:.0f}ms avg)")


def get_vector_health() -> dict:
    """
    Get health status and performance metrics for vector search.

    Returns:
        Health dashboard with performance indicators and recommendations.
    """
    stats = get_all_vector_stats()

    health: dict[str, Any] = {
        "status": "healthy",
        "issues": [],
        "recommendations": [],
        "metrics": {
            "indexed_projects": stats["totals"]["indexed_count"],
            "total_vectors": stats["totals"]["total_chunks"],
            "cache_hit_rate": stats["totals"].get("cache_hit_rate", "N/A"),
            "avg_search_time_ms": 0,
        },
    }

    search_times = [p.get("avg_search_ms", 0) for p in stats["projects"] if p.get("indexed")]
    if search_times:
        health["metrics"]["avg_search_time_ms"] = round(sum(search_times) / len(search_times), 1)

    for proj in stats["projects"]:
        _project_health_findings(proj, health)

    cache_stats = stats.get("cache", {})
    if cache_stats.get("size", 0) >= cache_stats.get("max_size", 1000) * 0.9:
        health["recommendations"].append(
            "Embedding cache is nearly full. Consider increasing cache_max_size in config."
        )

    if health["issues"]:
        health["status"] = "degraded" if len(health["issues"]) < 3 else "unhealthy"

    return health
