"""Tests for the PulseAudio pipe writer used by the meet bot."""

import os
import wave
from types import SimpleNamespace

import numpy as np

from tool_modules.aa_meet_bot.src import audio_output
from tool_modules.aa_meet_bot.src.audio_output import AudioOutputManager, AudioPipeWriter


def _fifo_with_reader(tmp_path):
    """Create a FIFO with an open non-blocking reader so writes succeed."""
    path = tmp_path / "pipe"
    os.mkfifo(path)
    reader = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    return path, reader


def test_write_converts_to_int16(tmp_path):
    """Float audio is clipped and written as int16 PCM."""
    path, reader = _fifo_with_reader(tmp_path)
    try:
        writer = AudioPipeWriter(path)
        assert writer.write(np.array([0.5, 2.0, -2.0], dtype=np.float32))
        data = np.frombuffer(os.read(reader, 64), dtype=np.int16)
        assert data.tolist() == [16383, 32767, -32767]
        writer.close()
        assert not writer.is_open()
    finally:
        os.close(reader)


def test_write_fails_when_pipe_missing(tmp_path):
    """A missing pipe means write() returns False instead of writing to a None fd."""
    assert not AudioPipeWriter(tmp_path / "missing").write(np.zeros(4, dtype=np.float32))


def test_write_fails_without_reader(tmp_path):
    """ENXIO (no reader) is reported as a failed open."""
    path = tmp_path / "pipe"
    os.mkfifo(path)
    assert not AudioPipeWriter(path).write(np.zeros(4, dtype=np.float32))


def test_write_handles_os_error(tmp_path, monkeypatch):
    """OS errors during write are logged and reported as failure."""
    path, reader = _fifo_with_reader(tmp_path)
    try:
        writer = AudioPipeWriter(path)
        assert writer.open()

        def fail(*_args):
            raise OSError("boom")

        monkeypatch.setattr(audio_output.os, "write", fail)
        assert not writer.write(np.zeros(4, dtype=np.float32))
        writer.close()
    finally:
        os.close(reader)


def test_resample_length():
    """Linear resampling changes the sample count by the rate ratio."""
    writer = AudioPipeWriter(SimpleNamespace())
    out = vars(AudioPipeWriter)["_resample"](writer, np.ones(160, dtype=np.float32), 16000, 8000)
    assert len(out) == 80
    assert out.dtype == np.float32


async def test_play_tts_result_from_wav(tmp_path, monkeypatch):
    """A TTS result with only a WAV path is loaded from disk and played."""
    wav_path = tmp_path / "a.wav"
    with wave.Wave_write(str(wav_path)) as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(np.array([16384, -16384], dtype=np.int16).tobytes())
    played = {}

    async def fake_play(audio, rate, real_time=True):
        played.update(audio=audio.tolist(), rate=rate, real_time=real_time)
        return True

    manager = AudioOutputManager(tmp_path / "pipe")
    monkeypatch.setattr(manager, "play_audio", fake_play)
    assert await manager.play_tts_result(SimpleNamespace(audio_data=None, audio_path=wav_path))
    assert played == {"audio": [0.5, -0.5], "rate": 8000, "real_time": True}


async def test_play_tts_result_without_audio(tmp_path):
    """A TTS result with no audio is rejected."""
    manager = AudioOutputManager(tmp_path / "pipe")
    assert not await manager.play_tts_result(SimpleNamespace(audio_data=None, audio_path=None))
