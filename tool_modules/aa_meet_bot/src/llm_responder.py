"""
LLM Response Generator.

Handles:
- Processing wake-word triggered commands
- Generating contextual responses using Gemini CLI (Vertex AI) or Ollama
- Jira context integration

LLM Backends:
- Gemini 2.5 Pro via CLI (default, fastest): Uses `gemini` CLI configured for Vertex AI
- Ollama (fallback): Local inference with qwen2.5 or other models
"""

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator, List, Optional

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from tool_modules.aa_meet_bot.src.config import get_config

logger = logging.getLogger(__name__)

# Ollama configuration - use iGPU for low power inference (~1s, 8-15W)
OLLAMA_HOST = "http://localhost:11435"  # iGPU port (low power, ~1s latency)
OLLAMA_MODEL = "qwen2.5:0.5b"  # Fast 0.5B model for real-time responses
OLLAMA_STREAMING = False  # Set to True for streaming responses (speak as sentences arrive)

# Gemini CLI configuration (primary)
GEMINI_MODEL = "gemini-2.5-pro"  # Confirmed working via Vertex AI


@dataclass
class JiraContext:
    """Context from Jira for the current sprint."""

    sprint_name: str = ""
    sprint_goal: str = ""
    issues: List[dict] = field(default_factory=list)
    my_issues: List[dict] = field(default_factory=list)
    last_updated: Optional[datetime] = None

    def to_prompt_context(self) -> str:
        """Convert to a string for LLM context."""
        if not self.issues:
            return "No Jira context loaded."

        lines = [
            f"## Current Sprint: {self.sprint_name}",
            f"Sprint Goal: {self.sprint_goal}",
            "",
            "### My Issues:",
        ]

        for issue in self.my_issues[:5]:  # Limit to 5 issues
            status = issue.get("status", "Unknown")
            summary = issue.get("summary", "")[:60]
            key = issue.get("key", "")
            lines.append(f"- [{key}] {summary} ({status})")

        lines.append("")
        lines.append("### Team Issues:")

        for issue in self.issues[:10]:  # Limit to 10 issues
            if issue not in self.my_issues:
                status = issue.get("status", "Unknown")
                summary = issue.get("summary", "")[:60]
                key = issue.get("key", "")
                assignee = issue.get("assignee", "Unassigned")
                lines.append(f"- [{key}] {summary} ({status}) - {assignee}")

        return "\n".join(lines)


@dataclass
class LLMResponse:
    """Response from the LLM."""

    text: str
    confidence: float = 1.0
    action: Optional[str] = None  # "update_jira", "lookup", "respond", etc.
    action_params: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = True
    error: Optional[str] = None


class LLMResponder:
    """
    LLM-based response generator for meeting interactions.

    Primary: Gemini 2.5 Pro via CLI (Vertex AI) - fastest response times
    Fallback: Ollama with local models

    Maintains conversation history throughout a meeting session for context.

    Modes:
    - "gemini": Standard CLI calls (new process per request)
    - "gemini_hotload": Keeps conversation in GeminiHotload for context
    - "ollama": Local Ollama inference
    """

    def __init__(self, backend: str = "ollama", meeting_id: str = "", use_hotload: bool = True):
        """
        Initialize LLM responder.

        Args:
            backend: "ollama" (default, fastest ~2s), "gemini" (~5.5s), or "gemini_hotload"
            meeting_id: Unique meeting session ID for conversation tracking
            use_hotload: If True and backend is "gemini", use GeminiHotload for context
        """
        self.config = get_config()
        self.jira_context = JiraContext()
        self.conversation_history: List[dict] = []
        self.max_history = 20  # Keep more history for meeting context
        self.backend = backend
        self.meeting_id = meeting_id or f"meeting-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        self.meeting_title = ""
        self.meeting_start = datetime.now()

        # Hotloaded Gemini instance (maintains conversation context internally)
        self._gemini_hotload = None
        self._use_hotload = use_hotload and backend == "gemini"

        logger.info(f"LLM Responder initialized for meeting: {self.meeting_id} (hotload={self._use_hotload})")

        # System prompt for meeting assistant - persona is David
        self.system_prompt = """You are David, a 43-year-old software engineer at Red Hat based in Ireland.

You are in a video meeting. Someone will ask you a QUESTION. Answer it directly.

RULES:
1. Keep responses SHORT - 1-2 sentences max
2. Be conversational and natural - you're speaking out loud
3. Answer the ACTUAL QUESTION asked
4. For greetings like "how are you?" just say "I'm good, thanks!" or similar
5. Only mention work/Jira if specifically asked

The user message contains a QUESTION. Answer it."""

    def set_meeting_context(self, meeting_id: str, title: str = "") -> None:
        """Set the meeting context for conversation tracking.

        Call this when joining a new meeting to reset conversation history.

        Args:
            meeting_id: Unique meeting identifier
            title: Meeting title for context
        """
        self.meeting_id = meeting_id
        self.meeting_title = title
        self.meeting_start = datetime.now()
        self.conversation_history = []  # Reset history for new meeting
        logger.info(f"Meeting context set: {meeting_id} - {title}")

    async def initialize(self) -> bool:
        """Check LLM backend is available and initialize hotload if enabled."""
        if self.backend == "ollama":
            # Try Ollama first (fastest - ~2s on iGPU)
            if await self._check_ollama():
                return True
            # Fall back to Gemini if Ollama unavailable
            logger.warning("Ollama unavailable, falling back to Gemini")
            self.backend = "gemini"
            return await self._check_gemini_cli()
        elif self.backend == "gemini":
            if self._use_hotload:
                return await self._init_gemini_hotload()
            return await self._check_gemini_cli()
        else:
            return await self._check_ollama()

    async def _init_gemini_hotload(self) -> bool:
        """Initialize the hotloaded Gemini instance."""
        try:
            from tool_modules.aa_meet_bot.src.gemini_hotload import GeminiHotload

            self._gemini_hotload = GeminiHotload(
                system_prompt=self.system_prompt,
                model=GEMINI_MODEL,
                timeout=30.0,
                max_history=self.max_history,
            )

            if await self._gemini_hotload.start():
                logger.info("Gemini hotload initialized - conversation context will be maintained")
                return True
            else:
                logger.warning("Gemini hotload failed, falling back to standard CLI")
                self._gemini_hotload = None
                self._use_hotload = False
                return await self._check_gemini_cli()

        except ImportError as e:
            logger.warning(f"Gemini hotload not available: {e}")
            self._use_hotload = False
            return await self._check_gemini_cli()

    async def _check_gemini_cli(self) -> bool:
        """Check if Gemini CLI is available and working."""
        try:
            # Quick test with Gemini CLI
            proc = await asyncio.create_subprocess_exec(
                "gemini",
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)

            if proc.returncode == 0:
                logger.info(f"Gemini CLI available, using model {GEMINI_MODEL}")
                return True
            else:
                logger.warning(f"Gemini CLI check failed: {stderr.decode()}")
                # Fall back to Ollama
                self.backend = "ollama"
                return await self._check_ollama()

        except FileNotFoundError:
            logger.warning("Gemini CLI not found, falling back to Ollama")
            self.backend = "ollama"
            return await self._check_ollama()
        except Exception as e:
            logger.warning(f"Gemini CLI error: {e}, falling back to Ollama")
            self.backend = "ollama"
            return await self._check_ollama()

    async def _check_ollama(self) -> bool:
        """Check if Ollama is available."""
        try:
            result = subprocess.run(
                ["curl", "-s", f"{OLLAMA_HOST}/api/tags"], capture_output=True, text=True, timeout=5
            )

            if result.returncode == 0:
                data = json.loads(result.stdout)
                models = [m["name"] for m in data.get("models", [])]

                if OLLAMA_MODEL in models or any(OLLAMA_MODEL.split(":")[0] in m for m in models):
                    logger.info(f"Ollama ready with model {OLLAMA_MODEL}")
                    return True
                else:
                    logger.warning(f"Model {OLLAMA_MODEL} not found. Available: {models}")
                    logger.info(f"Run: ollama pull {OLLAMA_MODEL}")
                    return False
            else:
                logger.error("Ollama not responding")
                return False

        except Exception as e:
            logger.error(f"Failed to connect to Ollama: {e}")
            return False

    async def load_jira_context(self, project: str = "AAP") -> bool:
        """
        Load Jira context for the current sprint.

        This preloads sprint information so responses are fast.
        """
        try:
            # Use the existing Jira MCP tools
            # For now, we'll create a placeholder that can be filled by the MCP tools
            logger.info(f"Loading Jira context for project {project}...")

            # This would normally call jira_my_issues and jira_search
            # For now, set up the structure
            self.jira_context = JiraContext(
                sprint_name="Current Sprint",
                sprint_goal="Deliver key features",
                issues=[],
                my_issues=[],
                last_updated=datetime.now(),
            )

            return True

        except Exception as e:
            logger.error(f"Failed to load Jira context: {e}")
            return False

    def update_jira_context(self, issues: List[dict], my_issues: List[dict] = None):
        """Update Jira context with fresh data."""
        self.jira_context.issues = issues
        self.jira_context.my_issues = my_issues or []
        self.jira_context.last_updated = datetime.now()

    def _build_messages(self, command: str, speaker: str, context_before: List[str] = None) -> List[dict]:
        """Build messages list for Ollama chat API.

        Includes system prompt, conversation history, and current command.
        """
        messages = [{"role": "system", "content": self.system_prompt}]

        # Add conversation history
        for entry in self.conversation_history[-self.max_history * 2 :]:
            messages.append(entry)

        # Add context from meeting if available
        if context_before:
            context_text = "\n".join(context_before[-5:])  # Last 5 lines
            messages.append(
                {"role": "user", "content": f"[Meeting context]\n{context_text}\n\n{speaker} asked: {command}"}
            )
        else:
            messages.append({"role": "user", "content": f"{speaker} asked: {command}"})

        return messages

    async def generate_response(
        self,
        command: str,
        speaker: str = "Someone",
        context_before: List[str] = None,
    ) -> LLMResponse:
        """
        Generate a response to a command/question.

        Maintains conversation history throughout the meeting session
        so the LLM has context about what was discussed earlier.

        Args:
            command: The text after the wake word
            speaker: Who said it
            context_before: Recent meeting transcript (what others said)

        Returns:
            LLMResponse with the generated text
        """
        try:
            # Build the prompt with full meeting context
            prompt_parts = [self.system_prompt]

            # Add meeting context
            if self.meeting_title:
                meeting_duration = (datetime.now() - self.meeting_start).total_seconds() / 60
                prompt_parts.append(f"\n## Current Meeting: {self.meeting_title}")
                prompt_parts.append(f"Duration: {meeting_duration:.0f} minutes")

            # Add Jira context
            jira_ctx = self.jira_context.to_prompt_context()
            if jira_ctx and jira_ctx != "No Jira context loaded.":
                prompt_parts.append(f"\n## Jira Context:\n{jira_ctx}")

            # Add FULL conversation history with David (this is the key for context)
            if self.conversation_history:
                prompt_parts.append(
                    f"\n## Our conversation so far in this meeting ({len(self.conversation_history)} exchanges):"
                )
                for msg in self.conversation_history:
                    role = "David" if msg["role"] == "user" else "You"
                    prompt_parts.append(f"{role}: {msg['content']}")

            # Add recent meeting transcript (what others are saying)
            if context_before:
                prompt_parts.append("\n## Recent meeting discussion:")
                for line in context_before[-10:]:  # Last 10 lines of transcript
                    prompt_parts.append(f"  {line}")

            # Add the current command
            prompt_parts.append(f"\n## Current question from {speaker}:")
            prompt_parts.append(command)
            prompt_parts.append("\n## Your response (1-3 sentences, conversational):")

            full_prompt = "\n".join(prompt_parts)

            logger.debug(
                f"Prompt length: {len(full_prompt)} chars, history: {len(self.conversation_history)} exchanges"
            )

            # Call appropriate backend
            if self._use_hotload and self._gemini_hotload:
                # Use hotloaded Gemini (maintains its own context)
                # Just send the command - hotload has the system prompt and history
                response = await self._gemini_hotload.send(f"{speaker}: {command}")
                response_text = response.text if not response.error else None
                if response.error:
                    logger.warning(f"Gemini hotload error: {response.error}")
            elif self.backend == "gemini":
                response_text = await self._call_gemini_cli(full_prompt)
            else:
                # Build messages format for Ollama
                messages = [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": f"{speaker} asked: {command}"},
                ]
                response_text = await self._call_ollama(messages)

            if response_text:
                # Add to history
                self.conversation_history.append({"role": "user", "content": f"{speaker}: {command}"})
                self.conversation_history.append({"role": "assistant", "content": response_text})

                # Trim history
                if len(self.conversation_history) > self.max_history * 2:
                    self.conversation_history = self.conversation_history[-self.max_history * 2 :]

                return LLMResponse(text=response_text, success=True)
            else:
                return LLMResponse(text="", success=False, error="No response from LLM")

        except Exception as e:
            logger.error(f"LLM response failed: {e}")
            return LLMResponse(text="", success=False, error=str(e))

    async def _call_gemini_cli(
        self,
        prompt: str,
        model: str = GEMINI_MODEL,
    ) -> Optional[str]:
        """
        Call Gemini via CLI configured for Vertex AI.

        Runs through bash -l to get user's environment variables
        (GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION, etc.)

        Args:
            prompt: The full prompt to send
            model: Gemini model name (default: gemini-2.5-pro)

        Returns:
            Response text or None on error
        """
        import os

        try:
            # Get user's home directory for sourcing profile
            home = os.path.expanduser("~")

            # Build the gemini command
            gemini_cmd = f"gemini --model {model} --output-format text"

            # Run through bash login shell to get environment variables
            # This sources ~/.bashrc and ~/.bash_profile
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-l",
                "-c",
                gemini_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={
                    **os.environ,
                    "HOME": home,
                    # Also try to pass these directly if they're in our env
                    "GOOGLE_CLOUD_PROJECT": os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
                    "GOOGLE_CLOUD_LOCATION": os.environ.get("GOOGLE_CLOUD_LOCATION", ""),
                },
            )

            stdout, stderr = await asyncio.wait_for(proc.communicate(prompt.encode()), timeout=30)  # 30 second timeout

            if proc.returncode == 0:
                response = stdout.decode().strip()
                logger.info(f"Gemini response: {response[:100]}...")
                return response
            else:
                error = stderr.decode()
                logger.error(f"Gemini CLI error: {error}")
                return None

        except asyncio.TimeoutError:
            logger.error("Gemini CLI timed out")
            return None
        except Exception as e:
            logger.error(f"Gemini CLI call error: {e}")
            return None

    async def stream_gemini_response(
        self,
        prompt: str,
        model: str = GEMINI_MODEL,
    ) -> AsyncIterator[str]:
        """
        Stream response from Gemini CLI.

        Yields text chunks as they arrive for lower latency TTS.

        Args:
            prompt: The full prompt to send
            model: Gemini model name

        Yields:
            Text chunks from the response
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "gemini",
                "--model",
                model,
                "--output-format",
                "stream-json",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Write prompt and close stdin
            proc.stdin.write(prompt.encode())
            await proc.stdin.drain()
            proc.stdin.close()

            # Read streaming JSON chunks
            async for line in proc.stdout:
                try:
                    chunk = json.loads(line.decode())
                    if "text" in chunk:
                        yield chunk["text"]
                except json.JSONDecodeError:
                    # Plain text line
                    text = line.decode().strip()
                    if text:
                        yield text

            await proc.wait()

        except Exception as e:
            logger.error(f"Gemini streaming error: {e}")

    async def _call_ollama(self, messages: List[dict]) -> Optional[str]:
        """Call Ollama API (non-streaming, for compatibility)."""
        full_response = []
        async for chunk in self._stream_ollama(messages):
            full_response.append(chunk)
        return "".join(full_response) if full_response else None

    async def _stream_ollama(self, messages: List[dict]) -> AsyncIterator[str]:
        """Stream response from Ollama API token by token."""
        import aiohttp

        payload = {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
                "num_predict": 100,
            },
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{OLLAMA_HOST}/api/chat", json=payload, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    async for line in resp.content:
                        if line:
                            try:
                                data = json.loads(line.decode())
                                content = data.get("message", {}).get("content", "")
                                if content:
                                    yield content
                            except json.JSONDecodeError:
                                continue
        except Exception as e:
            logger.error(f"Ollama streaming error: {e}")

    async def stream_ollama_sentences(self, messages: List[dict]) -> AsyncIterator[str]:
        """Stream complete sentences from Ollama for TTS.

        Buffers tokens until a sentence boundary (. ! ?) is reached,
        then yields the complete sentence for immediate TTS synthesis.
        """
        buffer = ""
        sentence_endings = {".", "!", "?"}

        async for token in self._stream_ollama(messages):
            buffer += token

            # Check for sentence boundaries
            for i, char in enumerate(buffer):
                if char in sentence_endings:
                    # Check it's not an abbreviation (e.g., "Dr.", "Mr.")
                    if i + 1 < len(buffer) and buffer[i + 1] == " ":
                        sentence = buffer[: i + 1].strip()
                        buffer = buffer[i + 2 :]  # Skip the space after punctuation
                        if sentence:
                            yield sentence
                        break
                    elif i + 1 == len(buffer):
                        # End of buffer, yield the sentence
                        sentence = buffer.strip()
                        buffer = ""
                        if sentence:
                            yield sentence
                        break

        # Yield any remaining text
        if buffer.strip():
            yield buffer.strip()

    def clear_history(self):
        """Clear conversation history."""
        self.conversation_history = []


# Global instance
_llm_responder: Optional[LLMResponder] = None


def get_llm_responder(backend: str = "gemini") -> LLMResponder:
    """
    Get or create the global LLM responder instance.

    Args:
        backend: "gemini" (default, fastest) or "ollama" (local)
    """
    global _llm_responder
    if _llm_responder is None:
        _llm_responder = LLMResponder(backend=backend)
    return _llm_responder


async def generate_meeting_response(command: str, speaker: str = "Someone", context: List[str] = None) -> LLMResponse:
    """
    Convenience function to generate a meeting response.

    Args:
        command: The command/question after wake word
        speaker: Who asked
        context: Recent conversation

    Returns:
        LLMResponse with generated text
    """
    responder = get_llm_responder()
    return await responder.generate_response(command, speaker, context)
