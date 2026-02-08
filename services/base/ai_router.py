"""
AI Model Router - Unified LLM Backend Interface.

Routes AI analysis requests to available LLM backends via CLI wrappers.
NO FALLBACKS - requires a capable LLM for all operations.

Supported backends:
- Claude CLI (claude): Anthropic Claude via CLI
- Gemini CLI (gemini): Google Gemini via Vertex AI
- Codex (codex): OpenAI Codex CLI
- OpenCode (opencode): OpenCode CLI

Usage:
    from services.base.ai_router import AIModelRouter, LLMUnavailableError

    router = AIModelRouter()

    # Check availability
    available = await router.check_availability()
    print(f"Available backends: {available}")

    # Analyze code
    try:
        result = await router.analyze(prompt, task="memory_leaks")
    except LLMUnavailableError:
        print("No LLM backend available!")
"""

import asyncio
import json
import logging
import os
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class LLMUnavailableError(Exception):
    """Raised when no LLM backend is available."""

    pass


class LLMAnalysisError(Exception):
    """Raised when LLM analysis fails."""

    pass


@dataclass
class LLMResponse:
    """Response from an LLM analysis."""

    text: str
    findings: list = field(default_factory=list)
    done: bool = False
    backend: str = ""
    latency_ms: int = 0
    success: bool = True
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "text": self.text,
            "findings": self.findings,
            "done": self.done,
            "backend": self.backend,
            "latency_ms": self.latency_ms,
            "success": self.success,
            "error": self.error,
            "timestamp": self.timestamp.isoformat(),
        }


class AIModelRouter:
    """
    Route AI requests to LLM backends.

    NO FALLBACKS - raises LLMUnavailableError if no backend works.
    This ensures quality analysis from capable models only.
    """

    # Backend configurations - CLI commands and arguments
    BACKENDS = {
        "claude": {
            "cmd": ["claude", "--print", "--dangerously-skip-permissions"],
            "check_cmd": ["claude", "--version"],
            "timeout": 120,
            "description": "Anthropic Claude via CLI",
        },
        "gemini": {
            "cmd": ["gemini", "--model", "gemini-2.5-pro", "--output-format", "text"],
            "check_cmd": ["gemini", "--version"],
            "timeout": 60,
            "description": "Google Gemini via Vertex AI",
        },
        "codex": {
            "cmd": ["codex", "--quiet", "--approval-mode", "full-auto"],
            "check_cmd": ["codex", "--version"],
            "timeout": 120,
            "description": "OpenAI Codex CLI",
        },
        "opencode": {
            "cmd": ["opencode", "--non-interactive"],
            "check_cmd": ["opencode", "--version"],
            "timeout": 120,
            "description": "OpenCode CLI",
        },
    }

    # Priority order for backend selection
    PRIORITY = ["claude", "gemini", "codex", "opencode"]

    def __init__(self, preferred_backend: Optional[str] = None):
        """
        Initialize the AI router.

        Args:
            preferred_backend: Preferred backend name (will try this first)
        """
        self.preferred_backend = preferred_backend
        self._availability_cache: dict[str, bool] = {}
        self._cache_time: Optional[datetime] = None
        self._cache_ttl_seconds = 300  # 5 minutes

    async def check_availability(self, force_refresh: bool = False) -> dict[str, bool]:
        """
        Check which LLM backends are available.

        Args:
            force_refresh: Force refresh of cached availability

        Returns:
            Dict mapping backend name to availability status
        """
        # Check cache
        if not force_refresh and self._cache_time:
            age = (datetime.now() - self._cache_time).total_seconds()
            if age < self._cache_ttl_seconds:
                return self._availability_cache.copy()

        results = {}

        # Check each backend in parallel
        async def check_backend(name: str) -> tuple[str, bool]:
            config = self.BACKENDS[name]
            check_cmd = config["check_cmd"]

            # First check if command exists
            if not shutil.which(check_cmd[0]):
                logger.debug(f"{name}: command not found")
                return name, False

            try:
                proc = await asyncio.create_subprocess_exec(
                    *check_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, _ = await asyncio.wait_for(proc.communicate(), timeout=10)

                available = proc.returncode == 0
                if available:
                    logger.debug(f"{name}: available")
                else:
                    logger.debug(f"{name}: check failed (exit code {proc.returncode})")
                return name, available

            except asyncio.TimeoutError:
                logger.debug(f"{name}: check timed out")
                return name, False
            except Exception as e:
                logger.debug(f"{name}: check error - {e}")
                return name, False

        # Run checks in parallel
        tasks = [check_backend(name) for name in self.BACKENDS]
        check_results = await asyncio.gather(*tasks)

        for name, available in check_results:
            results[name] = available

        # Update cache
        self._availability_cache = results
        self._cache_time = datetime.now()

        return results

    async def get_best_backend(self) -> str:
        """
        Get the best available backend.

        Returns:
            Name of the best available backend

        Raises:
            LLMUnavailableError: If no backend is available
        """
        availability = await self.check_availability()

        # Try preferred backend first
        if self.preferred_backend and availability.get(self.preferred_backend):
            return self.preferred_backend

        # Try backends in priority order
        for name in self.PRIORITY:
            if availability.get(name):
                return name

        # No backend available
        raise LLMUnavailableError(
            "No LLM backend available. Install one of: claude, gemini, codex, opencode"
        )

    async def analyze(
        self,
        prompt: str,
        task: str = "analysis",
        backend: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> LLMResponse:
        """
        Analyze using an LLM backend.

        Args:
            prompt: The analysis prompt to send
            task: Task identifier for logging
            backend: Specific backend to use (or auto-select)
            timeout: Override default timeout

        Returns:
            LLMResponse with analysis results

        Raises:
            LLMUnavailableError: If no backend is available
            LLMAnalysisError: If analysis fails
        """
        # Select backend
        if backend:
            availability = await self.check_availability()
            if not availability.get(backend):
                raise LLMUnavailableError(
                    f"Requested backend '{backend}' is not available"
                )
            selected_backend = backend
        else:
            selected_backend = await self.get_best_backend()

        config = self.BACKENDS[selected_backend]
        cmd = config["cmd"]
        cmd_timeout = timeout or config["timeout"]

        logger.info(f"Running {task} analysis with {selected_backend}")
        start_time = datetime.now()

        try:
            # Build the full prompt with JSON output instruction
            full_prompt = f"""{prompt}

IMPORTANT: Return your response as valid JSON with this structure:
{{
    "findings": [
        {{
            "file": "path/to/file.py",
            "line": 123,
            "category": "unused_imports|dead_code|bare_except|security|...",
            "description": "Description of the issue",
            "severity": "critical|high|medium|low",
            "suggestion": "Actionable fix (e.g., 'Remove import on line 42')"
        }}
    ],
    "done": true  // Set to true when you've found all issues or confirmed none exist
}}

Category guidelines:
- unused_imports: Import statements that are never used
- unused_variables: Variables assigned but never read
- dead_code: Functions/classes never called, unreachable code
- bare_except: Using 'except:' without specifying exception type
- empty_except: Exception handlers that do nothing (pass)
- security: Hardcoded secrets, injection vulnerabilities
- race_conditions: Concurrent access without synchronization
- memory_leaks: Unbounded caches, unclosed resources

If no issues found, return: {{"findings": [], "done": true}}
"""

            # Run the LLM command
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ},
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(full_prompt.encode()),
                    timeout=cmd_timeout,
                )
            except asyncio.TimeoutError:
                # Kill the subprocess on timeout to prevent zombie processes
                proc.kill()
                await proc.wait()
                latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                logger.error(
                    f"{selected_backend} analysis timed out after {cmd_timeout}s"
                )
                return LLMResponse(
                    text="",
                    backend=selected_backend,
                    latency_ms=latency_ms,
                    success=False,
                    error=f"Timeout after {cmd_timeout}s",
                )

            latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            if proc.returncode != 0:
                error_msg = stderr.decode().strip() if stderr else "Unknown error"
                logger.error(f"{selected_backend} analysis failed: {error_msg}")
                return LLMResponse(
                    text="",
                    backend=selected_backend,
                    latency_ms=latency_ms,
                    success=False,
                    error=error_msg,
                )

            # Parse response
            response_text = stdout.decode().strip()
            logger.debug(
                f"{selected_backend} response ({latency_ms}ms): {response_text[:200]}..."
            )

            # Try to parse as JSON
            findings = []
            done = False

            try:
                # Find JSON in response (may be wrapped in markdown code blocks)
                json_text = response_text
                if "```json" in json_text:
                    json_text = json_text.split("```json")[1].split("```")[0]
                elif "```" in json_text:
                    json_text = json_text.split("```")[1].split("```")[0]

                data = json.loads(json_text.strip())
                findings = data.get("findings", [])
                done = data.get("done", False)

            except json.JSONDecodeError:
                # Response wasn't JSON, treat as raw text
                logger.warning(f"Could not parse JSON from {selected_backend} response")

            return LLMResponse(
                text=response_text,
                findings=findings,
                done=done,
                backend=selected_backend,
                latency_ms=latency_ms,
                success=True,
            )

        except Exception as e:
            latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            logger.exception(f"{selected_backend} analysis error: {e}")
            return LLMResponse(
                text="",
                backend=selected_backend,
                latency_ms=latency_ms,
                success=False,
                error=str(e),
            )

    async def analyze_with_retry(
        self,
        prompt: str,
        task: str = "analysis",
        max_retries: int = 2,
        timeout: Optional[int] = None,
    ) -> LLMResponse:
        """
        Analyze with automatic retry on different backends.

        Tries each available backend in priority order until one succeeds.

        Args:
            prompt: The analysis prompt
            task: Task identifier
            max_retries: Maximum retry attempts
            timeout: Override timeout

        Returns:
            LLMResponse from first successful backend

        Raises:
            LLMUnavailableError: If no backend is available
            LLMAnalysisError: If all backends fail
        """
        availability = await self.check_availability()
        available_backends = [b for b in self.PRIORITY if availability.get(b)]

        if not available_backends:
            raise LLMUnavailableError("No LLM backend available")

        errors = []
        for backend in available_backends[:max_retries]:
            response = await self.analyze(
                prompt, task, backend=backend, timeout=timeout
            )
            if response.success:
                return response
            errors.append(f"{backend}: {response.error}")

        raise LLMAnalysisError(f"All backends failed: {'; '.join(errors)}")


# Global router instance
_router: Optional[AIModelRouter] = None
_router_lock = threading.Lock()


def get_ai_router(preferred_backend: Optional[str] = None) -> AIModelRouter:
    """
    Get or create the global AI router instance.

    Args:
        preferred_backend: Preferred backend name

    Returns:
        AIModelRouter instance
    """
    global _router
    if _router is None:
        with _router_lock:
            if _router is None:
                _router = AIModelRouter(preferred_backend=preferred_backend)
    return _router
