"""Tests for tool_modules.aa_workflow.src.sprint_prioritizer."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tool_modules.aa_workflow.src.sprint_prioritizer import (
    PRIORITY_SCORES,
    TYPE_SCORES,
    PrioritizedIssue,
    calculate_age_score,
    calculate_points_score,
    get_priority_summary,
    prioritize_issues,
    to_sprint_issue_format,
)

# ---------------------------------------------------------------------------
# calculate_age_score
# ---------------------------------------------------------------------------


class TestCalculateAgeScore:
    def test_empty_date(self):
        score, reason = calculate_age_score("")
        assert score == 0
        assert reason == ""

    def test_recent_issue(self):
        recent = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        score, reason = calculate_age_score(recent)
        assert score == 5
        assert "Recent" in reason

    def test_week_old(self):
        week_old = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        score, reason = calculate_age_score(week_old)
        assert score == 10
        assert "Week old" in reason

    def test_stale(self):
        stale = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d")
        score, reason = calculate_age_score(stale)
        assert score == 20
        assert "stale" in reason

    def test_aging(self):
        old = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d")
        score, reason = calculate_age_score(old)
        assert score == 30
        assert "Aging" in reason

    def test_iso_format_with_T(self):
        iso_date = (datetime.now() - timedelta(days=5)).isoformat()
        score, reason = calculate_age_score(iso_date)
        assert score == 5

    def test_iso_format_with_Z(self):
        iso_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        score, reason = calculate_age_score(iso_date)
        assert score == 5

    def test_invalid_date(self):
        score, reason = calculate_age_score("not-a-date")
        assert score == 0
        assert reason == ""


# ---------------------------------------------------------------------------
# calculate_points_score
# ---------------------------------------------------------------------------


class TestCalculatePointsScore:
    def test_none_points(self):
        score, reason = calculate_points_score(None)
        assert score == 10
        assert "Unestimated" in reason

    def test_zero_points(self):
        score, reason = calculate_points_score(0)
        assert score == 10
        assert "Unestimated" in reason

    def test_quick_win(self):
        score, reason = calculate_points_score(1)
        assert score == 40
        assert "Quick win" in reason

    def test_two_points(self):
        score, reason = calculate_points_score(2)
        assert score == 40
        assert "Quick win" in reason

    def test_medium_effort(self):
        score, reason = calculate_points_score(3)
        assert score == 30
        assert "Medium effort" in reason

    def test_five_points(self):
        score, reason = calculate_points_score(5)
        assert score == 30

    def test_larger_effort(self):
        score, reason = calculate_points_score(8)
        assert score == 20
        assert "Larger effort" in reason

    def test_large_item(self):
        score, reason = calculate_points_score(13)
        assert score == 10
        assert "Large item" in reason


# ---------------------------------------------------------------------------
# prioritize_issues
# ---------------------------------------------------------------------------


class TestPrioritizeIssues:
    def test_empty_list(self):
        result = prioritize_issues([])
        assert result == []

    def test_single_issue(self):
        issues = [
            {
                "key": "AAP-1",
                "summary": "Fix bug",
                "priority": "Major",
                "issuetype": "Bug",
                "storyPoints": 2,
            }
        ]
        result = prioritize_issues(issues)
        assert len(result) == 1
        assert result[0].key == "AAP-1"
        assert result[0].rank == 1
        assert result[0].score > 0

    def test_ranking_order(self):
        issues = [
            {
                "key": "AAP-1",
                "summary": "Minor task",
                "priority": "Minor",
                "issuetype": "Story",
                "storyPoints": 13,
            },
            {
                "key": "AAP-2",
                "summary": "Critical bug",
                "priority": "Critical",
                "issuetype": "Bug",
                "storyPoints": 1,
            },
        ]
        result = prioritize_issues(issues)
        assert result[0].key == "AAP-2"  # Critical bug with 1pt should be first
        assert result[0].rank == 1
        assert result[1].rank == 2

    def test_blocked_penalty(self):
        issues = [
            {
                "key": "AAP-1",
                "summary": "Blocked",
                "priority": "Critical",
                "blocked": True,
            },
            {
                "key": "AAP-2",
                "summary": "Open",
                "priority": "Major",
            },
        ]
        result = prioritize_issues(issues)
        # Blocked issue should be deprioritized despite higher priority
        blocked = next(i for i in result if i.key == "AAP-1")
        assert blocked.is_blocked
        assert "Blocked" in " ".join(blocked.reasoning)

    def test_waiting_penalty(self):
        issues = [
            {
                "key": "AAP-1",
                "summary": "Waiting",
                "priority": "Critical",
                "waitingReason": "Need clarification",
            },
            {
                "key": "AAP-2",
                "summary": "Ready",
                "priority": "Major",
            },
        ]
        result = prioritize_issues(issues)
        waiting = next(i for i in result if i.key == "AAP-1")
        assert waiting.waiting_reason == "Need clarification"
        assert any("Waiting" in r for r in waiting.reasoning)

    def test_blocked_from_status(self):
        issues = [
            {
                "key": "AAP-1",
                "summary": "Test",
                "status": "Blocked by dependency",
            }
        ]
        result = prioritize_issues(issues)
        assert result[0].is_blocked

    def test_priority_scores_mapping(self):
        for priority, expected_score in PRIORITY_SCORES.items():
            issues = [
                {
                    "key": f"TEST-{priority}",
                    "summary": f"Test {priority}",
                    "priority": priority.title(),
                }
            ]
            result = prioritize_issues(issues)
            assert result[0].factors["priority"] == expected_score

    def test_type_scores_mapping(self):
        for issue_type, expected_score in TYPE_SCORES.items():
            issues = [
                {
                    "key": f"TEST-{issue_type}",
                    "summary": f"Test {issue_type}",
                    "issuetype": issue_type.title(),
                }
            ]
            result = prioritize_issues(issues)
            assert result[0].factors["type"] == expected_score

    def test_custom_weights(self):
        issues = [
            {
                "key": "AAP-1",
                "summary": "Test",
                "priority": "Major",
                "storyPoints": 2,
            }
        ]
        config = {
            "prioritization": {
                "points_weight": 1.0,
                "priority_weight": 0.0,
                "age_weight": 0.0,
                "type_weight": 0.0,
            }
        }
        result = prioritize_issues(issues, config)
        # Score should be dominated by points (quick win = 40)
        assert result[0].score == pytest.approx(40.0)

    def test_bug_reasoning(self):
        issues = [
            {
                "key": "AAP-1",
                "summary": "Fix crash",
                "issuetype": "Bug",
                "priority": "Critical",
            }
        ]
        result = prioritize_issues(issues)
        assert any("Bug" in r or "fix first" in r.lower() for r in result[0].reasoning)
        assert any("Critical" in r or "High priority" in r for r in result[0].reasoning)

    def test_alternate_field_names(self):
        """Test backward compatibility with different field names."""
        issues = [
            {
                "key": "AAP-1",
                "summary": "Test",
                "type": "Task",
                "story_points": 3,
                "jiraStatus": "In Progress",
                "waiting_reason": "waiting for review",
            }
        ]
        result = prioritize_issues(issues)
        assert result[0].story_points == 3
        assert result[0].status == "In Progress"
        assert result[0].waiting_reason == "waiting for review"

    def test_defaults_for_missing_fields(self):
        issues = [{"key": "AAP-1", "summary": "Minimal"}]
        result = prioritize_issues(issues)
        assert result[0].priority == "Major"  # default
        assert result[0].issue_type == "Story"  # default


# ---------------------------------------------------------------------------
# get_priority_summary
# ---------------------------------------------------------------------------


class TestGetPrioritySummary:
    def test_empty_list(self):
        result = get_priority_summary([])
        assert "No issues" in result

    def test_summary_content(self):
        issues = [
            PrioritizedIssue(
                key="AAP-1",
                summary="Test issue",
                rank=1,
                score=85.0,
                reasoning=["High priority"],
                story_points=2,
                priority="Critical",
            )
        ]
        summary = get_priority_summary(issues)
        assert "AAP-1" in summary
        assert "Test issue" in summary
        assert "85.0" in summary
        assert "High priority" in summary

    def test_limits_to_ten(self):
        issues = [
            PrioritizedIssue(
                key=f"AAP-{i}",
                summary=f"Issue {i}",
                rank=i,
                score=100 - i,
            )
            for i in range(1, 15)
        ]
        summary = get_priority_summary(issues)
        assert "AAP-10" in summary
        assert "AAP-11" not in summary

    def test_status_icons(self):
        issues = [
            PrioritizedIssue(
                key="AAP-1",
                summary="Blocked",
                rank=1,
                score=10,
                is_blocked=True,
            ),
            PrioritizedIssue(
                key="AAP-2",
                summary="Waiting",
                rank=2,
                score=9,
                waiting_reason="clarification",
            ),
            PrioritizedIssue(
                key="AAP-3",
                summary="Ready",
                rank=3,
                score=8,
            ),
        ]
        summary = get_priority_summary(issues)
        summary.split("\n")
        text = summary
        # Should have different icons for different statuses
        assert "\U0001f534" in text  # red circle (blocked)
        assert "\u23f3" in text  # hourglass (waiting)
        assert "\U0001f7e2" in text  # green circle (ready)


# ---------------------------------------------------------------------------
# to_sprint_issue_format
# ---------------------------------------------------------------------------


class TestToSprintIssueFormat:
    def test_empty_list(self):
        assert to_sprint_issue_format([]) == []

    def test_basic_conversion(self):
        issues = [
            PrioritizedIssue(
                key="AAP-1",
                summary="Fix bug",
                rank=1,
                score=80.0,
                story_points=3,
                priority="Critical",
                status="New",
                assignee="alice",
                issue_type="Bug",
                created="2025-01-01",
                reasoning=["Quick win"],
            )
        ]
        result = to_sprint_issue_format(issues)
        assert len(result) == 1
        item = result[0]
        assert item["key"] == "AAP-1"
        assert item["storyPoints"] == 3
        assert item["priority"] == "Critical"
        assert item["jiraStatus"] == "New"
        assert item["assignee"] == "alice"
        assert item["approvalStatus"] == "pending"
        assert item["priorityReasoning"] == ["Quick win"]
        assert item["issueType"] == "Bug"
        assert item["created"] == "2025-01-01"

    def test_blocked_status(self):
        issues = [
            PrioritizedIssue(
                key="AAP-1",
                summary="Test",
                rank=1,
                score=10,
                is_blocked=True,
            )
        ]
        result = to_sprint_issue_format(issues)
        assert result[0]["approvalStatus"] == "blocked"

    def test_waiting_status(self):
        issues = [
            PrioritizedIssue(
                key="AAP-1",
                summary="Test",
                rank=1,
                score=10,
                waiting_reason="Need info",
            )
        ]
        result = to_sprint_issue_format(issues)
        assert result[0]["approvalStatus"] == "waiting"
        assert result[0]["waitingReason"] == "Need info"

    def test_estimated_actions(self):
        issues = [PrioritizedIssue(key="AAP-1", summary="T", rank=1, score=10)]
        result = to_sprint_issue_format(issues)
        assert "start_work" in result[0]["estimatedActions"]
        assert "implement" in result[0]["estimatedActions"]
        assert "create_mr" in result[0]["estimatedActions"]


# ---------------------------------------------------------------------------
# PrioritizedIssue dataclass
# ---------------------------------------------------------------------------


class TestPrioritizedIssueDataclass:
    def test_defaults(self):
        issue = PrioritizedIssue(key="AAP-1", summary="Test", rank=1, score=50.0)
        assert issue.reasoning == []
        assert issue.factors == {}
        assert issue.story_points == 0
        assert issue.priority == "Major"
        assert issue.issue_type == "Story"
        assert issue.status == "New"
        assert issue.created == ""
        assert issue.assignee == ""
        assert issue.is_blocked is False
        assert issue.waiting_reason is None
