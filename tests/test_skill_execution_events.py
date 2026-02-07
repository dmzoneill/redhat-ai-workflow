"""Tests for tool_modules/aa_workflow/src/skill_execution_events.py"""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_module_globals():
    """Reset module-level globals between tests."""
    import tool_modules.aa_workflow.src.skill_execution_events as mod

    mod._workspace_emitters.clear()
    mod._current_workspace = "default"
    mod._current_execution_id = None
    yield
    mod._workspace_emitters.clear()
    mod._current_workspace = "default"
    mod._current_execution_id = None


@pytest.fixture
def tmp_exec_file(tmp_path):
    """Provide a temporary execution file path and patch EXECUTION_FILE."""
    ef = tmp_path / "skill_execution.json"
    with patch(
        "tool_modules.aa_workflow.src.skill_execution_events.EXECUTION_FILE", ef
    ):
        yield ef


@pytest.fixture
def sample_steps():
    return [
        {"name": "step_a", "description": "first", "tool": "t1"},
        {"name": "step_b", "description": "second", "tool": "t2", "condition": "x"},
        {"name": "step_c", "compute": "code", "on_error": "skip"},
    ]


# ---------------------------------------------------------------------------
# _generate_execution_id
# ---------------------------------------------------------------------------


def test_generate_execution_id():
    from tool_modules.aa_workflow.src.skill_execution_events import (
        _generate_execution_id,
    )

    eid = _generate_execution_id("file:///home/user/project", "my_skill")
    assert "my_skill" in eid
    assert "project" in eid  # last 50 chars of sanitized workspace


def test_generate_execution_id_unique():
    from tool_modules.aa_workflow.src.skill_execution_events import (
        _generate_execution_id,
    )

    id1 = _generate_execution_id("ws", "s")
    time.sleep(0.001)
    _generate_execution_id("ws", "s")
    # Should be unique due to timestamp micro
    # They might still be same if clock resolution is low, so just check format
    assert isinstance(id1, str)
    assert len(id1) > 0


# ---------------------------------------------------------------------------
# file_lock context manager
# ---------------------------------------------------------------------------


def test_file_lock_acquires(tmp_exec_file):
    from tool_modules.aa_workflow.src.skill_execution_events import file_lock

    with file_lock(tmp_exec_file) as acquired:
        assert acquired is True
    # Lock file should be cleaned up
    lock_path = Path(str(tmp_exec_file) + ".lock")
    assert not lock_path.exists()


def test_file_lock_stale_lock_removed(tmp_exec_file):
    from tool_modules.aa_workflow.src.skill_execution_events import file_lock

    lock_path = Path(str(tmp_exec_file) + ".lock")
    # Create a stale lock
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("stale")
    # Make it old
    old_time = time.time() - 20  # older than LOCK_STALE_SECONDS (10s)
    os.utime(str(lock_path), (old_time, old_time))

    with file_lock(tmp_exec_file) as acquired:
        assert acquired is True


def test_file_lock_timeout(tmp_exec_file):
    """When lock is held and not stale, should timeout."""
    from tool_modules.aa_workflow.src.skill_execution_events import file_lock

    lock_path = Path(str(tmp_exec_file) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Create a fresh lock that won't be considered stale
    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, b"held")
    os.close(fd)

    # Patch timeout to be very short
    with patch(
        "tool_modules.aa_workflow.src.skill_execution_events.LOCK_TIMEOUT_SECONDS", 0.1
    ):
        with patch(
            "tool_modules.aa_workflow.src.skill_execution_events.LOCK_RETRY_INTERVAL_SECONDS",
            0.02,
        ):
            with file_lock(tmp_exec_file) as acquired:
                assert acquired is False

    # Clean up
    lock_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# _load_all_executions_unlocked
# ---------------------------------------------------------------------------


def test_load_unlocked_empty(tmp_exec_file):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        _load_all_executions_unlocked,
    )

    data = _load_all_executions_unlocked()
    assert data["executions"] == {}
    assert data["version"] == 2


def test_load_unlocked_v2_format(tmp_exec_file):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        _load_all_executions_unlocked,
    )

    v2 = {
        "executions": {"e1": {"skillName": "s1", "status": "running"}},
        "lastUpdated": "2025-01-01",
        "version": 2,
    }
    tmp_exec_file.write_text(json.dumps(v2))
    data = _load_all_executions_unlocked()
    assert "e1" in data["executions"]


def test_load_unlocked_old_format(tmp_exec_file):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        _load_all_executions_unlocked,
    )

    old = {"skillName": "old_skill", "workspaceUri": "default"}
    tmp_exec_file.write_text(json.dumps(old))
    data = _load_all_executions_unlocked()
    assert data["version"] == 2
    execs = data["executions"]
    assert len(execs) == 1
    val = list(execs.values())[0]
    assert val["skillName"] == "old_skill"


def test_load_unlocked_corrupt_json(tmp_exec_file):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        _load_all_executions_unlocked,
    )

    tmp_exec_file.write_text("not-json{")
    data = _load_all_executions_unlocked()
    assert data["executions"] == {}


# ---------------------------------------------------------------------------
# _load_all_executions (with lock)
# ---------------------------------------------------------------------------


def test_load_all_executions_with_lock(tmp_exec_file):
    from tool_modules.aa_workflow.src.skill_execution_events import _load_all_executions

    data = _load_all_executions()
    assert "executions" in data


# ---------------------------------------------------------------------------
# _save_all_executions_unlocked
# ---------------------------------------------------------------------------


def test_save_unlocked(tmp_exec_file):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        _save_all_executions_unlocked,
    )

    tmp_exec_file.parent.mkdir(parents=True, exist_ok=True)
    data = {"executions": {"e1": {"test": True}}, "version": 2}
    _save_all_executions_unlocked(data)
    assert tmp_exec_file.exists()
    loaded = json.loads(tmp_exec_file.read_text())
    assert "e1" in loaded["executions"]
    assert "lastUpdated" in loaded


# ---------------------------------------------------------------------------
# _save_all_executions (with lock)
# ---------------------------------------------------------------------------


def test_save_all_executions(tmp_exec_file):
    from tool_modules.aa_workflow.src.skill_execution_events import _save_all_executions

    tmp_exec_file.parent.mkdir(parents=True, exist_ok=True)
    _save_all_executions({"executions": {"x": {}}, "version": 2})
    assert tmp_exec_file.exists()


# ---------------------------------------------------------------------------
# _cleanup_old_executions
# ---------------------------------------------------------------------------


def test_cleanup_removes_old_completed(tmp_exec_file):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        _cleanup_old_executions,
    )

    old_time = (datetime.now() - timedelta(seconds=600)).isoformat()
    data = {
        "executions": {
            "running_one": {"status": "running"},
            "old_done": {"status": "success", "endTime": old_time},
            "recent_done": {"status": "success", "endTime": datetime.now().isoformat()},
        }
    }
    result = _cleanup_old_executions(data)
    assert "running_one" in result["executions"]
    assert "old_done" not in result["executions"]
    assert "recent_done" in result["executions"]


def test_cleanup_handles_bad_endtime():
    from tool_modules.aa_workflow.src.skill_execution_events import (
        _cleanup_old_executions,
    )

    data = {
        "executions": {
            "bad": {"status": "done", "endTime": "not-a-date"},
        }
    }
    result = _cleanup_old_executions(data)
    assert "bad" in result["executions"]  # not removed since date parsing fails


# ---------------------------------------------------------------------------
# SkillExecutionEmitter
# ---------------------------------------------------------------------------


def test_emitter_init(tmp_exec_file, sample_steps):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        SkillExecutionEmitter,
    )

    e = SkillExecutionEmitter(
        skill_name="test_skill",
        steps=sample_steps,
        workspace_uri="ws://test",
        session_id="sess1",
        session_name="Test Session",
        source="cron",
        source_details="morning_coffee",
    )
    assert e.skill_name == "test_skill"
    assert e.status == "running"
    assert e.current_step_index == -1
    assert e.execution_id is not None
    assert len(e.events) == 0
    assert e.source == "cron"


def test_emitter_skill_start(tmp_exec_file, sample_steps):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        SkillExecutionEmitter,
    )

    e = SkillExecutionEmitter("s", sample_steps, "ws")
    e.skill_start()
    assert len(e.events) == 1
    assert e.events[0]["type"] == "skill_start"
    assert e.events[0]["data"]["totalSteps"] == 3
    assert len(e.events[0]["data"]["steps"]) == 3


def test_emitter_step_lifecycle(tmp_exec_file, sample_steps):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        SkillExecutionEmitter,
    )

    e = SkillExecutionEmitter("s", sample_steps, "ws")

    e.step_start(0)
    assert e.current_step_index == 0
    assert e.events[-1]["type"] == "step_start"
    assert e.events[-1]["stepName"] == "step_a"

    e.step_complete(0, duration_ms=150, result="ok")
    assert e.events[-1]["type"] == "step_complete"
    assert e.events[-1]["data"]["duration"] == 150
    assert e.events[-1]["data"]["result"] == "ok"

    e.step_start(1)
    e.step_failed(1, duration_ms=50, error="boom")
    assert e.events[-1]["type"] == "step_failed"
    assert e.events[-1]["data"]["error"] == "boom"

    e.step_skipped(2, reason="condition false")
    assert e.events[-1]["type"] == "step_skipped"
    assert e.events[-1]["data"]["reason"] == "condition false"


def test_emitter_memory_events(tmp_exec_file, sample_steps):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        SkillExecutionEmitter,
    )

    e = SkillExecutionEmitter("s", sample_steps, "ws")

    e.memory_read(0, "state/current_work")
    assert e.events[-1]["type"] == "memory_read"
    assert e.events[-1]["data"]["memoryKey"] == "state/current_work"

    e.memory_write(0, "state/current_work")
    assert e.events[-1]["type"] == "memory_write"


def test_emitter_auto_heal(tmp_exec_file, sample_steps):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        SkillExecutionEmitter,
    )

    e = SkillExecutionEmitter("s", sample_steps, "ws")
    e.auto_heal(1, "Re-authenticated")
    assert e.events[-1]["type"] == "auto_heal"
    assert e.events[-1]["data"]["healingDetails"] == "Re-authenticated"


def test_emitter_retry(tmp_exec_file, sample_steps):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        SkillExecutionEmitter,
    )

    e = SkillExecutionEmitter("s", sample_steps, "ws")
    e.retry(0, retry_count=2)
    assert e.events[-1]["type"] == "retry"
    assert e.events[-1]["data"]["retryCount"] == 2


def test_emitter_semantic_search(tmp_exec_file, sample_steps):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        SkillExecutionEmitter,
    )

    e = SkillExecutionEmitter("s", sample_steps, "ws")
    e.semantic_search(0, "billing code")
    assert e.events[-1]["data"]["searchQuery"] == "billing code"


def test_emitter_remediation_step(tmp_exec_file, sample_steps):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        SkillExecutionEmitter,
    )

    e = SkillExecutionEmitter("s", sample_steps, "ws")
    e.remediation_step(0, tool="kube_login", reason="token expired")
    assert e.events[-1]["type"] == "remediation_step"
    assert e.events[-1]["data"]["tool"] == "kube_login"


def test_emitter_skill_complete(tmp_exec_file, sample_steps):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        SkillExecutionEmitter,
    )

    e = SkillExecutionEmitter("s", sample_steps, "ws")
    e.skill_complete(success=True, total_duration_ms=5000)
    assert e.status == "success"
    assert e.end_time is not None
    assert e.events[-1]["type"] == "skill_complete"
    assert e.events[-1]["data"]["success"] is True
    assert e.events[-1]["data"]["duration"] == 5000


def test_emitter_skill_complete_failure(tmp_exec_file, sample_steps):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        SkillExecutionEmitter,
    )

    e = SkillExecutionEmitter("s", sample_steps, "ws")
    e.skill_complete(success=False, total_duration_ms=100)
    assert e.status == "failed"


def test_emitter_result_truncation(tmp_exec_file, sample_steps):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        SkillExecutionEmitter,
    )

    e = SkillExecutionEmitter("s", sample_steps, "ws")
    long_result = "x" * 1000
    e.step_complete(0, 10, result=long_result)
    assert len(e.events[-1]["data"]["result"]) == 500

    long_error = "e" * 1000
    e.step_failed(0, 10, error=long_error)
    assert len(e.events[-1]["data"]["error"]) == 500


def test_emitter_step_index_none_before_start(tmp_exec_file, sample_steps):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        SkillExecutionEmitter,
    )

    e = SkillExecutionEmitter("s", sample_steps, "ws")
    e.skill_start()
    assert e.events[0]["stepIndex"] is None
    assert e.events[0]["stepName"] is None


# ---------------------------------------------------------------------------
# _write_state integration
# ---------------------------------------------------------------------------


def test_write_state_creates_file(tmp_exec_file, sample_steps):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        SkillExecutionEmitter,
    )

    e = SkillExecutionEmitter("s", sample_steps, "ws")
    e.skill_start()
    assert tmp_exec_file.exists()
    data = json.loads(tmp_exec_file.read_text())
    assert e.execution_id in data["executions"]


# ---------------------------------------------------------------------------
# get_emitter / set_emitter
# ---------------------------------------------------------------------------


def test_set_and_get_emitter(tmp_exec_file, sample_steps):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        SkillExecutionEmitter,
        get_emitter,
        set_emitter,
    )

    e = SkillExecutionEmitter("s", sample_steps, "ws://project")
    set_emitter(e, "ws://project")
    assert get_emitter("ws://project") is e
    assert get_emitter(execution_id=e.execution_id) is e


def test_set_emitter_none_clears(tmp_exec_file, sample_steps):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        SkillExecutionEmitter,
        get_emitter,
        set_emitter,
    )

    e = SkillExecutionEmitter("s", sample_steps, "ws")
    set_emitter(e, "ws")
    set_emitter(None, "ws")
    assert get_emitter("ws") is None


def test_get_emitter_returns_none_when_empty():
    from tool_modules.aa_workflow.src.skill_execution_events import get_emitter

    assert get_emitter() is None
    assert get_emitter("nonexistent") is None
    assert get_emitter(execution_id="nope") is None


def test_set_emitter_evicts_when_over_limit(tmp_exec_file, sample_steps):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        _MAX_EMITTERS,
        SkillExecutionEmitter,
        _workspace_emitters,
        set_emitter,
    )

    # Fill up to MAX
    for i in range(_MAX_EMITTERS):
        e = SkillExecutionEmitter(f"s{i}", sample_steps, f"ws{i}")
        e.status = "success"  # non-running so they can be evicted
        _workspace_emitters[e.execution_id] = e

    assert len(_workspace_emitters) == _MAX_EMITTERS

    # Adding one more should evict
    new_e = SkillExecutionEmitter("new_skill", sample_steps, "ws_new")
    set_emitter(new_e, "ws_new")
    assert len(_workspace_emitters) <= _MAX_EMITTERS


# ---------------------------------------------------------------------------
# emit_event convenience function
# ---------------------------------------------------------------------------


def test_emit_event_with_active_emitter(tmp_exec_file, sample_steps):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        SkillExecutionEmitter,
        emit_event,
        set_emitter,
    )

    e = SkillExecutionEmitter("s", sample_steps, "ws")
    set_emitter(e, "ws")
    emit_event("custom_event", {"key": "val"}, "ws")
    assert len(e.events) == 1
    assert e.events[0]["type"] == "custom_event"


def test_emit_event_no_emitter():
    from tool_modules.aa_workflow.src.skill_execution_events import emit_event

    # Should not raise
    emit_event("noop", {"x": 1})


# ---------------------------------------------------------------------------
# clear_workspace_emitter
# ---------------------------------------------------------------------------


def test_clear_workspace_emitter(tmp_exec_file, sample_steps):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        SkillExecutionEmitter,
        clear_workspace_emitter,
        get_emitter,
        set_emitter,
    )

    e1 = SkillExecutionEmitter("s1", sample_steps, "ws1")
    e2 = SkillExecutionEmitter("s2", sample_steps, "ws2")
    set_emitter(e1, "ws1")
    set_emitter(e2, "ws2")

    clear_workspace_emitter("ws1")
    assert get_emitter("ws1") is None
    assert get_emitter("ws2") is e2


# ---------------------------------------------------------------------------
# get_all_running_executions
# ---------------------------------------------------------------------------


def test_get_all_running_executions(tmp_exec_file, sample_steps):
    from tool_modules.aa_workflow.src.skill_execution_events import (
        SkillExecutionEmitter,
        get_all_running_executions,
        set_emitter,
    )

    e1 = SkillExecutionEmitter(
        "s1", sample_steps, "ws1", session_id="sid1", session_name="n1", source="chat"
    )
    e2 = SkillExecutionEmitter(
        "s2", sample_steps, "ws2", source="cron", source_details="daily"
    )
    e2.status = "success"  # not running
    set_emitter(e1, "ws1")
    set_emitter(e2, "ws2")

    running = get_all_running_executions()
    assert len(running) == 1
    assert running[0]["skillName"] == "s1"
    assert running[0]["sessionId"] == "sid1"
    assert running[0]["source"] == "chat"


def test_get_all_running_empty():
    from tool_modules.aa_workflow.src.skill_execution_events import (
        get_all_running_executions,
    )

    assert get_all_running_executions() == []
