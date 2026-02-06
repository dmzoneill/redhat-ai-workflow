"""
External Tools Wrapper for Slop Bot.

Wraps external code analysis tools and normalizes their output to a standard finding format.

Tier 1 - Dedicated Slop Detectors:
- ai-slop-detector: Python slop detection (placeholders, buzzwords, hallucinated deps)
- karpeslop: TypeScript/JavaScript slop detection (any-type abuse, vibe coding)

Tier 2 - Traditional Static Analysis:
- jscpd: Code duplication (150+ languages)
- radon: Cyclomatic complexity (Python)
- vulture: Dead code detection (Python)
- mypy: Type checking (Python)
- bandit: Security scanning (Python)
- ruff: Fast linting (Python)

Usage:
    from services.slop.external_tools import ExternalTools

    tools = ExternalTools()

    # Check which tools are available
    available = await tools.check_availability()

    # Run a specific tool
    findings = await tools.run_tool("radon", "/path/to/code")

    # Get tools for a file type
    applicable = tools.get_tools_for_file("server/main.py")
"""

import asyncio
import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Finding:
    """A normalized code quality finding."""

    id: str
    category: str
    severity: str  # critical, high, medium, low
    file: str
    line: int
    description: str
    suggestion: str = ""
    tool: str = ""
    raw_output: dict = field(default_factory=dict)
    detected_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "category": self.category,
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "description": self.description,
            "suggestion": self.suggestion,
            "tool": self.tool,
            "raw_output": self.raw_output,
            "detected_at": self.detected_at.isoformat(),
        }


class ExternalTools:
    """Wrapper for external code analysis tools."""

    # Tool configurations
    TOOLS = {
        # Tier 1: Dedicated Slop Detectors
        "slop-detector": {
            "cmd": ["slop-detector", "--json", "--project"],
            "check_cmd": ["slop-detector", "--version"],
            "install": "pip install ai-slop-detector",
            "detects": ["placeholder_code", "buzzword_inflation", "docstring_inflation", "hallucinated_deps"],
            "tier": 1,
            "languages": ["python"],
            "timeout": 300,
        },
        "karpeslop": {
            "cmd": ["npx", "karpeslop@latest", "--quiet"],
            "check_cmd": ["npx", "karpeslop@latest", "--version"],
            "install": "npx karpeslop@latest",
            "detects": ["hallucinated_imports", "any_type_abuse", "vibe_coding"],
            "tier": 1,
            "languages": ["typescript", "javascript", "tsx", "jsx"],
            "timeout": 60,
        },
        # Tier 2: Traditional Static Analysis
        "jscpd": {
            "cmd": ["npx", "jscpd", "--reporters", "json", "--output", "/dev/stdout"],
            "check_cmd": ["npx", "jscpd", "--version"],
            "install": "npm install -g jscpd",
            "detects": ["code_duplication"],
            "tier": 2,
            "languages": None,  # Supports 150+ languages
            "timeout": 300,
        },
        "radon": {
            "cmd": ["radon", "cc", "-j"],
            "check_cmd": ["radon", "--version"],
            "install": "pip install radon",
            "detects": ["complexity"],
            "tier": 2,
            "languages": ["python"],
            "timeout": 60,
        },
        "vulture": {
            "cmd": ["vulture", "--min-confidence", "80"],
            "check_cmd": ["vulture", "--version"],
            "install": "pip install vulture",
            "detects": ["dead_code"],
            "tier": 2,
            "languages": ["python"],
            "timeout": 300,
        },
        "mypy": {
            "cmd": ["mypy", "--no-error-summary", "--show-column-numbers"],
            "check_cmd": ["mypy", "--version"],
            "install": "pip install mypy",
            "detects": ["type_issues"],
            "tier": 2,
            "languages": ["python"],
            "timeout": 300,
        },
        "bandit": {
            "cmd": ["bandit", "-f", "json", "-r"],
            "check_cmd": ["bandit", "--version"],
            "install": "pip install bandit",
            "detects": ["security"],
            "tier": 2,
            "languages": ["python"],
            "timeout": 60,
        },
        "ruff": {
            "cmd": ["ruff", "check", "--output-format", "json"],
            "check_cmd": ["ruff", "--version"],
            "install": "pip install ruff",
            "detects": ["style_issues"],
            "tier": 2,
            "languages": ["python"],
            "timeout": 30,
        },
    }

    # File extension to language mapping
    EXTENSION_MAP = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".js": "javascript",
        ".jsx": "jsx",
    }

    def __init__(self):
        """Initialize the external tools wrapper."""
        self._availability_cache: dict[str, bool] = {}
        self._cache_time: Optional[datetime] = None
        self._cache_ttl_seconds = 300  # 5 minutes
        self._finding_counter = 0
        # Get venv bin path for tools installed in the virtual environment
        self._venv_bin = Path(__file__).parent.parent.parent / ".venv" / "bin"

    def _generate_finding_id(self, tool: str) -> str:
        """Generate a unique finding ID."""
        self._finding_counter += 1
        return f"slop-{tool}-{self._finding_counter:04d}"

    async def check_availability(self, force_refresh: bool = False) -> dict[str, bool]:
        """
        Check which tools are installed and available.

        Args:
            force_refresh: Force refresh of cached availability

        Returns:
            Dict mapping tool name to availability status
        """
        # Check cache
        if not force_refresh and self._cache_time:
            age = (datetime.now() - self._cache_time).total_seconds()
            if age < self._cache_ttl_seconds:
                return self._availability_cache.copy()

        results = {}

        async def check_tool(name: str) -> tuple[str, bool]:
            config = self.TOOLS[name]
            check_cmd = list(config["check_cmd"])  # Make a copy

            # Check if base command exists (in PATH or venv)
            base_cmd = check_cmd[0]
            if base_cmd != "npx":
                # First check system PATH
                if not shutil.which(base_cmd):
                    # Then check venv bin directory
                    venv_path = self._venv_bin / base_cmd
                    if venv_path.exists():
                        check_cmd[0] = str(venv_path)
                    else:
                        logger.debug(f"{name}: command '{base_cmd}' not found")
                        return name, False

            try:
                proc = await asyncio.create_subprocess_exec(
                    *check_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, _ = await asyncio.wait_for(proc.communicate(), timeout=15)

                available = proc.returncode == 0
                if available:
                    logger.debug(f"{name}: available")
                else:
                    logger.debug(f"{name}: check failed (exit code {proc.returncode})")
                return name, available

            except asyncio.TimeoutError:
                logger.debug(f"{name}: check timed out")
                return name, False
            except Exception as e:
                logger.debug(f"{name}: check error - {e}")
                return name, False

        # Run checks in parallel
        tasks = [check_tool(name) for name in self.TOOLS]
        check_results = await asyncio.gather(*tasks)

        for name, available in check_results:
            results[name] = available

        # Update cache
        self._availability_cache = results
        self._cache_time = datetime.now()

        return results

    def get_tools_for_file(self, file_path: str) -> list[str]:
        """
        Get applicable tools based on file extension.

        Args:
            file_path: Path to the file

        Returns:
            List of tool names that can analyze this file
        """
        ext = Path(file_path).suffix.lower()
        language = self.EXTENSION_MAP.get(ext)

        applicable = []
        for name, config in self.TOOLS.items():
            supported_languages = config.get("languages")
            if supported_languages is None:
                # Tool supports all languages (like jscpd)
                applicable.append(name)
            elif language and language in supported_languages:
                applicable.append(name)

        return applicable

    def get_tools_for_category(self, category: str) -> list[str]:
        """
        Get tools that detect a specific category of issues.

        Args:
            category: Issue category (e.g., "complexity", "dead_code")

        Returns:
            List of tool names that detect this category
        """
        return [name for name, config in self.TOOLS.items() if category in config.get("detects", [])]

    async def run_tool(self, tool: str, path: str) -> list[Finding]:
        """
        Run a tool and parse its output into findings.

        Args:
            tool: Tool name
            path: Path to analyze (file or directory)

        Returns:
            List of Finding objects
        """
        if tool not in self.TOOLS:
            logger.error(f"Unknown tool: {tool}")
            return []

        # Check if tool is available before trying to run it
        availability = await self.check_availability()
        if not availability.get(tool, False):
            logger.debug(f"Skipping {tool} - not available")
            return []

        config = self.TOOLS[tool]
        cmd = list(config["cmd"]) + [path]  # Make a copy
        timeout = config.get("timeout", 60)

        # Resolve command path (check venv if not in system PATH)
        base_cmd = cmd[0]
        if base_cmd != "npx" and not shutil.which(base_cmd):
            venv_path = self._venv_bin / base_cmd
            if venv_path.exists():
                cmd[0] = str(venv_path)

        logger.info(f"Running {tool} on {path}")

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )

            output = stdout.decode()

            # Parse based on tool
            parser = getattr(self, f"_parse_{tool.replace('-', '_')}", None)
            if parser:
                return parser(output, path)
            else:
                logger.warning(f"No parser for {tool}, returning raw output")
                return []

        except asyncio.TimeoutError:
            # Kill the subprocess on timeout to prevent zombie processes
            if proc is not None:
                proc.kill()
                await proc.wait()
            logger.error(f"{tool} timed out after {timeout}s")
            return []
        except Exception as e:
            # Ensure cleanup on any error
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.wait()
            logger.exception(f"{tool} error: {e}")
            return []

    def _parse_radon(self, output: str, path: str) -> list[Finding]:
        """Parse radon cyclomatic complexity output."""
        findings = []

        try:
            data = json.loads(output)

            for file_path, functions in data.items():
                for func in functions:
                    complexity = func.get("complexity", 0)
                    rank = func.get("rank", "A")
                    name = func.get("name", "unknown")
                    lineno = func.get("lineno", 0)

                    # Map rank to severity
                    severity_map = {
                        "A": None,  # Good, don't report
                        "B": None,  # Good, don't report
                        "C": "medium",
                        "D": "high",
                        "E": "critical",
                        "F": "critical",
                    }

                    severity = severity_map.get(rank)
                    if not severity:
                        continue

                    findings.append(
                        Finding(
                            id=self._generate_finding_id("radon"),
                            category="complexity",
                            severity=severity,
                            file=file_path,
                            line=lineno,
                            description=f"Function '{name}' has complexity grade {rank} (CC={complexity})",
                            suggestion="Consider breaking into smaller functions",
                            tool="radon",
                            raw_output=func,
                        )
                    )

        except json.JSONDecodeError:
            logger.warning("Could not parse radon JSON output")

        return findings

    def _parse_vulture(self, output: str, path: str) -> list[Finding]:
        """Parse vulture dead code output."""
        findings = []

        # Vulture output format: file.py:10: unused function 'foo' (90% confidence)
        pattern = r"(.+?):(\d+): (.+?) \((\d+)% confidence\)"

        for line in output.strip().split("\n"):
            if not line:
                continue

            match = re.match(pattern, line)
            if match:
                file_path, lineno, description, confidence = match.groups()

                # Map confidence to severity
                conf = int(confidence)
                if conf >= 90:
                    severity = "high"
                elif conf >= 70:
                    severity = "medium"
                else:
                    severity = "low"

                findings.append(
                    Finding(
                        id=self._generate_finding_id("vulture"),
                        category="dead_code",
                        severity=severity,
                        file=file_path,
                        line=int(lineno),
                        description=f"{description} ({confidence}% confidence)",
                        suggestion="Remove if no longer needed",
                        tool="vulture",
                        raw_output={"line": line},
                    )
                )

        return findings

    def _parse_bandit(self, output: str, path: str) -> list[Finding]:
        """Parse bandit security scan output."""
        findings = []

        try:
            data = json.loads(output)

            for result in data.get("results", []):
                severity = result.get("issue_severity", "LOW").lower()
                result.get("issue_confidence", "LOW")

                # Map bandit severity
                severity_map = {
                    "high": "critical",
                    "medium": "high",
                    "low": "medium",
                }
                mapped_severity = severity_map.get(severity, "low")

                findings.append(
                    Finding(
                        id=self._generate_finding_id("bandit"),
                        category="security",
                        severity=mapped_severity,
                        file=result.get("filename", ""),
                        line=result.get("line_number", 0),
                        description=f"{result.get('issue_text', '')} [{result.get('test_id', '')}]",
                        suggestion=result.get("more_info", ""),
                        tool="bandit",
                        raw_output=result,
                    )
                )

        except json.JSONDecodeError:
            logger.warning("Could not parse bandit JSON output")

        return findings

    def _parse_ruff(self, output: str, path: str) -> list[Finding]:
        """Parse ruff linter output."""
        findings = []

        try:
            data = json.loads(output)

            for issue in data:
                # Map ruff codes to severity
                code = issue.get("code", "")
                if code.startswith("E"):  # Errors
                    severity = "high"
                elif code.startswith("W"):  # Warnings
                    severity = "medium"
                elif code.startswith("F"):  # PyFlakes
                    severity = "high"
                else:
                    severity = "low"

                location = issue.get("location", {})

                findings.append(
                    Finding(
                        id=self._generate_finding_id("ruff"),
                        category="style_issues",
                        severity=severity,
                        file=issue.get("filename", ""),
                        line=location.get("row", 0),
                        description=f"[{code}] {issue.get('message', '')}",
                        suggestion=issue.get("fix", {}).get("message", "") if issue.get("fix") else "",
                        tool="ruff",
                        raw_output=issue,
                    )
                )

        except json.JSONDecodeError:
            logger.warning("Could not parse ruff JSON output")

        return findings

    def _parse_mypy(self, output: str, path: str) -> list[Finding]:
        """Parse mypy type checking output."""
        findings = []

        # mypy output format: file.py:10:5: error: Message [error-code]
        pattern = r"(.+?):(\d+):(\d+): (error|warning|note): (.+)"

        for line in output.strip().split("\n"):
            if not line:
                continue

            match = re.match(pattern, line)
            if match:
                file_path, lineno, col, level, message = match.groups()

                # Map level to severity
                severity_map = {
                    "error": "high",
                    "warning": "medium",
                    "note": "low",
                }
                severity = severity_map.get(level, "low")

                findings.append(
                    Finding(
                        id=self._generate_finding_id("mypy"),
                        category="type_issues",
                        severity=severity,
                        file=file_path,
                        line=int(lineno),
                        description=message,
                        suggestion="Add type annotations or fix type mismatch",
                        tool="mypy",
                        raw_output={"line": line},
                    )
                )

        return findings

    def _parse_jscpd(self, output: str, path: str) -> list[Finding]:
        """Parse jscpd code duplication output."""
        findings = []

        try:
            data = json.loads(output)

            for dup in data.get("duplicates", []):
                first = dup.get("firstFile", {})
                second = dup.get("secondFile", {})
                lines = dup.get("lines", 0)

                # Severity based on duplication size
                if lines >= 50:
                    severity = "critical"
                elif lines >= 20:
                    severity = "high"
                elif lines >= 10:
                    severity = "medium"
                else:
                    severity = "low"

                findings.append(
                    Finding(
                        id=self._generate_finding_id("jscpd"),
                        category="code_duplication",
                        severity=severity,
                        file=first.get("name", ""),
                        line=first.get("start", 0),
                        description=(
                            f"Duplicated code block ({lines} lines) also in"
                            f" {second.get('name', '')}:{second.get('start', 0)}"
                        ),
                        suggestion="Extract to shared function or module",
                        tool="jscpd",
                        raw_output=dup,
                    )
                )

        except json.JSONDecodeError:
            logger.warning("Could not parse jscpd JSON output")

        return findings

    def _parse_slop_detector(self, output: str, path: str) -> list[Finding]:
        """Parse ai-slop-detector output."""
        findings = []

        try:
            data = json.loads(output)

            for issue in data.get("issues", []):
                findings.append(
                    Finding(
                        id=self._generate_finding_id("slop-detector"),
                        category=issue.get("category", "ai_slop"),
                        severity=issue.get("severity", "medium"),
                        file=issue.get("file", ""),
                        line=issue.get("line", 0),
                        description=issue.get("description", ""),
                        suggestion=issue.get("suggestion", ""),
                        tool="slop-detector",
                        raw_output=issue,
                    )
                )

        except json.JSONDecodeError:
            logger.warning("Could not parse slop-detector JSON output")

        return findings

    def _parse_karpeslop(self, output: str, path: str) -> list[Finding]:
        """Parse karpeslop output."""
        findings = []

        # karpeslop outputs a report file, try to parse it
        try:
            # Look for JSON in output
            if "{" in output:
                json_start = output.index("{")
                json_text = output[json_start:]
                data = json.loads(json_text)

                for issue in data.get("issues", []):
                    findings.append(
                        Finding(
                            id=self._generate_finding_id("karpeslop"),
                            category=issue.get("pattern", "ai_slop"),
                            severity=issue.get("severity", "medium"),
                            file=issue.get("file", ""),
                            line=issue.get("line", 0),
                            description=issue.get("message", ""),
                            suggestion=issue.get("fix", ""),
                            tool="karpeslop",
                            raw_output=issue,
                        )
                    )

        except (json.JSONDecodeError, ValueError):
            logger.warning("Could not parse karpeslop output")

        return findings

    async def run_all_applicable(self, path: str) -> list[Finding]:
        """
        Run all applicable and available tools on a path.

        Args:
            path: Path to analyze

        Returns:
            Combined list of findings from all tools
        """
        # Get applicable tools for this path
        applicable = self.get_tools_for_file(path)

        # Check availability
        availability = await self.check_availability()

        # Filter to available tools
        tools_to_run = [t for t in applicable if availability.get(t)]

        if not tools_to_run:
            logger.warning(f"No tools available for {path}")
            return []

        # Run tools in parallel
        async def run_and_collect(tool: str) -> list[Finding]:
            return await self.run_tool(tool, path)

        tasks = [run_and_collect(tool) for tool in tools_to_run]
        results = await asyncio.gather(*tasks)

        # Flatten results
        all_findings = []
        for findings in results:
            all_findings.extend(findings)

        return all_findings
