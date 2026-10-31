"""Building and refreshing a project's LanceDB code index."""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from tool_modules.aa_code_search.src import cs_config
from tool_modules.aa_code_search.src.cs_chunking import _chunk_code_simple, _get_language, _should_index_file
from tool_modules.aa_code_search.src.cs_config import (
    _INDEX_ERRORS,
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_DIM,
    INDEX_STALE_MINUTES,
    INDEX_TYPE,
    NUM_PARTITIONS,
    NUM_SUB_VECTORS,
    _compute_file_hash,
    _get_project_path,
    _get_table_name,
    _get_vector_search_config,
    _now,
    _parse_timestamp,
)
from tool_modules.aa_code_search.src.cs_embeddings import _get_embedding_model, _get_lance_db

logger = logging.getLogger(__name__)

_MIN_ROWS_FOR_ANN_INDEX = 256  # Need enough data for partitions


@dataclass
class _IndexRun:
    """State of one indexing pass over a project."""

    project: str
    force: bool
    existing_hashes: dict[str, str] = field(default_factory=dict)
    new_hashes: dict[str, str] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(
        default_factory=lambda: {"files_indexed": 0, "files_skipped": 0, "chunks_created": 0, "errors": []}
    )


def _is_index_stale(project: str, max_age_minutes: int = INDEX_STALE_MINUTES) -> bool:
    """Check if the index is stale (older than max_age_minutes)."""
    metadata_path = cs_config.metadata_path(project)

    if not metadata_path.exists():
        return True  # Not indexed at all

    try:
        with open(metadata_path, encoding="utf-8") as f:
            metadata = json.load(f)

        indexed_at = _parse_timestamp(metadata.get("indexed_at", ""))
        age = _now() - indexed_at
        return age > timedelta(minutes=max_age_minutes)
    # Intentional: convert the failure into an error result for the caller.
    except _INDEX_ERRORS:
        return True


def _auto_update_if_stale(project: str) -> dict | None:
    """Auto-update index if stale. Returns stats if updated, None otherwise."""
    if not cs_config.AUTO_UPDATE_ON_SEARCH:
        return None

    if _is_index_stale(project):
        logger.info("Index for %s is stale, auto-updating...", project)
        return _index_project(project, force=False)

    return None


def _load_existing_hashes(run: _IndexRun) -> None:
    """Load the file hashes of the previous run (skipped when forcing a full re-index)."""
    metadata_path = cs_config.metadata_path(run.project)
    if run.force or not metadata_path.exists():
        return
    try:
        with open(metadata_path, encoding="utf-8") as f:
            run.existing_hashes = json.load(f).get("file_hashes", {})
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Corrupted metadata.json for %s, will re-index: %s", run.project, e)
        run.existing_hashes = {}


def _embed_file(file_path: Path, rel_path: str, model: Any) -> list[dict[str, Any]]:
    """Chunk and embed one file into LanceDB rows."""
    content = file_path.read_text(errors="ignore")
    chunks = _chunk_code_simple(content, rel_path, _get_language(rel_path))
    if not chunks:
        return []

    embeddings = model.encode([c["content"] for c in chunks]).tolist()
    return [
        {
            "id": f"{rel_path}:{chunk['start_line']}:{chunk['end_line']}",
            "vector": embedding,
            "content": chunk["content"],
            "file_path": chunk["file_path"],
            "start_line": chunk["start_line"],
            "end_line": chunk["end_line"],
            "type": chunk["type"],
            "name": chunk["name"],
            "language": chunk["language"],
        }
        for chunk, embedding in zip(chunks, embeddings, strict=False)
    ]


def _collect_rows(run: _IndexRun, project_path: Path, model: Any) -> None:
    """Hash every indexable file and embed the ones that changed."""
    for file_path in project_path.rglob("*"):
        if not file_path.is_file() or not _should_index_file(file_path, project_path):
            continue

        rel_path = str(file_path.relative_to(project_path))
        try:
            file_hash = _compute_file_hash(file_path)
            run.new_hashes[rel_path] = file_hash

            if not run.force and run.existing_hashes.get(rel_path) == file_hash:
                run.stats["files_skipped"] += 1
                continue

            rows = _embed_file(file_path, rel_path, model)
            if not rows:
                continue

            run.rows.extend(rows)
            run.stats["files_indexed"] += 1
            run.stats["chunks_created"] += len(rows)

        # Intentional: log the failure and continue at this boundary.
        except _INDEX_ERRORS as e:
            run.stats["errors"].append(f"{rel_path}: {e!s}")


def _write_table(run: _IndexRun, db: Any, table_name: str) -> tuple[Any, bool]:
    """Create, rewrite or append the project table. Returns (table, rewritten)."""
    if run.force or table_name not in db.table_names():
        return db.create_table(table_name, data=run.rows, mode="overwrite"), True

    # Incremental update: drop existing entries of changed files first
    table = db.open_table(table_name)
    unchanged = {k for k, v in run.existing_hashes.items() if run.new_hashes.get(k) == v}
    changed_files = set(run.new_hashes.keys()) - unchanged
    if not changed_files:
        table.add(run.rows)
        return table, False

    # LanceDB doesn't have easy delete, so we recreate
    existing_data = table.to_pandas().to_dict("records")
    run.rows = [d for d in existing_data if d.get("file_path") not in changed_files] + run.rows
    return db.create_table(table_name, data=run.rows, mode="overwrite"), True


def _create_ann_index(table: Any, row_count: int, stats: dict[str, Any]) -> None:
    """Create an IVF-PQ / IVF-FLAT index for fast approximate nearest neighbour search."""
    try:
        index_start = time.time()
        vs_config = _get_vector_search_config()
        index_type = vs_config.get("index_type", INDEX_TYPE)

        if index_type in ("IVF_PQ", "IVF_FLAT"):
            # At least 10 vectors per partition
            num_partitions = min(vs_config.get("num_partitions", NUM_PARTITIONS), row_count // 10)
            options: dict[str, Any] = {"metric": "cosine", "num_partitions": num_partitions, "index_type": index_type}
            if index_type == "IVF_PQ":
                num_sub_vectors = vs_config.get("num_sub_vectors", NUM_SUB_VECTORS)
                options["num_sub_vectors"] = min(num_sub_vectors, EMBEDDING_DIM)
            table.create_index(**options)
            stats["index_type"] = index_type
            stats["num_partitions"] = num_partitions
        else:
            # FLAT = no index (brute force)
            stats["index_type"] = "FLAT"

        stats["index_time_ms"] = (time.time() - index_start) * 1000
        logger.info("Created %s index in %.0fms", stats.get("index_type", "FLAT"), stats["index_time_ms"])

    # Intentional: log the failure and continue at this boundary.
    except _INDEX_ERRORS as e:
        logger.warning("Failed to create index (falling back to brute force): %s", e)
        stats["index_type"] = "FLAT"
        stats["index_error"] = str(e)


def _optimize_table(table: Any, stats: dict[str, Any]) -> None:
    """Merge fragment files and drop old versions (LanceDB writes new fragments on each write)."""
    try:
        optimize_start = time.time()
        table.optimize(cleanup_older_than=timedelta(days=0))
        stats["optimize_time_ms"] = (time.time() - optimize_start) * 1000
        logger.info("Optimized table in %.0fms", stats["optimize_time_ms"])
    # Intentional: log the failure and continue at this boundary.
    except _INDEX_ERRORS as e:
        logger.warning("Failed to optimize table: %s", e)
        stats["optimize_error"] = str(e)


def _save_metadata(run: _IndexRun) -> None:
    """Write metadata.json (hashes, stats and index config) for the project."""
    stats = run.stats
    metadata = {
        "project": run.project,
        "indexed_at": _now().isoformat(),
        "file_hashes": run.new_hashes,
        "stats": stats,
        "index_config": {
            "type": stats.get("index_type", "FLAT"),
            "num_partitions": stats.get("num_partitions", 0),
            "embedding_dim": EMBEDDING_DIM,
            "embedding_model": DEFAULT_EMBEDDING_MODEL,
        },
    }
    metadata_path = cs_config.metadata_path(run.project)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)


def _index_project(project: str, force: bool = False) -> dict:
    """
    Index a project's code into LanceDB.

    Returns statistics about the indexing.
    """
    project_path = _get_project_path(project)
    if not project_path or not project_path.exists():
        return {"error": f"Project path not found: {project}"}

    db = _get_lance_db(project)
    table_name = _get_table_name(project)
    model = _get_embedding_model()

    run = _IndexRun(project=project, force=force)
    _load_existing_hashes(run)
    _collect_rows(run, project_path, model)

    if run.rows:
        table, rewritten = _write_table(run, db, table_name)
        if rewritten and len(run.rows) >= _MIN_ROWS_FOR_ANN_INDEX:
            _create_ann_index(table, len(run.rows), run.stats)
        elif len(run.rows) < _MIN_ROWS_FOR_ANN_INDEX:
            run.stats["index_type"] = "FLAT"
            run.stats["index_note"] = "Too few vectors for IVF index, using brute force"
        _optimize_table(table, run.stats)

    _save_metadata(run)
    return run.stats
