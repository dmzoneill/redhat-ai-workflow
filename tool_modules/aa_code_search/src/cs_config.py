"""Code search configuration, shared constants and small helpers."""

import hashlib
import importlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

# Sets up sys.path so server imports resolve, also when loaded via spec_from_file_location
from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT  # Module initialization marker

logger = logging.getLogger(__name__)

# Failures expected from optional ML backends, LanceDB/pyarrow, pandas and file I/O
# (pyarrow's errors subclass ValueError/OSError; missing backends raise ImportError).
_INDEX_ERRORS: tuple[type[Exception], ...] = (
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    LookupError,
    AttributeError,
    ArithmeticError,
    ImportError,
)

# Configuration
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # Fast, good quality, runs locally
VECTOR_DB_PATH = Path.home() / ".cache" / "aa-workflow" / "vectors"
CHUNK_SIZE = 1500  # Characters per chunk
CHUNK_OVERLAP = 200  # Overlap between chunks
EMBEDDING_DIM = 384  # Dimension for all-MiniLM-L6-v2
INDEX_STALE_MINUTES = 60  # Consider index stale after this many minutes
AUTO_UPDATE_ON_SEARCH = True  # Auto-update stale indexes on search

# IVF-PQ Index Configuration
INDEX_TYPE = "IVF_PQ"  # Options: "IVF_PQ", "IVF_FLAT", "FLAT" (brute force)
NUM_PARTITIONS = 256  # Number of IVF partitions (clusters)
NUM_SUB_VECTORS = 96  # PQ sub-vectors for compression
DEFAULT_NPROBES = 20  # Partitions to search (higher = more accurate, slower)

# Query Cache Configuration
CACHE_ENABLED = True
CACHE_MAX_SIZE = 1000  # Max cached embeddings
CACHE_TTL_SECONDS = 3600  # Cache entries expire after 1 hour


def vector_db_path() -> Path:
    """Root of the per-project vector databases (read at call time so it can be overridden)."""
    return VECTOR_DB_PATH


def metadata_path(project: str) -> Path:
    """Path of a project's metadata.json."""
    return vector_db_path() / project / "metadata.json"


def _load_config() -> dict:
    """Load config via ConfigManager (empty when the server config is unavailable)."""
    try:
        return importlib.import_module("server.config_manager").config.get_all()
    # Intentional: convert the failure into an error result for the caller.
    except _INDEX_ERRORS:
        return {}


def _get_vector_search_config() -> dict:
    """Load vector search config from config.json."""
    config = _load_config()
    return config.get("vector_search", {})


def _get_project_path(project: str) -> Path | None:
    """Get project path from config."""
    config = _load_config()
    project_config = config.get("repositories", {}).get(project)
    if project_config:
        return Path(project_config.get("path", "")).expanduser()
    return None


def _configured_projects() -> list[str]:
    """Project names from config.json."""
    return list(_load_config().get("repositories", {}).keys())


def _get_table_name(project: str) -> str:
    """Generate a valid table name for LanceDB."""
    name = re.sub(r"[^a-zA-Z0-9_]", "_", project)
    return f"code_{name}"


def _now() -> datetime:
    """Current local time, timezone-aware."""
    return datetime.now(tz=timezone.utc).astimezone()


def _parse_timestamp(value: str) -> datetime:
    """Parse an ISO timestamp; naive values (older metadata) are local time."""
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.astimezone()


def _compute_file_hash(file_path: Path) -> str:
    """Compute hash of file content for change detection.

    SHA-256 (not MD5): indexes built with MD5 hashes see every file as changed
    once and are re-indexed on the next run.
    """
    content = file_path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def _format_size(num_bytes: int) -> str:
    """Human-readable size: B, KB or MB with one decimal."""
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes} B"
