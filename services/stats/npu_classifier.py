"""NPU-accelerated competency classifier using sentence-transformers with OpenVINO.

Uses all-MiniLM-L6-v2 model to compute embedding similarity between event text
and competency descriptors, providing bonus classification signals that complement
keyword-based matching.
"""

import logging
import time
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class NPUCompetencyClassifier:
    """Embedding similarity classifier for competency mapping."""

    def __init__(
        self,
        device: str = "CPU",
        confidence_threshold: float = 0.35,
        bonus_signals: int = 2,
    ):
        self.model: Any = None
        self.competency_embeddings: dict[str, np.ndarray] = {}
        self.enabled = False
        self.confidence_threshold = confidence_threshold
        self.bonus_signals = bonus_signals
        self.device = device
        self.stats = {
            "total_inferences": 0,
            "avg_latency_ms": 0.0,
            "model_name": "",
            "device_used": "",
        }

    async def initialize(self, competency_defs: dict, level: str = "sse") -> bool:
        """Load model and pre-compute competency embeddings.

        Re-call when level changes to update level-specific descriptors.
        """
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            logger.info("sentence-transformers not installed, NPU classifier disabled")
            return False

        model_name = "all-MiniLM-L6-v2"
        try:
            backend = "openvino"
            model_kwargs: dict[str, Any] = {}
            if self.device.upper() == "NPU":
                model_kwargs["device"] = "NPU"
            elif self.device.upper() == "CPU":
                model_kwargs["device"] = "CPU"

            try:
                self.model = SentenceTransformer(
                    model_name,
                    backend=backend,
                    model_kwargs=model_kwargs,
                )
                self.stats["device_used"] = self.device.upper()
            except Exception as e:
                logger.warning(
                    "Loading SentenceTransformer with OpenVINO backend: %s", e
                )
                self.model = SentenceTransformer(model_name)
                self.stats["device_used"] = "CPU (fallback)"

            self.stats["model_name"] = model_name
        except Exception as e:
            logger.warning(f"Failed to load embedding model: {e}")
            return False

        self._build_competency_embeddings(competency_defs, level)
        self.enabled = True
        logger.info(
            f"NPU classifier initialized: model={model_name}, "
            f"device={self.stats['device_used']}, "
            f"competencies={len(self.competency_embeddings)}"
        )
        return True

    def _build_competency_embeddings(self, competency_defs: dict, level: str) -> None:
        """Pre-compute embeddings for each competency using rich descriptors."""
        if not self.model:
            return

        from services.stats.scorer import get_level_description

        descriptors: dict[str, str] = {}
        for comp_id, defn in competency_defs.items():
            parts = [
                defn.get("name", comp_id),
                defn.get("category", ""),
                defn.get("goal", ""),
                defn.get("description", ""),
            ]
            level_data = get_level_description(comp_id, level)
            if level_data.get("title"):
                parts.append(level_data["title"])
            if level_data.get("description"):
                parts.append(level_data["description"])

            for phrase in defn.get("phrases", [])[:5]:
                parts.append(phrase)

            descriptors[comp_id] = " ".join(p for p in parts if p)

        if descriptors:
            texts = list(descriptors.values())
            ids = list(descriptors.keys())
            embeddings = self.model.encode(texts, normalize_embeddings=True)
            for i, comp_id in enumerate(ids):
                self.competency_embeddings[comp_id] = embeddings[i]

    def classify(self, classification_text: str) -> dict[str, float]:
        """Return {comp_id: confidence} for text against all competencies."""
        if not self.enabled or not self.model or not self.competency_embeddings:
            return {}

        start = time.monotonic()
        text_embedding = self.model.encode(
            [classification_text], normalize_embeddings=True
        )[0]

        results: dict[str, float] = {}
        for comp_id, comp_emb in self.competency_embeddings.items():
            similarity = float(np.dot(text_embedding, comp_emb))
            if similarity > 0:
                results[comp_id] = similarity

        elapsed_ms = (time.monotonic() - start) * 1000
        self.stats["total_inferences"] += 1
        n = self.stats["total_inferences"]
        self.stats["avg_latency_ms"] = (
            self.stats["avg_latency_ms"] * (n - 1) + elapsed_ms
        ) / n

        return results

    def get_bonus_signals(self, classification_text: str) -> dict[str, int]:
        """Return {comp_id: bonus_signal_count} for competencies above threshold.

        This is the primary interface called by map_competencies().
        """
        confidences = self.classify(classification_text)
        bonus: dict[str, int] = {}
        for comp_id, conf in confidences.items():
            if conf >= self.confidence_threshold:
                bonus[comp_id] = self.bonus_signals
        return bonus

    def get_stats(self) -> dict:
        """Return classifier performance statistics."""
        return {
            **self.stats,
            "enabled": self.enabled,
            "competencies_loaded": len(self.competency_embeddings),
            "confidence_threshold": self.confidence_threshold,
            "bonus_signals": self.bonus_signals,
        }
