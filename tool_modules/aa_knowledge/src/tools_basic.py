"""Knowledge Tools - Project-specific expertise loading and learning.

This module delegates to the canonical implementations in
tool_modules.aa_workflow.src.knowledge_tools to avoid code duplication.

Provides tools for:
- knowledge_load: Load project knowledge for a persona
- knowledge_scan: AI scans project, generates initial knowledge
- knowledge_update: Update specific section of knowledge
- knowledge_query: Query specific knowledge sections
- knowledge_learn: Record a learning from completing a task
- knowledge_list: List all available knowledge files
"""

from typing import TYPE_CHECKING

from mcp.types import TextContent

from server.tool_registry import ToolRegistry

# Import all shared helpers and implementations from the canonical module.
# These are re-exported so that external code (e.g. skills/bootstrap_all_knowledge.yaml)
# can still import them from this module.
from tool_modules.aa_workflow.src.knowledge_tools import (
    DEFAULT_KNOWLEDGE_SCHEMA,
    KNOWLEDGE_DIR,
    _check_for_significant_changes,
    _detect_project_from_path,
    _ensure_knowledge_dir,
    _format_knowledge_summary,
    _generate_initial_knowledge,
    _get_current_persona,
    _get_knowledge_path,
    _knowledge_learn_impl,
    _knowledge_list_impl,
    _knowledge_load_impl,
    _knowledge_query_impl,
    _knowledge_scan_impl,
    _knowledge_update_impl,
    _load_knowledge,
    _save_knowledge,
    _scan_project_structure,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

# Re-export for backwards compatibility with existing imports
__all__ = [
    "KNOWLEDGE_DIR",
    "DEFAULT_KNOWLEDGE_SCHEMA",
    "_get_knowledge_path",
    "_ensure_knowledge_dir",
    "_load_knowledge",
    "_save_knowledge",
    "_check_for_significant_changes",
    "_detect_project_from_path",
    "_get_current_persona",
    "_scan_project_structure",
    "_generate_initial_knowledge",
    "_format_knowledge_summary",
    "_knowledge_load_impl",
    "_knowledge_scan_impl",
    "_knowledge_update_impl",
    "_knowledge_query_impl",
    "_knowledge_learn_impl",
    "_knowledge_list_impl",
    "register_tools",
]


# ==================== TOOL REGISTRATION ====================


def register_tools(server: "FastMCP") -> int:
    """Register knowledge tools with the MCP server."""
    registry = ToolRegistry(server)

    @registry.tool()
    async def knowledge_load(
        project: str = "",
        persona: str = "",
        auto_scan: bool = True,
    ) -> list[TextContent]:
        """
        Load project knowledge for a persona into context.

        Loads project-specific expertise including architecture, patterns,
        gotchas, and learnings. If knowledge doesn't exist and auto_scan
        is True, will scan the project and generate initial knowledge.

        Args:
            project: Project name (from config.json). Auto-detected from cwd if empty.
            persona: Persona name. Uses current persona if empty.
            auto_scan: If True, auto-scan project when knowledge doesn't exist.

        Returns:
            Project knowledge formatted for context injection.
        """
        return await _knowledge_load_impl(project, persona, auto_scan)

    @registry.tool()
    async def knowledge_scan(
        project: str = "",
        persona: str = "",
        force: bool = False,
    ) -> list[TextContent]:
        """
        Scan a project and generate/update knowledge.

        Analyzes project structure, config files, dependencies, and README
        to build initial knowledge. Merges with existing knowledge unless
        force=True.

        Args:
            project: Project name (from config.json). Auto-detected from cwd if empty.
            persona: Persona name. Uses current persona if empty.
            force: If True, overwrite existing knowledge. Otherwise merge.

        Returns:
            Summary of scanned knowledge.
        """
        return await _knowledge_scan_impl(project, persona, force)

    @registry.tool()
    async def knowledge_update(
        project: str,
        persona: str,
        section: str,
        content: str,
        append: bool = True,
    ) -> list[TextContent]:
        """
        Update a specific section of project knowledge.

        Use this to manually add or update knowledge sections like
        architecture details, patterns, or gotchas.

        Args:
            project: Project name
            persona: Persona name
            section: Section to update (e.g., "gotchas", "patterns.coding", "architecture.overview")
            content: Content to add (YAML string for complex data, plain string for simple)
            append: If True, append to lists. If False, replace.

        Returns:
            Confirmation of update.
        """
        return await _knowledge_update_impl(project, persona, section, content, append)

    @registry.tool()
    async def knowledge_query(
        project: str = "",
        persona: str = "",
        section: str = "",
    ) -> list[TextContent]:
        """
        Query specific knowledge sections.

        Retrieve specific parts of project knowledge without loading
        the full context.

        Args:
            project: Project name. Auto-detected if empty.
            persona: Persona name. Uses current if empty.
            section: Dot-separated path to query (e.g., "architecture.key_modules", "gotchas")
                     Empty returns full knowledge summary.

        Returns:
            Requested knowledge section.
        """
        return await _knowledge_query_impl(project, persona, section)

    @registry.tool()
    async def knowledge_learn(
        learning: str,
        task: str = "",
        section: str = "learned_from_tasks",
        project: str = "",
        persona: str = "",
    ) -> list[TextContent]:
        """
        Record a learning from completing a task.

        This is the primary way knowledge grows over time. Call this after
        completing tasks, fixing bugs, or discovering patterns.

        Args:
            learning: What was learned (the insight)
            task: Task/issue that led to this learning (e.g., "AAP-12345")
            section: Where to store (default: learned_from_tasks, can be "gotchas", "patterns.coding", etc.)
            project: Project name. Auto-detected if empty.
            persona: Persona name. Uses current if empty.

        Returns:
            Confirmation of learning recorded.
        """
        return await _knowledge_learn_impl(learning, task, section, project, persona)

    @registry.tool()
    async def knowledge_list() -> list[TextContent]:
        """
        List all available knowledge files.

        Shows all knowledge organized by persona and project, with
        confidence levels and last update dates.

        Returns:
            List of knowledge files organized by persona and project.
        """
        return await _knowledge_list_impl()

    return registry.count
