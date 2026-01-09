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

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.types import TextContent

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

# Setup project path for server imports
from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import load_config, resolve_repo_path, run_cmd_full, truncate_output
from tool_modules.common import PROJECT_ROOT  # noqa: F401 - side effect: adds to sys.path

logger = logging.getLogger(__name__)


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


def register_tools(server: "FastMCP") -> int:
    """Register lint/test tools with the MCP server."""
    registry = ToolRegistry(server)

    # Load repository paths from config
    config = load_config()
    repos_data = config.get("repositories", {})
    if isinstance(repos_data, dict):
        repo_paths = {name: info.get("path", "") for name, info in repos_data.items() if info.get("path")}
    else:
        repo_paths = {}

    def resolve_path(repo: str) -> str:
        return _resolve_repo_path_local(repo, repo_paths)

    @auto_heal()

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
        try:
            path = resolve_path(repo)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {e}")]

        lines = [f"## Python Linting: `{repo}`", ""]
        all_passed = True

        # 1. Black
        lines.append("### Black (formatting)")
        black_args = ["black", "."]
        if not fix:
            black_args.append("--check")

        success, stdout, stderr = await run_cmd_full(black_args, cwd=path)
        if success:
            lines.append("✅ Passed")
        else:
            lines.append("❌ Issues found")
            all_passed = False
            output = stderr or stdout
            if output:
                lines.append(f"```\n{truncate_output(output, max_length=1500)}\n```")
        lines.append("")

        # 2. isort
        lines.append("### isort (imports)")
        isort_args = ["isort", "."]
        if not fix:
            isort_args.append("--check-only")

        success, stdout, stderr = await run_cmd_full(isort_args, cwd=path)
        if success:
            lines.append("✅ Passed")
        else:
            lines.append("❌ Issues found")
            all_passed = False
            output = stderr or stdout
            if output:
                lines.append(f"```\n{truncate_output(output, max_length=1500)}\n```")
        lines.append("")

        # 3. Flake8
        lines.append("### Flake8 (style)")
        success, stdout, stderr = await run_cmd_full(["flake8", ".", "--max-line-length=120"], cwd=path)
        if success:
            lines.append("✅ Passed")
        else:
            lines.append("❌ Issues found")
            all_passed = False
            if stdout:
                issue_count = len(stdout.strip().split("\n"))
                lines.append(f"Found {issue_count} issues:")
                lines.append(f"```\n{truncate_output(stdout, max_length=2000)}\n```")
        lines.append("")

        # 4. mypy (optional)
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

        # Summary
        lines.append("")
        if all_passed:
            lines.append("## ✅ All Python checks passed!")
        else:
            lines.append("## ❌ Some checks failed")
            if not fix:
                lines.append("*Run with fix=True to auto-fix formatting issues*")

        return [TextContent(type="text", text="\n".join(lines))]
