"""
Voice Interaction Pipeline.

Orchestrates the full voice interaction flow for a meeting instance:
1. Capture audio from meeting (sink monitor)
2. STT transcription (OpenVINO Whisper on NPU)
3. Wake word detection in text stream
4. LLM response generation (Gemini 2.5 Pro)
5. TTS synthesis (Piper)
6. Audio output to meeting (pipe source)

Target latency: 0.9-1.2s end-to-end (based on Xenith project).

Usage:
    pipeline = VoicePipeline(controller)
    await pipeline.start()

    # Pipeline runs in background, processing voice interactions

    await pipeline.stop()
"""

import asyncio
import functools
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import numpy as np

if TYPE_CHECKING:
    from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture
from tool_modules.aa_meet_bot.src.audio_output import AudioOutputManager
from tool_modules.aa_meet_bot.src.llm_responder import LLMResponder, get_llm_responder
from tool_modules.aa_meet_bot.src.stt_engine import NPUWhisperSTT
from tool_modules.aa_meet_bot.src.tts_engine import TTSEngine, get_tts_engine
from tool_modules.aa_meet_bot.src.wake_word import TextWakeWordDetector, WakeWordEvent

logger = logging.getLogger(__name__)

# Failures expected from audio devices, subprocesses, model backends and
# network calls; anything else is a bug and propagates.
_VOICE_ERRORS: tuple[type[Exception], ...] = (
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    AttributeError,
    KeyError,
    asyncio.TimeoutError,
)

# Utterance segmentation (RMS voice activity detection)
_SILENCE_THRESHOLD = 0.02
_MIN_SILENCE_MS = 800
_MAX_UTTERANCE_MS = 30000
# read_chunk() waits up to 2s per call, so 3 misses ~ 6s without audio
_MAX_EMPTY_READS = 3


@dataclass
class VoicePipelineStats:
    """Statistics for the voice pipeline."""

    total_utterances: int = 0
    wake_word_triggers: int = 0
    responses_generated: int = 0
    total_latency_ms: float = 0.0
    min_latency_ms: float = float("inf")
    max_latency_ms: float = 0.0
    errors: int = 0

    @property
    def avg_latency_ms(self) -> float:
        """Mean end-to-end response latency (0 when nothing has been answered)."""
        if self.responses_generated == 0:
            return 0.0
        return self.total_latency_ms / self.responses_generated

    def record_response(self, latency_ms: float) -> None:
        """Add one completed response's latency."""
        self.responses_generated += 1
        self.total_latency_ms += latency_ms
        self.min_latency_ms = min(self.min_latency_ms, latency_ms)
        self.max_latency_ms = max(self.max_latency_ms, latency_ms)


class VoicePipelineConfig(NamedTuple):
    """Configuration for the voice pipeline (immutable; build a new one to change it)."""

    # Wake word
    wake_word: str = "david"

    # STT settings (the Whisper model itself comes from the OpenVINO model dir)
    stt_model: str = "base"
    stt_device: str = "NPU"

    # LLM settings
    llm_backend: str = "gemini"  # "gemini" or "ollama"

    # TTS settings
    tts_backend: str = "piper"  # "piper" or "gpt-sovits"

    # Audio settings
    sample_rate: int = 16000

    # Processing settings
    use_parallel_tts: bool = True  # TTS while LLM streams

    # Callbacks
    on_transcription: Callable[[str], None] | None = None
    on_wake_word: Callable[[WakeWordEvent], None] | None = None
    on_response: Callable[[str], None] | None = None


class UtteranceSegmenter:
    """Collect audio chunks into utterances using RMS voice activity detection."""

    def __init__(
        self,
        sample_rate: int = 16000,
        silence_threshold: float = _SILENCE_THRESHOLD,
        min_silence_ms: float = _MIN_SILENCE_MS,
        max_utterance_ms: float = _MAX_UTTERANCE_MS,
    ):
        self.sample_rate = sample_rate
        self.silence_threshold = silence_threshold
        self.min_silence_ms = min_silence_ms
        self.max_utterance_ms = max_utterance_ms
        self._chunks: list[np.ndarray] = []
        self._silence_ms = 0.0

    def _buffered_ms(self) -> float:
        return sum(len(c) for c in self._chunks) / self.sample_rate * 1000

    def add_chunk(self, chunk: np.ndarray) -> np.ndarray | None:
        """Add a chunk; return a complete utterance once speech is followed by enough silence."""
        if len(chunk) == 0:
            return None
        rms = float(np.sqrt(np.mean(np.square(chunk, dtype=np.float64))))
        if rms >= self.silence_threshold:
            self._chunks.append(chunk)
            self._silence_ms = 0.0
        elif self._chunks:
            self._chunks.append(chunk)  # keep trailing silence
            self._silence_ms += len(chunk) / self.sample_rate * 1000
        else:
            return None

        if self._silence_ms >= self.min_silence_ms or self._buffered_ms() >= self.max_utterance_ms:
            utterance = np.concatenate(self._chunks)
            self.reset()
            return utterance
        return None

    def reset(self) -> None:
        """Drop any buffered audio."""
        self._chunks = []
        self._silence_ms = 0.0


@dataclass
class _Components:
    """Pipeline components, created by VoicePipeline.initialize()."""

    stt: NPUWhisperSTT
    llm: LLMResponder
    tts: TTSEngine
    wake_detector: TextWakeWordDetector
    audio_capture: PulseAudioCapture
    audio_output: AudioOutputManager


@dataclass
class _RunState:
    """Mutable run state of a VoicePipeline."""

    running: bool = False
    processing_response: bool = False
    capture_task: "asyncio.Task[None] | None" = None


class VoicePipeline:
    """
    Full voice interaction pipeline for a meeting instance.

    Handles the complete flow from audio capture to voice response.
    """

    def __init__(
        self,
        sink_name: str,
        pipe_path: Path,
        config: VoicePipelineConfig | None = None,
        controller: "GoogleMeetController | None" = None,
    ):
        """
        Initialize voice pipeline.

        Args:
            sink_name: PulseAudio sink name for audio capture
            pipe_path: Path to named pipe for audio output
            config: Pipeline configuration
            controller: Browser controller for mute/unmute operations
        """
        self.sink_name = sink_name
        self.pipe_path = pipe_path
        self.config = config or VoicePipelineConfig()
        self._controller = controller  # For mute/unmute
        self._parts: _Components | None = None
        self._state = _RunState()
        self.stats = VoicePipelineStats()

    async def initialize(self) -> bool:
        """Initialize all pipeline components."""
        logger.info("Initializing voice pipeline for sink: %s", self.sink_name)

        try:
            stt = NPUWhisperSTT(device=self.config.stt_device)
            if not await stt.initialize():
                logger.warning("STT initialization failed, will retry on first use")

            llm = get_llm_responder(backend=self.config.llm_backend)
            if not await llm.initialize():
                logger.warning("LLM initialization failed, will retry on first use")

            tts = get_tts_engine(backend=self.config.tts_backend)
            if not await tts.initialize():
                logger.warning("TTS initialization failed, will retry on first use")

            self._parts = _Components(
                stt=stt,
                llm=llm,
                tts=tts,
                wake_detector=TextWakeWordDetector(wake_word=self.config.wake_word),
                audio_capture=PulseAudioCapture(self.sink_name, sample_rate=self.config.sample_rate),
                audio_output=AudioOutputManager(self.pipe_path, target_sample_rate=self.config.sample_rate),
            )

            logger.info("Voice pipeline initialized")
            return True

        except _VOICE_ERRORS as e:
            logger.error("Failed to initialize voice pipeline: %s", e)
            return False

    async def start(self) -> None:
        """Start the voice pipeline."""
        if self._state.running:
            logger.warning("[VOICE] Voice pipeline already running")
            return

        if not await self.initialize():
            logger.error("[VOICE] Failed to initialize pipeline")
            return

        self._state.running = True
        self._state.capture_task = asyncio.create_task(self._capture_loop())
        logger.info("[VOICE] ========================================")
        logger.info("[VOICE] 🎧 VOICE PIPELINE STARTED")
        logger.info('[VOICE] 🔑 Wake word: "%s"', self.config.wake_word)
        logger.info("[VOICE] 🎤 Listening on sink: %s", self.sink_name)
        logger.info("[VOICE] 🔊 Output pipe: %s", self.pipe_path)
        logger.info("[VOICE] 🧠 STT: %s on %s", self.config.stt_model, self.config.stt_device)
        logger.info("[VOICE] 💬 LLM: %s", self.config.llm_backend)
        logger.info("[VOICE] 🔈 TTS: %s", self.config.tts_backend)
        logger.info("[VOICE] ========================================")

    async def stop(self) -> None:
        """Stop the voice pipeline."""
        self._state.running = False

        task = self._state.capture_task
        if task:
            task.cancel()
            # Wait for the cancelled task without swallowing our own cancellation
            await asyncio.wait({task}, timeout=5.0)
            self._state.capture_task = None

        if self._parts:
            await self._parts.audio_capture.stop()
            self._parts.audio_output.close()

        logger.info("[VOICE] ========================================")
        logger.info("[VOICE] 🛑 VOICE PIPELINE STOPPED")
        logger.info("[VOICE] 📊 Stats:")
        logger.info("[VOICE]    Utterances processed: %s", self.stats.total_utterances)
        logger.info("[VOICE]    Wake word triggers: %s", self.stats.wake_word_triggers)
        logger.info("[VOICE]    Responses generated: %s", self.stats.responses_generated)
        if self.stats.responses_generated > 0:
            logger.info("[VOICE]    Avg latency: %.0fms", self.stats.avg_latency_ms)
            logger.info("[VOICE]    Min latency: %.0fms", self.stats.min_latency_ms)
            logger.info("[VOICE]    Max latency: %.0fms", self.stats.max_latency_ms)
        logger.info("[VOICE]    Errors: %s", self.stats.errors)
        logger.info("[VOICE] ========================================")

    async def _capture_loop(self) -> None:
        """Main capture and processing loop."""
        parts = self._parts
        if parts is None:
            return
        segmenter = UtteranceSegmenter(sample_rate=self.config.sample_rate)

        try:
            if not await parts.audio_capture.start():
                logger.error("[VOICE] Failed to start audio capture on %s", self.sink_name)
                self.stats.errors += 1
                return

            empty_reads = 0
            while self._state.running:
                chunk = await parts.audio_capture.read_chunk()
                if chunk is None:
                    empty_reads += 1
                    if empty_reads >= _MAX_EMPTY_READS:
                        logger.warning("[VOICE] Audio source appears to be gone")
                        break
                    continue
                empty_reads = 0

                # Skip processing if we're currently responding
                if self._state.processing_response:
                    continue

                utterance = segmenter.add_chunk(chunk.data)
                if utterance is not None:
                    await self._process_utterance(utterance)

        except _VOICE_ERRORS as e:
            logger.error("Capture loop error: %s", e)
            self.stats.errors += 1

    async def _process_utterance(self, audio: np.ndarray) -> None:
        """Process a complete utterance."""
        parts = self._parts
        if parts is None:
            return
        self.stats.total_utterances += 1
        audio_duration_ms = len(audio) / self.config.sample_rate * 1000

        logger.info(
            "[VOICE] 🎤 Processing utterance #%s (%.0fms audio)", self.stats.total_utterances, audio_duration_ms
        )

        # Transcribe via NPU/STT
        stt_start = time.time()
        result = await parts.stt.transcribe(audio, sample_rate=self.config.sample_rate)
        stt_time_ms = (time.time() - stt_start) * 1000

        if not result.text:
            logger.info("[VOICE] 🔇 No speech detected (STT took %.0fms)", stt_time_ms)
            return

        text = result.text
        logger.info('[VOICE] 📝 STT Result (%.0fms): "%s"', stt_time_ms, text)

        if self.config.on_transcription:
            self.config.on_transcription(text)

        wake_word = self.config.wake_word
        event = parts.wake_detector.process_caption("Meeting", text)
        if event:
            self.stats.wake_word_triggers += 1
            logger.info('[VOICE] 🔔 WAKE WORD DETECTED! Wake word: "%s"', wake_word)
            logger.info('[VOICE] 🔔 Command after wake word: "%s"', event.command_text)

            if self.config.on_wake_word:
                self.config.on_wake_word(event)

            await self._respond_to_command(event)
        else:
            shown = f"{text[:50]}..." if len(text) > 50 else text
            logger.debug('[VOICE] No wake word "%s" in: "%s"', wake_word, shown)

    async def _generate_reply(self, parts: _Components, event: WakeWordEvent) -> str | None:
        """Ask the LLM for a reply to the wake-word command; None on failure."""
        command = event.command_text
        speaker = event.speaker
        context = event.context_before

        logger.info('[VOICE] 🤖 Processing command from %s: "%s"', speaker, command)
        if context:
            if len(context) > 100:
                logger.info('[VOICE] 📋 Context before wake word: "%s..."', context[:100])
            else:
                logger.info('[VOICE] 📋 Context: "%s"', context)

        logger.info("[VOICE] 🧠 Sending to Gemini LLM...")
        llm_start = time.time()
        llm_response = await parts.llm.generate_response(command, speaker=speaker, context_before=context)
        llm_time_ms = (time.time() - llm_start) * 1000

        if not llm_response.success or not llm_response.text:
            logger.error("[VOICE] ❌ LLM failed (%.0fms): %s", llm_time_ms, llm_response.error)
            return None

        logger.info('[VOICE] 💬 Gemini response (%.0fms): "%s"', llm_time_ms, llm_response.text)
        return llm_response.text

    async def _synthesize(self, parts: _Components, text: str) -> Any:
        """Synthesize speech; return the TTS result or None on failure."""
        tts_start = time.time()
        tts_result = await parts.tts.synthesize(text)
        tts_time_ms = (time.time() - tts_start) * 1000

        if not tts_result.success:
            logger.error("[VOICE] ❌ TTS failed (%.0fms): %s", tts_time_ms, tts_result.error)
            return None

        audio_duration_ms = (
            len(tts_result.audio_data) / tts_result.sample_rate * 1000 if tts_result.audio_data is not None else 0
        )
        logger.info("[VOICE] 🔊 TTS complete (%.0fms, %.0fms audio)", tts_time_ms, audio_duration_ms)
        return tts_result

    async def _speak(self, parts: _Components, tts_result: Any) -> None:
        """Unmute, play the synthesized audio, and always re-mute."""
        if self._controller:
            logger.info("[VOICE] 🎙️ Unmuting microphone...")
            await self._controller.unmute_and_speak()
        try:
            logger.info("[VOICE] 📢 Playing audio to meeting...")
            await parts.audio_output.play_tts_result(tts_result)
        finally:
            if self._controller:
                await self._controller.mute()
                logger.info("[VOICE] 🔇 Re-muted microphone")

    async def _mute_quietly(self) -> None:
        """Best-effort mute after a failure."""
        if self._controller:
            try:
                await self._controller.mute()
            except _VOICE_ERRORS as e:
                logger.debug("Mute after failure also failed: %s", e)

    async def _respond_to_command(self, event: WakeWordEvent) -> None:
        """Generate and speak a response to a wake word command."""
        if self._state.processing_response:
            logger.warning("[VOICE] ⚠️ Already processing a response, ignoring new wake word")
            return
        parts = self._parts
        if parts is None:
            return

        self._state.processing_response = True
        start_time = time.time()

        try:
            response_text = await self._generate_reply(parts, event)
            if response_text is None:
                self.stats.errors += 1
                return

            if self.config.on_response:
                self.config.on_response(response_text)

            # Synthesize speech (before unmuting)
            logger.info("[VOICE] 🔊 Synthesizing TTS (Piper)...")
            tts_result = await self._synthesize(parts, response_text)
            if tts_result is None:
                self.stats.errors += 1
                return

            await self._speak(parts, tts_result)

            latency = (time.time() - start_time) * 1000
            self.stats.record_response(latency)
            logger.info("[VOICE] ✅ Response complete! Total latency: %.0fms (STT→LLM→TTS→Play)", latency)

        except _VOICE_ERRORS as e:
            logger.error("[VOICE] ❌ Response generation failed: %s", e)
            self.stats.errors += 1
            await self._mute_quietly()
        finally:
            self._state.processing_response = False

    async def send_message(self, text: str) -> bool:
        """
        Send a text message to the meeting via TTS.

        This allows sending typed messages as voice.
        Automatically unmutes before speaking and re-mutes after.

        Args:
            text: Text to speak

        Returns:
            True if sent successfully
        """
        if self._state.processing_response:
            logger.warning("Already processing, queuing not supported")
            return False
        parts = self._parts
        if parts is None:
            logger.error("Send message failed: voice pipeline not initialized")
            return False

        self._state.processing_response = True

        try:
            tts_result = await self._synthesize(parts, text)
            if tts_result is None:
                return False

            await self._speak(parts, tts_result)

            logger.info("Sent message: %s...", text[:50])
            return True

        except _VOICE_ERRORS as e:
            logger.error("Send message failed: %s", e)
            await self._mute_quietly()
            return False
        finally:
            self._state.processing_response = False

    def get_stats(self) -> dict:
        """Get pipeline statistics."""
        return {
            "total_utterances": self.stats.total_utterances,
            "wake_word_triggers": self.stats.wake_word_triggers,
            "responses_generated": self.stats.responses_generated,
            "avg_latency_ms": self.stats.avg_latency_ms,
            "min_latency_ms": (self.stats.min_latency_ms if self.stats.min_latency_ms != float("inf") else 0),
            "max_latency_ms": self.stats.max_latency_ms,
            "errors": self.stats.errors,
            "running": self._state.running,
            "processing": self._state.processing_response,
        }


class VoicePipelineManager:
    """
    Manages voice pipelines for multiple meeting instances.
    """

    def __init__(self):
        self._pipelines: dict[str, VoicePipeline] = {}

    async def create_pipeline(
        self,
        instance_id: str,
        sink_name: str,
        pipe_path: Path,
        config: VoicePipelineConfig | None = None,
        controller: "GoogleMeetController | None" = None,
    ) -> VoicePipeline:
        """Create and start a voice pipeline for a meeting instance."""
        if instance_id in self._pipelines:
            logger.warning("Pipeline already exists for %s", instance_id)
            return self._pipelines[instance_id]

        pipeline = VoicePipeline(sink_name, pipe_path, config, controller)
        await pipeline.start()

        self._pipelines[instance_id] = pipeline
        return pipeline

    async def stop_pipeline(self, instance_id: str) -> None:
        """Stop and remove a pipeline."""
        if instance_id not in self._pipelines:
            return

        pipeline = self._pipelines.pop(instance_id)
        await pipeline.stop()

    async def stop_all(self) -> None:
        """Stop all pipelines."""
        for instance_id in list(self._pipelines.keys()):
            await self.stop_pipeline(instance_id)

    def get_pipeline(self, instance_id: str) -> VoicePipeline | None:
        """Get a pipeline by instance ID."""
        return self._pipelines.get(instance_id)

    def get_all_stats(self) -> dict:
        """Get stats for all pipelines."""
        return {instance_id: pipeline.get_stats() for instance_id, pipeline in self._pipelines.items()}


@functools.cache
def get_pipeline_manager() -> VoicePipelineManager:
    """Get the global pipeline manager."""
    return VoicePipelineManager()
