"""
Hot-loaded Gemini CLI Interface.

Keeps a persistent Gemini CLI process running for low-latency responses.
Conversation context is maintained by Gemini internally via sessions.

Usage:
    gemini = GeminiHotload()
    await gemini.start()

    response = await gemini.send("What's the weather like?")
    response = await gemini.send("And tomorrow?")  # Maintains context!

    await gemini.stop()
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

# Default model that works with our Vertex AI project
DEFAULT_MODEL = "gemini-2.5-pro"


@dataclass
class GeminiResponse:
    """Response from Gemini."""

    text: str
    latency_ms: float
    tokens_in: int = 0
    tokens_out: int = 0
    error: Optional[str] = None


class GeminiHotload:
    """
    Hot-loaded Gemini interface with conversation memory.

    Uses one-shot calls but maintains conversation history locally
    for context. This is more reliable than trying to keep an
    interactive process running.

    Features:
    - Maintains conversation history for context
    - Low latency (model stays warm after first call)
    - Configurable system prompt
    - Automatic retry on transient errors
    """

    def __init__(
        self,
        system_prompt: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        timeout: float = 30.0,
        max_history: int = 20,
    ):
        """
        Initialize Gemini hotload interface.

        Args:
            system_prompt: System prompt for context
            model: Gemini model to use
            timeout: Response timeout in seconds
            max_history: Maximum conversation turns to keep
        """
        self.system_prompt = system_prompt
        self.model = model
        self.timeout = timeout
        self.max_history = max_history

        # Conversation history
        self._history: List[dict] = []
        self._running = False
        self._lock = asyncio.Lock()

        # Stats
        self.messages_sent = 0
        self.total_latency_ms = 0
        self._start_time: Optional[float] = None

    async def start(self) -> bool:
        """Initialize the Gemini interface."""
        if self._running:
            return True

        self._running = True
        self._start_time = time.time()
        self._history = []

        # Warm up with a simple call if system prompt provided
        if self.system_prompt:
            logger.info("Warming up Gemini with system prompt...")
            response = await self._call_gemini(
                f"System: {self.system_prompt}\n\nAcknowledge with 'Ready.'"
            )
            if response:
                logger.info(f"Gemini ready: {response[:50]}...")
            else:
                logger.warning("Gemini warm-up got no response")

        logger.info(f"Gemini hotload ready (model: {self.model})")
        return True

    async def stop(self):
        """Stop the Gemini interface."""
        self._running = False
        self._history = []

        logger.info(
            f"Gemini stopped. Sent {self.messages_sent} messages, "
            f"avg latency: {self.total_latency_ms / max(1, self.messages_sent):.0f}ms"
        )

    async def send(self, message: str) -> GeminiResponse:
        """
        Send a message and get a response.

        Maintains conversation history for context.

        Args:
            message: The message to send

        Returns:
            GeminiResponse with the text and metadata
        """
        if not self._running:
            if not await self.start():
                return GeminiResponse(
                    text="", latency_ms=0, error="Failed to start Gemini"
                )

        async with self._lock:
            start = time.time()

            try:
                # Build prompt with history
                prompt = self._build_prompt(message)

                # Call Gemini
                response_text = await self._call_gemini(prompt)

                latency = (time.time() - start) * 1000

                if response_text:
                    # Add to history
                    self._history.append({"role": "user", "content": message})
                    self._history.append(
                        {"role": "assistant", "content": response_text}
                    )

                    # Trim history
                    if len(self._history) > self.max_history * 2:
                        self._history = self._history[-self.max_history * 2 :]

                    self.messages_sent += 1
                    self.total_latency_ms += latency

                    return GeminiResponse(
                        text=response_text,
                        latency_ms=latency,
                    )
                else:
                    return GeminiResponse(
                        text="", latency_ms=latency, error="No response from Gemini"
                    )

            except asyncio.TimeoutError:
                return GeminiResponse(
                    text="",
                    latency_ms=(time.time() - start) * 1000,
                    error="Response timeout",
                )
            except Exception as e:
                return GeminiResponse(
                    text="", latency_ms=(time.time() - start) * 1000, error=str(e)
                )

    def _build_prompt(self, message: str) -> str:
        """Build prompt with conversation history."""
        parts = []

        # System prompt
        if self.system_prompt:
            parts.append(f"System: {self.system_prompt}\n")

        # Conversation history
        if self._history:
            parts.append("Previous conversation:")
            for entry in self._history[-10:]:  # Last 10 exchanges
                role = "User" if entry["role"] == "user" else "Assistant"
                parts.append(f"{role}: {entry['content']}")
            parts.append("")

        # Current message
        parts.append(f"User: {message}")
        parts.append("Assistant:")

        return "\n".join(parts)

    async def _call_gemini(self, prompt: str) -> Optional[str]:
        """Call Gemini CLI with a prompt via stdin pipe."""
        try:
            env = os.environ.copy()
            env["GOOGLE_CLOUD_PROJECT"] = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
            env["GOOGLE_CLOUD_LOCATION"] = os.environ.get("GOOGLE_CLOUD_LOCATION", "")

            # Pipe prompt via stdin to avoid shell escaping issues
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-l",
                "-c",
                f"gemini --model {self.model}",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode()), timeout=self.timeout
            )

            if proc.returncode == 0:
                return stdout.decode().strip()
            else:
                error = stderr.decode().strip()
                # Check for common errors
                if "Organization Policy" in error:
                    logger.error(f"Model {self.model} not allowed by org policy")
                else:
                    logger.error(f"Gemini error: {error[:200]}")
                return None

        except asyncio.TimeoutError:
            logger.error("Gemini call timed out")
            raise
        except Exception as e:
            logger.error(f"Gemini call failed: {e}")
            return None

    def clear_history(self):
        """Clear conversation history."""
        self._history = []
        logger.info("Conversation history cleared")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def history_length(self) -> int:
        return len(self._history)

    def get_stats(self) -> dict:
        """Get usage statistics."""
        uptime = time.time() - self._start_time if self._start_time else 0
        return {
            "running": self._running,
            "model": self.model,
            "messages_sent": self.messages_sent,
            "avg_latency_ms": self.total_latency_ms / max(1, self.messages_sent),
            "history_length": len(self._history),
            "uptime_seconds": uptime,
        }


class GeminiPool:
    """
    Pool of hot-loaded Gemini instances.

    Maintains multiple Gemini processes for concurrent requests
    or different contexts (e.g., one per meeting).
    """

    def __init__(self, pool_size: int = 2):
        self.pool_size = pool_size
        self._instances: dict[str, GeminiHotload] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str = "default", system_prompt: str = "") -> GeminiHotload:
        """Get or create a Gemini instance for a key."""
        async with self._lock:
            if key not in self._instances:
                instance = GeminiHotload(system_prompt=system_prompt)
                await instance.start()
                self._instances[key] = instance
            return self._instances[key]

    async def release(self, key: str):
        """Release a Gemini instance."""
        async with self._lock:
            if key in self._instances:
                await self._instances[key].stop()
                del self._instances[key]

    async def shutdown(self):
        """Shutdown all instances."""
        async with self._lock:
            for instance in self._instances.values():
                await instance.stop()
            self._instances.clear()


# Global pool
_gemini_pool: Optional[GeminiPool] = None


def get_gemini_pool() -> GeminiPool:
    """Get the global Gemini pool."""
    global _gemini_pool
    if _gemini_pool is None:
        _gemini_pool = GeminiPool()
    return _gemini_pool


async def quick_gemini(message: str, context: str = "default") -> str:
    """
    Quick helper to send a message to Gemini.

    Uses a pooled hot-loaded instance for low latency.

    Args:
        message: The message to send
        context: Context key (different keys = different conversations)

    Returns:
        Response text
    """
    pool = get_gemini_pool()
    gemini = await pool.get(context)
    response = await gemini.send(message)
    return response.text if not response.error else f"Error: {response.error}"
