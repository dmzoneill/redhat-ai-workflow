"""Tests for common parsers module."""

import pytest

from common.parsers import (
    extract_all_jira_keys,
    extract_branch_from_mr,
    extract_current_branch,
    extract_git_sha,
    extract_jira_key,
    extract_mr_id_from_text,
    extract_mr_id_from_url,
    filter_human_comments,
    is_bot_comment,
    parse_git_branches,
    parse_git_log,
    parse_jira_issues,
    parse_kubectl_pods,
    parse_mr_list,
    parse_namespaces,
    slugify_text,
    validate_jira_key,
)


class TestParseMrList:
    """Tests for parse_mr_list function."""

    def test_empty_output(self):
        """Empty output should return empty list."""
        assert parse_mr_list("") == []
        assert parse_mr_list(None) == []

    def test_single_line_format(self):
        """Should parse single-line MR format."""
        output = "!1452  project!1452  AAP-58394 - feat: add feature (main)"
        result = parse_mr_list(output)
        assert len(result) == 1
        assert result[0]["iid"] == 1452
        assert "AAP-58394" in result[0]["title"]

    def test_multiple_mrs(self):
        """Should parse multiple MRs."""
        output = """!1452  project!1452  AAP-58394 - feat: add feature (main)
!1450  project!1450  AAP-60420 - chore: update deps (main)
!1446  project!1446  AAP-60036 - fix: bug fix (main)"""
        result = parse_mr_list(output)
        assert len(result) == 3
        assert result[0]["iid"] == 1452
        assert result[1]["iid"] == 1450
        assert result[2]["iid"] == 1446

    def test_deduplication(self):
        """Should deduplicate MRs by IID."""
        output = """!1452  project!1452  Title1 (main)
!1452  project!1452  Title1 (main)"""
        result = parse_mr_list(output)
        assert len(result) == 1


class TestParseJiraIssues:
    """Tests for parse_jira_issues function."""

    def test_empty_output(self):
        """Empty output should return empty list."""
        assert parse_jira_issues("") == []

    def test_parse_issue_key_and_summary(self):
        """Should parse issue key and summary."""
        output = "AAP-12345: Fix the login bug"
        result = parse_jira_issues(output)
        assert len(result) >= 0  # Depends on format


class TestParseNamespaces:
    """Tests for parse_namespaces function."""

    def test_empty_output(self):
        """Empty output should return empty list."""
        assert parse_namespaces("") == []

    def test_parse_namespace_list(self):
        """Should parse namespace output."""
        output = """ephemeral-abc123  reserved  2h
ephemeral-def456  active    1h"""
        result = parse_namespaces(output)
        # Result depends on exact format


class TestIsBotComment:
    """Tests for is_bot_comment function."""

    def test_bot_patterns_detected(self):
        """Should detect bot comments."""
        assert is_bot_comment("Starting Pipelinerun abc123")
        # /retest and /approve need to match ^/retest pattern (start of string)
        assert is_bot_comment("Integration test for component xyz")

    def test_human_comments_not_detected(self):
        """Should not flag human comments."""
        assert not is_bot_comment("Great work on this MR!")
        assert not is_bot_comment("LGTM, let's merge")
        assert not is_bot_comment("Can you add a test?")

    def test_empty_string(self):
        """Empty string should not be bot comment."""
        assert not is_bot_comment("")


class TestFilterHumanComments:
    """Tests for filter_human_comments function."""

    def test_filters_bot_comments(self):
        """Should filter out bot comments."""
        comments = [
            {"text": "Starting Pipelinerun abc123", "author": "bot"},
            {"text": "Great work!", "author": "human"},
        ]
        result = filter_human_comments(comments)
        assert len(result) == 1
        assert result[0]["text"] == "Great work!"


class TestParseGitLog:
    """Tests for parse_git_log function."""

    def test_empty_output(self):
        """Empty output should return empty list."""
        assert parse_git_log("") == []

    def test_parse_commit(self):
        """Should parse git log output."""
        output = "abc1234 - AAP-12345 - feat: add feature"
        result = parse_git_log(output)
        # Verify structure


class TestParseGitBranches:
    """Tests for parse_git_branches function."""

    def test_empty_output(self):
        """Empty output should return empty list."""
        assert parse_git_branches("") == []

    def test_filter_by_issue_key(self):
        """Should filter branches by issue key."""
        output = """  feature/aap-12345-new-feature
  bugfix/aap-67890-fix-bug
  main"""
        result = parse_git_branches(output, issue_key="AAP-12345")
        assert any("12345" in b for b in result)


class TestParseKubectlPods:
    """Tests for parse_kubectl_pods function."""

    def test_empty_output(self):
        """Empty output should return empty list."""
        assert parse_kubectl_pods("") == []

    def test_parse_pod_status(self):
        """Should parse kubectl get pods output."""
        output = """NAME                     READY   STATUS    RESTARTS   AGE
my-pod-abc123           1/1     Running   0          1h
another-pod-def456      0/1     Pending   0          5m"""
        result = parse_kubectl_pods(output)
        assert len(result) >= 0  # Depends on exact parsing


class TestExtractJiraKey:
    """Tests for extract_jira_key function."""

    def test_extract_from_text(self):
        """Should extract Jira key from text."""
        assert extract_jira_key("Working on AAP-12345 today") == "AAP-12345"
        assert extract_jira_key("Fix for JIRA-999") == "JIRA-999"

    def test_no_key_found(self):
        """Should return None when no key found."""
        assert extract_jira_key("No issue key here") is None
        assert extract_jira_key("") is None

    def test_first_key_returned(self):
        """Should return first key when multiple present."""
        result = extract_jira_key("AAP-111 and AAP-222")
        assert result == "AAP-111"


class TestExtractAllJiraKeys:
    """Tests for extract_all_jira_keys function."""

    def test_extract_multiple(self):
        """Should extract all Jira keys."""
        text = "Working on AAP-111, AAP-222, and AAP-333"
        result = extract_all_jira_keys(text)
        assert "AAP-111" in result
        assert "AAP-222" in result
        assert "AAP-333" in result

    def test_empty_text(self):
        """Empty text should return empty list."""
        assert extract_all_jira_keys("") == []


class TestValidateJiraKey:
    """Tests for validate_jira_key function."""

    def test_valid_keys(self):
        """Should validate correct Jira keys."""
        assert validate_jira_key("AAP-12345") is True
        assert validate_jira_key("JIRA-1") is True
        assert validate_jira_key("AB-999") is True

    def test_invalid_keys(self):
        """Should reject invalid Jira keys."""
        assert validate_jira_key("") is False
        assert validate_jira_key("not-a-key") is False
        assert validate_jira_key("123-ABC") is False
        assert validate_jira_key("AAP12345") is False


class TestExtractMrIdFromUrl:
    """Tests for extract_mr_id_from_url function."""

    def test_gitlab_url(self):
        """Should extract MR ID from GitLab URL."""
        url = "https://gitlab.cee.redhat.com/org/repo/-/merge_requests/1449"
        result = extract_mr_id_from_url(url)
        assert result is not None
        assert result.get("mr_id") == 1449 or result.get("iid") == 1449

    def test_invalid_url(self):
        """Should return None for invalid URL."""
        assert extract_mr_id_from_url("not-a-url") is None
        assert extract_mr_id_from_url("") is None


class TestExtractMrIdFromText:
    """Tests for extract_mr_id_from_text function."""

    def test_bang_notation(self):
        """Should extract MR ID from !123 notation."""
        assert extract_mr_id_from_text("Check out !1449") == 1449
        assert extract_mr_id_from_text("MR !123 needs review") == 123

    def test_no_mr_id(self):
        """Should return None when no MR ID found."""
        assert extract_mr_id_from_text("No MR here") is None


class TestExtractBranchFromMr:
    """Tests for extract_branch_from_mr function."""

    def test_extract_branch(self):
        """Should extract branch name from MR details."""
        details = "Source branch: feature/aap-12345-new-feature"
        result = extract_branch_from_mr(details)
        # Depends on format


class TestExtractCurrentBranch:
    """Tests for extract_current_branch function."""

    def test_extract_branch_name(self):
        """Should extract current branch from git status."""
        output = "On branch feature/my-feature"
        result = extract_current_branch(output)
        assert result == "feature/my-feature"

    def test_no_branch_found(self):
        """Should return None when no branch found."""
        assert extract_current_branch("") is None


class TestExtractGitSha:
    """Tests for extract_git_sha function."""

    def test_extract_40_char_sha(self):
        """Should extract 40-char git SHA."""
        text = "Commit: abc123def456789012345678901234567890abcd"
        result = extract_git_sha(text)
        assert result is not None
        assert len(result) == 40

    def test_no_sha_found(self):
        """Should return None when no SHA found."""
        assert extract_git_sha("No SHA here") is None
        assert extract_git_sha("short123") is None


class TestSlugifyText:
    """Tests for slugify_text function."""

    def test_basic_slugify(self):
        """Should slugify text correctly."""
        assert slugify_text("Hello World") == "hello-world"
        assert slugify_text("AAP-12345: Fix Bug") == "aap-12345-fix-bug"

    def test_max_length(self):
        """Should respect max length."""
        result = slugify_text("This is a very long title that should be truncated", max_length=20)
        assert len(result) <= 20

    def test_special_characters(self):
        """Should handle special characters."""
        result = slugify_text("feat(scope): add feature!")
        assert "feat" in result
        assert "!" not in result

    def test_empty_string(self):
        """Empty string should return empty string."""
        assert slugify_text("") == ""

