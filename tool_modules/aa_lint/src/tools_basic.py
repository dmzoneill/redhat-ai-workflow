"""Lint Tools - Code quality and testing tools.

Provides tools for:
- lint_python: Run Python linters (black, flake8, isort)
- lint_yaml: Validate YAML files
- lint_dockerfile: Lint Dockerfiles
- test_run: Run tests (pytest/npm)
- test_coverage: Get coverage report
- security_scan: Run security scans
- precommit_run: Run pre-commit hooks
"""

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.types import TextContent

if TYPE_CHECKING:
    from fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization


# Setup project path for server imports
from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import load_config, resolve_repo_path, run_cmd_full, truncate_output

logger = logging.getLogger(__name__)


def _get_repo_paths() -> dict:
    """Get repository paths from config."""
    config = load_config()
    repos_data = config.get("repositories", {})
    if isinstance(repos_data, dict):
        return {
            name: info.get("path", "")
            for name, info in repos_data.items()
            if info.get("path")
        }
    return {}


def _resolve_repo_path_local(repo: str, repo_paths: dict) -> str:
    """Resolve repository name to absolute path."""
    if os.path.isabs(repo):
        return repo
    if repo in repo_paths:
        return os.path.expanduser(repo_paths[repo])
    if repo == ".":
        return os.getcwd()
    path = resolve_repo_path(repo)
    if os.path.isdir(path):
        return path
    raise ValueError(f"Repository not found: {repo}")


async def _run_black(path: str, fix: bool, lines: list[str]) -> bool:
    """Run Black formatter and append results to lines."""
    lines.append("### Black (formatting)")
    black_args = ["black", "."]
    if not fix:
        black_args.append("--check")

    success, stdout, stderr = await run_cmd_full(black_args, cwd=path)
    if success:
        lines.append("✅ Passed")
    else:
        lines.append("❌ Issues found")
        output = stderr or stdout
        if output:
            lines.append(f"```\n{truncate_output(output, max_length=1500)}\n```")
    lines.append("")
    return success


async def _run_isort(path: str, fix: bool, lines: list[str]) -> bool:
    """Run isort and append results to lines."""
    lines.append("### isort (imports)")
    isort_args = ["isort", "."]
    if not fix:
        isort_args.append("--check-only")

    success, stdout, stderr = await run_cmd_full(isort_args, cwd=path)
    if success:
        lines.append("✅ Passed")
    else:
        lines.append("❌ Issues found")
        output = stderr or stdout
        if output:
            lines.append(f"```\n{truncate_output(output, max_length=1500)}\n```")
    lines.append("")
    return success


async def _run_flake8(path: str, lines: list[str]) -> bool:
    """Run Flake8 and append results to lines."""
    lines.append("### Flake8 (style)")
    success, stdout, stderr = await run_cmd_full(
        ["flake8", ".", "--max-line-length=120"], cwd=path
    )
    if success:
        lines.append("✅ Passed")
    else:
        lines.append("❌ Issues found")
        if stdout:
            issue_count = len(stdout.strip().split("\n"))
            lines.append(f"Found {issue_count} issues:")
            lines.append(f"```\n{truncate_output(stdout, max_length=2000)}\n```")
    lines.append("")
    return success


async def _run_mypy(path: str, lines: list[str]) -> None:
    """Run mypy if configured and append results to lines."""
    mypy_config = Path(path) / "mypy.ini"
    pyproject = Path(path) / "pyproject.toml"

    if mypy_config.exists() or (pyproject.exists() and "mypy" in pyproject.read_text()):
        lines.append("### mypy (types)")
        success, stdout, stderr = await run_cmd_full(["mypy", "."], cwd=path)
        if success:
            lines.append("✅ Passed")
        else:
            lines.append("⚠️ Type issues")
            if stdout:
                lines.append(f"```\n{truncate_output(stdout, max_length=1500)}\n```")


async def _lint_python_impl(
    repo: str, repo_paths: dict, fix: bool = False
) -> list[TextContent]:
    """Implementation of Python linting."""
    try:
        path = _resolve_repo_path_local(repo, repo_paths)
    except ValueError as e:
        return [TextContent(type="text", text=f"❌ {e}")]

    lines = [f"## Python Linting: `{repo}`", ""]

    # Run linters
    black_passed = await _run_black(path, fix, lines)
    isort_passed = await _run_isort(path, fix, lines)
    flake8_passed = await _run_flake8(path, lines)

    # mypy (optional)
    await _run_mypy(path, lines)

    # Summary
    all_passed = black_passed and isort_passed and flake8_passed
    lines.append("")
    if all_passed:
        lines.append("## ✅ All Python checks passed!")
    else:
        lines.append("## ❌ Some checks failed")
        if not fix:
            lines.append("*Run with fix=True to auto-fix formatting issues*")

    return [TextContent(type="text", text="\n".join(lines))]


def register_tools(server: "FastMCP") -> int:
    """Register lint/test tools with the MCP server."""
    registry = ToolRegistry(server)

    # Load repository paths from config
    config = load_config()
    repos_data = config.get("repositories", {})
    if isinstance(repos_data, dict):
        repo_paths = {
            name: info.get("path", "")
            for name, info in repos_data.items()
            if info.get("path")
        }
    else:
        repo_paths = {}

    def resolve_path(repo: str) -> str:
        return _resolve_repo_path_local(repo, repo_paths)

        # ==================== TOOLS USED IN SKILLS ====================

    @auto_heal()
    @registry.tool()
    async def lint_python(
        repo: str,
        fix: bool = False,
    ) -> list[TextContent]:
        """
        Run Python linters (black, flake8, isort).

        Args:
            repo: Repository name or path
            fix: Apply fixes automatically (black, isort)

        Returns:
            Lint results with issues found.
        """
        return await _lint_python_impl(repo, repo_paths, fix)
