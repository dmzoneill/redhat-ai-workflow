"""Tests for server/ralph_loop_manager.py"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from server.ralph_loop_manager import (
    add_hard_stop,
    ensure_loops_dir,
    generate_todo_from_goals,
    get_loop_status,
    list_active_loops,
    remove_hard_stop,
    start_ralph_loop,
    stop_ralph_loop,
    update_loop_iteration,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def loops_dir(tmp_path):
    d = tmp_path / "ralph_loops"
    d.mkdir()
    with patch("server.ralph_loop_manager.LOOPS_DIR", d):
        yield d


# ---------------------------------------------------------------------------
# ensure_loops_dir
# ---------------------------------------------------------------------------


def test_ensure_loops_dir(tmp_path):
    d = tmp_path / "new_loops"
    with patch("server.ralph_loop_manager.LOOPS_DIR", d):
        ensure_loops_dir()
    assert d.exists()


def test_ensure_loops_dir_idempotent(tmp_path):
    d = tmp_path / "existing"
    d.mkdir()
    with patch("server.ralph_loop_manager.LOOPS_DIR", d):
        ensure_loops_dir()
    assert d.exists()


# ---------------------------------------------------------------------------
# start_ralph_loop
# ---------------------------------------------------------------------------


def test_start_basic(loops_dir):
    config = start_ralph_loop("sess1")
    assert config["session_id"] == "sess1"
    assert config["max_iterations"] == 10
    assert config["current_iteration"] == 0
    assert config["status"] == "active"
    assert config["started_at"]
    assert config["last_updated"]

    # Verify file created
    f = loops_dir / "session_sess1.json"
    assert f.exists()
    data = json.loads(f.read_text())
    assert data["session_id"] == "sess1"


def test_start_with_options(loops_dir):
    config = start_ralph_loop(
        "sess2",
        max_iterations=5,
        todo_path="/custom/TODO.md",
        completion_criteria=["all green", "tests pass"],
        workspace_path="/home/user/project",
    )
    assert config["max_iterations"] == 5
    assert config["todo_path"] == "/custom/TODO.md"
    assert config["completion_criteria"] == ["all green", "tests pass"]
    assert config["workspace_path"] == "/home/user/project"


def test_start_default_todo_path_with_workspace(loops_dir):
    config = start_ralph_loop("sess3", workspace_path="/ws")
    assert config["todo_path"] == str(Path("/ws") / "TODO.md")


def test_start_default_todo_path_no_workspace(loops_dir):
    config = start_ralph_loop("sess4")
    assert config["todo_path"].endswith("TODO.md")


# ---------------------------------------------------------------------------
# stop_ralph_loop
# ---------------------------------------------------------------------------


def test_stop_existing(loops_dir):
    start_ralph_loop("sess_stop")
    assert stop_ralph_loop("sess_stop") is True
    assert not (loops_dir / "session_sess_stop.json").exists()


def test_stop_nonexistent(loops_dir):
    assert stop_ralph_loop("nope") is False


# ---------------------------------------------------------------------------
# get_loop_status
# ---------------------------------------------------------------------------


def test_status_not_found(loops_dir):
    assert get_loop_status("nope") is None


def test_status_basic(loops_dir):
    start_ralph_loop("sess_status")
    status = get_loop_status("sess_status")
    assert status is not None
    assert status["session_id"] == "sess_status"


def test_status_with_todo(loops_dir, tmp_path):
    todo = tmp_path / "TODO.md"
    todo.write_text("- [ ] Task 1\n- [ ] Task 2\n- [x] Task 3\n- [X] Task 4\n")
    start_ralph_loop("sess_todo", todo_path=str(todo))

    status = get_loop_status("sess_todo")
    assert status["incomplete_tasks"] == 2
    assert status["complete_tasks"] == 2
    assert status["has_hard_stop"] is False


def test_status_with_hard_stop(loops_dir, tmp_path):
    todo = tmp_path / "TODO.md"
    todo.write_text("**HARD STOP** - pause\n- [ ] Task 1\n")
    start_ralph_loop("sess_hs", todo_path=str(todo))

    status = get_loop_status("sess_hs")
    assert status["has_hard_stop"] is True


def test_status_todo_missing(loops_dir, tmp_path):
    start_ralph_loop("sess_notodo", todo_path=str(tmp_path / "nonexistent.md"))
    status = get_loop_status("sess_notodo")
    assert status is not None
    # No computed fields when todo doesn't exist
    assert "incomplete_tasks" not in status


def test_status_corrupt_json(loops_dir):
    f = loops_dir / "session_bad.json"
    f.write_text("not json")
    assert get_loop_status("bad") is None


# ---------------------------------------------------------------------------
# list_active_loops
# ---------------------------------------------------------------------------


def test_list_empty(loops_dir):
    assert list_active_loops() == []


def test_list_multiple(loops_dir):
    start_ralph_loop("a")
    start_ralph_loop("b")
    loops = list_active_loops()
    assert len(loops) == 2
    ids = {item["session_id"] for item in loops}
    assert ids == {"a", "b"}


def test_list_sorted_by_started_at(loops_dir):
    import time

    start_ralph_loop("first")
    time.sleep(0.01)
    start_ralph_loop("second")
    loops = list_active_loops()
    assert loops[0]["session_id"] == "second"  # most recent first


def test_list_skips_corrupt(loops_dir):
    start_ralph_loop("good")
    (loops_dir / "session_bad.json").write_text("nope")
    loops = list_active_loops()
    assert len(loops) == 1
    assert loops[0]["session_id"] == "good"


def test_list_with_todo_tasks(loops_dir, tmp_path):
    todo = tmp_path / "TODO.md"
    todo.write_text("- [ ] A\n- [x] B\n")
    start_ralph_loop("with_todo", todo_path=str(todo))

    loops = list_active_loops()
    assert len(loops) == 1
    assert loops[0]["incomplete_tasks"] == 1
    assert loops[0]["complete_tasks"] == 1


# ---------------------------------------------------------------------------
# update_loop_iteration
# ---------------------------------------------------------------------------


def test_update_iteration(loops_dir):
    start_ralph_loop("iter_sess")
    result = update_loop_iteration("iter_sess")
    assert result is not None
    assert result["current_iteration"] == 1

    result = update_loop_iteration("iter_sess")
    assert result["current_iteration"] == 2


def test_update_iteration_not_found(loops_dir):
    assert update_loop_iteration("nope") is None


def test_update_iteration_corrupt(loops_dir):
    (loops_dir / "session_bad.json").write_text("bad json")
    assert update_loop_iteration("bad") is None


# ---------------------------------------------------------------------------
# add_hard_stop
# ---------------------------------------------------------------------------


def test_add_hard_stop(loops_dir, tmp_path):
    todo = tmp_path / "TODO.md"
    todo.write_text("- [ ] Task 1\n")
    start_ralph_loop("hs_sess", todo_path=str(todo))

    assert add_hard_stop("hs_sess") is True
    content = todo.read_text()
    assert "**HARD STOP**" in content
    assert content.startswith("**HARD STOP**")


def test_add_hard_stop_idempotent(loops_dir, tmp_path):
    todo = tmp_path / "TODO.md"
    todo.write_text("**HARD STOP** - already here\n- [ ] Task\n")
    start_ralph_loop("hs2", todo_path=str(todo))

    assert add_hard_stop("hs2") is True
    # Should not add duplicate
    assert todo.read_text().count("**HARD STOP**") == 1


def test_add_hard_stop_no_session(loops_dir):
    assert add_hard_stop("nope") is False


def test_add_hard_stop_no_todo_path(loops_dir):
    # Create a config without todo_path
    f = loops_dir / "session_notodo.json"
    f.write_text(json.dumps({"session_id": "notodo"}))
    assert add_hard_stop("notodo") is False


def test_add_hard_stop_todo_missing(loops_dir, tmp_path):
    start_ralph_loop("missing_todo", todo_path=str(tmp_path / "gone.md"))
    assert add_hard_stop("missing_todo") is False


# ---------------------------------------------------------------------------
# remove_hard_stop
# ---------------------------------------------------------------------------


def test_remove_hard_stop(loops_dir, tmp_path):
    todo = tmp_path / "TODO.md"
    todo.write_text("**HARD STOP** - Manual verification required\n\n- [ ] Task 1\n")
    start_ralph_loop("rm_hs", todo_path=str(todo))

    assert remove_hard_stop("rm_hs") is True
    content = todo.read_text()
    assert "**HARD STOP**" not in content
    assert "- [ ] Task 1" in content


def test_remove_hard_stop_leading_blanks(loops_dir, tmp_path):
    todo = tmp_path / "TODO.md"
    todo.write_text("**HARD STOP** - pause\n\n\n- [ ] Task 1\n")
    start_ralph_loop("rm_hs2", todo_path=str(todo))

    remove_hard_stop("rm_hs2")
    content = todo.read_text()
    assert not content.startswith("\n")


def test_remove_hard_stop_no_marker(loops_dir, tmp_path):
    todo = tmp_path / "TODO.md"
    todo.write_text("- [ ] Task 1\n")
    start_ralph_loop("no_hs", todo_path=str(todo))

    assert remove_hard_stop("no_hs") is True  # Returns True even if no marker
    assert todo.read_text() == "- [ ] Task 1\n"  # Unchanged


def test_remove_hard_stop_no_session(loops_dir):
    assert remove_hard_stop("nope") is False


def test_remove_hard_stop_todo_missing(loops_dir, tmp_path):
    start_ralph_loop("gone_todo", todo_path=str(tmp_path / "gone.md"))
    assert remove_hard_stop("gone_todo") is False


# ---------------------------------------------------------------------------
# generate_todo_from_goals
# ---------------------------------------------------------------------------


def test_generate_basic(loops_dir, tmp_path):
    goals = "Fix the login bug\nAdd unit tests\nDeploy to staging"
    path = generate_todo_from_goals(goals, "sess1", workspace_path=str(tmp_path))
    content = Path(path).read_text()
    assert "- [ ] Fix the login bug" in content
    assert "- [ ] Add unit tests" in content
    assert "- [ ] Deploy to staging" in content
    assert "sess1" in content


def test_generate_with_prefixes(loops_dir, tmp_path):
    goals = "- Fix bug\n* Add tests\n• Deploy\n→ Monitor"
    path = generate_todo_from_goals(goals, "sess2", workspace_path=str(tmp_path))
    content = Path(path).read_text()
    assert "- [ ] Fix bug" in content
    assert "- [ ] Add tests" in content
    assert "- [ ] Deploy" in content
    assert "- [ ] Monitor" in content


def test_generate_with_numbering(loops_dir, tmp_path):
    goals = "1. First task\n2. Second task\n3. Third task"
    path = generate_todo_from_goals(goals, "sess3", workspace_path=str(tmp_path))
    content = Path(path).read_text()
    assert "- [ ] First task" in content
    assert "- [ ] Second task" in content


def test_generate_skips_empty_lines(loops_dir, tmp_path):
    goals = "Task 1\n\n\nTask 2\n   \n"
    path = generate_todo_from_goals(goals, "sess4", workspace_path=str(tmp_path))
    content = Path(path).read_text()
    assert content.count("- [ ]") == 2


def test_generate_default_workspace(loops_dir):
    goals = "Simple task"
    path = generate_todo_from_goals(goals, "sess5")
    assert path.endswith("TODO.md")
    # Clean up
    Path(path).unlink(missing_ok=True)
