"""Dynamic skill tool discovery from YAML files.

Parses skill YAML files to extract tool dependencies at runtime,
enabling Layer 3 of the tool filtering system.
"""

import logging
import re
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


class SkillToolDiscovery:
    """Dynamically discover tools required by a skill from YAML."""

    def __init__(self, skills_dir: Optional[Path] = None):
        """Initialize skill discovery.

        Args:
            skills_dir: Path to skills directory (defaults to project root/skills)
        """
        if skills_dir is None:
            # Path: tool_modules/aa_ollama/src/skill_discovery.py
            # parents[0] = tool_modules/aa_ollama/src
            # parents[1] = tool_modules/aa_ollama
            # parents[2] = tool_modules
            # parents[3] = project root (redhat-ai-workflow)
            skills_dir = Path(__file__).parents[3] / "skills"
        self.skills_dir = skills_dir
        self._cache: dict[str, set[str]] = {}

    def discover_tools(self, skill_name: str) -> set[str]:
        """Parse skill YAML and extract all tool references.

        Looks for:
        - step.tool: direct tool calls
        - step.tools: list of tools
        - step.parallel[].tool: parallel tool calls
        - step.then[]/else[]: conditional branches
        - step.loop.do[]: loop body
        - step.compute: flag for NPU (may have dynamic calls)

        Args:
            skill_name: Name of the skill (without .yaml extension)

        Returns:
            Set of tool names used by the skill
        """
        if skill_name in self._cache:
            return self._cache[skill_name]

        skill_path = self.skills_dir / f"{skill_name}.yaml"
        if not skill_path.exists():
            logger.warning(f"Skill not found: {skill_path}")
            return set()

        try:
            with open(skill_path) as f:
                skill = yaml.safe_load(f)
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse skill {skill_name}: {e}")
            return set()

        tools = set()

        # Extract from steps
        for step in skill.get("steps", []):
            self._extract_tools_from_step(step, tools)

        self._cache[skill_name] = tools
        logger.info(f"Discovered {len(tools)} tools for skill {skill_name}: {sorted(tools)}")
        return tools

    def _extract_tools_from_step(self, step: dict, tools: set[str]) -> None:
        """Recursively extract tools from a step.

        Args:
            step: Step dictionary from skill YAML
            tools: Set to add discovered tools to
        """
        # Direct tool reference
        if "tool" in step:
            tools.add(step["tool"])

        # List of tools
        if "tools" in step:
            tools.update(step["tools"])

        # Parallel tools
        if "parallel" in step:
            for parallel_step in step["parallel"]:
                if isinstance(parallel_step, dict):
                    self._extract_tools_from_step(parallel_step, tools)

        # Conditional branches
        for branch in ["then", "else"]:
            if branch in step:
                branch_steps = step[branch]
                if isinstance(branch_steps, list):
                    for sub_step in branch_steps:
                        if isinstance(sub_step, dict):
                            self._extract_tools_from_step(sub_step, tools)

        # Loop iterations
        if "loop" in step:
            loop_body = step.get("do", [])
            if isinstance(loop_body, list):
                for sub_step in loop_body:
                    if isinstance(sub_step, dict):
                        self._extract_tools_from_step(sub_step, tools)

        # Compute blocks may call tools dynamically - flag for NPU
        if "compute" in step:
            tools.add("__has_compute_block__")

    def has_dynamic_tools(self, skill_name: str) -> bool:
        """Check if skill has compute blocks that may call tools dynamically.

        Args:
            skill_name: Name of the skill

        Returns:
            True if skill has compute blocks
        """
        tools = self.discover_tools(skill_name)
        return "__has_compute_block__" in tools

    def list_skills(self) -> list[str]:
        """List all available skills.

        Returns:
            List of skill names
        """
        if not self.skills_dir.exists():
            return []
        return [p.stem for p in self.skills_dir.glob("*.yaml")]

    def get_skill_metadata(self, skill_name: str) -> dict:
        """Get metadata about a skill for context display.

        Args:
            skill_name: Name of the skill

        Returns:
            Dict with description, inputs, memory_ops, and other metadata
        """
        skill_path = self.skills_dir / f"{skill_name}.yaml"
        if not skill_path.exists():
            return {}

        try:
            with open(skill_path) as f:
                skill = yaml.safe_load(f)
        except yaml.YAMLError:
            return {}

        # Extract input definitions
        inputs = []
        for inp in skill.get("inputs", []):
            if isinstance(inp, dict):
                inputs.append(
                    {
                        "name": inp.get("name", ""),
                        "description": inp.get("description", ""),
                        "required": inp.get("required", False),
                        "default": inp.get("default"),
                    }
                )

        # Extract memory operations from steps
        memory_ops = self._extract_memory_operations(skill.get("steps", []))

        return {
            "name": skill_name,
            "description": skill.get("description", ""),
            "inputs": inputs,
            "step_count": len(skill.get("steps", [])),
            "memory_ops": memory_ops,
        }

    def _extract_memory_operations(self, steps: list) -> dict:
        """Extract memory read/write operations from skill steps.

        Looks for:
        - memory_* tool calls (memory_read, memory_write, memory_session_log, etc.)
        - memory.read_memory() / memory.write_memory() in compute blocks
        - check_known_issues / learn_tool_fix calls

        Args:
            steps: List of step dictionaries

        Returns:
            Dict with 'reads' and 'writes' lists
        """
        reads = []
        writes = []

        # Memory tool patterns
        memory_read_tools = {"memory_read", "memory_query", "check_known_issues", "knowledge_query"}
        memory_write_tools = {"memory_write", "memory_update", "memory_append", "memory_session_log", "learn_tool_fix"}

        # Patterns for compute blocks
        read_patterns = [
            re.compile(r'memory\.read_memory\(["\']([^"\']+)["\']'),
            re.compile(r"memory\.check_known_issues"),
            re.compile(r'read_memory\(["\']([^"\']+)["\']'),
        ]
        write_patterns = [
            re.compile(r'memory\.write_memory\(["\']([^"\']+)["\']'),
            re.compile(r'memory\.append_to_list\(["\']([^"\']+)["\']'),
            re.compile(r"memory_session_log"),
            re.compile(r'write_memory\(["\']([^"\']+)["\']'),
        ]

        for step in steps:
            if not isinstance(step, dict):
                continue

            # Check tool calls
            tool = step.get("tool", "")
            if tool in memory_read_tools:
                key = step.get("args", {}).get("key", "")
                reads.append({"tool": tool, "key": key, "step": step.get("name", "")})
            elif tool in memory_write_tools:
                key = step.get("args", {}).get("key", "")
                writes.append({"tool": tool, "key": key, "step": step.get("name", "")})

            # Check compute blocks for memory operations
            compute = step.get("compute", "")
            if compute:
                for pattern in read_patterns:
                    matches = pattern.findall(compute)
                    for match in matches:
                        if isinstance(match, str) and match:
                            reads.append({"source": "compute", "key": match, "step": step.get("name", "")})
                        elif pattern.pattern == r"memory\.check_known_issues":
                            reads.append({"source": "compute", "key": "learned/patterns", "step": step.get("name", "")})

                for pattern in write_patterns:
                    matches = pattern.findall(compute)
                    for match in matches:
                        if isinstance(match, str) and match:
                            writes.append({"source": "compute", "key": match, "step": step.get("name", "")})
                        elif "memory_session_log" in pattern.pattern:
                            writes.append({"source": "compute", "key": "sessions/today", "step": step.get("name", "")})

            # Recursively check nested structures
            for branch in ["then", "else", "parallel"]:
                if branch in step and isinstance(step[branch], list):
                    nested = self._extract_memory_operations(step[branch])
                    reads.extend(nested.get("reads", []))
                    writes.extend(nested.get("writes", []))

        # Deduplicate
        seen_reads = set()
        unique_reads = []
        for r in reads:
            key = (r.get("tool", r.get("source", "")), r.get("key", ""))
            if key not in seen_reads:
                seen_reads.add(key)
                unique_reads.append(r)

        seen_writes = set()
        unique_writes = []
        for w in writes:
            key = (w.get("tool", w.get("source", "")), w.get("key", ""))
            if key not in seen_writes:
                seen_writes.add(key)
                unique_writes.append(w)

        return {"reads": unique_reads, "writes": unique_writes}

    def clear_cache(self) -> None:
        """Clear the discovery cache."""
        self._cache.clear()


# ==================== Fast Skill Detection ====================

# Skill patterns for fast detection (no NPU needed)
SKILL_PATTERNS: dict[str, list[re.Pattern]] = {
    "test_mr_ephemeral": [
        re.compile(r"deploy.*mr|test.*mr|spin.*up.*mr", re.I),
        re.compile(r"ephemeral.*mr\s*\d+", re.I),
        re.compile(r"deploy.*ephemeral", re.I),
        re.compile(r"test.*in.*ephemeral", re.I),
    ],
    "review_pr": [
        re.compile(r"review.*mr|review.*!\d+", re.I),
        re.compile(r"check.*mr.*review", re.I),
        re.compile(r"look.*at.*mr", re.I),
    ],
    "start_work": [
        re.compile(r"start.*work.*aap-\d+", re.I),
        re.compile(r"begin.*aap-\d+", re.I),
        re.compile(r"pick.*up.*aap-\d+", re.I),
    ],
    "investigate_slack_alert": [
        re.compile(r"investigate.*alert", re.I),
        re.compile(r"look.*into.*alert", re.I),
        re.compile(r"whats.*firing", re.I),
        re.compile(r"what.*alerts", re.I),
    ],
    "create_mr": [
        re.compile(r"create.*mr|open.*mr", re.I),
        re.compile(r"push.*and.*mr", re.I),
        re.compile(r"submit.*mr", re.I),
    ],
    "check_pipeline": [
        re.compile(r"check.*pipeline|pipeline.*status", re.I),
        re.compile(r"ci.*status", re.I),
        re.compile(r"build.*status", re.I),
    ],
}


def detect_skill(message: str) -> str | None:
    """Fast skill detection using regex patterns.

    This is Layer 3's fast path - no NPU needed for common skill patterns.

    Args:
        message: User message to analyze

    Returns:
        Detected skill name, or None if no skill matched
    """
    for skill_name, patterns in SKILL_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(message):
                logger.debug(f"Fast skill detection: {skill_name} matched '{message[:50]}...'")
                return skill_name
    return None


def add_skill_pattern(skill_name: str, pattern: str) -> None:
    """Add a new pattern for skill detection.

    Args:
        skill_name: Name of the skill
        pattern: Regex pattern string
    """
    if skill_name not in SKILL_PATTERNS:
        SKILL_PATTERNS[skill_name] = []
    SKILL_PATTERNS[skill_name].append(re.compile(pattern, re.I))


# Singleton discovery instance
_discovery: Optional[SkillToolDiscovery] = None


def get_skill_discovery() -> SkillToolDiscovery:
    """Get or create the skill discovery instance."""
    global _discovery
    if _discovery is None:
        _discovery = SkillToolDiscovery()
    return _discovery


def discover_skill_tools(skill_name: str) -> set[str]:
    """Convenience function to discover tools for a skill."""
    return get_skill_discovery().discover_tools(skill_name)


