"""Tests for the fake research tool URLs shown in the meet-bot video frames."""

from types import SimpleNamespace

import pytest

video_frame = pytest.importorskip("tool_modules.aa_meet_bot.src.video_frame")


def test_fallback_tools_use_ldaps():
    """The fallback tool list shows directory lookups over LDAPS."""
    realistic_tools = vars(video_frame.RealtimeFrameMixin)["_realistic_tools"]
    tools = realistic_tools(None, SimpleNamespace(name="Ada Lovelace"), None)
    assert "ldaps://query?uid=alovelace" in tools
    assert not any(t.startswith("ldap://") for t in tools)


def test_enriched_tools_are_passed_through():
    """Enrichment data supplies its own tool list unchanged."""
    realistic_tools = vars(video_frame.RealtimeFrameMixin)["_realistic_tools"]
    assert realistic_tools(None, SimpleNamespace(name="x"), {"tools": ["a"]}) == ["a"]
