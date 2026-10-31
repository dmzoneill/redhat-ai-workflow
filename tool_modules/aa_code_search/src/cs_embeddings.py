"""Embedding backends (sentence-transformers, OpenVINO, ONNX), LanceDB loader and query cache."""

import importlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

from tool_modules.aa_code_search.src import cs_config
from tool_modules.aa_code_search.src.cs_config import (
    _INDEX_ERRORS,
    CACHE_MAX_SIZE,
    CACHE_TTL_SECONDS,
    DEFAULT_EMBEDDING_MODEL,
    _get_vector_search_config,
)

logger = logging.getLogger(__name__)

_HF_MODEL_NAME = f"sentence-transformers/{DEFAULT_EMBEDDING_MODEL}"


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


@dataclass
class _LoadedModels:
    """Lazily loaded heavy dependencies, shared by the whole process."""

    lancedb: Any = None
    sentence_transformer: Any = None
    openvino_model: Any = None


_MODELS = _LoadedModels()


@dataclass
class OpenVINOEmbedder:
    """Adapter exposing encode() for an OpenVINO model (GPU/CPU, dynamic shapes)."""

    model: Any
    tokenizer: Any
    device: str

    def encode(self, texts: str | list[str], **_kwargs: Any) -> Any:
        """Return embeddings for one string or a list of strings."""
        if isinstance(texts, str):
            texts = [texts]

        inputs = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )

        outputs = self.model(**inputs)
        # Mean pooling
        embeddings = outputs.last_hidden_state.mean(dim=1)
        return embeddings.numpy()


@dataclass
class OpenVINONPUEmbedder:
    """Embedder using NPU with fixed input shapes."""

    compiled_model: Any
    tokenizer: Any
    seq_len: int
    infer_request: Any = field(init=False)

    def __post_init__(self) -> None:
        self.infer_request = self.compiled_model.create_infer_request()

    def encode(self, texts: str | list[str], **_kwargs: Any) -> Any:
        """Return embeddings for one string or a list of strings."""
        np = importlib.import_module("numpy")
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

        # Get output and apply mean pooling with attention mask
        last_hidden_state = self.infer_request.get_output_tensor(0).data.copy()
        mask_expanded = np.expand_dims(inputs["attention_mask"], -1)
        sum_embeddings = np.sum(last_hidden_state * mask_expanded, axis=1)
        sum_mask = np.clip(np.sum(mask_expanded, axis=1), a_min=1e-9, a_max=None)
        return sum_embeddings / sum_mask


def _get_cached_embedding(query: str, model: Any) -> list[float]:
    """Get embedding with caching."""
    if not cs_config.CACHE_ENABLED:
        return model.encode([query])[0].tolist()

    # Check cache
    cached = _embedding_cache.get(query)
    if cached is not None:
        return cached

    # Generate and cache
    embedding = model.encode([query])[0].tolist()
    _embedding_cache.put(query, embedding)
    return embedding


def _get_lancedb() -> Any:
    """Lazy load lancedb."""
    if _MODELS.lancedb is None:
        try:
            _MODELS.lancedb = importlib.import_module("lancedb")
        except ImportError as e:
            raise ImportError("lancedb not installed. Run: uv add lancedb") from e
    return _MODELS.lancedb


def _embedding_options() -> dict:
    """The ``vector_search.embedding`` section of config.json."""
    return _get_vector_search_config().get("embedding", {})


def _backend_options(backend: str) -> dict:
    """Per-backend options from ``vector_search.embedding.backend_options``."""
    return _embedding_options().get("backend_options", {}).get(backend, {})


def _get_embedding_model() -> Any:
    """
    Lazy load embedding model with backend selection.

    Supports:
    - sentence-transformers (default, CPU)
    - openvino (Intel NPU/iGPU acceleration)
    - onnx (ONNX Runtime with CUDA/CPU)
    """
    backend = _embedding_options().get("backend", "sentence-transformers")

    # Try OpenVINO backend
    if backend == "openvino" and _MODELS.openvino_model is None:
        try:
            _MODELS.openvino_model = _load_openvino_model()
            if _MODELS.openvino_model:
                logger.info("Using OpenVINO embedding backend")
                return _MODELS.openvino_model
        # Intentional: log the failure and continue at this boundary.
        except _INDEX_ERRORS as e:
            logger.warning("OpenVINO backend failed, falling back: %s", e)

    # Try ONNX backend
    if backend == "onnx" and _MODELS.sentence_transformer is None:
        try:
            _MODELS.sentence_transformer = _load_onnx_model()
            if _MODELS.sentence_transformer:
                logger.info("Using ONNX embedding backend")
                return _MODELS.sentence_transformer
        # Intentional: log the failure and continue at this boundary.
        except _INDEX_ERRORS as e:
            logger.warning("ONNX backend failed, falling back: %s", e)

    # Default: sentence-transformers
    if _MODELS.sentence_transformer is None:
        try:
            sentence_transformers = importlib.import_module("sentence_transformers")
        except ImportError as e:
            raise ImportError("sentence-transformers not installed. Run: uv add sentence-transformers") from e
        _MODELS.sentence_transformer = sentence_transformers.SentenceTransformer(DEFAULT_EMBEDDING_MODEL)
        logger.info("Using sentence-transformers embedding backend")
    return _MODELS.sentence_transformer


def _load_openvino_model() -> Any:
    """
    Load embedding model with OpenVINO for NPU/iGPU acceleration.

    For NPU: Uses fixed input shapes (padding to max_length) to avoid
    dynamic shape compilation errors.

    Requires: uv add optimum[openvino] openvino
    """
    try:
        transformers = importlib.import_module("transformers")

        device = _backend_options("openvino").get("device", "NPU")

        # For NPU, we need fixed shapes - use static compilation
        if device == "NPU":
            return _load_openvino_npu_static()

        # For GPU/CPU, dynamic shapes work fine
        optimum_intel = importlib.import_module("optimum.intel")
        tokenizer = transformers.AutoTokenizer.from_pretrained(_HF_MODEL_NAME)
        model = optimum_intel.OVModelForFeatureExtraction.from_pretrained(
            _HF_MODEL_NAME,
            export=True,
            device=device,
        )
        return OpenVINOEmbedder(model, tokenizer, device)

    except ImportError as e:
        logger.debug("OpenVINO not available: %s", e)
        return None
    # Intentional: convert the failure into an error result for the caller.
    except _INDEX_ERRORS as e:
        logger.warning("Failed to load OpenVINO model: %s", e)
        return None


def _export_static_npu_model(ov: Any, ir_path: Path, seq_len: int) -> None:
    """Export the model with static input shapes to ``ir_path`` (once; cached on disk)."""
    logger.info("Exporting model with fixed shape (seq_len=%s) for NPU...", seq_len)

    # Export to CPU first, then reshape and compile for NPU
    optimum_intel = importlib.import_module("optimum.intel")
    ov_model = optimum_intel.OVModelForFeatureExtraction.from_pretrained(
        _HF_MODEL_NAME,
        export=True,
        compile=False,  # Don't compile yet
    )

    # Reshape to static dimensions
    model = ov_model.model
    model.reshape(
        {
            "input_ids": [1, seq_len],
            "attention_mask": [1, seq_len],
            "token_type_ids": [1, seq_len],
        }
    )

    ov.save_model(model, str(ir_path))
    logger.info("Saved static NPU model to %s", ir_path)


def _load_openvino_npu_static() -> Any:
    """
    Load embedding model for NPU with FIXED input shapes.

    NPU requires static shapes - we pad all inputs to a fixed length.
    Uses optimum-intel's export with static shapes.
    """
    try:
        ov = importlib.import_module("openvino")
        transformers = importlib.import_module("transformers")

        # Fixed sequence length for NPU (shorter = faster, but truncates long queries)
        fixed_seq_len = _backend_options("openvino").get("fixed_seq_len", 128)

        cache_dir = cs_config.vector_db_path() / "openvino_cache" / f"npu_seq{fixed_seq_len}"
        cache_dir.mkdir(parents=True, exist_ok=True)

        ir_path = cache_dir / "openvino_model.xml"
        tokenizer = transformers.AutoTokenizer.from_pretrained(_HF_MODEL_NAME)
        core = ov.Core()

        if not ir_path.exists():
            _export_static_npu_model(ov, ir_path, fixed_seq_len)

        logger.info("Compiling model for NPU (fixed seq_len=%s)...", fixed_seq_len)
        compiled_model = core.compile_model(core.read_model(str(ir_path)), "NPU", {"PERFORMANCE_HINT": "LATENCY"})

        embedder = OpenVINONPUEmbedder(compiled_model, tokenizer, fixed_seq_len)
        logger.info("✅ NPU embedder ready with fixed shapes")
        return embedder

    # Intentional: convert the failure into an error result for the caller.
    except _INDEX_ERRORS as e:
        logger.warning("Failed to load NPU static model: %s", e, exc_info=True)
        return None


def _load_onnx_model() -> Any:
    """
    Load embedding model with ONNX Runtime for GPU acceleration.

    Requires: uv add onnxruntime-gpu (or onnxruntime for CPU)
    """
    try:
        sentence_transformers = importlib.import_module("sentence_transformers")
        providers = _backend_options("onnx").get("providers", ["CUDAExecutionProvider", "CPUExecutionProvider"])

        # SentenceTransformers can use ONNX backend
        return sentence_transformers.SentenceTransformer(
            DEFAULT_EMBEDDING_MODEL,
            backend="onnx",
            model_kwargs={"providers": providers},
        )

    # Intentional: convert the failure into an error result for the caller.
    except _INDEX_ERRORS as e:
        logger.debug("ONNX backend not available: %s", e)
        return None


def _get_lance_db(project: str) -> Any:
    """Get or create LanceDB connection for a project."""
    lancedb = _get_lancedb()
    db_path = cs_config.vector_db_path() / project
    db_path.mkdir(parents=True, exist_ok=True)
    return lancedb.connect(str(db_path))
