"""
YAML Memory Adapter - Memory source for YAML-based storage.

This adapter exposes the YAML memory system (state, learned, knowledge)
as a memory source for the abstraction layer.

It wraps the existing memory tools functionality without duplicating code.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from services.memory_abstraction.models import AdapterResult, HealthStatus, MemoryItem, SourceFilter
from services.memory_abstraction.registry import memory_adapter
from tool_modules.common import PROJECT_ROOT

logger = logging.getLogger(__name__)

# Memory directory
MEMORY_DIR = PROJECT_ROOT / "memory"


@memory_adapter(
    name="yaml",
    display_name="Memory State",
    capabilities={"query", "search", "store"},
    intent_keywords=[
        "working on",
        "current",
        "active",
        "my issues",
        "status",
        "pattern",
        "fix",
        "learned",
        "known",
        "solution",
        "knowledge",
        "project",
        "architecture",
    ],
    priority=70,  # High priority for state/context queries
    latency_class="fast",  # Local file reads
)
class YamlMemoryAdapter:
    """
    Adapter for YAML-based memory storage.

    Provides access to:
    - state/current_work: Active issues, branches, MRs
    - state/environments: Environment health
    - state/shared_context: Cross-session context
    - learned/patterns: Error patterns and fixes
    - learned/tool_fixes: Known tool fixes
    - knowledge/personas/*: Persona-specific knowledge
    """

    # Memory sections and their search keywords
    SECTIONS = {
        "state/current_work": {
            "keywords": ["working on", "current", "active", "my issues", "branch", "mr"],
            "type": "state",
        },
        "state/environments": {
            "keywords": ["environment", "stage", "prod", "health", "deployment"],
            "type": "state",
        },
        "state/shared_context": {
            "keywords": ["context", "focus", "preferences", "team"],
            "type": "state",
        },
        "learned/patterns": {
            "keywords": ["pattern", "error", "fix", "solution", "known issue"],
            "type": "learned",
        },
        "learned/tool_fixes": {
            "keywords": ["tool", "fix", "workaround", "bug"],
            "type": "learned",
        },
        "learned/runbooks": {
            "keywords": ["runbook", "procedure", "steps", "how to"],
            "type": "learned",
        },
    }

    async def query(
        self,
        question: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """
        Query YAML memory for relevant information.

        Args:
            question: Natural language question
            filter: Optional filter with key for specific file

        Returns:
            AdapterResult with matching items
        """
        items = []

        # If specific key requested, read that file
        if filter and filter.key:
            item = await self._read_key(filter.key, question)
            if item:
                items.append(item)
        else:
            # Search relevant sections based on question
            relevant_sections = self._find_relevant_sections(question)

            for section_key in relevant_sections:
                item = await self._read_key(section_key, question)
                if item:
                    items.append(item)

        return AdapterResult(
            source="yaml",
            found=len(items) > 0,
            items=items,
        )

    async def search(
        self,
        query: str,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """Search is the same as query for YAML."""
        return await self.query(query, filter)

    async def store(
        self,
        key: str,
        value: Any,
        filter: SourceFilter | None = None,
    ) -> AdapterResult:
        """
        Store data in YAML memory.

        Args:
            key: Memory key (e.g., "state/current_work")
            value: Data to store (dict or string)
            filter: Optional filter (unused)

        Returns:
            AdapterResult indicating success
        """
        try:
            path = self._resolve_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)

            # If value is a dict, merge with existing
            if isinstance(value, dict):
                existing = {}
                if path.exists():
                    with open(path) as f:
                        existing = yaml.safe_load(f) or {}

                # Merge (value overwrites existing)
                existing.update(value)
                value = existing

            # Write YAML
            with open(path, "w") as f:
                yaml.safe_dump(value, f, default_flow_style=False)

            return AdapterResult(
                source="yaml",
                found=True,
                items=[
                    MemoryItem(
                        source="yaml",
                        type="state",
                        relevance=1.0,
                        summary=f"Stored to {key}",
                        content=f"Successfully wrote to {path}",
                        metadata={"key": key, "path": str(path)},
                    )
                ],
            )

        except Exception as e:
            logger.error(f"Failed to store {key}: {e}")
            return AdapterResult(
                source="yaml",
                found=False,
                items=[],
                error=str(e),
            )

    async def health_check(self) -> HealthStatus:
        """Check if YAML memory is accessible."""
        try:
            # Check if memory directory exists and is readable
            if not MEMORY_DIR.exists():
                return HealthStatus(
                    healthy=False,
                    error=f"Memory directory not found: {MEMORY_DIR}",
                )

            # Count files
            yaml_files = list(MEMORY_DIR.rglob("*.yaml"))

            return HealthStatus(
                healthy=True,
                details={
                    "directory": str(MEMORY_DIR),
                    "file_count": len(yaml_files),
                },
            )

        except Exception as e:
            return HealthStatus(healthy=False, error=str(e))

    async def _read_key(self, key: str, question: str) -> MemoryItem | None:
        """Read a specific memory key and create a MemoryItem."""
        try:
            path = self._resolve_path(key)

            if not path.exists():
                return None

            with open(path) as f:
                data = yaml.safe_load(f)

            if not data:
                return None

            # Calculate relevance based on question match
            relevance = self._calculate_relevance(data, question)

            # Format content based on type
            content = self._format_content(key, data)
            summary = self._generate_summary(key, data)

            return MemoryItem(
                source="yaml",
                type=self.SECTIONS.get(key, {}).get("type", "state"),
                relevance=relevance,
                summary=summary,
                content=content,
                metadata={
                    "key": key,
                    "path": str(path),
                    "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                },
            )

        except Exception as e:
            logger.warning(f"Failed to read {key}: {e}")
            return None

    def _resolve_path(self, key: str) -> Path:
        """Resolve a memory key to file path."""
        if not key.endswith(".yaml"):
            key = f"{key}.yaml"
        return MEMORY_DIR / key

    def _find_relevant_sections(self, question: str) -> list[str]:
        """Find memory sections relevant to the question."""
        question_lower = question.lower()
        relevant = []

        for section_key, section_info in self.SECTIONS.items():
            for keyword in section_info["keywords"]:
                if keyword in question_lower:
                    relevant.append(section_key)
                    break

        # Default to current_work if nothing matches
        if not relevant:
            relevant = ["state/current_work"]

        return relevant[:3]  # Max 3 sections

    def _calculate_relevance(self, data: dict, question: str) -> float:
        """Calculate relevance score based on content match."""
        if not data or not question:
            return 0.5

        question_lower = question.lower()
        data_str = str(data).lower()

        # Count keyword matches
        words = question_lower.split()
        matches = sum(1 for word in words if word in data_str)

        # Normalize to 0.5-1.0 range
        relevance = 0.5 + (matches / max(len(words), 1)) * 0.5
        return min(relevance, 1.0)

    def _format_content(self, key: str, data: dict) -> str:
        """Format data content for display."""
        if "current_work" in key:
            return self._format_current_work(data)
        elif "patterns" in key:
            return self._format_patterns(data)
        elif "environments" in key:
            return self._format_environments(data)
        else:
            # Generic YAML dump
            return yaml.safe_dump(data, default_flow_style=False)[:500]

    def _format_current_work(self, data: dict) -> str:
        """Format current work data."""
        lines = []

        # Active issues
        issues = data.get("active_issues", [])
        if issues:
            lines.append("**Active Issues:**")
            for issue in issues[:5]:
                key = issue.get("key", "unknown")
                status = issue.get("status", "unknown")
                branch = issue.get("branch", "")
                lines.append(f"- {key}: {status}" + (f" (branch: {branch})" if branch else ""))

        # Current branch
        branch = data.get("current_branch")
        if branch:
            lines.append(f"\n**Current Branch:** {branch}")

        # Notes
        notes = data.get("notes")
        if notes:
            lines.append(f"\n**Notes:** {notes[:200]}")

        return "\n".join(lines) if lines else "No active work"

    def _format_patterns(self, data: dict) -> str:
        """Format learned patterns data."""
        lines = []

        patterns = data.get("error_patterns", []) or data.get("patterns", [])
        if patterns:
            lines.append("**Known Patterns:**")
            for pattern in patterns[:5]:
                p = pattern.get("pattern", "")
                fix = pattern.get("fix", pattern.get("meaning", ""))
                if p:
                    lines.append(f"- {p}: {fix}")

        return "\n".join(lines) if lines else "No patterns"

    def _format_environments(self, data: dict) -> str:
        """Format environment data."""
        lines = []

        for env_name, env_data in data.items():
            if isinstance(env_data, dict):
                status = env_data.get("status", "unknown")
                lines.append(f"**{env_name}:** {status}")

        return "\n".join(lines) if lines else "No environment data"

    def _generate_summary(self, key: str, data: dict) -> str:
        """Generate a one-line summary for the item."""
        if "current_work" in key:
            issues = data.get("active_issues", [])
            count = len(issues)
            return f"Current work: {count} active issue(s)"
        elif "patterns" in key:
            patterns = data.get("error_patterns", []) or data.get("patterns", [])
            return f"Learned patterns: {len(patterns)} entries"
        elif "environments" in key:
            return f"Environment status: {', '.join(data.keys())}"
        else:
            return f"Memory: {key}"
