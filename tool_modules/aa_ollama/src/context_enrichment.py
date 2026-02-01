"""Context enrichment for inference - loads memory, patterns, and semantic knowledge.

This module provides the context that gets injected alongside filtered tools:
- Current memory state (active issues, branches, repos)
- Learned patterns (error fixes, gotchas)
- Semantic knowledge (relevant code from vector search)
- Environment status (VPN, cluster auth)

This module is workspace-aware: when ctx is provided, it uses the workspace's
project for loading project-specific memory and semantic search.
"""

import logging
from pathlib import Path
from typing import Optional

import yaml
from fastmcp import Context

logger = logging.getLogger(__name__)

# Memory paths
MEMORY_DIR = Path.home() / ".aa-workflow" / "memory"
PROJECT_MEMORY_DIR = Path(__file__).parents[4] / "memory"


def _get_memory_dir() -> Path:
    """Get the memory directory, preferring user home."""
    if MEMORY_DIR.exists():
        return MEMORY_DIR
    if PROJECT_MEMORY_DIR.exists():
        return PROJECT_MEMORY_DIR
    return MEMORY_DIR


def _get_project_memory_path(project: str) -> Path:
    """Get the memory path for a specific project.

    Args:
        project: Project name

    Returns:
        Path to project's current_work.yaml
    """
    memory_dir = _get_memory_dir()
    return memory_dir / "state" / "projects" / project / "current_work.yaml"


def load_memory_state(project: Optional[str] = None) -> dict:
    """Load current work state from memory.

    Args:
        project: Project name for project-specific memory. If None, uses global.

    Returns:
        Dict with active_issues, current_branch, current_repo, notes
    """
    result = {
        "active_issues": [],
        "current_branch": None,
        "current_repo": None,
        "notes": None,
        "open_mrs": [],
        "follow_ups": [],
    }

    # Determine which memory file to load
    if project:
        current_work_path = _get_project_memory_path(project)
        result["current_repo"] = project  # Set repo from project
    else:
        memory_dir = _get_memory_dir()
        current_work_path = memory_dir / "state" / "current_work.yaml"

    if not current_work_path.exists():
        return result

    try:
        with open(current_work_path) as f:
            data = yaml.safe_load(f) or {}

        result["active_issues"] = data.get("active_issues", [])[:5]  # Limit to 5
        result["current_branch"] = data.get("current_branch") or data.get("branch")
        if not result["current_repo"]:
            result["current_repo"] = data.get("repo") or data.get("current_repo")
        result["notes"] = data.get("notes", "")[:300] if data.get("notes") else None
        result["open_mrs"] = data.get("open_mrs", [])[:3]
        result["follow_ups"] = data.get("follow_ups", [])[:3]

    except Exception as e:
        logger.warning(f"Failed to load current_work.yaml: {e}")

    return result


async def load_memory_state_async(ctx: "Context" = None) -> dict:
    """Load current work state from memory (workspace-aware).

    Args:
        ctx: MCP Context for workspace identification

    Returns:
        Dict with active_issues, current_branch, current_repo, notes
    """
    project = None

    if ctx:
        try:
            from server.workspace_utils import get_workspace_project

            project = await get_workspace_project(ctx)
        except Exception as e:
            logger.warning(f"Failed to get workspace project: {e}")

    return load_memory_state(project)


def load_environment_status() -> dict:
    """Load environment status (VPN, cluster auth, Ollama instances).

    Returns:
        Dict with vpn_connected, kubeconfigs, ollama_instances
    """
    result = {
        "vpn_connected": False,
        "kubeconfigs": {
            "stage": False,
            "prod": False,
            "ephemeral": False,
            "konflux": False,
        },
        "ollama_instances": [],
    }

    # Check VPN (look for marker file or tun interface)
    vpn_marker = Path.home() / ".aa-workflow" / ".vpn_connected"
    result["vpn_connected"] = vpn_marker.exists()

    # Check kubeconfigs exist
    kube_dir = Path.home() / ".kube"
    kubeconfig_map = {
        "stage": "config.s",
        "prod": "config.p",
        "ephemeral": "config.e",
        "konflux": "config.k",
    }
    for env, filename in kubeconfig_map.items():
        result["kubeconfigs"][env] = (kube_dir / filename).exists()

    # Load Ollama instances from config
    config_path = Path(__file__).parents[4] / "config.json"
    if config_path.exists():
        try:
            import json

            with open(config_path) as f:
                config = json.load(f)
            for name, inst in config.get("ollama_instances", {}).items():
                result["ollama_instances"].append(
                    {
                        "name": name,
                        "url": inst.get("url", ""),
                        "device": inst.get("device", "unknown"),
                    }
                )
        except Exception as e:
            logger.warning(f"Failed to load ollama instances: {e}")

    return result


def load_learned_patterns(
    tool_names: Optional[list[str]] = None,
    skill_name: Optional[str] = None,
    limit: int = 5,
) -> list[dict]:
    """Load learned error patterns relevant to the context.

    Args:
        tool_names: List of tool names to filter patterns for
        skill_name: Skill name to filter patterns for
        limit: Maximum patterns to return

    Returns:
        List of pattern dicts with pattern, root_cause, fix
    """
    memory_dir = _get_memory_dir()
    patterns_path = memory_dir / "learned" / "patterns.yaml"

    if not patterns_path.exists():
        return []

    try:
        with open(patterns_path) as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"Failed to load patterns.yaml: {e}")
        return []

    all_patterns = data.get("error_patterns", [])
    if not all_patterns:
        return []

    # Filter by relevance
    relevant = []
    tool_set = set(tool_names or [])

    for pattern in all_patterns:
        if not isinstance(pattern, dict):
            continue

        # Check if pattern is relevant to any of our tools
        pattern_tool = pattern.get("tool_name", "")
        if tool_set and pattern_tool and pattern_tool in tool_set:
            relevant.append(pattern)
            continue

        # Check if pattern mentions the skill
        if skill_name:
            pattern_text = str(pattern.get("pattern", "")).lower()
            if skill_name.lower() in pattern_text:
                relevant.append(pattern)
                continue

        # Include general patterns (no specific tool)
        if not pattern_tool:
            relevant.append(pattern)

    # Sort by recency if available, otherwise just take first N
    relevant = relevant[:limit]

    return [
        {
            "pattern": p.get("pattern", p.get("error_pattern", "")),
            "root_cause": p.get("root_cause", ""),
            "fix": p.get("fix", p.get("fix_description", "")),
            "tool": p.get("tool_name", ""),
        }
        for p in relevant
    ]


def load_session_log(limit: int = 5) -> list[dict]:
    """Load recent session log entries.

    Args:
        limit: Maximum entries to return

    Returns:
        List of log entry dicts with time, action, details
    """
    from datetime import date

    memory_dir = _get_memory_dir()
    today = date.today().isoformat()
    log_path = memory_dir / "sessions" / f"{today}.yaml"

    if not log_path.exists():
        return []

    try:
        with open(log_path) as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"Failed to load session log: {e}")
        return []

    entries = data.get("entries", data.get("actions", []))
    if not entries:
        return []

    # Return most recent entries
    return entries[-limit:]


def load_persona_prompt(persona_name: str) -> str:
    """Load persona system prompt.

    Args:
        persona_name: Name of the persona

    Returns:
        System prompt text (truncated)
    """
    personas_dir = Path(__file__).parents[4] / "personas"

    # Try YAML first, then MD
    yaml_path = personas_dir / f"{persona_name}.yaml"
    md_path = personas_dir / f"{persona_name}.md"

    if yaml_path.exists():
        try:
            with open(yaml_path) as f:
                data = yaml.safe_load(f) or {}
            return data.get("system_prompt", data.get("description", ""))[:500]
        except Exception:
            pass

    if md_path.exists():
        try:
            return md_path.read_text()[:500]
        except Exception:
            pass

    return ""


def run_semantic_search(
    message: str,
    project: Optional[str] = None,
    limit: int = 3,
) -> list[dict]:
    """Run semantic search on the message to find relevant code.

    Args:
        message: User message to search for
        project: Project to search in (auto-detected from memory if not provided)
        limit: Maximum results to return

    Returns:
        List of code snippets with file, lines, content, relevance
    """
    # Try to import code search tools
    try:
        import sys

        tool_modules_dir = Path(__file__).parents[2]
        if str(tool_modules_dir) not in sys.path:
            sys.path.insert(0, str(tool_modules_dir))

        from aa_code_search.src.tools_basic import _search_code
    except ImportError as e:
        logger.warning(f"Code search not available: {e}")
        return []

    # Auto-detect project from memory state if not provided
    if not project:
        memory_state = load_memory_state()
        project = memory_state.get("current_repo")

    if not project:
        # Default to backend
        project = "automation-analytics-backend"

    try:
        result = _search_code(query=message, project=project, limit=limit)

        # Parse the result (it returns a formatted string)
        if isinstance(result, str):
            # Extract relevant info from the formatted output
            snippets = []
            current_snippet = {}

            for line in result.split("\n"):
                if line.startswith("📄 "):
                    if current_snippet:
                        snippets.append(current_snippet)
                    current_snippet = {"file": line[3:].strip(), "content": "", "relevance": 0}
                elif line.startswith("   Lines "):
                    current_snippet["lines"] = line.strip()
                elif line.startswith("   Relevance: "):
                    try:
                        current_snippet["relevance"] = float(line.split(":")[1].strip().rstrip("%")) / 100
                    except (ValueError, IndexError):
                        pass
                elif current_snippet and line.startswith("   "):
                    current_snippet["content"] += line[3:] + "\n"

            if current_snippet:
                snippets.append(current_snippet)

            return snippets[:limit]

        return []

    except Exception as e:
        logger.warning(f"Semantic search failed: {e}")
        return []


async def run_semantic_search_async(
    message: str,
    ctx: "Context" = None,
    project: Optional[str] = None,
    limit: int = 3,
) -> list[dict]:
    """Run semantic search on the message (workspace-aware).

    Args:
        message: User message to search for
        ctx: MCP Context for workspace identification
        project: Project to search in (uses workspace project if not provided)
        limit: Maximum results to return

    Returns:
        List of code snippets with file, lines, content, relevance
    """
    # Get project from workspace if not provided
    if not project and ctx:
        try:
            from server.workspace_utils import get_workspace_project

            project = await get_workspace_project(ctx)
        except Exception as e:
            logger.warning(f"Failed to get workspace project: {e}")

    return run_semantic_search(message, project, limit)


def enrich_context(
    persona: str,
    detected_skill: Optional[str] = None,
    tool_names: Optional[list[str]] = None,
    message: Optional[str] = None,
    include_semantic_search: bool = True,
    project: Optional[str] = None,
) -> dict:
    """Load all context enrichment data.

    Args:
        persona: Active persona name
        detected_skill: Detected skill name (optional)
        tool_names: List of filtered tool names (optional)
        message: User message for semantic search (optional)
        include_semantic_search: Whether to run semantic search
        project: Project name for workspace-specific context (optional)

    Returns:
        Dict with all context sections
    """
    result = {
        "memory_state": load_memory_state(project),
        "environment": load_environment_status(),
        "learned_patterns": load_learned_patterns(tool_names, detected_skill),
        "session_log": load_session_log(),
        "persona_prompt": load_persona_prompt(persona),
        "semantic_knowledge": [],
    }

    # Run semantic search if message provided
    if include_semantic_search and message:
        result["semantic_knowledge"] = run_semantic_search(message, project)

    return result


async def enrich_context_async(
    persona: str,
    ctx: "Context" = None,
    detected_skill: Optional[str] = None,
    tool_names: Optional[list[str]] = None,
    message: Optional[str] = None,
    include_semantic_search: bool = True,
) -> dict:
    """Load all context enrichment data (workspace-aware).

    Args:
        persona: Active persona name
        ctx: MCP Context for workspace identification
        detected_skill: Detected skill name (optional)
        tool_names: List of filtered tool names (optional)
        message: User message for semantic search (optional)
        include_semantic_search: Whether to run semantic search

    Returns:
        Dict with all context sections
    """
    # Get project from workspace
    project = None
    if ctx:
        try:
            from server.workspace_utils import get_workspace_project

            project = await get_workspace_project(ctx)
        except Exception as e:
            logger.warning(f"Failed to get workspace project: {e}")

    result = {
        "memory_state": load_memory_state(project),
        "environment": load_environment_status(),
        "learned_patterns": load_learned_patterns(tool_names, detected_skill),
        "session_log": load_session_log(),
        "persona_prompt": load_persona_prompt(persona),
        "semantic_knowledge": [],
    }

    # Run semantic search if message provided
    if include_semantic_search and message:
        result["semantic_knowledge"] = run_semantic_search(message, project)

    return result
