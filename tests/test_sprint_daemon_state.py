"""Tests for the Jira-refresh and review-check helpers in services.sprint.daemon_state."""

import pytest

from services.sprint.daemon_state import (
    apply_sprint_points,
    filter_assigned,
    merge_sprint_issues,
    parse_mr_status,
    review_check_prompt,
    sprint_metadata,
)
from tool_modules.aa_workflow.src.sprint_history import SprintIssue


def test_sprint_metadata_maps_active_sprint():
    """Active sprint info becomes currentSprint metadata with zeroed points."""
    meta = sprint_metadata({"id": 7, "name": "S7", "startDate": "a", "endDate": "b"})
    assert meta == {"id": "7", "name": "S7", "startDate": "a", "endDate": "b", "totalPoints": 0, "completedPoints": 0}


@pytest.mark.parametrize("info", [None, {}, {"error": "boom"}])
def test_sprint_metadata_none_on_failure(info):
    """Missing or failed sprint lookups give no metadata."""
    assert sprint_metadata(info) is None


def test_filter_assigned_matches_username_or_full_name_case_insensitively():
    """Issues are kept when the assignee equals the username or the full name."""
    issues = [{"assignee": "DOneill"}, {"assignee": "David ONeill"}, {"assignee": "someone"}, {}]
    kept = filter_assigned(issues, {"jira_username": "doneill", "full_name": "david oneill"})
    assert kept == issues[:2]


def test_filter_assigned_keeps_all_without_user_config():
    """No configured user means no filtering."""
    issues = [{"assignee": "a"}, {"assignee": "b"}]
    assert filter_assigned(issues, {}) is issues


def test_merge_sprint_issues_preserves_known_issue_state_and_defaults_new_ones():
    """Approval, waiting reason, chat and timeline survive a refresh; new issues start pending."""
    existing = SprintIssue(
        key="AAP-1", summary="old", approval_status="approved", waiting_reason="w", chat_id="c", timeline=[]
    )
    merged = merge_sprint_issues(
        [
            {"key": "AAP-1", "summary": "new", "storyPoints": 3, "jiraStatus": "In Progress"},
            {"key": "AAP-2", "summary": "fresh"},
        ],
        [existing],
    )
    assert len(merged) == 2
    first, second = merged[0], merged[1]
    assert (first.summary, first.story_points, first.jira_status) == ("new", 3, "In Progress")
    assert (first.approval_status, first.waiting_reason, first.chat_id) == ("approved", "w", "c")
    assert (second.approval_status, second.waiting_reason, second.chat_id, second.timeline) == (
        "pending",
        None,
        None,
        [],
    )
    assert (second.priority, second.issue_type) == ("Major", "Story")


def test_apply_sprint_points_counts_total_and_completed():
    """Total sums every issue; completed only issues in a completed status."""
    sprint = {"totalPoints": 0, "completedPoints": 0}
    issues = [
        SprintIssue(key="A", summary="", story_points=3, jira_status="Done"),
        SprintIssue(key="B", summary="", story_points=5, jira_status="In Progress"),
    ]
    apply_sprint_points(sprint, issues)
    assert sprint == {"totalPoints": 8, "completedPoints": 3}


def test_apply_sprint_points_ignores_missing_sprint():
    """Without sprint metadata nothing happens."""
    apply_sprint_points(None, [SprintIssue(key="A", summary="", story_points=1)])


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("[MR_STATUS: READY_TO_MERGE]\n[MR_ID: 42]", ("READY_TO_MERGE", None, 42)),
        ("[mr_status: approved_with_hold] reason: wait for QA ", ("APPROVED_WITH_HOLD", "wait for QA", None)),
        ("[MR_STATUS: NO_MR]", ("NO_MR", None, None)),
        ("nothing useful", None),
    ],
)
def test_parse_mr_status(output, expected):
    """Status, hold reason and MR ID are parsed; unparseable output gives None."""
    assert parse_mr_status(output) == expected


def test_review_check_prompt_mentions_issue_and_first_five_patterns():
    """The prompt names the issue and at most five don't-merge patterns."""
    prompt = review_check_prompt("AAP-9", ["p1", "p2", "p3", "p4", "p5", "p6"])
    assert 'search="AAP-9"' in prompt
    assert "p1, p2, p3, p4, p5" in prompt
    assert "p6" not in prompt
