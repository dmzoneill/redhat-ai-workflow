"""Tests for scripts/common/lint_utils.py"""

from unittest.mock import patch

import pytest

from scripts.common.lint_utils import LintResult, format_lint_error, run_lint_check

# ---------------------------------------------------------------------------
# LintResult dataclass
# ---------------------------------------------------------------------------


class TestLintResult:
    def test_fields(self):
        r = LintResult(
            passed=True,
            black_ok=True,
            flake8_ok=True,
            errors=[],
            message="Lint passed",
        )
        assert r.passed is True
        assert r.errors == []

    def test_to_dict(self):
        r = LintResult(
            passed=False,
            black_ok=False,
            flake8_ok=True,
            errors=["Black: needs formatting"],
            message="Black: needs formatting",
        )
        d = r.to_dict()
        assert d == {
            "passed": False,
            "black_ok": False,
            "flake8_ok": True,
            "errors": ["Black: needs formatting"],
            "message": "Black: needs formatting",
        }


# ---------------------------------------------------------------------------
# run_lint_check
# ---------------------------------------------------------------------------


class TestRunLintCheck:
    @patch("scripts.common.lint_utils.run_cmd_sync", return_value=(True, ""))
    @patch("shutil.which", return_value="/usr/bin/black")
    @patch("scripts.common.lint_utils.get_flake8_ignore_codes", return_value="E501")
    @patch("scripts.common.lint_utils.get_flake8_max_line_length", return_value=100)
    def test_both_pass(self, mock_len, mock_codes, mock_which, mock_cmd):
        result = run_lint_check("/tmp/repo")
        assert result.passed is True
        assert result.black_ok is True
        assert result.flake8_ok is True
        assert result.message == "Lint passed"

    @patch(
        "scripts.common.lint_utils.run_cmd_sync", return_value=(False, "would reformat")
    )
    @patch("shutil.which", return_value="/usr/bin/black")
    @patch("scripts.common.lint_utils.get_flake8_ignore_codes", return_value="E501")
    @patch("scripts.common.lint_utils.get_flake8_max_line_length", return_value=100)
    def test_black_fails(self, mock_len, mock_codes, mock_which, mock_cmd):
        result = run_lint_check("/tmp/repo", check_flake8=False)
        assert result.passed is False
        assert result.black_ok is False
        assert any("Black" in e for e in result.errors)

    @patch("scripts.common.lint_utils.run_cmd_sync")
    @patch("shutil.which", return_value="/usr/bin/flake8")
    @patch("scripts.common.lint_utils.get_flake8_ignore_codes", return_value="E501")
    @patch("scripts.common.lint_utils.get_flake8_max_line_length", return_value=100)
    def test_flake8_fails(self, mock_len, mock_codes, mock_which, mock_cmd):
        # Black passes, flake8 fails
        mock_cmd.side_effect = [
            (True, ""),  # black
            (
                False,
                "file.py:1:1: E302 expected 2 blank lines\nfile.py:2:1: W291 trailing ws",
            ),  # flake8
        ]
        result = run_lint_check("/tmp/repo")
        assert result.passed is False
        assert result.flake8_ok is False
        assert any("Flake8: 2 issue(s)" in e for e in result.errors)

    @patch("scripts.common.lint_utils.run_cmd_sync", return_value=(True, ""))
    @patch("shutil.which", return_value="/usr/bin/black")
    @patch("scripts.common.lint_utils.get_flake8_ignore_codes", return_value="E501")
    @patch("scripts.common.lint_utils.get_flake8_max_line_length", return_value=100)
    def test_skip_black(self, mock_len, mock_codes, mock_which, mock_cmd):
        result = run_lint_check("/tmp/repo", check_black=False)
        assert result.black_ok is True  # Not checked = ok

    @patch("scripts.common.lint_utils.run_cmd_sync", return_value=(True, ""))
    @patch("shutil.which", return_value="/usr/bin/flake8")
    @patch("scripts.common.lint_utils.get_flake8_ignore_codes", return_value="E501")
    @patch("scripts.common.lint_utils.get_flake8_max_line_length", return_value=100)
    def test_skip_flake8(self, mock_len, mock_codes, mock_which, mock_cmd):
        result = run_lint_check("/tmp/repo", check_flake8=False)
        assert result.flake8_ok is True

    @patch("scripts.common.lint_utils.run_cmd_sync", return_value=(True, ""))
    @patch("shutil.which", return_value=None)
    @patch("scripts.common.lint_utils.get_flake8_ignore_codes", return_value="E501")
    @patch("scripts.common.lint_utils.get_flake8_max_line_length", return_value=100)
    def test_tools_not_installed(self, mock_len, mock_codes, mock_which, mock_cmd):
        # which returns None -> tools not found -> skips checks
        result = run_lint_check("/tmp/repo")
        assert result.passed is True

    @patch("scripts.common.lint_utils.run_cmd_sync", return_value=(True, ""))
    @patch("shutil.which", return_value="/usr/bin/black")
    @patch("scripts.common.lint_utils.get_flake8_ignore_codes", return_value="E501")
    @patch("scripts.common.lint_utils.get_flake8_max_line_length", return_value=100)
    def test_specific_files(self, mock_len, mock_codes, mock_which, mock_cmd):
        run_lint_check("/tmp/repo", files=["a.py", "b.py"], check_flake8=False)
        cmd_args = mock_cmd.call_args[0][0]
        assert "a.py" in cmd_args
        assert "b.py" in cmd_args

    @patch(
        "scripts.common.lint_utils.run_cmd_sync",
        return_value=(False, "timed out after 60s"),
    )
    @patch("shutil.which", return_value="/usr/bin/black")
    @patch("scripts.common.lint_utils.get_flake8_ignore_codes", return_value="E501")
    @patch("scripts.common.lint_utils.get_flake8_max_line_length", return_value=100)
    def test_black_timeout(self, mock_len, mock_codes, mock_which, mock_cmd):
        result = run_lint_check("/tmp/repo", check_flake8=False)
        assert result.black_ok is False
        assert any("timed out" in e for e in result.errors)

    @patch("scripts.common.lint_utils.run_cmd_sync")
    @patch("shutil.which", return_value="/usr/bin/flake8")
    @patch("scripts.common.lint_utils.get_flake8_ignore_codes", return_value="E501")
    @patch("scripts.common.lint_utils.get_flake8_max_line_length", return_value=100)
    def test_flake8_timeout(self, mock_len, mock_codes, mock_which, mock_cmd):
        mock_cmd.side_effect = [
            (True, ""),  # black
            (False, "Timed out waiting for output"),  # flake8
        ]
        result = run_lint_check("/tmp/repo")
        assert result.flake8_ok is False
        assert any("timed out" in e for e in result.errors)

    @patch("scripts.common.lint_utils.run_cmd_sync", return_value=(False, ""))
    @patch("shutil.which", return_value="/usr/bin/flake8")
    @patch("scripts.common.lint_utils.get_flake8_ignore_codes", return_value="E501")
    @patch("scripts.common.lint_utils.get_flake8_max_line_length", return_value=100)
    def test_flake8_fail_but_empty_output(
        self, mock_len, mock_codes, mock_which, mock_cmd
    ):
        # flake8 returns failure but no output -> treated as OK
        mock_cmd.side_effect = [
            (True, ""),  # black
            (False, ""),  # flake8 with empty output
        ]
        result = run_lint_check("/tmp/repo")
        assert result.flake8_ok is True  # Empty output = no real issues

    @patch("scripts.common.lint_utils.run_cmd_sync", return_value=(True, ""))
    @patch("shutil.which", return_value="/usr/bin/flake8")
    def test_custom_ignore_and_length(self, mock_which, mock_cmd):
        run_lint_check(
            "/tmp/repo", check_black=False, ignore_codes="W503", max_line_length=120
        )
        cmd_args = mock_cmd.call_args[0][0]
        assert "--max-line-length=120" in cmd_args
        assert "--ignore=W503" in cmd_args

    @patch("scripts.common.lint_utils.run_cmd_sync")
    @patch("shutil.which", return_value="/usr/bin/tool")
    @patch("scripts.common.lint_utils.get_flake8_ignore_codes", return_value="E501")
    @patch("scripts.common.lint_utils.get_flake8_max_line_length", return_value=100)
    def test_both_fail(self, mock_len, mock_codes, mock_which, mock_cmd):
        mock_cmd.side_effect = [
            (False, "would reformat"),  # black
            (False, "file.py:1:1: E302"),  # flake8
        ]
        result = run_lint_check("/tmp/repo")
        assert result.passed is False
        assert result.black_ok is False
        assert result.flake8_ok is False
        assert len(result.errors) == 2
        assert ";" in result.message  # errors joined with ";"


# ---------------------------------------------------------------------------
# format_lint_error
# ---------------------------------------------------------------------------


class TestFormatLintError:
    def test_passed(self):
        r = LintResult(
            passed=True, black_ok=True, flake8_ok=True, errors=[], message="ok"
        )
        assert "passed" in format_lint_error(r)

    def test_failed_with_errors(self):
        r = LintResult(
            passed=False,
            black_ok=False,
            flake8_ok=True,
            errors=["Black: needs formatting"],
            message="Black: needs formatting",
        )
        output = format_lint_error(r)
        assert "Lint errors found" in output
        assert "Black: needs formatting" in output
        assert "black . && flake8" in output

    def test_multiple_errors(self):
        r = LintResult(
            passed=False,
            black_ok=False,
            flake8_ok=False,
            errors=["Black: err", "Flake8: err"],
            message="both",
        )
        output = format_lint_error(r)
        assert "Black: err" in output
        assert "Flake8: err" in output
