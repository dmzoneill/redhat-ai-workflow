"""Tests for the meet-bot voice pipeline."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from tool_modules.aa_meet_bot.src import voice_pipeline
from tool_modules.aa_meet_bot.src.voice_pipeline import (
    UtteranceSegmenter,
    VoicePipeline,
    VoicePipelineConfig,
    VoicePipelineStats,
    get_pipeline_manager,
)


def _speech(n=1600, level=0.5):
    return np.full(n, level, dtype=np.float32)


def _silence(n=1600):
    return np.zeros(n, dtype=np.float32)


def test_module_imports_and_stats_defaults():
    """The module imports (float('inf') default) and stats start empty."""
    stats = VoicePipelineStats()
    assert stats.min_latency_ms == float("inf")
    assert stats.avg_latency_ms == 0.0
    stats.record_response(100.0)
    stats.record_response(300.0)
    assert (stats.min_latency_ms, stats.max_latency_ms, stats.avg_latency_ms) == (100.0, 300.0, 200.0)


def test_config_keyword_construction():
    """VoicePipelineConfig keeps its keyword constructor and defaults."""
    config = VoicePipelineConfig(wake_word="bot", stt_model="base", stt_device="CPU")
    assert config.wake_word == "bot"
    assert config.stt_device == "CPU"
    assert config.sample_rate == 16000
    assert config.on_response is None


def test_segmenter_emits_after_silence():
    """Speech followed by >= 800ms of silence is emitted with its trailing silence."""
    seg = UtteranceSegmenter()
    assert seg.add_chunk(_silence()) is None  # leading silence ignored
    assert seg.add_chunk(_speech()) is None
    for _ in range(7):
        assert seg.add_chunk(_silence()) is None
    utterance = seg.add_chunk(_silence())
    assert utterance is not None
    assert len(utterance) == 9 * 1600
    assert seg.add_chunk(_silence()) is None


def test_segmenter_caps_utterance_length():
    """Continuous speech is cut at the maximum utterance length."""
    seg = UtteranceSegmenter(max_utterance_ms=500)
    results = [seg.add_chunk(_speech()) for _ in range(5)]
    assert all(r is None for r in results[:4])
    assert results[4] is not None
    assert seg.add_chunk(np.zeros(0, dtype=np.float32)) is None


def _pipeline_with_parts(monkeypatch, *, tts_success=True, llm_text="Hi there"):
    calls = []

    async def transcribe(audio, sample_rate):
        calls.append(("stt", len(audio), sample_rate))
        return SimpleNamespace(text="david what is up")

    async def generate_response(command, speaker, context_before):
        calls.append(("llm", command, speaker, context_before))
        return SimpleNamespace(success=bool(llm_text), text=llm_text, error="e")

    async def synthesize(text):
        calls.append(("tts", text))
        return SimpleNamespace(success=tts_success, error="e", audio_data=_speech(800), sample_rate=16000)

    async def play(result):
        calls.append(("play", len(result.audio_data)))
        return True

    event = SimpleNamespace(command_text="what is up", speaker="Meeting", context_before=[])
    parts = SimpleNamespace(
        stt=SimpleNamespace(transcribe=transcribe),
        llm=SimpleNamespace(generate_response=generate_response),
        tts=SimpleNamespace(synthesize=synthesize),
        wake_detector=SimpleNamespace(process_caption=lambda _speaker, text: event if "david" in text else None),
        audio_output=SimpleNamespace(play_tts_result=play, close=lambda: None),
    )

    async def unmute():
        calls.append(("unmute",))

    async def mute():
        calls.append(("mute",))

    controller = SimpleNamespace(unmute_and_speak=unmute, mute=mute)
    responses = []
    pipeline = VoicePipeline("sink", Path("/tmp/p"), VoicePipelineConfig(on_response=responses.append), controller)
    monkeypatch.setattr(pipeline, "_parts", parts)
    return pipeline, calls, responses


async def test_utterance_to_spoken_reply(monkeypatch):
    """An utterance with the wake word goes STT -> LLM -> TTS -> unmute/play/mute."""
    pipeline, calls, responses = _pipeline_with_parts(monkeypatch)
    await vars(VoicePipeline)["_process_utterance"](pipeline, _speech(3200))
    assert [c[0] for c in calls] == ["stt", "llm", "tts", "unmute", "play", "mute"]
    assert calls[0] == ("stt", 3200, 16000)
    assert responses == ["Hi there"]
    stats = pipeline.get_stats()
    assert stats["responses_generated"] == 1
    assert stats["wake_word_triggers"] == 1
    assert stats["min_latency_ms"] > 0
    assert not stats["processing"]


async def test_llm_and_tts_failures_count_errors(monkeypatch):
    """Failures are counted and nothing is played."""
    pipeline, calls, _ = _pipeline_with_parts(monkeypatch, llm_text="")
    await vars(VoicePipeline)["_process_utterance"](pipeline, _speech())
    assert "play" not in [c[0] for c in calls]
    assert pipeline.stats.errors == 1
    pipeline, calls, _ = _pipeline_with_parts(monkeypatch, tts_success=False)
    await vars(VoicePipeline)["_process_utterance"](pipeline, _speech())
    assert "play" not in [c[0] for c in calls]
    assert pipeline.stats.errors == 1
    assert pipeline.get_stats()["min_latency_ms"] == 0


async def test_send_message(monkeypatch):
    """send_message speaks the text; without components it fails cleanly."""
    pipeline, calls, _ = _pipeline_with_parts(monkeypatch)
    assert await pipeline.send_message("hello")
    assert [c[0] for c in calls] == ["tts", "unmute", "play", "mute"]
    assert not await VoicePipeline("sink", Path("/tmp/p")).send_message("hello")


async def test_capture_loop_feeds_segmenter(monkeypatch):
    """The capture loop reads chunks, segments them and stops when the source goes away."""
    pipeline, calls, _ = _pipeline_with_parts(monkeypatch)
    chunks = [_speech()] + [_silence()] * 8
    started = []

    async def start():
        started.append(True)
        return True

    async def read_chunk():
        return SimpleNamespace(data=chunks.pop(0)) if chunks else None

    vars(pipeline)["_parts"].audio_capture = SimpleNamespace(start=start, read_chunk=read_chunk)
    vars(pipeline)["_state"].running = True
    await asyncio.wait_for(vars(VoicePipeline)["_capture_loop"](pipeline), timeout=5)
    assert started == [True]
    assert pipeline.stats.total_utterances == 1
    assert calls[0] == ("stt", 9 * 1600, 16000)


def test_get_pipeline_manager_singleton():
    """The global manager is shared."""
    assert get_pipeline_manager() is get_pipeline_manager()
    assert voice_pipeline.get_pipeline_manager().get_all_stats() == {}
