"""Tests for tool_modules/aa_workflow/src/tool_gap_detector.py"""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from tool_modules.aa_workflow.src.tool_gap_detector import (
    ToolGapDetector,
    ToolGapRequest,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the singleton between tests."""
    ToolGapDetector._instance = None
    yield
    ToolGapDetector._instance = None


@pytest.fixture
def gap_file(tmp_path):
    """Provide a temp file and patch TOOL_GAP_FILE."""
    f = tmp_path / "tool_requests.yaml"
    with patch("tool_modules.aa_workflow.src.tool_gap_detector.TOOL_GAP_FILE", f):
        yield f


# ---------------------------------------------------------------------------
# ToolGapRequest dataclass
# ---------------------------------------------------------------------------


def test_tool_gap_request_defaults():
    r = ToolGapRequest(
        id="tgr_1",
        timestamp="2025-01-01",
        suggested_tool_name="my_tool",
        desired_action="do something",
    )
    assert r.context == ""
    assert r.suggested_args == {}
    assert r.workaround_used is None
    assert r.requesting_skills == []
    assert r.issue_key is None
    assert r.vote_count == 1
    assert r.status == "open"


def test_tool_gap_request_custom():
    r = ToolGapRequest(
        id="t1",
        timestamp="t",
        suggested_tool_name="tool",
        desired_action="action",
        context="ctx",
        suggested_args={"a": 1},
        workaround_used="manual",
        requesting_skills=["s1"],
        issue_key="AAP-123",
        vote_count=5,
        status="in_progress",
        last_requested="lr",
    )
    assert r.vote_count == 5
    assert r.status == "in_progress"


# ---------------------------------------------------------------------------
# Singleton behavior
# ---------------------------------------------------------------------------


def test_singleton(gap_file):
    d1 = ToolGapDetector()
    d2 = ToolGapDetector()
    assert d1 is d2


# ---------------------------------------------------------------------------
# _load / _save
# ---------------------------------------------------------------------------


def test_load_empty(gap_file):
    d = ToolGapDetector()
    assert d._gaps == []


def test_load_existing(gap_file):
    gap_file.write_text(
        yaml.dump(
            {
                "tool_requests": [
                    {"id": "t1", "suggested_tool_name": "tool1", "vote_count": 3},
                ],
            }
        )
    )
    d = ToolGapDetector()
    assert len(d._gaps) == 1
    assert d._gaps[0]["suggested_tool_name"] == "tool1"


def test_load_corrupt_yaml(gap_file):
    gap_file.write_text(": bad yaml [[[")
    d = ToolGapDetector()
    # Should fallback to empty
    assert isinstance(d._gaps, list)


def test_save_creates_file(gap_file):
    d = ToolGapDetector()
    d._gaps = [{"id": "x", "suggested_tool_name": "t"}]
    d._save()
    assert gap_file.exists()
    data = yaml.safe_load(gap_file.read_text())
    assert len(data["tool_requests"]) == 1
    assert "last_updated" in data


def test_save_creates_parent_dirs(tmp_path):
    deep_file = tmp_path / "a" / "b" / "c" / "tool_requests.yaml"
    with patch(
        "tool_modules.aa_workflow.src.tool_gap_detector.TOOL_GAP_FILE", deep_file
    ):
        ToolGapDetector._instance = None
        d = ToolGapDetector()
        d._gaps = [{"id": "y"}]
        d._save()
    assert deep_file.exists()


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------


def test_log_new_gap(gap_file):
    d = ToolGapDetector()
    gap_id = d.log(
        suggested_tool_name="quay_check",
        action="Check image tag",
        skill="sprint_autopilot",
        context="During sprint",
        args={"repo": "myrepo"},
        workaround="manual curl",
        issue_key="AAP-99",
    )
    assert gap_id is not None
    assert len(d._gaps) == 1
    g = d._gaps[0]
    assert g["suggested_tool_name"] == "quay_check"
    assert g["desired_action"] == "Check image tag"
    assert g["requesting_skills"] == ["sprint_autopilot"]
    assert g["vote_count"] == 1
    assert g["status"] == "open"
    assert g["workaround_used"] == "manual curl"
    assert g["issue_key"] == "AAP-99"


def test_log_duplicate_increments_vote(gap_file):
    d = ToolGapDetector()
    d.log("tool_a", "action", "skill1")
    d.log("tool_a", "action", "skill2", context="more ctx", workaround="w")

    assert len(d._gaps) == 1
    g = d._gaps[0]
    assert g["vote_count"] == 2
    assert set(g["requesting_skills"]) == {"skill1", "skill2"}
    assert g["workaround_used"] == "w"
    assert g["context"] == "more ctx"


def test_log_duplicate_preserves_existing_workaround(gap_file):
    d = ToolGapDetector()
    d.log("tool_b", "act", "s1", workaround="original")
    d.log("tool_b", "act", "s2", workaround="new")

    # Should keep original
    assert d._gaps[0]["workaround_used"] == "original"


def test_log_duplicate_preserves_existing_context(gap_file):
    d = ToolGapDetector()
    d.log("tool_c", "act", "s1", context="original")
    d.log("tool_c", "act", "s2", context="new")

    assert d._gaps[0]["context"] == "original"


def test_log_persists_to_file(gap_file):
    d = ToolGapDetector()
    d.log("tool_d", "act", "s1")
    data = yaml.safe_load(gap_file.read_text())
    assert len(data["tool_requests"]) == 1


# ---------------------------------------------------------------------------
# try_or_log
# ---------------------------------------------------------------------------


def test_try_or_log_tool_exists(gap_file):
    d = ToolGapDetector()
    mock_registry = MagicMock()
    mock_registry.tool_exists.return_value = True

    with patch.dict(
        "sys.modules",
        {
            "server.main": MagicMock(
                get_tool_registry=MagicMock(return_value=mock_registry)
            )
        },
    ):
        exists, result = d.try_or_log("existing_tool", "act", "s")

    assert exists is True
    assert result is None
    assert len(d._gaps) == 0


def test_try_or_log_tool_not_exists_no_fallback(gap_file):
    d = ToolGapDetector()

    # Simulate ImportError for server.main
    with patch.dict("sys.modules", {"server.main": None}):
        # Need to handle the import error properly
        pass

    # Simpler: just let the import fail naturally
    exists, result = d.try_or_log("missing_tool", "do X", "my_skill")
    assert exists is False
    assert isinstance(result, str)  # gap_id
    assert len(d._gaps) == 1


def test_try_or_log_with_fallback_success(gap_file):
    d = ToolGapDetector()
    exists, result = d.try_or_log(
        "missing_tool",
        "do X",
        "s",
        fallback=lambda: "fallback_result",
    )
    assert exists is False
    assert result == "fallback_result"
    assert len(d._gaps) == 1
    assert d._gaps[0]["workaround_used"] == "fallback provided"


def test_try_or_log_with_fallback_failure(gap_file):
    d = ToolGapDetector()

    def bad_fallback():
        raise ValueError("fallback failed")

    exists, result = d.try_or_log(
        "missing_tool",
        "do X",
        "s",
        fallback=bad_fallback,
    )
    assert exists is False
    assert isinstance(result, str)  # returns gap_id on fallback failure


def test_try_or_log_registry_get_tool(gap_file):
    """Test branch where registry has get_tool instead of tool_exists."""
    d = ToolGapDetector()
    mock_registry = MagicMock(spec=[])  # no tool_exists
    mock_registry.get_tool = MagicMock(return_value=MagicMock())

    mock_main = MagicMock()
    mock_main.get_tool_registry.return_value = mock_registry

    with patch.dict("sys.modules", {"server.main": mock_main}):
        exists, result = d.try_or_log("found_tool", "act", "s")

    assert exists is True


# ---------------------------------------------------------------------------
# get_gaps
# ---------------------------------------------------------------------------


def test_get_gaps_all(gap_file):
    d = ToolGapDetector()
    d._gaps = [
        {"id": "a", "status": "open", "vote_count": 3},
        {"id": "b", "status": "implemented", "vote_count": 1},
        {"id": "c", "status": "open", "vote_count": 5},
    ]
    result = d.get_gaps()
    assert len(result) == 3
    # Sorted by vote_count descending
    assert result[0]["id"] == "c"
    assert result[1]["id"] == "a"


def test_get_gaps_filtered(gap_file):
    d = ToolGapDetector()
    d._gaps = [
        {"id": "a", "status": "open", "vote_count": 1},
        {"id": "b", "status": "implemented", "vote_count": 2},
    ]
    result = d.get_gaps(status="open")
    assert len(result) == 1
    assert result[0]["id"] == "a"


def test_get_gaps_limit(gap_file):
    d = ToolGapDetector()
    d._gaps = [{"id": f"g{i}", "status": "open", "vote_count": i} for i in range(20)]
    result = d.get_gaps(limit=5)
    assert len(result) == 5


# ---------------------------------------------------------------------------
# get_most_requested
# ---------------------------------------------------------------------------


def test_get_most_requested(gap_file):
    d = ToolGapDetector()
    d._gaps = [
        {"id": "a", "status": "open", "vote_count": 10},
        {"id": "b", "status": "open", "vote_count": 5},
        {"id": "c", "status": "rejected", "vote_count": 20},  # not open
    ]
    result = d.get_most_requested(limit=10)
    assert len(result) == 2
    assert result[0]["id"] == "a"  # highest vote open


# ---------------------------------------------------------------------------
# update_status
# ---------------------------------------------------------------------------


def test_update_status_found(gap_file):
    d = ToolGapDetector()
    d._gaps = [{"id": "target", "status": "open"}]
    assert d.update_status("target", "in_progress") is True
    assert d._gaps[0]["status"] == "in_progress"


def test_update_status_not_found(gap_file):
    d = ToolGapDetector()
    d._gaps = [{"id": "other", "status": "open"}]
    assert d.update_status("nope", "closed") is False


# ---------------------------------------------------------------------------
# get_by_skill
# ---------------------------------------------------------------------------


def test_get_by_skill(gap_file):
    d = ToolGapDetector()
    d._gaps = [
        {"id": "a", "requesting_skills": ["sprint_autopilot", "deploy"]},
        {"id": "b", "requesting_skills": ["deploy"]},
        {"id": "c", "requesting_skills": ["other"]},
    ]
    result = d.get_by_skill("deploy")
    assert len(result) == 2
    ids = {g["id"] for g in result}
    assert ids == {"a", "b"}


def test_get_by_skill_not_found(gap_file):
    d = ToolGapDetector()
    d._gaps = [{"id": "a", "requesting_skills": ["x"]}]
    assert d.get_by_skill("y") == []


# ---------------------------------------------------------------------------
# format_summary
# ---------------------------------------------------------------------------


def test_format_summary_empty(gap_file):
    d = ToolGapDetector()
    result = d.format_summary()
    assert "No tool gaps" in result


def test_format_summary_with_gaps(gap_file):
    d = ToolGapDetector()
    d._gaps = [
        {
            "id": "a",
            "suggested_tool_name": "quay_check",
            "desired_action": "Check tags",
            "requesting_skills": ["s1", "s2"],
            "workaround_used": "manual curl",
            "context": "During deploy",
            "status": "open",
            "vote_count": 3,
        }
    ]
    result = d.format_summary()
    assert "quay_check" in result
    assert "3 requests" in result
    assert "Check tags" in result
    assert "s1" in result
    assert "manual curl" in result
    assert "During deploy" in result


def test_format_summary_limit(gap_file):
    d = ToolGapDetector()
    d._gaps = [
        {
            "id": f"g{i}",
            "suggested_tool_name": f"tool_{i}",
            "desired_action": "a",
            "requesting_skills": [],
            "status": "open",
            "vote_count": 1,
        }
        for i in range(20)
    ]
    result = d.format_summary(limit=3)
    # Should only include 3 tools
    assert result.count("###") == 3


# ---------------------------------------------------------------------------
# reload
# ---------------------------------------------------------------------------


def test_reload(gap_file):
    d = ToolGapDetector()
    assert d._gaps == []

    # Write gaps to file externally
    gap_file.write_text(
        yaml.dump(
            {
                "tool_requests": [{"id": "ext", "suggested_tool_name": "external"}],
            }
        )
    )

    d.reload()
    assert len(d._gaps) == 1
    assert d._gaps[0]["suggested_tool_name"] == "external"
