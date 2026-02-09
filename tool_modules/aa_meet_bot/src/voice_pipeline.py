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
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import numpy as np

if TYPE_CHECKING:
    from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController
    from tool_modules.aa_meet_bot.src.llm_responder import LLMResponder
    from tool_modules.aa_meet_bot.src.tts_engine import TTSEngine

from tool_modules.common import PROJECT_ROOT

__project_root__ = PROJECT_ROOT

from tool_modules.aa_meet_bot.src.audio_capture import AudioBuffer, AudioCapture
from tool_modules.aa_meet_bot.src.audio_output import AudioOutputManager
from tool_modules.aa_meet_bot.src.llm_responder import get_llm_responder
from tool_modules.aa_meet_bot.src.stt_engine import OpenVINOSTT
from tool_modules.aa_meet_bot.src.tts_engine import get_tts_engine
from tool_modules.aa_meet_bot.src.wake_word import TextWakeWordDetector, WakeWordEvent

logger = logging.getLogger(__name__)


@dataclass
class VoicePipelineStats:
    """Statistics for the voice pipeline."""

    total_utterances: int = 0
    wake_word_triggers: int = 0
    responses_generated: int = 0
    total_latency_ms: float = 0.0
    min_latency_ms: float = float("in")
    max_latency_ms: float = 0.0
    errors: int = 0

    @property
    def avg_latency_ms(self) -> float:
        if self.responses_generated == 0:
            return 0.0
        return self.total_latency_ms / self.responses_generated


@dataclass
class VoicePipelineConfig:
    """Configuration for the voice pipeline."""

    # Wake word
    wake_word: str = "david"

    # STT settings
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
    on_transcription: Optional[Callable[[str], None]] = None
    on_wake_word: Optional[Callable[[WakeWordEvent], None]] = None
    on_response: Optional[Callable[[str], None]] = None


class VoicePipeline:
    """
    Full voice interaction pipeline for a meeting instance.

    Handles the complete flow from audio capture to voice response.
    """

    def __init__(
        self,
        sink_name: str,
        pipe_path: Path,
        config: Optional[VoicePipelineConfig] = None,
        controller: Optional["GoogleMeetController"] = None,
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

        # Components
        self._audio_capture: Optional[AudioCapture] = None
        self._audio_output: Optional[AudioOutputManager] = None
        self._stt: Optional[OpenVINOSTT] = None
        self._llm: Optional[LLMResponder] = None
        self._tts: Optional[TTSEngine] = None
        self._wake_detector: Optional[TextWakeWordDetector] = None

        # State
        self._running = False
        self._processing_response = False
        self._capture_task: Optional[asyncio.Task] = None
        self._executor = ThreadPoolExecutor(max_workers=2)

        # Stats
        self.stats = VoicePipelineStats()

    async def initialize(self) -> bool:
        """Initialize all pipeline components."""
        logger.info(f"Initializing voice pipeline for sink: {self.sink_name}")

        try:
            # Initialize STT
            self._stt = OpenVINOSTT(
                model_name=self.config.stt_model,
                device=self.config.stt_device,
            )
            if not await self._stt.load():
                logger.warning("STT initialization failed, will retry on first use")

            # Initialize LLM
            self._llm = get_llm_responder(backend=self.config.llm_backend)
            if not await self._llm.initialize():
                logger.warning("LLM initialization failed, will retry on first use")

            # Initialize TTS
            self._tts = get_tts_engine(backend=self.config.tts_backend)
            if not await self._tts.initialize():
                logger.warning("TTS initialization failed, will retry on first use")

            # Initialize wake word detector
            self._wake_detector = TextWakeWordDetector(wake_word=self.config.wake_word)

            # Initialize audio components
            self._audio_capture = AudioCapture(
                self.sink_name,
                sample_rate=self.config.sample_rate,
            )
            self._audio_output = AudioOutputManager(
                self.pipe_path,
                target_sample_rate=self.config.sample_rate,
            )

            logger.info("Voice pipeline initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize voice pipeline: {e}")
            return False

    async def start(self) -> None:
        """Start the voice pipeline."""
        if self._running:
            logger.warning("[VOICE] Voice pipeline already running")
            return

        if not await self.initialize():
            logger.error("[VOICE] Failed to initialize pipeline")
            return

        self._running = True
        self._capture_task = asyncio.create_task(self._capture_loop())
        logger.info("[VOICE] ========================================")
        logger.info("[VOICE] 🎧 VOICE PIPELINE STARTED")
        logger.info(f'[VOICE] 🔑 Wake word: "{self.config.wake_word}"')
        logger.info(f"[VOICE] 🎤 Listening on sink: {self.sink_name}")
        logger.info(f"[VOICE] 🔊 Output pipe: {self.pipe_path}")
        logger.info(
            f"[VOICE] 🧠 STT: {self.config.stt_model} on {self.config.stt_device}"
        )
        logger.info(f"[VOICE] 💬 LLM: {self.config.llm_backend}")
        logger.info(f"[VOICE] 🔈 TTS: {self.config.tts_backend}")
        logger.info("[VOICE] ========================================")

    async def stop(self) -> None:
        """Stop the voice pipeline."""
        self._running = False

        if self._capture_task:
            self._capture_task.cancel()
            try:
                await self._capture_task
            except asyncio.CancelledError:
                pass
            self._capture_task = None

        if self._audio_capture:
            await self._audio_capture.stop()

        if self._audio_output:
            self._audio_output.close()

        self._executor.shutdown(wait=False)

        logger.info("[VOICE] ========================================")
        logger.info("[VOICE] 🛑 VOICE PIPELINE STOPPED")
        logger.info("[VOICE] 📊 Stats:")
        logger.info(f"[VOICE]    Utterances processed: {self.stats.total_utterances}")
        logger.info(f"[VOICE]    Wake word triggers: {self.stats.wake_word_triggers}")
        logger.info(f"[VOICE]    Responses generated: {self.stats.responses_generated}")
        if self.stats.responses_generated > 0:
            avg_latency = self.stats.total_latency_ms / self.stats.responses_generated
            logger.info(f"[VOICE]    Avg latency: {avg_latency:.0f}ms")
            logger.info(f"[VOICE]    Min latency: {self.stats.min_latency_ms:.0f}ms")
            logger.info(f"[VOICE]    Max latency: {self.stats.max_latency_ms:.0f}ms")
        logger.info(f"[VOICE]    Errors: {self.stats.errors}")
        logger.info("[VOICE] ========================================")

    async def _capture_loop(self) -> None:
        """Main capture and processing loop."""
        audio_buffer = AudioBuffer(
            sample_rate=self.config.sample_rate,
            silence_threshold=0.02,
            min_silence_duration_ms=800,
            max_buffer_duration_ms=30000,
        )

        try:
            async for audio_chunk in self._audio_capture.start_numpy():
                if not self._running:
                    break

                # Skip processing if we're currently responding
                if self._processing_response:
                    continue

                # Buffer audio until utterance complete
                utterance = audio_buffer.add_chunk(audio_chunk)
                if utterance is None or len(utterance) == 0:
                    continue

                # Process utterance
                await self._process_utterance(utterance)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Capture loop error: {e}")
            self.stats.errors += 1

    async def _process_utterance(self, audio: np.ndarray) -> None:
        """Process a complete utterance."""
        self.stats.total_utterances += 1
        audio_duration_ms = len(audio) / self.config.sample_rate * 1000

        logger.info(
            f"[VOICE] 🎤 Processing utterance #{self.stats.total_utterances} ({audio_duration_ms:.0f}ms audio)"
        )

        # Transcribe via NPU/STT
        stt_start = time.time()
        result = await self._stt.transcribe(audio)
        stt_time_ms = (time.time() - stt_start) * 1000

        if not result.text:
            logger.info(f"[VOICE] 🔇 No speech detected (STT took {stt_time_ms:.0f}ms)")
            return

        text = result.text
        logger.info(f'[VOICE] 📝 STT Result ({stt_time_ms:.0f}ms): "{text}"')

        # Callback
        if self.config.on_transcription:
            self.config.on_transcription(text)

        # Check for wake word
        wake_word = self.config.wake_word
        event = self._wake_detector.process_caption("Meeting", text)
        if event:
            self.stats.wake_word_triggers += 1
            logger.info(f'[VOICE] 🔔 WAKE WORD DETECTED! Wake word: "{wake_word}"')
            logger.info(f'[VOICE] 🔔 Command after wake word: "{event.command_text}"')

            # Callback
            if self.config.on_wake_word:
                self.config.on_wake_word(event)

            # Generate and speak response
            await self._respond_to_command(event)
        else:
            logger.debug(
                f'[VOICE] No wake word "{wake_word}" in: "{text[:50]}..."'
                if len(text) > 50
                else f'[VOICE] No wake word "{wake_word}" in: "{text}"'
            )

    async def _respond_to_command(self, event: WakeWordEvent) -> None:
        """Generate and speak a response to a wake word command."""
        if self._processing_response:
            logger.warning(
                "[VOICE] ⚠️ Already processing a response, ignoring new wake word"
            )
            return

        self._processing_response = True
        start_time = time.time()

        try:
            command = event.command_text
            speaker = event.speaker
            context = event.context_before

            logger.info(f'[VOICE] 🤖 Processing command from {speaker}: "{command}"')
            if context:
                logger.info(
                    f'[VOICE] 📋 Context before wake word: "{context[:100]}..."'
                    if len(context) > 100
                    else f'[VOICE] 📋 Context: "{context}"'
                )

            # Generate LLM response
            logger.info("[VOICE] 🧠 Sending to Gemini LLM...")
            llm_start = time.time()
            llm_response = await self._llm.generate_response(
                command,
                speaker=speaker,
                context_before=context,
            )
            llm_time_ms = (time.time() - llm_start) * 1000

            if not llm_response.success or not llm_response.text:
                logger.error(
                    f"[VOICE] ❌ LLM failed ({llm_time_ms:.0f}ms): {llm_response.error}"
                )
                self.stats.errors += 1
                return

            response_text = llm_response.text
            logger.info(
                f'[VOICE] 💬 Gemini response ({llm_time_ms:.0f}ms): "{response_text}"'
            )

            # Callback
            if self.config.on_response:
                self.config.on_response(response_text)

            # Synthesize speech (before unmuting)
            logger.info("[VOICE] 🔊 Synthesizing TTS (Piper)...")
            tts_start = time.time()
            tts_result = await self._tts.synthesize(response_text)
            tts_time_ms = (time.time() - tts_start) * 1000

            if not tts_result.success:
                logger.error(
                    f"[VOICE] ❌ TTS failed ({tts_time_ms:.0f}ms): {tts_result.error}"
                )
                self.stats.errors += 1
                return

            audio_duration_ms = (
                len(tts_result.audio_data) / tts_result.sample_rate * 1000
                if tts_result.audio_data is not None
                else 0
            )
            logger.info(
                f"[VOICE] 🔊 TTS complete ({tts_time_ms:.0f}ms, {audio_duration_ms:.0f}ms audio)"
            )

            # Unmute microphone before speaking
            if self._controller:
                logger.info("[VOICE] 🎙️ Unmuting microphone...")
                await self._controller.unmute_and_speak()

            try:
                # Play audio
                logger.info("[VOICE] 📢 Playing audio to meeting...")
                await self._audio_output.play_tts_result(tts_result)
            finally:
                # Always re-mute after speaking
                if self._controller:
                    await self._controller.mute()
                    logger.info("[VOICE] 🔇 Re-muted microphone")

            # Record stats
            latency = (time.time() - start_time) * 1000
            self.stats.responses_generated += 1
            self.stats.total_latency_ms += latency
            self.stats.min_latency_ms = min(self.stats.min_latency_ms, latency)
            self.stats.max_latency_ms = max(self.stats.max_latency_ms, latency)

            logger.info(
                f"[VOICE] ✅ Response complete! Total latency: {latency:.0f}ms (STT→LLM→TTS→Play)"
            )

        except Exception as e:
            logger.error(f"[VOICE] ❌ Response generation failed: {e}")
            self.stats.errors += 1
            # Ensure we're muted even on error
            if self._controller:
                try:
                    await self._controller.mute()
                except Exception:
                    pass
        finally:
            self._processing_response = False

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
        if self._processing_response:
            logger.warning("Already processing, queuing not supported")
            return False

        self._processing_response = True

        try:
            # Synthesize first (before unmuting)
            tts_result = await self._tts.synthesize(text)

            if not tts_result.success:
                logger.error(f"TTS failed: {tts_result.error}")
                return False

            # Unmute microphone before speaking
            if self._controller:
                await self._controller.unmute_and_speak()
                logger.debug("Unmuted microphone for send_message")

            try:
                # Play
                await self._audio_output.play_tts_result(tts_result)
            finally:
                # Always re-mute after speaking
                if self._controller:
                    await self._controller.mute()
                    logger.debug("Re-muted microphone after send_message")

            logger.info(f"Sent message: {text[:50]}...")
            return True

        except Exception as e:
            logger.error(f"Send message failed: {e}")
            # Ensure we're muted even on error
            if self._controller:
                try:
                    await self._controller.mute()
                except Exception:
                    pass
            return False
        finally:
            self._processing_response = False

    def get_stats(self) -> dict:
        """Get pipeline statistics."""
        return {
            "total_utterances": self.stats.total_utterances,
            "wake_word_triggers": self.stats.wake_word_triggers,
            "responses_generated": self.stats.responses_generated,
            "avg_latency_ms": self.stats.avg_latency_ms,
            "min_latency_ms": (
                self.stats.min_latency_ms
                if self.stats.min_latency_ms != float("in")
                else 0
            ),
            "max_latency_ms": self.stats.max_latency_ms,
            "errors": self.stats.errors,
            "running": self._running,
            "processing": self._processing_response,
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
        config: Optional[VoicePipelineConfig] = None,
        controller: Optional["GoogleMeetController"] = None,
    ) -> VoicePipeline:
        """Create and start a voice pipeline for a meeting instance."""
        if instance_id in self._pipelines:
            logger.warning(f"Pipeline already exists for {instance_id}")
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

    def get_pipeline(self, instance_id: str) -> Optional[VoicePipeline]:
        """Get a pipeline by instance ID."""
        return self._pipelines.get(instance_id)

    def get_all_stats(self) -> dict:
        """Get stats for all pipelines."""
        return {
            instance_id: pipeline.get_stats()
            for instance_id, pipeline in self._pipelines.items()
        }


# Global manager
_pipeline_manager: Optional[VoicePipelineManager] = None


def get_pipeline_manager() -> VoicePipelineManager:
    """Get the global pipeline manager."""
    global _pipeline_manager
    if _pipeline_manager is None:
        _pipeline_manager = VoicePipelineManager()
    return _pipeline_manager
