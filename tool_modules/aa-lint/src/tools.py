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

    @registry.tool()
    async def lint_yaml(
        repo: str,
        path_filter: str = ".",
    ) -> list[TextContent]:
        """
        Validate YAML files using yamllint.

        Args:
            repo: Repository name or path
            path_filter: Specific path to lint (default: all)

        Returns:
            YAML validation results.
        """
        try:
            repo_path = resolve_path(repo)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {e}")]

        target = os.path.join(repo_path, path_filter)

        success, stdout, stderr = await run_cmd_full(["yamllint", "-f", "parsable", target], cwd=repo_path)

        lines = [f"## YAML Linting: `{repo}`", ""]

        if success:
            lines.append("✅ All YAML files valid")
        else:
            output = stdout or stderr
            if output:
                issues = output.strip().split("\n")
                lines.append(f"❌ Found {len(issues)} issues:")
                lines.append("```")
                for issue in issues[:30]:
                    lines.append(issue)
                if len(issues) > 30:
                    lines.append(f"... and {len(issues) - 30} more")
                lines.append("```")
            else:
                lines.append("❌ Validation failed")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def lint_dockerfile(
        repo: str,
        dockerfile: str = "Dockerfile",
    ) -> list[TextContent]:
        """
        Lint Dockerfile using hadolint.

        Args:
            repo: Repository name or path
            dockerfile: Path to Dockerfile (relative to repo)

        Returns:
            Dockerfile best practice suggestions.
        """
        try:
            repo_path = resolve_path(repo)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {e}")]

        dockerfile_path = os.path.join(repo_path, dockerfile)

        if not os.path.exists(dockerfile_path):
            return [TextContent(type="text", text=f"❌ Dockerfile not found: {dockerfile}")]

        success, stdout, stderr = await run_cmd_full(["hadolint", dockerfile_path])

        lines = [f"## Dockerfile Linting: `{dockerfile}`", ""]

        if success and not stdout.strip():
            lines.append("✅ No issues found")
        else:
            output = stdout or stderr
            if output:
                lines.append("⚠️ Suggestions:")
                lines.append("```")
                lines.append(truncate_output(output, max_length=2000))
                lines.append("```")
            else:
                lines.append("❌ Linting failed")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def test_run(
        repo: str,
        test_path: str = "",
        verbose: bool = False,
        coverage: bool = False,
    ) -> list[TextContent]:
        """
        Run tests (pytest or npm test).

        Args:
            repo: Repository name or path
            test_path: Specific test file/directory (optional)
            verbose: Show verbose output
            coverage: Run with coverage

        Returns:
            Test results summary.
        """
        try:
            repo_path = resolve_path(repo)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {e}")]

        lines = [f"## Running Tests: `{repo}`", ""]

        if (Path(repo_path) / "pyproject.toml").exists() or (Path(repo_path) / "pytest.ini").exists():
            cmd = ["pytest"]
            if test_path:
                cmd.append(test_path)
            if verbose:
                cmd.append("-v")
            if coverage:
                cmd.extend(["--cov=.", "--cov-report=term-missing"])

            lines.append("**Framework:** pytest")
            lines.append(f"**Command:** `{' '.join(cmd)}`")
            lines.append("")

        elif (Path(repo_path) / "package.json").exists():
            cmd = ["npm", "test"]
            if test_path:
                cmd.extend(["--", test_path])

            lines.append("**Framework:** npm test")
            lines.append("")
        else:
            return [TextContent(type="text", text="⚠️ No test framework detected (pytest/npm)")]

        success, stdout, stderr = await run_cmd_full(cmd, cwd=repo_path, timeout=600)

        output = stdout + "\n" + stderr

        if "pytest" in cmd[0]:
            for line in output.split("\n"):
                if "passed" in line or "failed" in line or "error" in line:
                    if "=" in line:
                        lines.append(f"**Result:** {line.strip()}")
                        break

        if success:
            lines.append("\n✅ Tests passed!")
        else:
            lines.append("\n❌ Tests failed")

        lines.append("\n### Output")
        lines.append("```")
        lines.append(truncate_output(output, max_length=5000, mode="tail"))
        lines.append("```")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def test_coverage(repo: str) -> list[TextContent]:
        """
        Get test coverage report.

        Args:
            repo: Repository name or path

        Returns:
            Coverage percentage and uncovered files.
        """
        try:
            repo_path = resolve_path(repo)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {e}")]

        lines = [f"## Test Coverage: `{repo}`", ""]

        success, stdout, stderr = await run_cmd_full(
            ["pytest", "--cov=.", "--cov-report=term-missing", "-q"],
            cwd=repo_path,
            timeout=600,
        )

        output = stdout + "\n" + stderr

        in_coverage = False
        coverage_lines = []
        for line in output.split("\n"):
            if "TOTAL" in line or "coverage:" in line.lower():
                coverage_lines.append(line)
            elif "Name" in line and "Stmts" in line:
                in_coverage = True
                coverage_lines.append(line)
            elif in_coverage and line.strip():
                if line.startswith("---") or line.startswith("==="):
                    in_coverage = False
                else:
                    coverage_lines.append(line)

        if coverage_lines:
            lines.append("```")
            lines.extend(coverage_lines[:30])
            lines.append("```")
        else:
            lines.append("⚠️ Could not parse coverage output")
            lines.append(f"```\n{truncate_output(output, max_length=2000)}\n```")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def security_scan(repo: str) -> list[TextContent]:
        """
        Run security scan (bandit for Python, npm audit for Node).

        Args:
            repo: Repository name or path

        Returns:
            Security vulnerabilities found.
        """
        try:
            repo_path = resolve_path(repo)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {e}")]

        lines = [f"## Security Scan: `{repo}`", ""]

        if (Path(repo_path) / "pyproject.toml").exists() or (Path(repo_path) / "requirements.txt").exists():
            lines.append("### Bandit (Python)")
            success, stdout, stderr = await run_cmd_full(["bandit", "-r", ".", "-f", "txt", "-ll"], cwd=repo_path)

            if success:
                lines.append("✅ No issues found")
            else:
                output = stdout or stderr
                lines.append(f"```\n{truncate_output(output, max_length=2000)}\n```")

        if (Path(repo_path) / "package.json").exists():
            lines.append("\n### npm audit")
            success, stdout, stderr = await run_cmd_full(["npm", "audit", "--json"], cwd=repo_path)

            try:
                audit = json.loads(stdout)
                vulns = audit.get("metadata", {}).get("vulnerabilities", {})
                total = sum(vulns.values())

                if total == 0:
                    lines.append("✅ No vulnerabilities found")
                else:
                    lines.append(f"⚠️ Found {total} vulnerabilities:")
                    for severity, count in vulns.items():
                        if count > 0:
                            lines.append(f"  - {severity}: {count}")
            except (json.JSONDecodeError, ValueError, TypeError, KeyError):
                lines.append(f"```\n{truncate_output(stdout, max_length=1500)}\n```")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def precommit_run(
        repo: str,
        all_files: bool = False,
    ) -> list[TextContent]:
        """
        Run pre-commit hooks.

        Args:
            repo: Repository name or path
            all_files: Run on all files (not just staged)

        Returns:
            Pre-commit hook results.
        """
        try:
            repo_path = resolve_path(repo)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {e}")]

        if not (Path(repo_path) / ".pre-commit-config.yaml").exists():
            return [TextContent(type="text", text="⚠️ No .pre-commit-config.yaml found")]

        cmd = ["pre-commit", "run"]
        if all_files:
            cmd.append("--all-files")

        success, stdout, stderr = await run_cmd_full(cmd, cwd=repo_path, timeout=300)

        lines = [f"## Pre-commit: `{repo}`", ""]

        output = stdout or stderr

        for line in output.split("\n"):
            if "Passed" in line:
                lines.append(f"✅ {line}")
            elif "Failed" in line:
                lines.append(f"❌ {line}")
            elif "Skipped" in line:
                lines.append(f"⏭️ {line}")
            elif line.strip() and not line.startswith(" "):
                lines.append(line)

        if success:
            lines.append("\n## ✅ All hooks passed!")
        else:
            lines.append("\n## ❌ Some hooks failed")

        return [TextContent(type="text", text="\n".join(lines))]

    logger.info(f"Registered {registry.count} lint tools")
    return registry.count
