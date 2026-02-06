"""
Intent Classifier - Classify query intent for source routing.

This module provides intent classification to determine which memory
sources should be queried for a given question. It supports:

1. Keyword-based fallback (always available)
2. NPU-accelerated classification (when available)
3. Learnable classification (training data in ~/.cache/aa-workflow/classifiers/)

The classifier is used by the QueryRouter to select appropriate
adapters based on the user's query intent.

Usage:
    from services.memory_abstraction.classifier import IntentClassifier

    classifier = IntentClassifier()
    result = await classifier.classify("What's the billing calculation?")
    # IntentClassification(intent="code_lookup", confidence=0.85, sources_suggested=["code"])
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import IntentClassification
from .registry import ADAPTER_MANIFEST

logger = logging.getLogger(__name__)

# Path for learned classifier models
CLASSIFIER_DIR = Path.home() / ".cache" / "aa-workflow" / "classifiers"


@dataclass
class IntentPattern:
    """Pattern for keyword-based intent matching."""

    intent: str
    patterns: list[str]  # Regex patterns
    sources: list[str]  # Suggested sources
    weight: float = 1.0  # Pattern weight for scoring


# Default intent patterns (keyword-based fallback)
DEFAULT_INTENT_PATTERNS = [
    IntentPattern(
        intent="status_check",
        patterns=[
            r"\b(what am i|working on|current|active|my issues?)\b",
            r"\b(status|progress|state)\b.*\b(work|issue|task)\b",
        ],
        sources=["yaml", "calendar"],  # Include calendar for upcoming meetings
        weight=1.0,
    ),
    IntentPattern(
        intent="code_lookup",
        patterns=[
            r"\b(function|class|method|implementation|code)\b",
            r"\b(show|find|where is|how does)\b.*\b(code|function|class)\b",
            r"\b(search|look for)\b.*\b(code|implementation)\b",
        ],
        sources=["code"],
        weight=1.0,
    ),
    IntentPattern(
        intent="troubleshooting",
        patterns=[
            r"\b(error|bug|issue|problem|wrong|broken|fix)\b",
            r"\b(why|how to fix|debug|troubleshoot)\b",
            r"\b(not working|failing|failed)\b",
        ],
        sources=["code", "yaml", "inscope"],
        weight=1.2,  # Higher weight for troubleshooting
    ),
    IntentPattern(
        intent="documentation",
        patterns=[
            r"\b(how to|configure|setup|documentation|docs)\b",
            r"\b(rds|clowder|konflux|bonfire|openshift)\b",
            r"\b(guide|tutorial|example)\b",
        ],
        sources=["inscope", "code"],
        weight=1.0,
    ),
    IntentPattern(
        intent="history",
        patterns=[
            r"\b(discussed|talked about|conversation|said)\b",
            r"\b(last time|before|previously|earlier)\b",
            r"\b(slack|message|chat)\b",
        ],
        sources=["slack"],
        weight=1.0,
    ),
    IntentPattern(
        intent="pattern_lookup",
        patterns=[
            r"\b(pattern|known fix|learned|solution)\b",
            r"\b(have we seen|encountered before)\b",
        ],
        sources=["yaml"],
        weight=1.0,
    ),
    IntentPattern(
        intent="issue_context",
        patterns=[
            r"\b(AAP|APPSRE|KONFLUX|JIRA)-\d+\b",
            r"\b(issue|ticket|jira)\b.*\b(details?|status|info)\b",
        ],
        sources=["jira", "yaml"],
        weight=1.0,
    ),
    IntentPattern(
        intent="gitlab",
        patterns=[
            r"\b(gitlab|merge request|mrs?|!?\d{3,})\b",
            r"\b(pipeline|ci|cd)\b.*\b(status|failed|passed)\b",
            r"\b(glab|approval|reviewer)\b",
            r"\b(open|my|list)\b.*\bmrs?\b",
        ],
        sources=["gitlab"],
        weight=1.0,
    ),
    IntentPattern(
        intent="github",
        patterns=[
            r"\b(github|pull request|pr|gh)\b",
            r"\b(workflow|actions|release)\b",
            r"\b(fork|star|contributor)\b",
        ],
        sources=["github"],
        weight=1.0,
    ),
    IntentPattern(
        intent="calendar",
        patterns=[
            r"\b(calendar|meeting|meetings|event|events|schedule|appointment)\b",
            r"\b(today|tomorrow|this week|next week)\b",
            r"\b(availability|when am i|standup|sync|call)\b",
            r"\b(busy|free)\b",
        ],
        sources=["calendar"],
        weight=1.0,
    ),
    IntentPattern(
        intent="email",
        patterns=[
            r"\b(email|emails|gmail|mail|inbox)\b",
            r"\b(from|to|subject)\b",
            r"\b(unread|sent|received|attachment)\b",
        ],
        sources=["gmail"],
        weight=1.0,
    ),
    IntentPattern(
        intent="files",
        patterns=[
            r"\b(drive|google drive|document|file|spreadsheet)\b",
            r"\b(sheet|slides|presentation|pdf)\b",
            r"\b(shared|my files|find file|search drive)\b",
        ],
        sources=["gdrive"],
        weight=1.0,
    ),
]


class IntentClassifier:
    """
    Classify query intent for source routing.

    Supports multiple classification strategies:
    1. Keyword-based (always available, fast)
    2. NPU-accelerated (when Ollama/NPU available)
    3. Learned model (when training data available)
    """

    def __init__(self):
        self.patterns = DEFAULT_INTENT_PATTERNS
        self._npu_client = None
        self._npu_available: bool | None = None
        self._model_loaded = False

        # Ensure classifier directory exists
        CLASSIFIER_DIR.mkdir(parents=True, exist_ok=True)

    async def classify(
        self,
        query: str,
        use_npu: bool = True,
    ) -> IntentClassification:
        """
        Classify query intent.

        Args:
            query: The query to classify
            use_npu: Whether to try NPU classification (default True)

        Returns:
            IntentClassification with intent, confidence, and suggested sources
        """
        # Try NPU classification first (if available and enabled)
        if use_npu and await self._is_npu_available():
            try:
                result = await self._npu_classify(query)
                if result and result.confidence > 0.7:
                    logger.debug(f"NPU classification: {result.intent} ({result.confidence:.2f})")
                    return result
            except Exception as e:
                logger.warning(f"NPU classification failed, falling back to keywords: {e}")

        # Fall back to keyword-based classification
        return self._keyword_classify(query)

    def _keyword_classify(self, query: str) -> IntentClassification:
        """
        Classify using keyword patterns.

        This is the fallback classifier that's always available.
        """
        query_lower = query.lower()

        # Score each intent pattern
        scores: dict[str, float] = {}
        sources_by_intent: dict[str, set[str]] = {}

        for pattern in self.patterns:
            for regex in pattern.patterns:
                if re.search(regex, query_lower, re.IGNORECASE):
                    intent = pattern.intent
                    scores[intent] = scores.get(intent, 0) + pattern.weight
                    if intent not in sources_by_intent:
                        sources_by_intent[intent] = set()
                    sources_by_intent[intent].update(pattern.sources)
                    break  # Only count first match per pattern

        if not scores:
            # No matches - return general intent
            return IntentClassification(
                intent="general",
                confidence=0.5,
                sources_suggested=self._get_default_sources(),
            )

        # Get highest scoring intent
        best_intent = max(scores, key=scores.get)
        max_score = scores[best_intent]

        # Normalize confidence (0.5 - 1.0 range)
        confidence = min(0.5 + (max_score * 0.15), 1.0)

        # Get sources for best intent, filtered by available adapters
        sources = list(sources_by_intent.get(best_intent, set()))
        sources = self._filter_available_sources(sources)

        return IntentClassification(
            intent=best_intent,
            confidence=confidence,
            sources_suggested=sources,
        )

    async def _is_npu_available(self) -> bool:
        """Check if NPU classification is available."""
        if self._npu_available is not None:
            return self._npu_available

        try:
            # Try to import the Ollama client
            from tool_modules.aa_ollama.src.client import OllamaClient

            client = OllamaClient(instance="npu")
            # Quick health check
            self._npu_available = await client.is_available()
            self._npu_client = client if self._npu_available else None

        except ImportError:
            logger.debug("Ollama client not available")
            self._npu_available = False
        except Exception as e:
            logger.debug(f"NPU not available: {e}")
            self._npu_available = False

        return self._npu_available

    async def _npu_classify(self, query: str) -> IntentClassification | None:
        """
        Classify using NPU (Ollama with qwen2.5:0.5b).

        Returns None if classification fails.
        """
        if not self._npu_client:
            return None

        # Build classification prompt
        intent_list = ", ".join(IntentClassification.INTENTS.keys())
        prompt = f"""Classify the intent of this query for a developer assistant.

Query: "{query}"

Available intents: {intent_list}

Respond with JSON only:
{{"intent": "intent_name", "confidence": 0.0-1.0, "sources": ["source1", "source2"]}}

Available sources: code, slack, yaml, inscope, jira"""

        try:
            response = await self._npu_client.generate(
                model="qwen2.5:0.5b",
                prompt=prompt,
                format="json",
                options={"temperature": 0.1},  # Low temperature for consistency
            )

            # Parse response
            data = json.loads(response)
            return IntentClassification(
                intent=data.get("intent", "general"),
                confidence=float(data.get("confidence", 0.5)),
                sources_suggested=data.get("sources", []),
            )

        except json.JSONDecodeError:
            logger.warning(f"NPU returned invalid JSON: {response[:100]}")
            return None
        except Exception as e:
            logger.warning(f"NPU classification error: {e}")
            return None

    async def learn(
        self,
        query: str,
        correct_intent: str,
        correct_sources: list[str],
    ) -> bool:
        """
        Learn from user feedback when classification was wrong.

        Appends to training data for future model retraining.

        Args:
            query: The original query
            correct_intent: The correct intent classification
            correct_sources: The correct sources to use

        Returns:
            True if learning was recorded
        """
        training_file = CLASSIFIER_DIR / "intent_training.jsonl"

        try:
            entry = {
                "query": query,
                "intent": correct_intent,
                "sources": correct_sources,
                "query_hash": hashlib.md5(query.encode()).hexdigest()[:8],
            }

            with open(training_file, "a") as f:
                f.write(json.dumps(entry) + "\n")

            logger.info(f"Recorded intent learning: {correct_intent} for '{query[:50]}...'")
            return True

        except Exception as e:
            logger.error(f"Failed to record learning: {e}")
            return False

    def _get_default_sources(self) -> list[str]:
        """Get default sources when no intent is detected."""
        # Return all available adapters with query capability
        available = ADAPTER_MANIFEST.list_by_capability("query")
        if available:
            return available
        # If no adapters discovered yet, return common defaults
        # These will be filtered by _filter_available_sources
        return ["yaml", "code", "calendar", "gmail", "gdrive"]

    def _filter_available_sources(self, sources: list[str]) -> list[str]:
        """Filter sources to only include available adapters."""
        available = set(ADAPTER_MANIFEST.list_adapters())
        if not available:
            # No adapters discovered yet - return sources as-is
            # They'll be validated when actually queried
            return sources
        filtered = [s for s in sources if s in available]
        return filtered if filtered else self._get_default_sources()

    def add_pattern(self, pattern: IntentPattern) -> None:
        """Add a custom intent pattern."""
        self.patterns.append(pattern)
        logger.debug(f"Added intent pattern: {pattern.intent}")

    def get_training_stats(self) -> dict[str, Any]:
        """Get statistics about training data."""
        training_file = CLASSIFIER_DIR / "intent_training.jsonl"

        if not training_file.exists():
            return {"count": 0, "intents": {}}

        count = 0
        intents: dict[str, int] = {}

        try:
            with open(training_file) as f:
                for line in f:
                    entry = json.loads(line)
                    count += 1
                    intent = entry.get("intent", "unknown")
                    intents[intent] = intents.get(intent, 0) + 1
        except Exception as e:
            logger.error(f"Error reading training data: {e}")

        return {"count": count, "intents": intents}
