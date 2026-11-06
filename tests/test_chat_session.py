"""Tests for ChatSession and persona tool count defaults."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from server.workspace_state import (
    MAX_FILTER_CACHE_SIZE,
    ChatSession,
    get_all_persona_tool_counts,
    get_default_persona,
    get_persona_tool_count,
    update_persona_tool_count,
)


class TestChatSession:
    """Tests for ChatSession dataclass."""

    def test_default_values(self):
        """Test ChatSession has correct defaults."""
        session = ChatSession(
            session_id="abc123",
            workspace_uri="file:///test",
        )

        assert session.session_id == "abc123"
        assert session.workspace_uri == "file:///test"
        assert session.persona == get_default_persona()
        assert session.issue_key is None
        assert session.branch is None
        assert session.active_tools == set()
        assert session.started_at is not None
        assert session.last_activity is not None
        assert not session.tool_filter_cache

    def test_to_dict(self):
        """Test ChatSession serialization."""
        session = ChatSession(
            session_id="abc123",
            workspace_uri="file:///test",
            persona="devops",
            issue_key="AAP-12345",
            branch="feature-branch",
            name="My Session",
        )
        session.active_tools = {"git", "gitlab"}

        result = session.to_dict()

        assert result["session_id"] == "abc123"
        assert result["workspace_uri"] == "file:///test"
        assert result["persona"] == "devops"
        assert result["issue_key"] == "AAP-12345"
        assert result["branch"] == "feature-branch"
        assert result["name"] == "My Session"
        # active_tools setter converts to static_tool_count
        assert result["static_tool_count"] == 2
        assert result["tool_count"] == 2

    def test_touch_updates_last_activity(self):
        """Test that touch updates last_activity."""
        session = ChatSession(session_id="abc", workspace_uri="file:///test")

        # Set last_activity to a known past time instead of sleeping
        past_time = datetime.now(tz=timezone.utc) - timedelta(seconds=10)
        session.last_activity = past_time

        session.touch()

        assert session.last_activity > past_time

    def test_is_stale(self):
        """Test stale session detection."""
        session = ChatSession(session_id="abc", workspace_uri="file:///test")

        # Fresh session should not be stale
        assert session.is_stale(max_age_hours=1) is False

        # Manually set old last_activity
        session.last_activity = datetime.now(tz=timezone.utc) - timedelta(hours=5)
        assert session.is_stale(max_age_hours=4) is True
        assert session.is_stale(max_age_hours=6) is False

    def test_clear_filter_cache(self):
        """Test clearing the tool filter cache."""
        session = ChatSession(session_id="abc", workspace_uri="file:///test")
        session.tool_filter_cache = {"key1": ["tool1"], "key2": ["tool2"]}

        session.clear_filter_cache()

        assert not session.tool_filter_cache


class TestPersonaToolCounts:
    """Tests for persona tool count cache functions."""

    @pytest.fixture(autouse=True)
    def empty_counts(self):
        """Run each test against an empty persona tool count cache."""
        with patch.dict("server.workspace_defaults._persona_tool_counts", clear=True):
            yield

    def test_get_persona_tool_count_missing(self):
        """get_persona_tool_count returns 0 for unknown persona."""
        assert get_persona_tool_count("nonexistent") == 0

    def test_update_and_get_persona_tool_count(self):
        """update_persona_tool_count stores value retrievable by get."""
        update_persona_tool_count("developer", 42)
        assert get_persona_tool_count("developer") == 42

    def test_get_all_persona_tool_counts(self):
        """get_all_persona_tool_counts returns copy of all counts."""
        update_persona_tool_count("developer", 10)
        update_persona_tool_count("devops", 20)
        counts = get_all_persona_tool_counts()
        assert counts == {"developer": 10, "devops": 20}
        # Verify it's a copy (mutating returned dict shouldn't affect cache)
        counts["developer"] = 999
        assert get_persona_tool_count("developer") == 10

    def test_update_overwrites(self):
        """update_persona_tool_count overwrites previous value."""
        update_persona_tool_count("devops", 5)
        update_persona_tool_count("devops", 15)
        assert get_persona_tool_count("devops") == 15


class TestGetDefaultPersona:
    """Tests for get_default_persona function."""

    def test_returns_from_config(self):
        """get_default_persona reads from config agent.default_persona."""
        mock_cfg = {"agent": {"default_persona": "developer"}}
        with (
            patch("server.utils.load_config", mock_cfg, create=True),
            patch("server.utils.load_config", return_value=mock_cfg),
        ):
            # We need to patch the import inside the function
            result = get_default_persona()
            assert result == "developer"

    def test_fallback_on_exception(self):
        """get_default_persona returns 'researcher' when config fails."""
        with patch("server.utils.load_config", side_effect=OSError("Config missing")):
            result = get_default_persona()
            assert result == "researcher"


class TestChatSessionAdvanced:
    """Tests for ChatSession methods not covered by basic tests."""

    def test_touch_with_tool_name(self):
        """touch() with tool_name tracks tool call info."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        assert session.last_tool is None
        assert session.last_tool_time is None
        assert session.tool_call_count == 0

        session.touch(tool_name="git_status")

        assert session.last_tool == "git_status"
        assert session.last_tool_time is not None
        assert session.tool_call_count == 1

        session.touch(tool_name="git_diff")
        assert session.last_tool == "git_diff"
        assert session.tool_call_count == 2

    def test_touch_without_tool_name(self):
        """touch() without tool_name only updates last_activity."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.touch()
        assert session.last_tool is None
        assert session.tool_call_count == 0

    def test_tool_count_property_dynamic_preferred(self):
        """tool_count returns dynamic_tool_count when > 0."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.static_tool_count = 50
        session.dynamic_tool_count = 10
        assert session.tool_count == 10

    def test_tool_count_property_static_fallback(self):
        """tool_count returns static_tool_count when dynamic is 0."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.static_tool_count = 50
        session.dynamic_tool_count = 0
        assert session.tool_count == 50

    def test_active_tools_getter_returns_empty(self):
        """active_tools getter always returns empty set (deprecated)."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.static_tool_count = 99
        assert session.active_tools == set()

    def test_active_tools_setter_sets_static_count(self):
        """active_tools setter converts set length to static_tool_count."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.active_tools = {"a", "b", "c"}
        assert session.static_tool_count == 3

    def test_active_tools_setter_empty(self):
        """active_tools setter with empty set sets count to 0."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.static_tool_count = 5
        session.active_tools = set()
        assert session.static_tool_count == 0

    def test_add_to_filter_cache_basic(self):
        """add_to_filter_cache stores tools."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.add_to_filter_cache("hash1", ["tool_a", "tool_b"])
        assert session.tool_filter_cache["hash1"] == ["tool_a", "tool_b"]

    def test_add_to_filter_cache_eviction(self):
        """add_to_filter_cache evicts oldest entries when full."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        # Fill cache to MAX_FILTER_CACHE_SIZE
        for i in range(MAX_FILTER_CACHE_SIZE):
            session.add_to_filter_cache(f"key_{i}", [f"tool_{i}"])

        assert len(session.tool_filter_cache) == MAX_FILTER_CACHE_SIZE
        assert "key_0" in session.tool_filter_cache

        # Adding one more should evict key_0
        session.add_to_filter_cache("new_key", ["new_tool"])
        assert len(session.tool_filter_cache) == MAX_FILTER_CACHE_SIZE
        assert "key_0" not in session.tool_filter_cache
        assert "new_key" in session.tool_filter_cache

    def test_cache_intent_basic(self):
        """cache_intent stores and retrieves intent."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        intent = {"category": "code_search", "confidence": 0.9}
        session.cache_intent("hash_abc", intent)
        assert session.get_cached_intent("hash_abc") == intent

    def test_get_cached_intent_miss(self):
        """get_cached_intent returns None for unknown hash."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        assert session.get_cached_intent("unknown") is None

    def test_cache_intent_eviction(self):
        """cache_intent evicts oldest when full."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        for i in range(session.MAX_INTENT_CACHE_SIZE):
            session.cache_intent(f"key_{i}", {"index": i})

        assert len(session.intent_cache) == session.MAX_INTENT_CACHE_SIZE

        session.cache_intent("overflow", {"index": "new"})
        assert len(session.intent_cache) == session.MAX_INTENT_CACHE_SIZE
        assert "key_0" not in session.intent_cache
        assert "overflow" in session.intent_cache

    def test_cache_memory_query_basic(self):
        """cache_memory_query stores and retrieves query result."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        result = {"data": "some_result"}
        session.cache_memory_query("hash_xyz", result)
        assert session.get_cached_memory_query("hash_xyz") == result

    def test_get_cached_memory_query_miss(self):
        """get_cached_memory_query returns None for unknown hash."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        assert session.get_cached_memory_query("unknown") is None

    def test_cache_memory_query_eviction(self):
        """cache_memory_query evicts oldest when full."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        for i in range(session.MAX_QUERY_CACHE_SIZE):
            session.cache_memory_query(f"key_{i}", {"index": i})

        assert len(session.memory_query_cache) == session.MAX_QUERY_CACHE_SIZE

        session.cache_memory_query("overflow", {"index": "new"})
        assert len(session.memory_query_cache) == session.MAX_QUERY_CACHE_SIZE
        assert "key_0" not in session.memory_query_cache
        assert "overflow" in session.memory_query_cache

    def test_clear_memory_caches(self):
        """clear_memory_caches clears both caches."""
        session = ChatSession(session_id="s1", workspace_uri="file:///test")
        session.cache_intent("h1", {"a": 1})
        session.cache_memory_query("h2", {"b": 2})
        assert len(session.intent_cache) == 1
        assert len(session.memory_query_cache) == 1

        session.clear_memory_caches()
        assert not session.intent_cache
        assert not session.memory_query_cache

    def test_to_dict_full(self):
        """to_dict includes all fields including tool tracking."""
        session = ChatSession(
            session_id="s1",
            workspace_uri="file:///test",
            persona="devops",
            project="my-project",
            is_project_auto_detected=True,
            issue_key="AAP-111",
            branch="feature",
            name="Test Session",
        )
        session.static_tool_count = 30
        session.dynamic_tool_count = 5
        session.last_filter_message = "deploy to stage"
        session.last_filter_time = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)
        session.last_tool = "k8s_get_pods"
        session.last_tool_time = datetime(2025, 1, 15, 10, 5, tzinfo=timezone.utc)
        session.tool_call_count = 7
        session.meeting_references = [{"meeting_id": 1, "title": "Sprint"}]

        d = session.to_dict()

        assert d["session_id"] == "s1"
        assert d["persona"] == "devops"
        assert d["project"] == "my-project"
        assert d["is_project_auto_detected"] is True
        assert d["static_tool_count"] == 30
        assert d["dynamic_tool_count"] == 5
        assert d["tool_count"] == 5  # dynamic preferred
        assert d["last_filter_message"] == "deploy to stage"
        assert d["last_filter_time"] is not None
        assert d["last_tool"] == "k8s_get_pods"
        assert d["last_tool_time"] is not None
        assert d["tool_call_count"] == 7
        assert d["meeting_references"] == [{"meeting_id": 1, "title": "Sprint"}]
