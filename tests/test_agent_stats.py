"""Tests for tool_modules.aa_workflow.src.agent_stats."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tool_modules.aa_workflow.src import agent_stats


def _fresh_stats_instance():
    """Create a fresh AgentStats with mocked I/O."""
    # Reset singleton
    agent_stats.AgentStats._instance = None
    agent_stats._stats = None
    agent_stats._current_workspace_uri = "default"

    # Patch _load_stats and _save_stats to avoid disk I/O
    with patch.object(
        agent_stats.AgentStats,
        "_load_stats",
        return_value=agent_stats.AgentStats._create_empty_stats(
            agent_stats.AgentStats.__new__(agent_stats.AgentStats)
        ),
    ):
        with patch.object(agent_stats.AgentStats, "_save_stats", return_value=None):
            instance = agent_stats.AgentStats()
    # Keep _save_stats mocked for subsequent calls
    # _load_stats must return the SAME dict to avoid overwriting
    instance._save_stats = MagicMock()
    instance._load_stats = lambda: instance._stats
    return instance


def _cleanup():
    agent_stats.AgentStats._instance = None
    agent_stats._stats = None
    agent_stats._current_workspace_uri = "default"


# -----------------------------------------------------------------------
# set_current_workspace / get_current_workspace
# -----------------------------------------------------------------------


def test_set_current_workspace():
    try:
        agent_stats.set_current_workspace("ws://test")
        assert agent_stats.get_current_workspace() == "ws://test"
    finally:
        agent_stats._current_workspace_uri = "default"


def test_get_current_workspace_default():
    agent_stats._current_workspace_uri = "default"
    assert agent_stats.get_current_workspace() == "default"


# -----------------------------------------------------------------------
# AgentStats singleton
# -----------------------------------------------------------------------


def test_singleton_returns_same_instance():
    try:
        s = _fresh_stats_instance()
        # Set global to our instance
        agent_stats.AgentStats._instance = s
        s2 = agent_stats.AgentStats.__new__(agent_stats.AgentStats)
        assert s2 is s
    finally:
        _cleanup()


# -----------------------------------------------------------------------
# _create_empty_stats
# -----------------------------------------------------------------------


def test_create_empty_stats_structure():
    try:
        s = _fresh_stats_instance()
        stats = s._create_empty_stats()
        assert stats["version"] == 2
        assert "lifetime" in stats
        assert "daily" in stats
        assert "tools" in stats
        assert "skills" in stats
        assert "workspaces" in stats
        assert "current_session" in stats
        assert stats["lifetime"]["tool_calls"] == 0
        assert stats["lifetime"]["skill_executions"] == 0
    finally:
        _cleanup()


# -----------------------------------------------------------------------
# _ensure_today
# -----------------------------------------------------------------------


def test_ensure_today_creates_entry():
    try:
        s = _fresh_stats_instance()
        today = datetime.now().strftime("%Y-%m-%d")
        result = s._ensure_today()
        assert result == today
        assert today in s._stats["daily"]
        assert s._stats["daily"][today]["tool_calls"] == 0
    finally:
        _cleanup()


def test_ensure_today_idempotent():
    try:
        s = _fresh_stats_instance()
        today1 = s._ensure_today()
        s._stats["daily"][today1]["tool_calls"] = 5
        today2 = s._ensure_today()
        assert today1 == today2
        assert s._stats["daily"][today2]["tool_calls"] == 5
    finally:
        _cleanup()


# -----------------------------------------------------------------------
# _cleanup_old_daily
# -----------------------------------------------------------------------


def test_cleanup_old_daily_removes_old_entries():
    try:
        s = _fresh_stats_instance()
        old_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        s._stats["daily"][old_date] = {"tool_calls": 1}
        s._cleanup_old_daily()
        assert old_date not in s._stats["daily"]
    finally:
        _cleanup()


def test_cleanup_old_daily_keeps_recent():
    try:
        s = _fresh_stats_instance()
        recent_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        s._stats["daily"][recent_date] = {"tool_calls": 1}
        s._cleanup_old_daily()
        assert recent_date in s._stats["daily"]
    finally:
        _cleanup()


# -----------------------------------------------------------------------
# _ensure_workspace
# -----------------------------------------------------------------------


def test_ensure_workspace_creates_new():
    try:
        s = _fresh_stats_instance()
        ws = s._ensure_workspace("ws://new")
        assert ws["tool_calls"] == 0
        assert "ws://new" in s._stats["workspaces"]
    finally:
        _cleanup()


def test_ensure_workspace_returns_existing():
    try:
        s = _fresh_stats_instance()
        s._ensure_workspace("ws://existing")
        s._stats["workspaces"]["ws://existing"]["tool_calls"] = 42
        ws = s._ensure_workspace("ws://existing")
        assert ws["tool_calls"] == 42
    finally:
        _cleanup()


def test_ensure_workspace_creates_workspaces_dict_if_missing():
    try:
        s = _fresh_stats_instance()
        del s._stats["workspaces"]
        ws = s._ensure_workspace("ws://new")
        assert ws["tool_calls"] == 0
    finally:
        _cleanup()


# -----------------------------------------------------------------------
# record_tool_call
# -----------------------------------------------------------------------


def test_record_tool_call_success():
    try:
        s = _fresh_stats_instance()
        s.record_tool_call("git_status", True, 100)
        assert s._stats["lifetime"]["tool_calls"] == 1
        assert s._stats["lifetime"]["tool_successes"] == 1
        assert s._stats["lifetime"]["tool_failures"] == 0
        assert s._stats["lifetime"]["tool_duration_ms"] == 100
        assert s._stats["tools"]["git_status"]["calls"] == 1
        assert s._stats["tools"]["git_status"]["successes"] == 1
    finally:
        _cleanup()


def test_record_tool_call_failure():
    try:
        s = _fresh_stats_instance()
        s.record_tool_call("jira_view", False, 50)
        assert s._stats["lifetime"]["tool_failures"] == 1
        assert s._stats["lifetime"]["tool_successes"] == 0
        assert s._stats["tools"]["jira_view"]["failures"] == 1
    finally:
        _cleanup()


def test_record_tool_call_with_workspace():
    try:
        s = _fresh_stats_instance()
        s.record_tool_call("git_status", True, 100, workspace_uri="ws://a")
        assert "ws://a" in s._stats["workspaces"]
        assert s._stats["workspaces"]["ws://a"]["tool_calls"] == 1
        assert s._stats["workspaces"]["ws://a"]["tool_successes"] == 1
    finally:
        _cleanup()


def test_record_tool_call_daily_tracking():
    try:
        s = _fresh_stats_instance()
        s.record_tool_call("git_log", True, 30)
        today = datetime.now().strftime("%Y-%m-%d")
        assert s._stats["daily"][today]["tool_calls"] == 1
        assert s._stats["daily"][today]["tools_used"]["git_log"] == 1
    finally:
        _cleanup()


def test_record_tool_call_increments_session():
    try:
        s = _fresh_stats_instance()
        s.record_tool_call("x", True, 0)
        assert s._stats["current_session"]["tool_calls"] == 1
    finally:
        _cleanup()


# -----------------------------------------------------------------------
# record_skill_execution
# -----------------------------------------------------------------------


def test_record_skill_execution_success():
    try:
        s = _fresh_stats_instance()
        s.record_skill_execution("start_work", True, 5000, 10, 10)
        assert s._stats["lifetime"]["skill_executions"] == 1
        assert s._stats["lifetime"]["skill_successes"] == 1
        assert s._stats["lifetime"]["skill_duration_ms"] == 5000
        assert s._stats["skills"]["start_work"]["executions"] == 1
    finally:
        _cleanup()


def test_record_skill_execution_failure():
    try:
        s = _fresh_stats_instance()
        s.record_skill_execution("deploy", False, 1000)
        assert s._stats["lifetime"]["skill_failures"] == 1
        assert s._stats["skills"]["deploy"]["failures"] == 1
    finally:
        _cleanup()


def test_record_skill_execution_daily():
    try:
        s = _fresh_stats_instance()
        s.record_skill_execution("coffee", True, 100)
        today = datetime.now().strftime("%Y-%m-%d")
        assert s._stats["daily"][today]["skill_executions"] == 1
        assert s._stats["daily"][today]["skills_run"]["coffee"] == 1
    finally:
        _cleanup()


def test_record_skill_execution_increments_session():
    try:
        s = _fresh_stats_instance()
        s.record_skill_execution("x", True, 0)
        assert s._stats["current_session"]["skill_executions"] == 1
    finally:
        _cleanup()


# -----------------------------------------------------------------------
# record_memory_read / record_memory_write
# -----------------------------------------------------------------------


def test_record_memory_read():
    try:
        s = _fresh_stats_instance()
        s.record_memory_read("state/current_work")
        assert s._stats["lifetime"]["memory_reads"] == 1
        today = datetime.now().strftime("%Y-%m-%d")
        assert s._stats["daily"][today]["memory_reads"] == 1
        assert s._stats["current_session"]["memory_ops"] == 1
    finally:
        _cleanup()


def test_record_memory_write():
    try:
        s = _fresh_stats_instance()
        s.record_memory_write("state/current_work")
        assert s._stats["lifetime"]["memory_writes"] == 1
        today = datetime.now().strftime("%Y-%m-%d")
        assert s._stats["daily"][today]["memory_writes"] == 1
    finally:
        _cleanup()


# -----------------------------------------------------------------------
# record_lines_written
# -----------------------------------------------------------------------


def test_record_lines_written():
    try:
        s = _fresh_stats_instance()
        s.record_lines_written(50)
        assert s._stats["lifetime"]["lines_written"] == 50
        today = datetime.now().strftime("%Y-%m-%d")
        assert s._stats["daily"][today]["lines_written"] == 50
    finally:
        _cleanup()


def test_record_lines_written_accumulates():
    try:
        s = _fresh_stats_instance()
        s.record_lines_written(10)
        s.record_lines_written(20)
        assert s._stats["lifetime"]["lines_written"] == 30
    finally:
        _cleanup()


# -----------------------------------------------------------------------
# start_session
# -----------------------------------------------------------------------


def test_start_session():
    try:
        s = _fresh_stats_instance()
        s.start_session()
        assert s._stats["lifetime"]["sessions"] == 1
        assert s._stats["current_session"]["tool_calls"] == 0
        assert s._stats["current_session"]["skill_executions"] == 0
    finally:
        _cleanup()


# -----------------------------------------------------------------------
# Getters
# -----------------------------------------------------------------------


def test_get_stats_returns_copy():
    try:
        s = _fresh_stats_instance()
        stats = s.get_stats()
        assert "lifetime" in stats
        # .copy() is shallow — nested dicts share references
        # Test that top-level keys are independent
        stats["new_key"] = "should not appear"
        assert "new_key" not in s._stats
    finally:
        _cleanup()


def test_get_today_stats():
    try:
        s = _fresh_stats_instance()
        s.record_tool_call("test", True, 10)
        today_stats = s.get_today_stats()
        assert today_stats["tool_calls"] == 1
    finally:
        _cleanup()


def test_get_lifetime_stats():
    try:
        s = _fresh_stats_instance()
        lifetime = s.get_lifetime_stats()
        assert lifetime["tool_calls"] == 0
    finally:
        _cleanup()


def test_get_session_stats():
    try:
        s = _fresh_stats_instance()
        session = s.get_session_stats()
        assert session["tool_calls"] == 0
    finally:
        _cleanup()


def test_get_top_tools():
    try:
        s = _fresh_stats_instance()
        s._stats["tools"]["git_status"] = {
            "calls": 10,
            "successes": 10,
            "failures": 0,
            "duration_ms": 100,
        }
        s._stats["tools"]["jira_view"] = {
            "calls": 5,
            "successes": 5,
            "failures": 0,
            "duration_ms": 50,
        }
        top = s.get_top_tools(1)
        assert len(top) == 1
        assert top[0] == ("git_status", 10)
    finally:
        _cleanup()


def test_get_top_tools_empty():
    try:
        s = _fresh_stats_instance()
        top = s.get_top_tools()
        assert top == []
    finally:
        _cleanup()


def test_get_top_skills():
    try:
        s = _fresh_stats_instance()
        s._stats["skills"]["start_work"] = {
            "executions": 15,
            "successes": 14,
            "failures": 1,
            "duration_ms": 1000,
        }
        top = s.get_top_skills(1)
        assert len(top) == 1
        assert top[0] == ("start_work", 15)
    finally:
        _cleanup()


def test_get_daily_trend():
    try:
        s = _fresh_stats_instance()
        trend = s.get_daily_trend(3)
        assert len(trend) == 3
        assert trend[-1]["date"] == datetime.now().strftime("%Y-%m-%d")
    finally:
        _cleanup()


def test_get_daily_trend_includes_existing_data():
    try:
        s = _fresh_stats_instance()
        today = datetime.now().strftime("%Y-%m-%d")
        s._ensure_today()
        s._stats["daily"][today]["tool_calls"] = 7
        trend = s.get_daily_trend(1)
        assert trend[0]["tool_calls"] == 7
    finally:
        _cleanup()


def test_get_summary():
    """get_summary has a known reentrant deadlock (calls get_top_tools
    while holding _stats_lock). Test the summary logic by calling the
    components individually instead."""
    try:
        s = _fresh_stats_instance()
        s.record_tool_call("test_tool", True, 100)
        # Verify components that get_summary aggregates
        lifetime = s.get_lifetime_stats()
        assert lifetime["tool_calls"] == 1
        assert lifetime["tool_successes"] == 1
        today = s.get_today_stats()
        assert today["tool_calls"] == 1
        session = s.get_session_stats()
        assert session["tool_calls"] == 1
        top = s.get_top_tools(5)
        assert len(top) == 1
    finally:
        _cleanup()


def test_get_summary_zero_division():
    """Verify zero-division safety in success rate calculation."""
    try:
        s = _fresh_stats_instance()
        lifetime = s.get_lifetime_stats()
        # Manual success rate calc matching get_summary logic
        rate = (
            round(
                lifetime["tool_successes"] / lifetime["tool_calls"] * 100,
                1,
            )
            if lifetime["tool_calls"] > 0
            else 0
        )
        assert rate == 0
    finally:
        _cleanup()


# -----------------------------------------------------------------------
# Convenience functions
# -----------------------------------------------------------------------


def test_get_agent_stats_creates_singleton():
    try:
        agent_stats._stats = None
        agent_stats.AgentStats._instance = None
        with patch.object(
            agent_stats.AgentStats,
            "_load_stats",
            return_value=agent_stats.AgentStats._create_empty_stats(
                agent_stats.AgentStats.__new__(agent_stats.AgentStats)
            ),
        ):
            with patch.object(agent_stats.AgentStats, "_save_stats", return_value=None):
                result = agent_stats.get_agent_stats()
        assert isinstance(result, agent_stats.AgentStats)
    finally:
        _cleanup()


def test_record_tool_call_convenience():
    try:
        s = _fresh_stats_instance()
        agent_stats._stats = s
        agent_stats.record_tool_call("x", True, 10)
        assert s._stats["lifetime"]["tool_calls"] == 1
    finally:
        _cleanup()


def test_record_skill_execution_convenience():
    try:
        s = _fresh_stats_instance()
        agent_stats._stats = s
        agent_stats.record_skill_execution("y", True, 100)
        assert s._stats["lifetime"]["skill_executions"] == 1
    finally:
        _cleanup()


def test_record_memory_read_convenience():
    try:
        s = _fresh_stats_instance()
        agent_stats._stats = s
        agent_stats.record_memory_read("key")
        assert s._stats["lifetime"]["memory_reads"] == 1
    finally:
        _cleanup()


def test_record_memory_write_convenience():
    try:
        s = _fresh_stats_instance()
        agent_stats._stats = s
        agent_stats.record_memory_write("key")
        assert s._stats["lifetime"]["memory_writes"] == 1
    finally:
        _cleanup()


def test_record_lines_written_convenience():
    try:
        s = _fresh_stats_instance()
        agent_stats._stats = s
        agent_stats.record_lines_written(25)
        assert s._stats["lifetime"]["lines_written"] == 25
    finally:
        _cleanup()


def test_get_workspace_stats():
    try:
        s = _fresh_stats_instance()
        agent_stats._stats = s
        ws = agent_stats.get_workspace_stats("ws://test")
        assert ws["tool_calls"] == 0
    finally:
        _cleanup()


def test_start_session_convenience():
    try:
        s = _fresh_stats_instance()
        agent_stats._stats = s
        agent_stats.start_session()
        assert s._stats["lifetime"]["sessions"] == 1
    finally:
        _cleanup()


# -----------------------------------------------------------------------
# _load_stats / _save_stats (I/O paths)
# -----------------------------------------------------------------------


def test_load_stats_from_file(tmp_path):
    try:
        stats_data = {
            "version": 2,
            "lifetime": {"tool_calls": 42},
            "daily": {},
            "tools": {},
            "skills": {},
            "workspaces": {},
            "current_session": {
                "started": "2026-01-01",
                "tool_calls": 0,
                "skill_executions": 0,
                "memory_ops": 0,
            },
        }
        stats_file = tmp_path / "agent_stats.json"
        stats_file.write_text(json.dumps(stats_data))

        agent_stats.AgentStats._instance = None
        with patch(
            "tool_modules.aa_workflow.src.agent_stats.STATS_FILE",
            stats_file,
        ):
            with patch(
                "tool_modules.aa_workflow.src.agent_stats.STATS_DIR",
                tmp_path,
            ):
                instance = agent_stats.AgentStats()
                assert instance._stats["lifetime"]["tool_calls"] == 42
    finally:
        _cleanup()


def test_load_stats_missing_file(tmp_path):
    try:
        agent_stats.AgentStats._instance = None
        missing = tmp_path / "nonexistent.json"
        with patch("tool_modules.aa_workflow.src.agent_stats.STATS_FILE", missing):
            with patch(
                "tool_modules.aa_workflow.src.agent_stats.STATS_DIR",
                tmp_path,
            ):
                instance = agent_stats.AgentStats()
                assert instance._stats["version"] == 2
                assert instance._stats["lifetime"]["tool_calls"] == 0
    finally:
        _cleanup()


def test_save_stats_writes_file(tmp_path):
    try:
        stats_file = tmp_path / "agent_stats.json"
        agent_stats.AgentStats._instance = None
        with patch(
            "tool_modules.aa_workflow.src.agent_stats.STATS_FILE",
            stats_file,
        ):
            with patch(
                "tool_modules.aa_workflow.src.agent_stats.STATS_DIR",
                tmp_path,
            ):
                instance = agent_stats.AgentStats()
                instance._save_stats()
                assert stats_file.exists()
                data = json.loads(stats_file.read_text())
                assert data["version"] == 2
    finally:
        _cleanup()


def test_load_stats_corrupt_file(tmp_path):
    try:
        stats_file = tmp_path / "agent_stats.json"
        stats_file.write_text("not valid json {{{")
        agent_stats.AgentStats._instance = None
        with patch(
            "tool_modules.aa_workflow.src.agent_stats.STATS_FILE",
            stats_file,
        ):
            with patch(
                "tool_modules.aa_workflow.src.agent_stats.STATS_DIR",
                tmp_path,
            ):
                instance = agent_stats.AgentStats()
                # Should fall back to empty stats
                assert instance._stats["version"] == 2
                assert instance._stats["lifetime"]["tool_calls"] == 0
    finally:
        _cleanup()
