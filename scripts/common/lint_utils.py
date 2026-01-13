"""Shared linting utilities.

Provides consistent lint checking across tools and skills.
"""

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Add project root to path for server imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.config_loader import get_flake8_ignore_codes, get_flake8_max_line_length  # noqa: E402
from server.utils import run_cmd_sync  # noqa: E402


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

    # Check black - doesn't need shell env
    if check_black and shutil.which("black"):
        cmd = ["black", "--check"]
        if files:
            cmd.extend(files)
        else:
            cmd.append(".")

        success, output = run_cmd_sync(cmd, cwd=str(path), timeout=60, use_shell=False)
        if not success:
            if "timed out" in output.lower():
                errors.append("Black: Check timed out")
            else:
                errors.append("Black: Code needs formatting (run 'black .')")
            black_ok = False

    # Check flake8 - doesn't need shell env
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

        success, output = run_cmd_sync(cmd, cwd=str(path), timeout=60, use_shell=False)
        if not success and output.strip():
            if "timed out" in output.lower():
                errors.append("Flake8: Check timed out")
            else:
                issue_lines = [line for line in output.split("\n") if line.strip()]
                issue_count = len(issue_lines)
                errors.append(f"Flake8: {issue_count} issue(s) found")
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
