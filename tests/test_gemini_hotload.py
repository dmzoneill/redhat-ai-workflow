"""Tests for GeminiHotload start-up and send behaviour."""

import asyncio

from tool_modules.aa_meet_bot.src.gemini_hotload import GeminiHotload


def _with_reply(hotload, reply):
    """Replace the CLI call with a coroutine returning ``reply``."""

    async def fake_call(_prompt):
        return reply

    vars(hotload)["_call_gemini"] = fake_call
    return hotload


def test_start_without_prompt_is_ready():
    """No warm-up is needed without a system prompt."""
    hotload = _with_reply(GeminiHotload(), None)
    assert asyncio.run(hotload.start()) is True
    assert hotload.is_running


def test_start_reports_failed_warm_up():
    """A silent CLI during warm-up makes start() return False."""
    hotload = _with_reply(GeminiHotload(system_prompt="be brief"), None)
    assert asyncio.run(hotload.start()) is False
    assert not hotload.is_running


def test_start_with_working_warm_up():
    """A warm-up reply makes start() return True."""
    hotload = _with_reply(GeminiHotload(system_prompt="be brief"), "Ready.")
    assert asyncio.run(hotload.start()) is True


def test_send_reports_start_failure():
    """send() surfaces a failed start as an error response."""
    hotload = _with_reply(GeminiHotload(system_prompt="be brief"), None)
    response = asyncio.run(hotload.send("hi"))
    assert response.error == "Failed to start Gemini"


def test_send_records_history():
    """A successful send keeps both turns in history."""
    hotload = _with_reply(GeminiHotload(), "hello")
    response = asyncio.run(hotload.send("hi"))
    assert response.text == "hello"
    assert response.error is None
    assert hotload.history_length == 2


def test_send_contains_os_errors():
    """OS errors from the CLI become error responses."""
    hotload = GeminiHotload()

    async def broken(_prompt):
        raise OSError("no bash")

    vars(hotload)["_call_gemini"] = broken
    assert asyncio.run(hotload.send("hi")).error == "no bash"
