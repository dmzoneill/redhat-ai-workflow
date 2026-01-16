"""Ollama HTTP client with retry, timeout, and fallback handling.

Provides a unified interface to interact with Ollama instances,
with automatic fallback to alternative instances when primary is unavailable.
"""

import logging
import time
from typing import Any, Optional

import httpx

from .instances import OllamaInstance, get_instance, get_instance_names

logger = logging.getLogger(__name__)


class OllamaClient:
    """HTTP client for Ollama API with health checking and metrics."""

    def __init__(
        self,
        instance: str | OllamaInstance = "npu",
        timeout: float = 30.0,
        connect_timeout: float = 5.0,
    ):
        """Initialize Ollama client.

        Args:
            instance: Instance name or OllamaInstance object
            timeout: Request timeout in seconds
            connect_timeout: Connection timeout in seconds
        """
        if isinstance(instance, str):
            self.instance = get_instance(instance)
        else:
            self.instance = instance

        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self._available: Optional[bool] = None
        self._last_check: float = 0
        self._check_interval: float = 30.0  # Re-check availability every 30s
        self._latency_samples: list[float] = []
        self._max_samples: int = 100

    @property
    def host(self) -> str:
        """Get the host URL."""
        return self.instance.host

    @property
    def default_model(self) -> str:
        """Get the default model for this instance."""
        return self.instance.default_model

    @property
    def name(self) -> str:
        """Get the instance name."""
        return self.instance.name

    def is_available(self, force_check: bool = False) -> bool:
        """Check if instance is online.

        Args:
            force_check: Force a fresh check even if cached

        Returns:
            True if instance is available
        """
        now = time.time()

        # Use cached result if recent enough
        if not force_check and self._available is not None:
            if now - self._last_check < self._check_interval:
                return self._available

        # Perform health check
        try:
            with httpx.Client(timeout=self.connect_timeout) as client:
                response = client.get(f"{self.host}/api/tags")
                self._available = response.status_code == 200
        except Exception as e:
            logger.debug(f"Health check failed for {self.name}: {e}")
            self._available = False

        self._last_check = now
        return self._available

    def get_loaded_models(self) -> list[str]:
        """Get list of currently loaded models."""
        try:
            with httpx.Client(timeout=self.connect_timeout) as client:
                response = client.get(f"{self.host}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            pass
        return []

    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        stream: bool = False,
        temperature: float = 0.0,
        max_tokens: int = 100,
        system: Optional[str] = None,
    ) -> str:
        """Generate text completion.

        Args:
            prompt: The prompt to complete
            model: Model to use (defaults to instance default)
            stream: Whether to stream response (not implemented)
            temperature: Sampling temperature (0 = deterministic)
            max_tokens: Maximum tokens to generate
            system: Optional system prompt

        Returns:
            Generated text

        Raises:
            httpx.HTTPError: On request failure
            httpx.TimeoutException: On timeout
        """
        model = model or self.default_model
        start_time = time.perf_counter()

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,  # Always non-streaming for simplicity
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        if system:
            payload["system"] = system

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.host}/api/generate",
                    json=payload,
                )
                response.raise_for_status()

                elapsed = (time.perf_counter() - start_time) * 1000
                self._record_latency(elapsed)

                data = response.json()
                return data.get("response", "")

        except httpx.TimeoutException:
            logger.warning(f"Timeout generating from {self.name} after {self.timeout}s")
            raise
        except httpx.HTTPError as e:
            logger.error(f"HTTP error from {self.name}: {e}")
            raise

    def classify(
        self,
        text: str,
        categories: list[str],
        max_text_length: int = 200,
    ) -> Optional[str]:
        """Classify text into one of the categories.

        Args:
            text: Text to classify
            categories: List of category names
            max_text_length: Max characters of text to include in prompt

        Returns:
            Matched category name, or None on failure
        """
        prompt = f"""Classify the following text into exactly ONE of these categories: {', '.join(categories)}

Text: "{text[:max_text_length]}"

Reply with ONLY the category name, nothing else:"""

        try:
            result = self.generate(prompt, max_tokens=30, temperature=0)
            result_lower = result.strip().lower()

            # Find matching category
            for cat in categories:
                if cat.lower() in result_lower:
                    return cat

            # If no exact match, return first category mentioned
            for cat in categories:
                if cat.lower().replace("_", " ") in result_lower:
                    return cat

            logger.warning(f"No category matched in response: {result}")
            return None

        except Exception as e:
            logger.error(f"Classification failed: {e}")
            return None

    def classify_multi(
        self,
        text: str,
        categories: list[str],
        max_categories: int = 3,
        max_text_length: int = 200,
    ) -> list[str]:
        """Classify text into multiple categories.

        Args:
            text: Text to classify
            categories: List of category names
            max_categories: Maximum categories to return
            max_text_length: Max characters of text to include

        Returns:
            List of matched category names
        """
        categories_str = "\n".join(f"- {cat}" for cat in categories)

        prompt = f"""Which of these categories are relevant to the request? Select 0-{max_categories} categories.

Categories:
{categories_str}

Request: "{text[:max_text_length]}"

Reply with category names separated by commas, or NONE if no categories apply:"""

        try:
            result = self.generate(prompt, max_tokens=50, temperature=0)

            if "NONE" in result.upper():
                return []

            # Parse comma-separated categories
            matched = []
            result_lower = result.lower()
            for cat in categories:
                if cat.lower() in result_lower or cat.lower().replace("_", " ") in result_lower:
                    matched.append(cat)
                    if len(matched) >= max_categories:
                        break

            return matched

        except Exception as e:
            logger.error(f"Multi-classification failed: {e}")
            return []

    def _record_latency(self, latency_ms: float) -> None:
        """Record a latency sample."""
        self._latency_samples.append(latency_ms)
        if len(self._latency_samples) > self._max_samples:
            self._latency_samples = self._latency_samples[-self._max_samples :]

    @property
    def avg_latency_ms(self) -> float:
        """Get average latency in milliseconds."""
        if not self._latency_samples:
            return 0.0
        return sum(self._latency_samples) / len(self._latency_samples)

    @property
    def last_latency_ms(self) -> float:
        """Get last recorded latency."""
        return self._latency_samples[-1] if self._latency_samples else 0.0

    def get_status(self) -> dict:
        """Get detailed status of this instance."""
        return {
            "name": self.name,
            "host": self.host,
            "available": self.is_available(),
            "model": self.default_model,
            "power_watts": self.instance.power_watts,
            "best_for": self.instance.best_for,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "last_latency_ms": round(self.last_latency_ms, 1),
            "samples": len(self._latency_samples),
        }


# ==================== Client Factory ====================

# Cached clients
_clients: dict[str, OllamaClient] = {}


def get_client(instance: str = "npu") -> OllamaClient:
    """Get or create a client for an instance.

    Args:
        instance: Instance name

    Returns:
        OllamaClient for the instance
    """
    if instance not in _clients:
        _clients[instance] = OllamaClient(instance)
    return _clients[instance]


def npu_client() -> OllamaClient:
    """Get NPU client (convenience function)."""
    return get_client("npu")


def get_available_client(
    primary: str = "npu",
    fallback_chain: Optional[list[str]] = None,
) -> Optional[OllamaClient]:
    """Get first available client from primary + fallback chain.

    Args:
        primary: Primary instance to try first
        fallback_chain: List of fallback instances to try

    Returns:
        First available OllamaClient, or None if all offline
    """
    if fallback_chain is None:
        fallback_chain = ["igpu", "nvidia", "cpu"]

    # Build ordered list: primary + fallbacks (avoiding duplicates)
    instances_to_try = [primary] + [f for f in fallback_chain if f != primary]

    for instance_name in instances_to_try:
        if instance_name not in get_instance_names():
            continue

        client = get_client(instance_name)
        if client.is_available():
            logger.info(f"Using {instance_name} for inference")
            return client
        else:
            logger.debug(f"{instance_name} not available, trying next...")

    logger.warning("No inference instances available")
    return None


def get_all_status() -> dict[str, dict]:
    """Get status of all configured instances.

    Returns:
        Dict mapping instance name to status dict
    """
    status = {}
    for name in get_instance_names():
        client = get_client(name)
        status[name] = client.get_status()
    return status


def clear_clients() -> None:
    """Clear cached clients (useful for testing)."""
    global _clients
    _clients = {}
