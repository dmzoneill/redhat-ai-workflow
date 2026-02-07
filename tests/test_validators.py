"""Tests for scripts/common/validators.py - Git and tool validation functions."""

import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from scripts.common.validators import (
    check_branch_exists,
    check_can_force_push,
    check_commits_ahead_behind,
    check_tools,
    check_uncommitted_changes,
    estimate_diff_size,
    validate_git_repo,
    validate_jira_issue,
)

# ==================== validate_git_repo ====================


class TestValidateGitRepo:
    @patch("scripts.common.validators.run_cmd_sync")
    def test_not_a_git_repo(self, mock_cmd):
        mock_cmd.return_value = (False, "fatal: not a git repository")
        with pytest.raises(ValueError, match="Not a git repository"):
            validate_git_repo("/some/path")

    @patch("scripts.common.validators.run_cmd_sync")
    def test_valid_repo_no_issues(self, mock_cmd):
        mock_cmd.side_effect = [
            (True, ".git"),  # rev-parse --git-dir
            (True, "main"),  # rev-parse --abbrev-ref HEAD
        ]
        with patch("os.path.exists", return_value=False):
            result = validate_git_repo("/repo")
        assert result["valid"] is True
        assert result["issues"] == []
        assert result["current_branch"] == "main"
        assert result["is_detached"] is False

    @patch("scripts.common.validators.run_cmd_sync")
    def test_absolute_git_dir(self, mock_cmd):
        mock_cmd.side_effect = [
            (True, "/repo/.git"),  # already absolute
            (True, "main"),
        ]
        with patch("os.path.exists", return_value=False):
            result = validate_git_repo("/repo")
        assert result["git_dir"] == "/repo/.git"

    @patch("scripts.common.validators.run_cmd_sync")
    def test_relative_git_dir(self, mock_cmd):
        mock_cmd.side_effect = [
            (True, ".git"),  # relative - should be joined with repo path
            (True, "main"),
        ]
        with patch("os.path.exists", return_value=False):
            result = validate_git_repo("/myrepo")
        assert result["git_dir"] == "/myrepo/.git"

    @patch("scripts.common.validators.run_cmd_sync")
    def test_rebase_in_progress(self, mock_cmd):
        mock_cmd.side_effect = [
            (True, "/repo/.git"),
            (True, "feature"),
        ]

        def exists_side_effect(path):
            return "rebase-merge" in path

        with patch("os.path.exists", side_effect=exists_side_effect):
            result = validate_git_repo("/repo")
        assert "rebase_in_progress" in result["issues"]

    @patch("scripts.common.validators.run_cmd_sync")
    def test_merge_in_progress(self, mock_cmd):
        mock_cmd.side_effect = [
            (True, "/repo/.git"),
            (True, "feature"),
        ]

        def exists_side_effect(path):
            return "MERGE_HEAD" in path

        with patch("os.path.exists", side_effect=exists_side_effect):
            result = validate_git_repo("/repo")
        assert "merge_in_progress" in result["issues"]

    @patch("scripts.common.validators.run_cmd_sync")
    def test_cherry_pick_in_progress(self, mock_cmd):
        mock_cmd.side_effect = [
            (True, "/repo/.git"),
            (True, "feature"),
        ]

        def exists_side_effect(path):
            return "CHERRY_PICK_HEAD" in path

        with patch("os.path.exists", side_effect=exists_side_effect):
            result = validate_git_repo("/repo")
        assert "cherry_pick_in_progress" in result["issues"]

    @patch("scripts.common.validators.run_cmd_sync")
    def test_detached_head(self, mock_cmd):
        mock_cmd.side_effect = [
            (True, "/repo/.git"),
            (True, "HEAD"),
        ]
        with patch("os.path.exists", return_value=False):
            result = validate_git_repo("/repo")
        assert result["is_detached"] is True
        assert "detached_head" in result["issues"]

    @patch("scripts.common.validators.run_cmd_sync")
    def test_branch_detection_fails(self, mock_cmd):
        mock_cmd.side_effect = [
            (True, "/repo/.git"),
            (False, "error"),
        ]
        with patch("os.path.exists", return_value=False):
            result = validate_git_repo("/repo")
        assert result["current_branch"] is None

    @patch("scripts.common.validators.run_cmd_sync")
    @patch("os.getcwd", return_value="/current/dir")
    def test_dot_uses_cwd(self, mock_cwd, mock_cmd):
        mock_cmd.side_effect = [
            (True, ".git"),
            (True, "main"),
        ]
        with patch("os.path.exists", return_value=False):
            result = validate_git_repo(".")
        # First call should use cwd
        assert mock_cmd.call_args_list[0][1]["cwd"] == "/current/dir"


# ==================== check_uncommitted_changes ====================


class TestCheckUncommittedChanges:
    @patch("scripts.common.validators.run_cmd_sync")
    def test_no_changes(self, mock_cmd):
        mock_cmd.return_value = (True, "")
        result = check_uncommitted_changes("/repo")
        assert result["has_changes"] is False

    @patch("scripts.common.validators.run_cmd_sync")
    def test_with_staged(self, mock_cmd):
        mock_cmd.return_value = (True, "M  file.py\nA  new.py")
        result = check_uncommitted_changes("/repo")
        assert result["has_changes"] is True
        assert result["staged"] == 2

    @patch("scripts.common.validators.run_cmd_sync")
    def test_with_unstaged(self, mock_cmd):
        # Git porcelain: first char=staged, second=unstaged
        # "MM" means both staged and unstaged modification
        # strip() eats leading spaces on the whole output, so use MM format
        mock_cmd.return_value = (True, "MM file.py")
        result = check_uncommitted_changes("/repo")
        assert result["has_changes"] is True
        assert result["unstaged"] == 1

    @patch("scripts.common.validators.run_cmd_sync")
    def test_with_untracked(self, mock_cmd):
        mock_cmd.return_value = (True, "?? newfile.py\n?? another.py")
        result = check_uncommitted_changes("/repo")
        assert result["has_changes"] is True
        assert result["untracked"] == 2

    @patch("scripts.common.validators.run_cmd_sync")
    def test_command_failure(self, mock_cmd):
        mock_cmd.return_value = (False, "fatal: error")
        result = check_uncommitted_changes("/repo")
        assert result["has_changes"] is False
        assert "error" in result

    @patch("scripts.common.validators.run_cmd_sync")
    def test_files_limited_to_10(self, mock_cmd):
        lines = "\n".join(f"M  file{i}.py" for i in range(20))
        mock_cmd.return_value = (True, lines)
        result = check_uncommitted_changes("/repo")
        assert len(result["files"]) == 10

    @patch("scripts.common.validators.run_cmd_sync")
    @patch("os.getcwd", return_value="/cwd")
    def test_dot_uses_cwd(self, mock_cwd, mock_cmd):
        mock_cmd.return_value = (True, "")
        check_uncommitted_changes(".")
        assert mock_cmd.call_args[1]["cwd"] == "/cwd"


# ==================== check_tools ====================


class TestCheckTools:
    @patch("shutil.which")
    def test_all_available(self, mock_which):
        mock_which.return_value = "/usr/bin/tool"
        result = check_tools(["git", "glab"])
        assert result["all_available"] is True
        assert result["missing"] == []
        assert result["available"] == ["git", "glab"]

    @patch("shutil.which")
    def test_some_missing(self, mock_which):
        mock_which.side_effect = lambda t: "/usr/bin/git" if t == "git" else None
        result = check_tools(["git", "glab", "black"])
        assert result["all_available"] is False
        assert result["missing"] == ["glab", "black"]
        assert result["available"] == ["git"]

    @patch("shutil.which")
    def test_all_missing(self, mock_which):
        mock_which.return_value = None
        result = check_tools(["foo", "bar"])
        assert result["all_available"] is False
        assert result["missing"] == ["foo", "bar"]

    @patch("shutil.which")
    def test_empty_list(self, mock_which):
        result = check_tools([])
        assert result["all_available"] is True
        assert result["missing"] == []


# ==================== check_branch_exists ====================


class TestCheckBranchExists:
    @patch("scripts.common.validators.run_cmd_sync")
    def test_local_only(self, mock_cmd):
        mock_cmd.side_effect = [
            (True, ""),  # local exists
            (False, ""),  # remote not found
        ]
        result = check_branch_exists("feature")
        assert result["exists"] is True
        assert result["local"] is True
        assert result["remote"] is False
        assert result["full_name"] == "feature"

    @patch("scripts.common.validators.run_cmd_sync")
    def test_remote_only(self, mock_cmd):
        mock_cmd.side_effect = [
            (False, ""),  # local not found
            (True, ""),  # remote exists
        ]
        result = check_branch_exists("feature")
        assert result["exists"] is True
        assert result["remote"] is True
        assert result["full_name"] == "origin/feature"

    @patch("scripts.common.validators.run_cmd_sync")
    def test_not_found(self, mock_cmd):
        mock_cmd.return_value = (False, "")
        result = check_branch_exists("nope")
        assert result["exists"] is False

    @patch("scripts.common.validators.run_cmd_sync")
    def test_skip_remote(self, mock_cmd):
        mock_cmd.return_value = (True, "")
        result = check_branch_exists("feature", check_remote=False)
        assert result["local"] is True
        assert result["remote"] is False
        # Should only call once (local check only)
        assert mock_cmd.call_count == 1


# ==================== check_can_force_push ====================


class TestCheckCanForcePush:
    @patch("scripts.common.validators.run_cmd_sync")
    def test_allowed(self, mock_cmd):
        mock_cmd.return_value = (True, "Everything up-to-date")
        result = check_can_force_push("feature")
        assert result["allowed"] is True

    @patch("scripts.common.validators.run_cmd_sync")
    def test_protected_branch(self, mock_cmd):
        mock_cmd.return_value = (False, "remote: Protected branch")
        result = check_can_force_push("main")
        assert result["allowed"] is False
        assert "protected" in result["reason"].lower()

    @patch("scripts.common.validators.run_cmd_sync")
    def test_permission_denied(self, mock_cmd):
        mock_cmd.return_value = (False, "Permission denied 403")
        result = check_can_force_push("main")
        assert result["allowed"] is False
        assert "Permission denied" in result["reason"]

    @patch("scripts.common.validators.run_cmd_sync")
    def test_remote_rejected(self, mock_cmd):
        mock_cmd.return_value = (False, "remote rejected")
        result = check_can_force_push("main")
        assert result["allowed"] is False
        assert "rejected" in result["reason"].lower()

    @patch("scripts.common.validators.run_cmd_sync")
    def test_non_zero_but_ok(self, mock_cmd):
        mock_cmd.return_value = (False, "nothing to push")
        result = check_can_force_push("feature")
        assert result["allowed"] is True


# ==================== validate_jira_issue ====================


class TestValidateJiraIssue:
    def test_standard_format(self):
        result = validate_jira_issue("AAP-12345")
        assert result["valid"] is True
        assert result["project"] == "AAP"
        assert result["number"] == 12345
        assert result["key"] == "AAP-12345"

    def test_lowercase(self):
        result = validate_jira_issue("aap-123")
        assert result["valid"] is True
        assert result["project"] == "AAP"
        assert result["key"] == "AAP-123"

    def test_number_only(self):
        result = validate_jira_issue("12345")
        assert result["valid"] is True
        assert result["project"] == "AAP"
        assert result["number"] == 12345

    def test_invalid_format(self):
        result = validate_jira_issue("not-valid-format")
        assert result["valid"] is False
        assert result["project"] is None
        assert result["number"] is None


# ==================== check_commits_ahead_behind ====================


class TestCheckCommitsAheadBehind:
    @patch("scripts.common.validators.run_cmd_sync")
    def test_up_to_date(self, mock_cmd):
        mock_cmd.side_effect = [
            (True, ""),  # git fetch
            (True, "0"),  # ahead
            (True, "0"),  # behind
        ]
        result = check_commits_ahead_behind("origin/main", "/repo")
        assert result["ahead"] == 0
        assert result["behind"] == 0
        assert result["diverged"] is False
        assert result["up_to_date"] is True

    @patch("scripts.common.validators.run_cmd_sync")
    def test_ahead(self, mock_cmd):
        mock_cmd.side_effect = [
            (True, ""),  # git fetch
            (True, "3"),  # ahead
            (True, "0"),  # behind
        ]
        result = check_commits_ahead_behind()
        assert result["ahead"] == 3
        assert result["behind"] == 0
        assert result["diverged"] is False

    @patch("scripts.common.validators.run_cmd_sync")
    def test_diverged(self, mock_cmd):
        mock_cmd.side_effect = [
            (True, ""),
            (True, "2"),
            (True, "5"),
        ]
        result = check_commits_ahead_behind()
        assert result["ahead"] == 2
        assert result["behind"] == 5
        assert result["diverged"] is True
        assert result["up_to_date"] is False

    @patch("scripts.common.validators.run_cmd_sync")
    def test_command_failure(self, mock_cmd):
        mock_cmd.side_effect = [
            (True, ""),
            (False, "error"),
            (False, "error"),
        ]
        result = check_commits_ahead_behind()
        assert result["ahead"] == 0
        assert result["behind"] == 0


# ==================== estimate_diff_size ====================


class TestEstimateDiffSize:
    @patch("scripts.common.validators.run_cmd_sync")
    def test_normal_diff(self, mock_cmd):
        mock_cmd.return_value = (
            True,
            " api/handler.py | 10 ++--\n core/models.py | 5 +-\n 2 files changed, 10 insertions(+), 5 deletions(-)",
        )
        result = estimate_diff_size()
        assert result["files_changed"] == 2
        assert result["lines_added"] == 10
        assert result["lines_removed"] == 5
        assert result["total_lines"] == 15
        assert result["is_large"] is False

    @patch("scripts.common.validators.run_cmd_sync")
    def test_large_diff(self, mock_cmd):
        mock_cmd.return_value = (
            True,
            " 55 files changed, 3000 insertions(+), 2500 deletions(-)",
        )
        result = estimate_diff_size()
        assert result["is_large"] is True

    @patch("scripts.common.validators.run_cmd_sync")
    def test_no_output(self, mock_cmd):
        mock_cmd.return_value = (False, "")
        result = estimate_diff_size()
        assert result["files_changed"] == 0
        assert result["lines_added"] == 0
        assert result["lines_removed"] == 0
        assert result["is_large"] is False

    @patch("scripts.common.validators.run_cmd_sync")
    def test_single_file(self, mock_cmd):
        mock_cmd.return_value = (
            True,
            " main.py | 1 +\n 1 file changed, 1 insertion(+)",
        )
        result = estimate_diff_size()
        assert result["files_changed"] == 1
        assert result["lines_added"] == 1
        assert result["lines_removed"] == 0
