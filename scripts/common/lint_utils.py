"""Shared linting utilities.

Provides consistent lint checking across tools and skills.
"""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from scripts.common.config_loader import get_flake8_ignore_codes, get_flake8_max_line_length


@dataclass
class LintResult:
    """Result of a lint check."""

    passed: bool
    black_ok: bool
    flake8_ok: bool
    errors: list[str]
    message: str

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "black_ok": self.black_ok,
            "flake8_ok": self.flake8_ok,
            "errors": self.errors,
            "message": self.message,
        }


def run_lint_check(
    repo_path: str | Path,
    check_black: bool = True,
    check_flake8: bool = True,
    files: Optional[list[str]] = None,
    ignore_codes: Optional[str] = None,
    max_line_length: Optional[int] = None,
) -> LintResult:
    """
    Run lint checks on a repository.

    Args:
        repo_path: Path to the repository
        check_black: Run black formatting check
        check_flake8: Run flake8 linting
        files: Specific files to check (default: all)
        ignore_codes: Flake8 codes to ignore (default: from config)
        max_line_length: Max line length for flake8 (default: from config)

    Returns:
        LintResult with pass/fail status and error details.
    """
    # Get defaults from config
    if ignore_codes is None:
        ignore_codes = get_flake8_ignore_codes()
    if max_line_length is None:
        max_line_length = get_flake8_max_line_length()

    path = Path(repo_path)
    errors = []
    black_ok = True
    flake8_ok = True

    # Check black
    if check_black and shutil.which("black"):
        cmd = ["black", "--check"]
        if files:
            cmd.extend(files)
        else:
            cmd.append(".")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(path),
                timeout=60,
            )
            if result.returncode != 0:
                black_ok = False
                errors.append("Black: Code needs formatting (run 'black .')")
        except subprocess.TimeoutExpired:
            errors.append("Black: Check timed out")
            black_ok = False
        except Exception as e:
            errors.append(f"Black: Error - {e}")
            black_ok = False

    # Check flake8
    if check_flake8 and shutil.which("flake8"):
        cmd = [
            "flake8",
            f"--max-line-length={max_line_length}",
            f"--ignore={ignore_codes}",
        ]
        if files:
            cmd.extend(files)
        else:
            cmd.append(".")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(path),
                timeout=60,
            )
            if result.returncode != 0 and result.stdout.strip():
                flake8_ok = False
                issue_lines = [line for line in result.stdout.split("\n") if line.strip()]
                issue_count = len(issue_lines)
                errors.append(f"Flake8: {issue_count} issue(s) found")
        except subprocess.TimeoutExpired:
            errors.append("Flake8: Check timed out")
            flake8_ok = False
        except Exception as e:
            errors.append(f"Flake8: Error - {e}")
            flake8_ok = False

    passed = black_ok and flake8_ok
    message = "Lint passed" if passed else "; ".join(errors)

    return LintResult(
        passed=passed,
        black_ok=black_ok,
        flake8_ok=flake8_ok,
        errors=errors,
        message=message,
    )


def format_lint_error(result: LintResult) -> str:
    """Format lint errors for display."""
    if result.passed:
        return "✅ Lint checks passed"

    lines = ["❌ Lint errors found. Fix before proceeding:\n"]
    for error in result.errors:
        lines.append(f"  - {error}")
    lines.append("\nRun 'black . && flake8' to check locally.")
    return "\n".join(lines)
