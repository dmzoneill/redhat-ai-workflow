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
"""

import hashlib
import json
import logging
import os
import re
import sys
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from threading import Lock
from typing import Any

from mcp.types import TextContent

# Setup project path for server imports and establish package context
# This must be before any relative imports to work with spec_from_file_location
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization marker

# Add current directory to sys.path to support relative imports inside functions
# when loaded via spec_from_file_location (e.g., from server/main.py or persona_loader.py)
_TOOLS_DIR = Path(__file__).parent.absolute()
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

# Lazy imports for heavy dependencies
_lancedb = None
_sentence_transformer = None
_openvino_model = None

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

logger = logging.getLogger(__name__)


# ============================================================================
# Watcher Import Helper
# ============================================================================
# The watcher module needs special handling because this file can be loaded in
# two different ways:
# 1. As a package: `from aa_code_search.src.tools_basic import ...`
# 2. Via spec_from_file_location: `importlib.util.spec_from_file_location(...)`
#
# In case 2, relative imports fail because __package__ is None.
# This helper tries both import styles to work in all contexts.


def _import_watcher():
    """Import watcher module, handling both package and standalone loading."""
    try:
        # Try relative import first (works when loaded as package)
        from . import watcher

        return watcher
    except ImportError:
        # Fall back to absolute import (works when _TOOLS_DIR is in sys.path)
        import watcher

        return watcher


# ============================================================================
# Query Embedding Cache (LRU with TTL)
# ============================================================================


class EmbeddingCache:
    """Thread-safe LRU cache with TTL for query embeddings."""

    def __init__(self, max_size: int = CACHE_MAX_SIZE, ttl_seconds: int = CACHE_TTL_SECONDS):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, tuple[list[float], float]] = OrderedDict()
        self._lock = Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> list[float] | None:
        """Get embedding from cache if exists and not expired."""
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            embedding, timestamp = self._cache[key]

            # Check TTL
            if time.time() - timestamp > self.ttl_seconds:
                del self._cache[key]
                self._misses += 1
                return None

            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._hits += 1
            return embedding

    def put(self, key: str, embedding: list[float]) -> None:
        """Add embedding to cache."""
        with self._lock:
            # Remove oldest if at capacity
            while len(self._cache) >= self.max_size:
                self._cache.popitem(last=False)

            self._cache[key] = (embedding, time.time())

    def clear(self) -> None:
        """Clear the cache."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict:
        """Get cache statistics."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": f"{hit_rate:.1f}%",
            }


# Global cache instance
_embedding_cache = EmbeddingCache()


def _get_vector_search_config() -> dict:
    """Load vector search config from config.json."""
    config = _load_config()
    return config.get("vector_search", {})


def _get_cached_embedding(query: str, model) -> list[float]:
    """Get embedding with caching."""
    if not CACHE_ENABLED:
        return model.encode([query])[0].tolist()

    # Check cache
    cached = _embedding_cache.get(query)
    if cached is not None:
        return cached

    # Generate and cache
    embedding = model.encode([query])[0].tolist()
    _embedding_cache.put(query, embedding)
    return embedding


def _get_lancedb():
    """Lazy load lancedb."""
    global _lancedb
    if _lancedb is None:
        try:
            import lancedb

            _lancedb = lancedb
        except ImportError:
            raise ImportError("lancedb not installed. Run: pip install lancedb")
    return _lancedb


def _get_embedding_model():
    """
    Lazy load embedding model with backend selection.

    Supports:
    - sentence-transformers (default, CPU)
    - openvino (Intel NPU/iGPU acceleration)
    - onnx (ONNX Runtime with CUDA/CPU)
    """
    global _sentence_transformer, _openvino_model

    # Check config for backend preference
    vs_config = _get_vector_search_config()
    backend = vs_config.get("embedding", {}).get("backend", "sentence-transformers")

    # Try OpenVINO backend
    if backend == "openvino":
        if _openvino_model is None:
            try:
                _openvino_model = _load_openvino_model()
                if _openvino_model:
                    logger.info("Using OpenVINO embedding backend")
                    return _openvino_model
            except Exception as e:
                logger.warning(f"OpenVINO backend failed, falling back: {e}")

    # Try ONNX backend
    if backend == "onnx":
        if _sentence_transformer is None:
            try:
                _sentence_transformer = _load_onnx_model()
                if _sentence_transformer:
                    logger.info("Using ONNX embedding backend")
                    return _sentence_transformer
            except Exception as e:
                logger.warning(f"ONNX backend failed, falling back: {e}")

    # Default: sentence-transformers
    if _sentence_transformer is None:
        try:
            from sentence_transformers import SentenceTransformer

            _sentence_transformer = SentenceTransformer(DEFAULT_EMBEDDING_MODEL)
            logger.info("Using sentence-transformers embedding backend")
        except ImportError:
            raise ImportError("sentence-transformers not installed. Run: pip install sentence-transformers")
    return _sentence_transformer


def _load_openvino_model():
    """
    Load embedding model with OpenVINO for NPU/iGPU acceleration.

    For NPU: Uses fixed input shapes (padding to max_length) to avoid
    dynamic shape compilation errors.

    Requires: pip install optimum[openvino] openvino
    """
    try:
        import numpy as np
        import openvino as ov
        from transformers import AutoTokenizer

        vs_config = _get_vector_search_config()
        ov_config = vs_config.get("embedding", {}).get("backend_options", {}).get("openvino", {})
        device = ov_config.get("device", "NPU")

        # For NPU, we need fixed shapes - use static compilation
        if device == "NPU":
            return _load_openvino_npu_static()

        # For GPU/CPU, dynamic shapes work fine
        from optimum.intel import OVModelForFeatureExtraction

        model_name = f"sentence-transformers/{DEFAULT_EMBEDDING_MODEL}"
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = OVModelForFeatureExtraction.from_pretrained(
            model_name,
            export=True,
            device=device,
        )

        # Wrap in a class with encode() method for compatibility
        class OpenVINOEmbedder:
            def __init__(self, model, tokenizer, device):
                self.model = model
                self.tokenizer = tokenizer
                self.device = device

            def encode(self, texts, **kwargs):
                if isinstance(texts, str):
                    texts = [texts]

                inputs = self.tokenizer(texts, padding=True, truncation=True, max_length=512, return_tensors="pt")

                outputs = self.model(**inputs)
                # Mean pooling
                embeddings = outputs.last_hidden_state.mean(dim=1)
                return embeddings.numpy()

        return OpenVINOEmbedder(model, tokenizer, device)

    except ImportError as e:
        logger.debug(f"OpenVINO not available: {e}")
        return None
    except Exception as e:
        logger.warning(f"Failed to load OpenVINO model: {e}")
        return None


def _load_openvino_npu_static():
    """
    Load embedding model for NPU with FIXED input shapes.

    NPU requires static shapes - we pad all inputs to a fixed length.
    Uses optimum-intel's export with static shapes.
    """
    try:
        from pathlib import Path

        import numpy as np
        import openvino as ov
        from optimum.intel import OVModelForFeatureExtraction
        from transformers import AutoTokenizer

        vs_config = _get_vector_search_config()
        ov_config = vs_config.get("embedding", {}).get("backend_options", {}).get("openvino", {})

        # Fixed sequence length for NPU (shorter = faster, but truncates long queries)
        FIXED_SEQ_LEN = ov_config.get("fixed_seq_len", 128)

        model_name = f"sentence-transformers/{DEFAULT_EMBEDDING_MODEL}"
        cache_dir = VECTOR_DB_PATH / "openvino_cache" / f"npu_seq{FIXED_SEQ_LEN}"
        cache_dir.mkdir(parents=True, exist_ok=True)

        ir_path = cache_dir / "openvino_model.xml"
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        core = ov.Core()

        # Export with static shapes if not cached
        if not ir_path.exists():
            logger.info(f"Exporting model with fixed shape (seq_len={FIXED_SEQ_LEN}) for NPU...")

            # Use optimum-intel to export with static shapes
            # Export to CPU first, then we'll reshape and compile for NPU
            ov_model = OVModelForFeatureExtraction.from_pretrained(
                model_name,
                export=True,
                compile=False,  # Don't compile yet
            )

            # Reshape to static dimensions
            model = ov_model.model
            model.reshape(
                {
                    "input_ids": [1, FIXED_SEQ_LEN],
                    "attention_mask": [1, FIXED_SEQ_LEN],
                    "token_type_ids": [1, FIXED_SEQ_LEN],
                }
            )

            # Save the reshaped model
            ov.save_model(model, str(ir_path))
            logger.info(f"Saved static NPU model to {ir_path}")

        # Load and compile for NPU
        logger.info(f"Compiling model for NPU (fixed seq_len={FIXED_SEQ_LEN})...")
        ov_model = core.read_model(str(ir_path))

        # NPU-specific optimizations
        config = {
            "PERFORMANCE_HINT": "LATENCY",
        }

        compiled_model = core.compile_model(ov_model, "NPU", config)

        class OpenVINONPUEmbedder:
            """Embedder using NPU with fixed input shapes."""

            def __init__(self, compiled_model, tokenizer, seq_len):
                self.compiled_model = compiled_model
                self.tokenizer = tokenizer
                self.seq_len = seq_len
                self.infer_request = compiled_model.create_infer_request()

            def encode(self, texts, **kwargs):
                if isinstance(texts, str):
                    texts = [texts]

                # Tokenize with FIXED padding (critical for NPU)
                inputs = self.tokenizer(
                    texts,
                    padding="max_length",  # Always pad to max
                    truncation=True,
                    max_length=self.seq_len,
                    return_tensors="np",
                )

                # Run inference
                self.infer_request.infer(
                    {
                        "input_ids": inputs["input_ids"],
                        "attention_mask": inputs["attention_mask"],
                        "token_type_ids": inputs.get("token_type_ids", np.zeros_like(inputs["input_ids"])),
                    }
                )

                # Get output and apply mean pooling
                last_hidden_state = self.infer_request.get_output_tensor(0).data.copy()

                # Mean pooling with attention mask
                attention_mask = inputs["attention_mask"]
                mask_expanded = np.expand_dims(attention_mask, -1)
                sum_embeddings = np.sum(last_hidden_state * mask_expanded, axis=1)
                sum_mask = np.clip(np.sum(mask_expanded, axis=1), a_min=1e-9, a_max=None)
                embeddings = sum_embeddings / sum_mask

                return embeddings

        embedder = OpenVINONPUEmbedder(compiled_model, tokenizer, FIXED_SEQ_LEN)
        logger.info("✅ NPU embedder ready with fixed shapes")
        return embedder

    except Exception as e:
        logger.warning(f"Failed to load NPU static model: {e}")
        import traceback

        traceback.print_exc()
        return None


def _load_onnx_model():
    """
    Load embedding model with ONNX Runtime for GPU acceleration.

    Requires: pip install onnxruntime-gpu (or onnxruntime for CPU)
    """
    try:
        from sentence_transformers import SentenceTransformer

        vs_config = _get_vector_search_config()
        providers = (
            vs_config.get("embedding", {})
            .get("backend_options", {})
            .get("onnx", {})
            .get("providers", ["CUDAExecutionProvider", "CPUExecutionProvider"])
        )

        # SentenceTransformers can use ONNX backend
        model = SentenceTransformer(DEFAULT_EMBEDDING_MODEL, backend="onnx", model_kwargs={"providers": providers})

        return model

    except Exception as e:
        logger.debug(f"ONNX backend not available: {e}")
        return None


def _load_config() -> dict:
    """Load config.json from project root."""
    config_paths = [
        Path.cwd() / "config.json",
        Path(__file__).parent.parent.parent.parent.parent / "config.json",
    ]
    for config_path in config_paths:
        if config_path.exists():
            with open(config_path) as f:
                return json.load(f)
    return {}


def _get_project_path(project: str) -> Path | None:
    """Get project path from config."""
    config = _load_config()
    project_config = config.get("repositories", {}).get(project)
    if project_config:
        return Path(project_config.get("path", "")).expanduser()
    return None


def _get_table_name(project: str) -> str:
    """Generate a valid table name for LanceDB."""
    name = re.sub(r"[^a-zA-Z0-9_]", "_", project)
    return f"code_{name}"


def _get_lance_db(project: str):
    """Get or create LanceDB connection for a project."""
    lancedb = _get_lancedb()
    db_path = VECTOR_DB_PATH / project
    db_path.mkdir(parents=True, exist_ok=True)

    db = lancedb.connect(str(db_path))
    return db


def _chunk_code_simple(content: str, file_path: str, language: str) -> list[dict]:
    """
    Simple code chunking by logical boundaries.

    For Python, chunks by:
    - Class definitions
    - Function definitions
    - Module-level code blocks
    """
    chunks = []

    if language == "python":
        chunks = _chunk_python_code(content, file_path)
    else:
        # Fallback: chunk by size with overlap
        chunks = _chunk_by_size(content, file_path, language)

    return chunks


def _chunk_python_code(content: str, file_path: str) -> list[dict]:
    """Chunk Python code by functions and classes."""
    chunks = []
    lines = content.split("\n")

    current_chunk = []
    current_type = "module"
    current_name = "module"
    chunk_start_line = 1

    for i, line in enumerate(lines, 1):
        stripped = line.lstrip()
        current_indent = len(line) - len(stripped)

        # Detect new top-level definitions
        is_new_def = False
        new_type = current_type
        new_name = current_name

        if stripped.startswith("class ") and current_indent == 0:
            is_new_def = True
            new_type = "class"
            match = re.match(r"class\s+(\w+)", stripped)
            new_name = match.group(1) if match else "unknown"
        elif stripped.startswith("def ") and current_indent == 0:
            is_new_def = True
            new_type = "function"
            match = re.match(r"def\s+(\w+)", stripped)
            new_name = match.group(1) if match else "unknown"
        elif stripped.startswith("async def ") and current_indent == 0:
            is_new_def = True
            new_type = "async_function"
            match = re.match(r"async def\s+(\w+)", stripped)
            new_name = match.group(1) if match else "unknown"

        if is_new_def and current_chunk:
            # Save previous chunk
            chunk_content = "\n".join(current_chunk)
            if chunk_content.strip():
                chunks.append(
                    {
                        "content": chunk_content,
                        "file_path": file_path,
                        "start_line": chunk_start_line,
                        "end_line": i - 1,
                        "type": current_type,
                        "name": current_name,
                        "language": "python",
                    }
                )
            current_chunk = []
            chunk_start_line = i
            current_type = new_type
            current_name = new_name

        current_chunk.append(line)

    # Save final chunk
    if current_chunk:
        chunk_content = "\n".join(current_chunk)
        if chunk_content.strip():
            chunks.append(
                {
                    "content": chunk_content,
                    "file_path": file_path,
                    "start_line": chunk_start_line,
                    "end_line": len(lines),
                    "type": current_type,
                    "name": current_name,
                    "language": "python",
                }
            )

    # Split large chunks
    final_chunks = []
    for chunk in chunks:
        if len(chunk["content"]) > CHUNK_SIZE * 2:
            # Split large chunks
            sub_chunks = _chunk_by_size(
                chunk["content"],
                chunk["file_path"],
                "python",
                base_line=chunk["start_line"],
                chunk_type=chunk["type"],
                chunk_name=chunk["name"],
            )
            final_chunks.extend(sub_chunks)
        else:
            final_chunks.append(chunk)

    return final_chunks


def _chunk_by_size(
    content: str,
    file_path: str,
    language: str,
    base_line: int = 1,
    chunk_type: str = "code",
    chunk_name: str = "unknown",
) -> list[dict]:
    """Chunk content by size with overlap."""
    chunks = []
    lines = content.split("\n")

    current_chunk_lines = []
    current_start = base_line
    current_size = 0

    for i, line in enumerate(lines):
        line_size = len(line) + 1  # +1 for newline

        if current_size + line_size > CHUNK_SIZE and current_chunk_lines:
            # Save chunk
            chunks.append(
                {
                    "content": "\n".join(current_chunk_lines),
                    "file_path": file_path,
                    "start_line": current_start,
                    "end_line": current_start + len(current_chunk_lines) - 1,
                    "type": chunk_type,
                    "name": chunk_name,
                    "language": language,
                }
            )

            # Start new chunk with overlap
            overlap_lines = int(CHUNK_OVERLAP / 50)  # Approximate lines for overlap
            current_chunk_lines = current_chunk_lines[-overlap_lines:] if overlap_lines > 0 else []
            current_start = current_start + len(current_chunk_lines) - overlap_lines
            current_size = sum(len(l) + 1 for l in current_chunk_lines)

        current_chunk_lines.append(line)
        current_size += line_size

    # Save final chunk
    if current_chunk_lines:
        chunks.append(
            {
                "content": "\n".join(current_chunk_lines),
                "file_path": file_path,
                "start_line": current_start,
                "end_line": current_start + len(current_chunk_lines) - 1,
                "type": chunk_type,
                "name": chunk_name,
                "language": language,
            }
        )

    return chunks


def _get_language(file_path: str) -> str:
    """Detect language from file extension."""
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".jsx": "javascript",
        ".tsx": "typescript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".rb": "ruby",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".md": "markdown",
        ".sh": "shell",
        ".bash": "shell",
    }
    ext = Path(file_path).suffix.lower()
    return ext_map.get(ext, "unknown")


def _should_index_file(file_path: Path, project_path: Path) -> bool:
    """Check if file should be indexed."""
    # Skip hidden files and directories
    rel_path = file_path.relative_to(project_path)
    for part in rel_path.parts:
        if part.startswith("."):
            return False

    # Skip common non-code directories
    skip_dirs = {
        "__pycache__",
        "node_modules",
        "venv",
        ".venv",
        "env",
        "dist",
        "build",
        ".git",
        ".tox",
        "htmlcov",
        "coverage",
        ".pytest_cache",
        ".mypy_cache",
        "migrations",
        ".eggs",
    }
    if any(part in skip_dirs for part in rel_path.parts):
        return False

    # Only index code files
    code_extensions = {
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".go",
        ".rs",
        ".java",
        ".rb",
        ".yaml",
        ".yml",
        ".md",
        ".sh",
    }
    return file_path.suffix.lower() in code_extensions


def _compute_file_hash(file_path: Path) -> str:
    """Compute hash of file content for change detection."""
    content = file_path.read_bytes()
    return hashlib.md5(content).hexdigest()


def _is_index_stale(project: str, max_age_minutes: int = INDEX_STALE_MINUTES) -> bool:
    """Check if the index is stale (older than max_age_minutes)."""
    metadata_path = VECTOR_DB_PATH / project / "metadata.json"

    if not metadata_path.exists():
        return True  # Not indexed at all

    try:
        with open(metadata_path) as f:
            metadata = json.load(f)

        indexed_at = datetime.fromisoformat(metadata.get("indexed_at", ""))
        age = datetime.now() - indexed_at
        return age > timedelta(minutes=max_age_minutes)
    except Exception:
        return True


def _auto_update_if_stale(project: str) -> dict | None:
    """Auto-update index if stale. Returns stats if updated, None otherwise."""
    if not AUTO_UPDATE_ON_SEARCH:
        return None

    if _is_index_stale(project):
        logger.info(f"Index for {project} is stale, auto-updating...")
        return _index_project(project, force=False)

    return None


def _index_project(project: str, force: bool = False) -> dict:
    """
    Index a project's code into LanceDB.

    Returns statistics about the indexing.
    """
    project_path = _get_project_path(project)
    if not project_path or not project_path.exists():
        return {"error": f"Project path not found: {project}"}

    # Get LanceDB connection
    db = _get_lance_db(project)
    table_name = _get_table_name(project)

    # Get embedding model
    model = _get_embedding_model()

    # Track statistics
    stats = {
        "files_indexed": 0,
        "files_skipped": 0,
        "chunks_created": 0,
        "errors": [],
    }

    # Load existing file hashes to detect changes
    metadata_path = VECTOR_DB_PATH / project / "metadata.json"
    existing_hashes = {}
    if metadata_path.exists() and not force:
        with open(metadata_path) as f:
            existing_hashes = json.load(f).get("file_hashes", {})

    new_hashes = {}
    all_data = []

    # Find all code files
    for file_path in project_path.rglob("*"):
        if not file_path.is_file():
            continue
        if not _should_index_file(file_path, project_path):
            continue

        rel_path = str(file_path.relative_to(project_path))

        try:
            # Check if file changed
            file_hash = _compute_file_hash(file_path)
            new_hashes[rel_path] = file_hash

            if not force and existing_hashes.get(rel_path) == file_hash:
                stats["files_skipped"] += 1
                continue

            # Read and chunk file
            content = file_path.read_text(errors="ignore")
            language = _get_language(rel_path)
            chunks = _chunk_code_simple(content, rel_path, language)

            if not chunks:
                continue

            # Generate embeddings
            texts = [c["content"] for c in chunks]
            embeddings = model.encode(texts).tolist()

            # Prepare data for LanceDB
            for i, chunk in enumerate(chunks):
                all_data.append(
                    {
                        "id": f"{rel_path}:{chunk['start_line']}:{chunk['end_line']}",
                        "vector": embeddings[i],
                        "content": chunk["content"],
                        "file_path": chunk["file_path"],
                        "start_line": chunk["start_line"],
                        "end_line": chunk["end_line"],
                        "type": chunk["type"],
                        "name": chunk["name"],
                        "language": chunk["language"],
                    }
                )

            stats["files_indexed"] += 1
            stats["chunks_created"] += len(chunks)

        except Exception as e:
            stats["errors"].append(f"{rel_path}: {str(e)}")

    # Create or overwrite table
    index_created = False
    if all_data:
        if force or table_name not in db.table_names():
            # Create new table
            table = db.create_table(table_name, data=all_data, mode="overwrite")
            index_created = True
        else:
            # Append to existing (for incremental updates)
            # First delete existing entries for changed files
            table = db.open_table(table_name)
            changed_files = set(new_hashes.keys()) - set(
                k for k, v in existing_hashes.items() if new_hashes.get(k) == v
            )
            if changed_files:
                # LanceDB doesn't have easy delete, so we recreate
                existing_data = table.to_pandas().to_dict("records")
                filtered_data = [d for d in existing_data if d.get("file_path") not in changed_files]
                all_data = filtered_data + all_data
                table = db.create_table(table_name, data=all_data, mode="overwrite")
                index_created = True
            else:
                table.add(all_data)

        # Create IVF-PQ index for fast approximate nearest neighbor search
        if index_created and len(all_data) >= 256:  # Need enough data for partitions
            try:
                index_start = time.time()
                vs_config = _get_vector_search_config()
                index_type = vs_config.get("index_type", INDEX_TYPE)

                if index_type == "IVF_PQ":
                    num_partitions = min(
                        vs_config.get("num_partitions", NUM_PARTITIONS),
                        len(all_data) // 10,  # At least 10 vectors per partition
                    )
                    num_sub_vectors = vs_config.get("num_sub_vectors", NUM_SUB_VECTORS)

                    table.create_index(
                        metric="cosine",
                        num_partitions=num_partitions,
                        num_sub_vectors=min(num_sub_vectors, EMBEDDING_DIM),
                        index_type="IVF_PQ",
                    )
                    stats["index_type"] = "IVF_PQ"
                    stats["num_partitions"] = num_partitions

                elif index_type == "IVF_FLAT":
                    num_partitions = min(vs_config.get("num_partitions", NUM_PARTITIONS), len(all_data) // 10)
                    table.create_index(
                        metric="cosine",
                        num_partitions=num_partitions,
                        index_type="IVF_FLAT",
                    )
                    stats["index_type"] = "IVF_FLAT"
                    stats["num_partitions"] = num_partitions

                else:
                    # FLAT = no index (brute force)
                    stats["index_type"] = "FLAT"

                stats["index_time_ms"] = (time.time() - index_start) * 1000
                logger.info(f"Created {stats.get('index_type', 'FLAT')} index in {stats['index_time_ms']:.0f}ms")

            except Exception as e:
                logger.warning(f"Failed to create index (falling back to brute force): {e}")
                stats["index_type"] = "FLAT"
                stats["index_error"] = str(e)
        elif len(all_data) < 256:
            stats["index_type"] = "FLAT"
            stats["index_note"] = "Too few vectors for IVF index, using brute force"

    # Save metadata
    metadata = {
        "project": project,
        "indexed_at": datetime.now().isoformat(),
        "file_hashes": new_hashes,
        "stats": stats,
        "index_config": {
            "type": stats.get("index_type", "FLAT"),
            "num_partitions": stats.get("num_partitions", 0),
            "embedding_dim": EMBEDDING_DIM,
            "embedding_model": DEFAULT_EMBEDDING_MODEL,
        },
    }
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    return stats


def _search_code(
    query: str,
    project: str,
    limit: int = 10,
    file_filter: str = "",
    type_filter: str = "",
    auto_update: bool = True,
    nprobes: int | None = None,
) -> list[dict]:
    """
    Search indexed code semantically.

    Uses IVF-PQ index for fast approximate nearest neighbor search when available.
    Query embeddings are cached for repeated queries.

    Args:
        query: Natural language query
        project: Project name
        limit: Max results to return
        file_filter: Filter by file path pattern
        type_filter: Filter by code type (function, class, etc.)
        auto_update: Auto-update stale indexes
        nprobes: Number of partitions to search (higher = more accurate, slower)
                 Default from config or DEFAULT_NPROBES

    Returns list of matching code chunks with relevance scores.
    """
    start_time = time.time()

    # Auto-update if stale
    if auto_update:
        update_stats = _auto_update_if_stale(project)
        if update_stats and "error" not in update_stats:
            logger.info(f"Auto-updated index: {update_stats.get('files_indexed', 0)} files")

    # Get LanceDB connection
    db = _get_lance_db(project)
    table_name = _get_table_name(project)

    if table_name not in db.table_names():
        return [{"error": f"Project '{project}' not indexed. Run code_index first."}]

    table = db.open_table(table_name)

    # Get embedding model and encode query (with caching)
    model = _get_embedding_model()
    embed_start = time.time()
    query_embedding = _get_cached_embedding(query, model)
    embed_time_ms = (time.time() - embed_start) * 1000

    # Get search config
    vs_config = _get_vector_search_config()
    if nprobes is None:
        nprobes = vs_config.get("nprobes", DEFAULT_NPROBES)

    # Search with nprobes for IVF indexes
    search_start = time.time()
    search_query = table.search(query_embedding).limit(limit * 2)

    # Set nprobes if using IVF index
    try:
        search_query = search_query.nprobes(nprobes)
    except (AttributeError, TypeError):
        # nprobes not supported (FLAT index or old LanceDB version)
        pass

    results = search_query.to_pandas()
    search_time_ms = (time.time() - search_start) * 1000

    # Apply filters
    if file_filter:
        results = results[results["file_path"].str.contains(file_filter, case=False)]
    if type_filter:
        results = results[results["type"] == type_filter]

    # Limit results
    results = results.head(limit)

    # Format results
    formatted = []
    for _, row in results.iterrows():
        # Convert distance to similarity (LanceDB uses L2 distance by default, cosine for our index)
        distance = row.get("_distance", 0)
        # For cosine distance, similarity = 1 - distance (distance is 0-2 for cosine)
        similarity = max(0, 1 - distance / 2)

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

    # Track search stats with timing breakdown
    total_time_ms = (time.time() - start_time) * 1000
    _update_search_stats(
        project,
        total_time_ms,
        {
            "embed_time_ms": embed_time_ms,
            "search_time_ms": search_time_ms,
            "cache_hit": embed_time_ms < 1,  # Cache hits are < 1ms
            "nprobes": nprobes,
        },
    )

    return formatted


def _get_index_stats(project: str) -> dict:
    """Get comprehensive statistics about indexed project."""
    metadata_path = VECTOR_DB_PATH / project / "metadata.json"
    db_path = VECTOR_DB_PATH / project

    if not metadata_path.exists():
        return {"indexed": False, "project": project}

    with open(metadata_path) as f:
        metadata = json.load(f)

    # Get table stats
    chunk_count = 0
    try:
        db = _get_lance_db(project)
        table_name = _get_table_name(project)
        if table_name in db.table_names():
            table = db.open_table(table_name)
            chunk_count = len(table)
    except Exception:
        pass

    # Calculate disk size
    disk_size_bytes = 0
    if db_path.exists():
        for f in db_path.rglob("*"):
            if f.is_file():
                disk_size_bytes += f.stat().st_size

    # Format disk size
    if disk_size_bytes >= 1024 * 1024:
        disk_size = f"{disk_size_bytes / (1024 * 1024):.1f} MB"
    elif disk_size_bytes >= 1024:
        disk_size = f"{disk_size_bytes / 1024:.1f} KB"
    else:
        disk_size = f"{disk_size_bytes} B"

    # Calculate index age
    indexed_at = metadata.get("indexed_at", "")
    index_age = ""
    is_stale = False
    if indexed_at:
        try:
            indexed_time = datetime.fromisoformat(indexed_at)
            age = datetime.now() - indexed_time
            if age.days > 0:
                index_age = f"{age.days}d ago"
            elif age.seconds >= 3600:
                index_age = f"{age.seconds // 3600}h ago"
            elif age.seconds >= 60:
                index_age = f"{age.seconds // 60}m ago"
            else:
                index_age = "just now"
            is_stale = age > timedelta(minutes=INDEX_STALE_MINUTES)
        except Exception:
            pass

    # Get search stats
    search_stats = metadata.get("search_stats", {})

    # Get index config
    index_config = metadata.get("index_config", {})

    # Get global cache stats
    cache_stats = _embedding_cache.stats()

    return {
        "indexed": True,
        "project": project,
        "indexed_at": indexed_at,
        "index_age": index_age,
        "is_stale": is_stale,
        "files_indexed": metadata.get("stats", {}).get("files_indexed", 0),
        "files_total": len(metadata.get("file_hashes", {})),
        "chunks_count": chunk_count,
        "disk_size": disk_size,
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


def _update_search_stats(project: str, search_time_ms: float, details: dict | None = None) -> None:
    """Update search statistics in metadata."""
    metadata_path = VECTOR_DB_PATH / project / "metadata.json"

    if not metadata_path.exists():
        return

    try:
        with open(metadata_path) as f:
            metadata = json.load(f)

        search_stats = metadata.get(
            "search_stats",
            {
                "total_searches": 0,
                "total_search_time_ms": 0,
                "last_search": None,
                "avg_search_time_ms": 0,
                "cache_hits": 0,
                "cache_misses": 0,
                "avg_embed_time_ms": 0,
                "avg_vector_search_time_ms": 0,
            },
        )

        search_stats["total_searches"] += 1
        search_stats["total_search_time_ms"] += search_time_ms
        search_stats["last_search"] = datetime.now().isoformat()
        search_stats["avg_search_time_ms"] = round(
            search_stats["total_search_time_ms"] / search_stats["total_searches"], 1
        )

        # Track detailed timing if provided
        if details:
            if details.get("cache_hit"):
                search_stats["cache_hits"] = search_stats.get("cache_hits", 0) + 1
            else:
                search_stats["cache_misses"] = search_stats.get("cache_misses", 0) + 1

            # Running average for embed time
            embed_time = details.get("embed_time_ms", 0)
            prev_avg_embed = search_stats.get("avg_embed_time_ms", 0)
            n = search_stats["total_searches"]
            search_stats["avg_embed_time_ms"] = round((prev_avg_embed * (n - 1) + embed_time) / n, 2)

            # Running average for vector search time
            vector_time = details.get("search_time_ms", 0)
            prev_avg_vector = search_stats.get("avg_vector_search_time_ms", 0)
            search_stats["avg_vector_search_time_ms"] = round((prev_avg_vector * (n - 1) + vector_time) / n, 2)

        metadata["search_stats"] = search_stats

        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)
    except Exception as e:
        logger.debug(f"Failed to update search stats: {e}")


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
    watcher_mod = _import_watcher()
    get_watcher = watcher_mod.get_watcher

    config = _load_config()
    projects = list(config.get("repositories", {}).keys())
    vs_config = config.get("vector_search", {})

    result = {
        "projects": [],
        "totals": {
            "indexed_count": 0,
            "total_chunks": 0,
            "total_files": 0,
            "total_size_bytes": 0,
            "total_size": "0 B",
            "total_searches": 0,
            "watchers_active": 0,
            "total_cache_hits": 0,
            "total_cache_misses": 0,
        },
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

        if stats.get("indexed"):
            watcher = get_watcher(proj)
            watcher_active = watcher.is_running if watcher else False

            project_stats = {
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

            result["projects"].append(project_stats)
            result["totals"]["indexed_count"] += 1
            result["totals"]["total_chunks"] += stats.get("chunks_count", 0)
            result["totals"]["total_files"] += stats.get("files_total", 0)
            result["totals"]["total_size_bytes"] += stats.get("disk_size_bytes", 0)
            result["totals"]["total_searches"] += stats.get("search_count", 0)
            result["totals"]["total_cache_hits"] += stats.get("cache_hits", 0)
            result["totals"]["total_cache_misses"] += stats.get("cache_misses", 0)
            if watcher_active:
                result["totals"]["watchers_active"] += 1
        else:
            result["projects"].append(
                {
                    "project": proj,
                    "indexed": False,
                }
            )

    # Format total size
    total_bytes = result["totals"]["total_size_bytes"]
    if total_bytes >= 1024 * 1024:
        result["totals"]["total_size"] = f"{total_bytes / (1024 * 1024):.1f} MB"
    elif total_bytes >= 1024:
        result["totals"]["total_size"] = f"{total_bytes / 1024:.1f} KB"
    else:
        result["totals"]["total_size"] = f"{total_bytes} B"

    # Calculate overall cache hit rate
    total_cache = result["totals"]["total_cache_hits"] + result["totals"]["total_cache_misses"]
    if total_cache > 0:
        result["totals"]["cache_hit_rate"] = f"{result['totals']['total_cache_hits'] / total_cache * 100:.1f}%"
    else:
        result["totals"]["cache_hit_rate"] = "N/A"

    return result


def get_vector_health() -> dict:
    """
    Get health status and performance metrics for vector search.

    Returns:
        Health dashboard with performance indicators and recommendations.
    """
    stats = get_all_vector_stats()

    health = {
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

    # Calculate average search time across all projects
    search_times = [p.get("avg_search_ms", 0) for p in stats["projects"] if p.get("indexed")]
    if search_times:
        health["metrics"]["avg_search_time_ms"] = round(sum(search_times) / len(search_times), 1)

    # Check for issues
    for proj in stats["projects"]:
        if not proj.get("indexed"):
            health["issues"].append(f"Project '{proj['project']}' not indexed")
            continue

        if proj.get("is_stale"):
            health["issues"].append(f"Project '{proj['project']}' index is stale ({proj.get('index_age', 'unknown')})")

        if proj.get("index_type") == "FLAT" and proj.get("chunks", 0) > 1000:
            health["recommendations"].append(
                f"Project '{proj['project']}' has {proj['chunks']} vectors but no ANN index. "
                "Re-index to create IVF-PQ index for faster search."
            )

        if proj.get("avg_search_ms", 0) > 500:
            health["issues"].append(f"Project '{proj['project']}' search is slow ({proj['avg_search_ms']:.0f}ms avg)")

    # Check cache effectiveness
    cache_stats = stats.get("cache", {})
    if cache_stats.get("size", 0) >= cache_stats.get("max_size", 1000) * 0.9:
        health["recommendations"].append(
            "Embedding cache is nearly full. Consider increasing cache_max_size in config."
        )

    # Overall status
    if health["issues"]:
        health["status"] = "degraded" if len(health["issues"]) < 3 else "unhealthy"

    return health


# ============================================================================
# MCP Tool Registration
# ============================================================================


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
        if not project:
            # Try to detect from config
            config = _load_config()
            projects = list(config.get("repositories", {}).keys())
            if len(projects) == 1:
                project = projects[0]
            else:
                return [TextContent(type="text", text=f"❌ Please specify a project. Available: {', '.join(projects)}")]

        try:
            stats = _index_project(project, force=force)

            if "error" in stats:
                return [TextContent(type="text", text=f"❌ {stats['error']}")]

            # Build result message
            index_type = stats.get("index_type", "FLAT")
            index_info = f"- Index type: **{index_type}**"
            if stats.get("num_partitions"):
                index_info += f" ({stats['num_partitions']} partitions)"
            if stats.get("index_time_ms"):
                index_info += f"\n- Index build time: {stats['index_time_ms']:.0f}ms"
            if stats.get("index_note"):
                index_info += f"\n- Note: {stats['index_note']}"

            result = f"""✅ **Indexed {project}**

📊 **Statistics:**
- Files indexed: {stats['files_indexed']}
- Files skipped (unchanged): {stats['files_skipped']}
- Code chunks created: {stats['chunks_created']}
{index_info}
"""
            if stats["errors"]:
                result += f"\n⚠️ **Errors ({len(stats['errors'])}):**\n"
                for err in stats["errors"][:5]:
                    result += f"- {err}\n"
                if len(stats["errors"]) > 5:
                    result += f"- ... and {len(stats['errors']) - 5} more\n"

            result += f"\n💡 Now use `code_search('{project}', 'your query')` to search semantically."
            result += f"\n🏥 Use `code_health()` to check performance metrics."

            return [TextContent(type="text", text=result)]

        except ImportError as e:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Missing dependency: {e}\n\nInstall with:\n```\npip install lancedb sentence-transformers\n```",
                )
            ]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Indexing failed: {e}")]

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
        if not project:
            config = _load_config()
            projects = list(config.get("repositories", {}).keys())
            if len(projects) == 1:
                project = projects[0]
            else:
                return [TextContent(type="text", text=f"❌ Please specify a project. Available: {', '.join(projects)}")]

        try:
            results = _search_code(
                query=query,
                project=project,
                limit=limit,
                file_filter=file_filter,
                type_filter=type_filter,
            )

            if not results:
                return [
                    TextContent(
                        type="text",
                        text=f"No results found for: {query}\n\nTry a different query or check if the project is indexed with `code_stats('{project}')`",
                    )
                ]

            if "error" in results[0]:
                return [TextContent(type="text", text=f"❌ {results[0]['error']}")]

            output = f'## 🔍 Search Results for: "{query}"\n\n'

            for i, result in enumerate(results, 1):
                output += f"### {i}. `{result['file_path']}` (lines {result['start_line']}-{result['end_line']})\n"
                output += f"**Type:** {result['type']} | **Name:** {result['name']} | **Relevance:** {result['similarity']:.0%}\n\n"

                # Truncate long content
                content = result["content"]
                if len(content) > 800:
                    content = content[:800] + "\n... (truncated)"

                output += f"```{result['language']}\n{content}\n```\n\n"

            return [TextContent(type="text", text=output)]

        except ImportError as e:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Missing dependency: {e}\n\nInstall with:\n```\npip install lancedb sentence-transformers\n```",
                )
            ]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Search failed: {e}")]

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
        watcher_mod = _import_watcher()
        get_watcher = watcher_mod.get_watcher

        config = _load_config()
        projects = list(config.get("repositories", {}).keys())

        if project:
            projects = [project] if project in projects else []

        if not projects:
            return [TextContent(type="text", text=f"❌ Project '{project}' not found in config.json")]

        output = "## 📊 Code Index Statistics\n\n"

        # Summary stats
        total_chunks = 0
        total_size_bytes = 0
        total_searches = 0

        for proj in projects:
            stats = _get_index_stats(proj)

            if stats.get("indexed"):
                total_chunks += stats.get("chunks_count", 0)
                total_size_bytes += stats.get("disk_size_bytes", 0)
                total_searches += stats.get("search_count", 0)

                # Status indicator
                stale_indicator = "⚠️ STALE" if stats.get("is_stale") else ""
                watcher = get_watcher(proj)
                watcher_indicator = "👁️" if watcher and watcher.is_running else ""

                output += f"### ✅ {proj} {stale_indicator} {watcher_indicator}\n\n"

                output += "| Metric | Value |\n"
                output += "|--------|-------|\n"
                output += f"| **Files** | {stats.get('files_total', 0)} indexed |\n"
                output += f"| **Chunks** | {stats.get('chunks_count', 0):,} |\n"
                output += f"| **Disk Size** | {stats.get('disk_size', '0 B')} |\n"
                output += f"| **Last Indexed** | {stats.get('index_age', 'Unknown')} |\n"
                output += f"| **Model** | `{stats.get('embedding_model', 'unknown')}` |\n"

                # Search stats
                if stats.get("search_count", 0) > 0:
                    output += f"| **Searches** | {stats.get('search_count', 0):,} total |\n"
                    output += f"| **Avg Search Time** | {stats.get('avg_search_time_ms', 0):.0f}ms |\n"

                # Watcher status
                if watcher:
                    ws = watcher.status
                    output += f"| **Watcher** | {'🟢 Active' if ws['running'] else '🔴 Stopped'} |\n"
                    if ws.get("changes_pending", 0) > 0:
                        output += f"| **Pending Changes** | {ws['changes_pending']} |\n"

                output += "\n"
            else:
                output += f"### ❌ {proj} (not indexed)\n"
                output += f"Run `code_index('{proj}')` to index.\n\n"

        # Overall summary if multiple projects
        if len(projects) > 1:
            if total_size_bytes >= 1024 * 1024:
                total_size = f"{total_size_bytes / (1024 * 1024):.1f} MB"
            elif total_size_bytes >= 1024:
                total_size = f"{total_size_bytes / 1024:.1f} KB"
            else:
                total_size = f"{total_size_bytes} B"

            output += "---\n\n"
            output += f"**Total:** {total_chunks:,} chunks, {total_size}, {total_searches:,} searches\n"

        return [TextContent(type="text", text=output)]

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
        # Check if indexed
        stats = _get_index_stats(project)
        if not stats.get("indexed"):
            # Index first
            index_result = _index_project(project)
            if "error" in index_result:
                return [TextContent(type="text", text=f"❌ {index_result['error']}")]
            stats = _get_index_stats(project)

        # Define semantic queries to understand the codebase
        queries = [
            ("API routes and endpoints", "api"),
            ("Database models and schemas", "models"),
            ("Authentication and authorization", "auth"),
            ("Error handling and exceptions", "errors"),
            ("Configuration and settings", "config"),
            ("Background tasks and workers", "tasks"),
            ("Data validation and input checking", "validation"),
            ("External service integrations", "integrations"),
            ("Logging and monitoring", "logging"),
            ("Testing patterns and fixtures", "testing"),
        ]

        findings = {}

        for query, key in queries:
            try:
                results = _search_code(query, project, limit=5)
                if results and "error" not in results[0]:
                    findings[key] = results
            except Exception:
                pass

        # Format findings for Claude to analyze
        output = f"""## 🔬 Deep Scan Results: {project}

**Indexed:** {stats.get('chunks_count', 0)} code chunks from {stats.get('file_count', 0)} files

---

### 📋 Findings by Category

"""

        for key, results in findings.items():
            output += f"#### {key.replace('_', ' ').title()}\n\n"
            for r in results[:3]:  # Top 3 per category
                output += f"- `{r['file_path']}:{r['start_line']}` - {r['type']} `{r['name']}` ({r['similarity']:.0%} match)\n"
            output += "\n"

        output += """---

### 🧠 Claude Analysis Instructions

Based on these findings, please:

1. **Summarize the architecture** - How is the system structured?
2. **Identify key modules** - What are the important directories?
3. **Document patterns** - What coding/testing/deployment patterns are used?
4. **Note gotchas** - Any non-obvious behaviors or potential issues?

Then use `knowledge_update()` to save findings to memory:

```python
knowledge_update("PROJECT", "developer", "architecture.overview", "Your summary...")
knowledge_update("PROJECT", "developer", "gotchas", "- issue: X\\n  reason: Y\\n  solution: Z")
```
""".replace(
            "PROJECT", project
        )

        return [TextContent(type="text", text=output)]

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
        watcher_mod = _import_watcher()
        get_all_watchers = watcher_mod.get_all_watchers
        start_watcher = watcher_mod.start_watcher
        stop_watcher = watcher_mod.stop_watcher

        if action == "status":
            watchers = get_all_watchers()
            if not watchers:
                return [
                    TextContent(
                        type="text",
                        text="## 👁️ Code Watchers\n\nNo active watchers.\n\nStart one with `code_watch('project', 'start')`",
                    )
                ]

            output = "## 👁️ Code Watchers\n\n"
            for proj, watcher in watchers.items():
                status = watcher.status
                output += f"### {'🟢' if status['running'] else '🔴'} {proj}\n"
                output += f"- **Running:** {status['running']}\n"
                output += f"- **Last update:** {status['last_update'] or 'Never'}\n"
                output += f"- **Pending changes:** {status['changes_pending']}\n"
                output += f"- **Debounce:** {status['debounce_seconds']}s\n\n"

            return [TextContent(type="text", text=output)]

        if not project:
            config = _load_config()
            projects = list(config.get("repositories", {}).keys())
            return [TextContent(type="text", text=f"❌ Please specify a project. Available: {', '.join(projects)}")]

        project_path = _get_project_path(project)
        if not project_path or not project_path.exists():
            return [TextContent(type="text", text=f"❌ Project path not found: {project}")]

        if action == "start":
            try:
                # Ensure project is indexed first
                stats = _get_index_stats(project)
                if not stats.get("indexed"):
                    return [
                        TextContent(
                            type="text",
                            text=f"❌ Project '{project}' not indexed. Run `code_index('{project}')` first.",
                        )
                    ]

                watcher = await start_watcher(
                    project=project,
                    project_path=project_path,
                    index_func=_index_project,
                    debounce_seconds=debounce_seconds,
                )

                return [
                    TextContent(
                        type="text",
                        text=f"""✅ **Started watching {project}**

📁 Path: `{project_path}`
⏱️ Debounce: {debounce_seconds}s (waits for quiet period before re-indexing)

The index will automatically update when you save files.
Use `code_watch(action='status')` to check watcher status.
Use `code_watch('{project}', 'stop')` to stop watching.
""",
                    )
                ]

            except ImportError as e:
                return [
                    TextContent(
                        type="text",
                        text=f"❌ Missing dependency: {e}\n\nInstall with:\n```\npip install watchfiles\n```",
                    )
                ]
            except Exception as e:
                return [TextContent(type="text", text=f"❌ Failed to start watcher: {e}")]

        elif action == "stop":
            stopped = await stop_watcher(project)
            if stopped:
                return [TextContent(type="text", text=f"✅ Stopped watching {project}")]
            else:
                return [TextContent(type="text", text=f"⚠️ No active watcher for {project}")]

        else:
            return [TextContent(type="text", text=f"❌ Unknown action: {action}. Use 'start', 'stop', or 'status'.")]

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
        watcher_mod = _import_watcher()
        start_watcher = watcher_mod.start_watcher
        stop_all_watchers = watcher_mod.stop_all_watchers

        config = _load_config()
        projects = list(config.get("repositories", {}).keys())

        if action == "start":
            results = []
            for project in projects:
                project_path = _get_project_path(project)
                if not project_path or not project_path.exists():
                    results.append(f"⚠️ {project}: path not found")
                    continue

                stats = _get_index_stats(project)
                if not stats.get("indexed"):
                    results.append(f"⚠️ {project}: not indexed (run code_index first)")
                    continue

                try:
                    await start_watcher(
                        project=project,
                        project_path=project_path,
                        index_func=_index_project,
                        debounce_seconds=debounce_seconds,
                    )
                    results.append(f"✅ {project}: watching")
                except Exception as e:
                    results.append(f"❌ {project}: {e}")

            output = "## 👁️ Started Watchers\n\n"
            output += "\n".join(results)
            output += f"\n\n**Debounce:** {debounce_seconds}s"

            return [TextContent(type="text", text=output)]

        elif action == "stop":
            count = await stop_all_watchers()
            return [TextContent(type="text", text=f"✅ Stopped {count} watcher(s)")]

        else:
            return [TextContent(type="text", text=f"❌ Unknown action: {action}. Use 'start' or 'stop'.")]

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
        try:
            health = get_vector_health()
            stats = get_all_vector_stats()

            # Status emoji
            status_emoji = {
                "healthy": "🟢",
                "degraded": "🟡",
                "unhealthy": "🔴",
            }.get(health["status"], "⚪")

            output = f"""## 🏥 Vector Search Health

### Status: {status_emoji} {health['status'].upper()}

---

### 📊 Performance Metrics

| Metric | Value |
|--------|-------|
| **Indexed Projects** | {health['metrics']['indexed_projects']} |
| **Total Vectors** | {health['metrics']['total_vectors']:,} |
| **Avg Search Time** | {health['metrics']['avg_search_time_ms']:.1f}ms |
| **Cache Hit Rate** | {health['metrics']['cache_hit_rate']} |

---

### ⚙️ Configuration

| Setting | Value |
|---------|-------|
| **Index Type** | {stats['config']['index_type']} |
| **nprobes** | {stats['config']['nprobes']} |
| **Embedding Model** | `{stats['config']['embedding_model']}` |
| **Embedding Backend** | {stats['config']['embedding_backend']} |
| **Cache Enabled** | {stats['config']['cache_enabled']} |

---

### 🔄 Cache Status

| Metric | Value |
|--------|-------|
| **Cache Size** | {stats['cache']['size']} / {stats['cache']['max_size']} |
| **Session Hit Rate** | {stats['cache']['hit_rate']} |
| **Total Hits** | {stats['cache']['hits']} |
| **Total Misses** | {stats['cache']['misses']} |

"""

            if health["issues"]:
                output += "---\n\n### ⚠️ Issues\n\n"
                for issue in health["issues"]:
                    output += f"- {issue}\n"
                output += "\n"

            if health["recommendations"]:
                output += "---\n\n### 💡 Recommendations\n\n"
                for rec in health["recommendations"]:
                    output += f"- {rec}\n"
                output += "\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [TextContent(type="text", text=f"❌ Health check failed: {e}")]

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
        if action == "clear":
            _embedding_cache.clear()
            return [TextContent(type="text", text="✅ Embedding cache cleared")]

        stats = _embedding_cache.stats()

        output = f"""## 🗄️ Embedding Cache

| Metric | Value |
|--------|-------|
| **Size** | {stats['size']} / {stats['max_size']} |
| **Hit Rate** | {stats['hit_rate']} |
| **Hits** | {stats['hits']} |
| **Misses** | {stats['misses']} |

💡 Cache stores query embeddings to speed up repeated searches.
Use `code_cache('clear')` to clear the cache.
"""

        return [TextContent(type="text", text=output)]


