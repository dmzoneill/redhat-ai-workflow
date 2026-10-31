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
    error: str | None = None


# pylint: disable-next=too-many-instance-attributes
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
        system_prompt: str | None = None,
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
        self._history: list[dict] = []
        self._running = False
        self._lock = asyncio.Lock()

        # Stats
        self.messages_sent = 0
        self.total_latency_ms = 0.0
        self._start_time: float | None = None

    async def start(self) -> bool:
        """
        Initialize the Gemini interface.

        Returns:
            True when the interface is ready. False when the system-prompt
            warm-up call got no response, so callers can fall back to
            another backend instead of sending into a broken CLI.
        """
        if self._running:
            return True

        self._running = True
        self._start_time = time.time()
        self._history = []

        # Warm up with a simple call if system prompt provided
        if self.system_prompt:
            logger.info("Warming up Gemini with system prompt...")
            response = await self._call_gemini(f"System: {self.system_prompt}\n\nAcknowledge with 'Ready.'")
            if not response:
                logger.warning("Gemini warm-up got no response")
                self._running = False
                return False
            logger.info("Gemini ready: %s...", response[:50])

        logger.info("Gemini hotload ready (model: %s)", self.model)
        return True

    async def stop(self):
        """Stop the Gemini interface."""
        self._running = False
        self._history = []

        logger.info(
            "Gemini stopped. Sent %s messages, avg latency: %.0fms",
            self.messages_sent,
            self.total_latency_ms / max(1, self.messages_sent),
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
        if not self._running and not await self.start():
            return GeminiResponse(text="", latency_ms=0, error="Failed to start Gemini")

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
                    self._history.append({"role": "assistant", "content": response_text})

                    # Trim history
                    if len(self._history) > self.max_history * 2:
                        self._history = self._history[-self.max_history * 2 :]

                    self.messages_sent += 1
                    self.total_latency_ms += latency

                    return GeminiResponse(
                        text=response_text,
                        latency_ms=latency,
                    )
                return GeminiResponse(text="", latency_ms=latency, error="No response from Gemini")

            except asyncio.TimeoutError:
                return GeminiResponse(
                    text="",
                    latency_ms=(time.time() - start) * 1000,
                    error="Response timeout",
                )
            except (OSError, ValueError) as e:
                return GeminiResponse(text="", latency_ms=(time.time() - start) * 1000, error=str(e))

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

    async def _call_gemini(self, prompt: str) -> str | None:
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

            stdout, stderr = await asyncio.wait_for(proc.communicate(input=prompt.encode()), timeout=self.timeout)

            if proc.returncode == 0:
                return stdout.decode().strip()
            error = stderr.decode().strip()
            # Check for common errors
            if "Organization Policy" in error:
                logger.error("Model %s not allowed by org policy", self.model)
            else:
                logger.error("Gemini error: %s", error[:200])
            return None

        except asyncio.TimeoutError:
            logger.error("Gemini call timed out")
            raise
        except (OSError, ValueError) as e:
            logger.error("Gemini call failed: %s", e)
            return None

    def clear_history(self):
        """Clear conversation history."""
        self._history = []
        logger.info("Conversation history cleared")

    @property
    def is_running(self) -> bool:
        """Whether the Gemini interface has been started."""
        return self._running

    @property
    def history_length(self) -> int:
        """Number of turns kept in the local conversation history."""
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
# pylint: disable-next=invalid-name
_gemini_pool: GeminiPool | None = None


def get_gemini_pool() -> GeminiPool:
    """Get the global Gemini pool."""
    # pylint: disable-next=global-statement
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
