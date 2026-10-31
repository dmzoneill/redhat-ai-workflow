"""Check the ffmpeg command lines built by the research video generator."""

import asyncio
from pathlib import Path

import pytest

from tool_modules.aa_meet_bot.src.video_config import Attendee

# video_theme needs OpenCV; skip cleanly where it is not installed.
video_research = pytest.importorskip("tool_modules.aa_meet_bot.src.video_research")

VALID_FLAGS = {"-y", "-re", "-f", "-i", "-vf", "-c:v", "-preset", "-crf", "-pix_fmt", "-t"}


class _FakeProcess:
    returncode = 0

    async def communicate(self):
        """Return empty output like a finished ffmpeg run."""
        return b"", b""

    async def wait(self):
        """Return the exit status like a finished ffmpeg run."""
        return 0


@pytest.fixture(name="captured")
def fixture_captured(monkeypatch):
    """Capture the argv passed to create_subprocess_exec."""
    calls: list[list[str]] = []

    async def fake_exec(*cmd, **_kwargs):
        calls.append(list(cmd))
        return _FakeProcess()

    monkeypatch.setattr(video_research.asyncio, "create_subprocess_exec", fake_exec)
    return calls


def _private(obj, name: str):
    """Fetch a private coroutine method by name for command-building tests."""
    return getattr(obj, name)


def _flags(cmd: list[str]) -> list[str]:
    return [arg for arg in cmd[1:-1] if arg.startswith("-") and arg != "-"]


def _value_after(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


def test_generate_video_file_command(captured, tmp_path: Path):
    """The file render uses -f lavfi, -vf and -crf rather than mangled flags."""
    out = tmp_path / "out.mp4"
    gen = video_research.ResearchVideoGenerator()
    asyncio.run(gen.generate_video_file([Attendee(name="Alice")], out))
    cmd = captured[0]
    assert set(_flags(cmd)) <= VALID_FLAGS
    assert _value_after(cmd, "-f") == "lavfi"
    assert _value_after(cmd, "-crf") == "23"
    assert "drawtext" in _value_after(cmd, "-vf")
    assert cmd[-1] == str(out)


def test_stdout_stream_command(captured):
    """The stdout stream writes matroska to '-'."""
    gen = video_research.ResearchVideoGenerator()
    asyncio.run(_private(gen, "_stream_single_attendee_stdout")(Attendee(name="Bob"), 0, 1))
    cmd = captured[0]
    assert set(_flags(cmd)) <= VALID_FLAGS
    formats = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-f"]
    assert formats == ["lavfi", "matroska"]
    assert cmd[-1] == "-"


def test_device_stream_command(captured):
    """The v4l2 stream sets the output format before the device path."""
    gen = video_research.ResearchVideoGenerator()
    asyncio.run(_private(gen, "_stream_single_attendee")(Attendee(name="Cy"), "/dev/video9", 0, 1))
    cmd = captured[0]
    assert set(_flags(cmd)) <= VALID_FLAGS
    formats = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-f"]
    assert formats == ["lavfi", "v4l2"]
    assert cmd[-1] == "/dev/video9"
