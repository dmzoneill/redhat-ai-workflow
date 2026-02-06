"""Memory Tools - Persistent context storage across sessions.

NOTE: For unified memory access across multiple sources (YAML, code search,
Slack, InScope, Jira), use the new memory_query tool from memory_unified.py.
These tools remain for backward compatibility and direct YAML file access.

Provides tools for reading, writing, and managing persistent memory:
- memory_read: Read memory files
- memory_write: Write complete memory files
- memory_update: Update specific fields
- memory_append: Append to lists
- memory_query: Query with JSONPath expressions (DEPRECATED: use memory_unified.memory_query)
- memory_session_log: Log session actions
- memory_stats: Get memory health and usage statistics
- check_known_issues: Search for known fixes
- learn_tool_fix: Save solutions to memory

Memory paths can be:
- Global: "state/environments", "learned/patterns"
- Project-specific: "state/current_work" (auto-resolves to workspace project path)

Project-specific paths are stored under:
  memory/state/projects/<project>/current_work.yaml

This module is workspace-aware: project-specific paths use the workspace's
project from WorkspaceRegistry when ctx is available.

For the new unified memory interface, see:
- services/memory_abstraction/ - Core abstraction layer
- tool_modules/aa_workflow/src/memory_unified.py - Unified MCP tools
"""

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from fastmcp import Context
from mcp.types import TextContent

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry

# Support both package import and direct loading
try:
    from .constants import MEMORY_DIR
except ImportError:
    TOOL_MODULES_DIR = Path(__file__).parent.parent.parent
    PROJECT_DIR = TOOL_MODULES_DIR.parent
    MEMORY_DIR = PROJECT_DIR / "memory"

if TYPE_CHECKING:
    from fastmcp import FastMCP


# Keys that are project-specific (stored per-project)
PROJECT_SPECIFIC_KEYS = {"state/current_work"}


def _resolve_memory_path(key: str) -> Path:
    """Resolve a memory key to its actual file path (sync version).

    Handles project-specific keys by routing them to the project's directory.
    For workspace-aware resolution, use _resolve_memory_path_async() instead.

    Args:
        key: Memory key like "state/current_work" or "learned/patterns"

    Returns:
        Resolved Path to the memory file.
    """
    # Normalize key
    if not key.endswith(".yaml"):
        key_normalized = key
    else:
        key_normalized = key[:-5]  # Remove .yaml

    # Check if this is a project-specific key
    if key_normalized in PROJECT_SPECIFIC_KEYS:
        try:
            from tool_modules.aa_workflow.src.chat_context import get_project_work_state_path

            return get_project_work_state_path()
        except ImportError:
            try:
                from .chat_context import get_project_work_state_path

                return get_project_work_state_path()
            except ImportError:
                # Fallback to global path if chat_context not available
                pass

    # Global path
    if not key.endswith(".yaml"):
        key = f"{key}.yaml"
    return MEMORY_DIR / key


async def _resolve_memory_path_async(key: str, ctx: Any = None) -> Path:
    """Resolve a memory key to its actual file path (async, workspace-aware).

    Uses WorkspaceRegistry to get the workspace's project for project-specific keys.

    Args:
        key: Memory key like "state/current_work" or "learned/patterns"
        ctx: MCP Context for workspace identification (optional)

    Returns:
        Resolved Path to the memory file.
    """
    # Normalize key
    if not key.endswith(".yaml"):
        key_normalized = key
    else:
        key_normalized = key[:-5]  # Remove .yaml

    # Check if this is a project-specific key
    if key_normalized in PROJECT_SPECIFIC_KEYS:
        if ctx is not None:
            try:
                from server.workspace_utils import get_workspace_project

                project = await get_workspace_project(ctx)
                return MEMORY_DIR / "state" / "projects" / project / "current_work.yaml"
            except Exception:
                pass

        # Fall back to sync version
        try:
            from tool_modules.aa_workflow.src.chat_context import get_project_work_state_path

            return get_project_work_state_path()
        except ImportError:
            try:
                from .chat_context import get_project_work_state_path

                return get_project_work_state_path()
            except ImportError:
                pass

    # Global path
    if not key.endswith(".yaml"):
        key = f"{key}.yaml"
    return MEMORY_DIR / key


# ==================== TOOL IMPLEMENTATIONS ====================


def _check_pattern_matches(patterns: list, pattern_key: str, error_lower: str, tool_lower: str = "") -> list:
    """Check a list of patterns for matches and return formatted results."""
    matches = []
    for pattern in patterns:
        pattern_text = pattern.get("pattern", "").lower()
        if not pattern_text:
            continue

        if pattern_text in error_lower or (tool_lower and pattern_text in tool_lower):
            match_data = {"source": pattern_key, "pattern": pattern.get("pattern")}

            # Different patterns have different fields
            if pattern_key == "jira_cli_patterns":
                match_data["description"] = pattern.get("description", "")
                match_data["solution"] = pattern.get("solution", "")
            else:
                match_data["meaning"] = pattern.get("meaning", "")
                match_data["fix"] = pattern.get("fix", "")
                match_data["commands"] = pattern.get("commands", [])

            matches.append(match_data)
    return matches


def _load_patterns_from_memory() -> dict:
    """Load patterns from memory/learned/patterns.yaml."""
    patterns_file = MEMORY_DIR / "learned" / "patterns.yaml"
    if not patterns_file.exists():
        return {}

    try:
        with open(patterns_file) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _load_tool_fixes_from_memory() -> list:
    """Load tool fixes from memory/learned/tool_fixes.yaml."""
    fixes_file = MEMORY_DIR / "learned" / "tool_fixes.yaml"
    if not fixes_file.exists():
        return []

    try:
        with open(fixes_file) as f:
            fixes_data = yaml.safe_load(f) or {}
            return fixes_data.get("tool_fixes", [])
    except Exception:
        return []


def _format_known_issue_matches(matches: list) -> list[str]:
    """Format known issue matches for display."""
    lines = ["## 💡 Known Issues Found!\n"]
    for i, match in enumerate(matches[:5], 1):  # Limit to 5 matches
        source = match.get("source", "unknown")
        lines.append(f"### Match {i} (from {source})\n")

        if source == "tool_fixes":
            lines.append(f"**Tool:** `{match.get('tool_name', '?')}`")
            lines.append(f"**Pattern:** `{match.get('error_pattern', '?')}`")
            lines.append(f"**Root cause:** {match.get('root_cause', '?')}")
            lines.append(f"**Fix:** {match.get('fix_applied', '?')}")
            if match.get("date_learned"):
                lines.append(f"*Learned: {match.get('date_learned')}*")
        elif source == "jira_cli_patterns":
            lines.append(f"**Pattern:** {match.get('pattern', '?')}")
            if match.get("description"):
                lines.append(f"\n{match.get('description')}")
            if match.get("solution"):
                lines.append(f"**Solution:** {match.get('solution')}")
        else:
            lines.append(f"**Pattern:** `{match.get('pattern', '?')}`")
            lines.append(f"**Meaning:** {match.get('meaning', '?')}")
            lines.append(f"**Fix:** {match.get('fix', '?')}")
            if match.get("commands"):
                lines.append(f"**Commands:** {', '.join(match.get('commands', []))}")

        lines.append("")

    if len(matches) > 5:
        lines.append(f"... and {len(matches) - 5} more matches\n")

    return lines


def _collect_file_stats() -> tuple[dict, int]:
    """Collect file sizes and metadata from memory directory."""
    file_stats = {}
    total_size = 0
    for file in MEMORY_DIR.rglob("*.yaml"):
        relative = file.relative_to(MEMORY_DIR)
        size_bytes = file.stat().st_size
        total_size += size_bytes
        file_stats[str(relative)] = {
            "size_kb": round(size_bytes / 1024, 2),
            "modified": datetime.fromtimestamp(file.stat().st_mtime).isoformat(),
        }
    return file_stats, total_size


def _collect_autoheal_stats() -> dict:
    """Collect auto-heal statistics from tool_failures.yaml."""
    failures_file = MEMORY_DIR / "learned" / "tool_failures.yaml"
    if not failures_file.exists():
        return {}

    with open(failures_file) as f:
        failures_data = yaml.safe_load(f) or {}

    total_failures = failures_data.get("stats", {}).get("total_failures", 0)
    auto_fixed = failures_data.get("stats", {}).get("auto_fixed", 0)
    success_rate = (auto_fixed / total_failures) if total_failures > 0 else 0

    autoheal_stats = {
        "total_failures": total_failures,
        "auto_fixed": auto_fixed,
        "manual_required": failures_data.get("stats", {}).get("manual_required", 0),
        "success_rate": round(success_rate, 2),
        "recent_count": len(failures_data.get("failures", [])),
    }

    # Daily/weekly stats if available
    if "daily" in failures_data.get("stats", {}):
        autoheal_stats["daily_stats"] = failures_data["stats"]["daily"]
    if "weekly" in failures_data.get("stats", {}):
        autoheal_stats["weekly_stats"] = failures_data["stats"]["weekly"]

    return autoheal_stats


def _collect_pattern_stats() -> dict:
    """Collect pattern statistics from patterns.yaml."""
    patterns_file = MEMORY_DIR / "learned" / "patterns.yaml"
    if not patterns_file.exists():
        return {}

    with open(patterns_file) as f:
        patterns_data = yaml.safe_load(f) or {}

    pattern_categories = [
        "auth_patterns",
        "error_patterns",
        "bonfire_patterns",
        "pipeline_patterns",
        "jira_cli_patterns",
    ]

    by_category = {}
    total_patterns = 0
    for cat in pattern_categories:
        count = len(patterns_data.get(cat, []))
        by_category[cat] = count
        total_patterns += count

    return {
        "total": total_patterns,
        "by_category": by_category,
    }


def _format_memory_stats(stats: dict) -> list[str]:
    """Format memory statistics for display."""
    lines = ["## 📊 Memory System Statistics\n"]

    # Storage summary
    lines.append("### 💾 Storage Usage")
    lines.append(f"**Total:** {stats['storage']['total_kb']} KB")
    for subdir, size_kb in sorted(stats["storage"].items()):
        if subdir != "total_kb":
            lines.append(f"- {subdir}/: {size_kb} KB")
    lines.append("")

    # Auto-heal summary
    if stats.get("auto_heal"):
        ah = stats["auto_heal"]
        lines.append("### 🔧 Auto-Heal Performance")
        lines.append(f"**Success Rate:** {ah['success_rate']:.0%}")
        lines.append(f"**Total Failures:** {ah['total_failures']}")
        lines.append(f"**Auto-Fixed:** {ah['auto_fixed']}")
        lines.append(f"**Manual Required:** {ah['manual_required']}")
        lines.append(f"**Recent Entries:** {ah['recent_count']}")
        lines.append("")

    # Pattern summary
    if stats.get("patterns"):
        p = stats["patterns"]
        lines.append("### 📋 Learned Patterns")
        lines.append(f"**Total:** {p['total']} patterns")
        for cat, count in sorted(p["by_category"].items()):
            lines.append(f"- {cat}: {count}")
        lines.append("")

    # Session summary
    if stats.get("sessions"):
        s = stats["sessions"]
        lines.append("### 📅 Session Activity")
        lines.append(f"**Today ({s['today_date']}):** {s['today_actions']} actions")
        lines.append(f"**Total Sessions:** {s['total_session_files']} days")
        lines.append("")

    # Top 10 largest files
    lines.append("### 📁 Largest Files")
    sorted_files = sorted(stats["files"].items(), key=lambda x: x[1]["size_kb"], reverse=True)[:10]
    for file_path, info in sorted_files:
        lines.append(f"- {file_path}: {info['size_kb']} KB")
    lines.append("")

    # Health warnings
    lines.append("### ⚡ Health Checks")
    warnings = []

    # Check for large files
    large_files = [f for f, info in stats["files"].items() if info["size_kb"] > 50]
    if large_files:
        warnings.append(f"⚠️ {len(large_files)} files over 50 KB")

    # Check auto-heal rate
    if stats.get("auto_heal") and stats["auto_heal"]["success_rate"] < 0.7:
        warnings.append(f"⚠️ Auto-heal success rate low: {stats['auto_heal']['success_rate']:.0%}")

    # Check total storage
    if stats["storage"]["total_kb"] > 1024:
        warnings.append(f"⚠️ Total storage over 1 MB: {stats['storage']['total_kb']} KB")

    if warnings:
        for w in warnings:
            lines.append(w)
    else:
        lines.append("✅ All checks passed - memory system healthy")

    return lines


async def _memory_read_impl(key: str = "", ctx: Any = None) -> list[TextContent]:
    """
    Read from persistent memory.

    Memory stores context that persists across Claude sessions:
    - state/current_work - Active issues, branches, MRs (workspace-specific)
    - state/environments - Stage/prod health status
    - learned/patterns - Error patterns and solutions
    - learned/runbooks - Procedures that worked

    Args:
        key: Memory key to read (e.g., "state/current_work", "learned/patterns")
             Leave empty to list available memory files.
        ctx: MCP Context for workspace-aware path resolution (optional)

    Returns:
        Memory contents or list of available memory files.
    """
    # Track memory read
    from tool_modules.aa_workflow.src.agent_stats import record_memory_read

    record_memory_read()

    if not key:
        # List available memory
        lines = ["## Available Memory\n"]
        for subdir in ["state", "learned", "sessions"]:
            d = MEMORY_DIR / subdir
            if d.exists():
                lines.append(f"### {subdir}/")
                for f in d.glob("*.yaml"):
                    lines.append(f"- {subdir}/{f.stem}")
                # Also list project-specific state
                if subdir == "state":
                    projects_dir = d / "projects"
                    if projects_dir.exists():
                        for project_dir in projects_dir.iterdir():
                            if project_dir.is_dir():
                                lines.append(f"  - {subdir}/projects/{project_dir.name}/")
                                for f in project_dir.glob("*.yaml"):
                                    lines.append(f"    - {f.stem}")
        return [TextContent(type="text", text="\n".join(lines))]

    # Resolve the memory path (handles project-specific keys, workspace-aware)
    memory_file = await _resolve_memory_path_async(key, ctx)

    if not memory_file.exists():
        # Show helpful message for project-specific keys
        key_normalized = key.replace(".yaml", "")
        if key_normalized in PROJECT_SPECIFIC_KEYS:
            return [
                TextContent(
                    type="text",
                    text=f"❌ No work state for current project.\n\n"
                    f"File would be at: `{memory_file}`\n\n"
                    "Use `start_work` skill to begin tracking work for this project.",
                )
            ]
        return [
            TextContent(
                type="text",
                text=f"❌ Memory not found: {key}\n\n" "Use memory_read() without args to see available memory.",
            )
        ]

    try:
        content = memory_file.read_text()
        display_key = str(memory_file.relative_to(MEMORY_DIR))
        return [TextContent(type="text", text=f"## Memory: {display_key}\n\n```yaml\n{content}\n```")]
    except Exception as e:
        return [TextContent(type="text", text=f"❌ Error reading memory: {e}")]


async def _memory_write_impl(key: str, content: str, ctx: Any = None) -> list[TextContent]:
    """
    Write to persistent memory.

    Updates a memory file with new content. Use this to save:
    - Current work state (what you're working on) - workspace-specific
    - Learned patterns (solutions that worked)
    - Session notes (context for next session)

    Args:
        key: Memory key to write (e.g., "state/current_work", "learned/patterns")
        content: YAML content to write
        ctx: MCP Context for workspace-aware path resolution (optional)

    Returns:
        Confirmation of the write.
    """
    # Track memory write
    from tool_modules.aa_workflow.src.agent_stats import record_memory_write

    record_memory_write()

    # Resolve the memory path (handles project-specific keys, workspace-aware)
    memory_file = await _resolve_memory_path_async(key, ctx)

    # Ensure parent directory exists
    memory_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Validate YAML
        yaml.safe_load(content)

        # Write to file
        memory_file.write_text(content)

        display_key = str(memory_file.relative_to(MEMORY_DIR))
        return [TextContent(type="text", text=f"✅ Memory saved: {display_key}")]
    except yaml.YAMLError as e:
        return [TextContent(type="text", text=f"❌ Invalid YAML: {e}")]
    except Exception as e:
        return [TextContent(type="text", text=f"❌ Error writing memory: {e}")]


async def _memory_update_impl(key: str, path: str, value: str, ctx: Any = None) -> list[TextContent]:
    """
    Update a specific field in memory.

    Updates a single field in a YAML memory file without rewriting everything.

    Args:
        key: Memory file (e.g., "state/current_work")
        path: Dot-separated path to the field (e.g., "active_issues", "notes")
        value: New value (as YAML string)
        ctx: MCP Context for workspace-aware path resolution (optional)

    Returns:
        Confirmation of the update.
    """
    # Track memory write
    from tool_modules.aa_workflow.src.agent_stats import record_memory_write

    record_memory_write()

    # Resolve the memory path (handles project-specific keys, workspace-aware)
    memory_file = await _resolve_memory_path_async(key, ctx)

    # For project-specific keys, create the file if it doesn't exist
    key_normalized = key.replace(".yaml", "")
    if not memory_file.exists():
        if key_normalized in PROJECT_SPECIFIC_KEYS:
            # Create empty file for project-specific keys
            memory_file.parent.mkdir(parents=True, exist_ok=True)
            memory_file.write_text("{}")
        else:
            return [TextContent(type="text", text=f"❌ Memory not found: {key}")]

    try:
        # Load existing
        with open(memory_file) as f:
            data = yaml.safe_load(f) or {}

        # Parse the new value
        new_value = yaml.safe_load(value)

        # Navigate to the path and update
        parts = path.split(".")
        target = data
        for part in parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]
        target[parts[-1]] = new_value

        # Write back
        with open(memory_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

        display_key = str(memory_file.relative_to(MEMORY_DIR))
        return [TextContent(type="text", text=f"✅ Updated {display_key}: {path} = {value}")]
    except Exception as e:
        return [TextContent(type="text", text=f"❌ Error updating memory: {e}")]


async def _memory_append_impl(key: str, list_path: str, item: str, ctx: Any = None) -> list[TextContent]:
    """
    Append an item to a list in memory.

    Useful for adding to lists like active_issues, follow_ups, recent_alerts.

    Args:
        key: Memory file (e.g., "state/current_work")
        list_path: Path to the list (e.g., "active_issues", "follow_ups")
        item: Item to append (as YAML string)
        ctx: MCP Context for workspace-aware path resolution (optional)

    Returns:
        Confirmation of the append.
    """
    # Track memory write
    from tool_modules.aa_workflow.src.agent_stats import record_memory_write

    record_memory_write()

    # Resolve the memory path (handles project-specific keys, workspace-aware)
    memory_file = await _resolve_memory_path_async(key, ctx)

    # For project-specific keys, create the file if it doesn't exist
    key_normalized = key.replace(".yaml", "")
    if not memory_file.exists():
        if key_normalized in PROJECT_SPECIFIC_KEYS:
            # Create empty file for project-specific keys
            memory_file.parent.mkdir(parents=True, exist_ok=True)
            memory_file.write_text("{}")
        else:
            return [TextContent(type="text", text=f"❌ Memory not found: {key}")]

    try:
        # Load existing
        with open(memory_file) as f:
            data = yaml.safe_load(f) or {}

        # Parse the new item
        new_item = yaml.safe_load(item)

        # Navigate to the list
        parts = list_path.split(".")
        target = data
        for part in parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]

        # Ensure it's a list and append
        if parts[-1] not in target:
            target[parts[-1]] = []
        if not isinstance(target[parts[-1]], list):
            return [TextContent(type="text", text=f"❌ {list_path} is not a list")]

        target[parts[-1]].append(new_item)

        # Write back
        with open(memory_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

        display_key = str(memory_file.relative_to(MEMORY_DIR))
        return [TextContent(type="text", text=f"✅ Appended to {display_key}: {list_path}")]
    except Exception as e:
        return [TextContent(type="text", text=f"❌ Error appending to memory: {e}")]


async def _memory_query_impl(key: str, query: str, ctx: Any = None) -> list[TextContent]:
    """
    Query memory using JSONPath expressions.

    This allows querying specific data without reading entire memory files.
    Useful for filtering large lists or extracting nested values.

    Args:
        key: Memory file (e.g., "state/current_work", "learned/patterns")
        query: JSONPath query expression
        ctx: MCP Context for workspace-aware path resolution (optional)

    JSONPath Examples:
        - `$.active_issues[0]` - First active issue
        - `$.active_issues[?(@.status=='In Progress')]` - Issues in progress
        - `$.active_issues[*].key` - All issue keys
        - `$.environments.stage.status` - Stage environment status
        - `$.error_patterns[?(@.pattern =~ /auth.*/i)]` - Patterns matching regex

    Returns:
        Matching data as YAML.
    """
    # Track memory read
    from tool_modules.aa_workflow.src.agent_stats import record_memory_read

    record_memory_read()
    try:
        from jsonpath_ng import parse
    except ImportError:
        return [
            TextContent(
                type="text",
                text="❌ jsonpath_ng not installed.\n\n"
                "Install with: `uv add jsonpath-ng`\n\n"
                "For now, use memory_read() instead.",
            )
        ]

    # Resolve the memory path (handles project-specific keys, workspace-aware)
    memory_file = await _resolve_memory_path_async(key, ctx)

    if not memory_file.exists():
        display_key = str(memory_file.relative_to(MEMORY_DIR))
        return [TextContent(type="text", text=f"❌ Memory not found: {display_key}")]

    try:
        # Load memory file
        with open(memory_file) as f:
            data = yaml.safe_load(f) or {}

        # Parse and execute JSONPath query
        expr = parse(query)
        matches = [match.value for match in expr.find(data)]

        display_key = str(memory_file.relative_to(MEMORY_DIR))
        if not matches:
            return [
                TextContent(
                    type="text",
                    text=f"No matches found for query: `{query}`\n\n"
                    f"**File:** {display_key}\n\n"
                    "Try a different JSONPath expression or use memory_read() to see full contents.",
                )
            ]

        # Format results
        result_yaml = yaml.dump(matches, default_flow_style=False)
        return [
            TextContent(
                type="text",
                text=f"## Query Results: {display_key}\n\n"
                f"**Query:** `{query}`\n"
                f"**Matches:** {len(matches)}\n\n"
                f"```yaml\n{result_yaml}```",
            )
        ]
    except Exception as e:
        key_normalized = key.replace(".yaml", "")
        return [
            TextContent(
                type="text",
                text=f"❌ Query error: {e}\n\n"
                "**Common issues:**\n"
                "- Invalid JSONPath syntax\n"
                "- Path doesn't exist in data\n"
                "- Check query with simpler expressions first\n\n"
                f"Use memory_read('{key_normalized}') to see full structure.",
            )
        ]


async def _memory_session_log_impl(action: str, details: str = "") -> list[TextContent]:
    """
    Log an action to today's session log.

    Creates a running log of what was done during this session.
    Useful for handoff to future sessions.

    Args:
        action: What was done (e.g., "Started work on AAP-12345")
        details: Additional details (optional)

    Returns:
        Confirmation of the log entry.
    """
    # Track memory write
    from tool_modules.aa_workflow.src.agent_stats import record_memory_write

    record_memory_write()

    today = datetime.now().strftime("%Y-%m-%d")
    session_file = MEMORY_DIR / "sessions" / f"{today}.yaml"
    session_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Load existing or create new
        if session_file.exists():
            with open(session_file) as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {"date": today, "entries": []}

        if "entries" not in data:
            data["entries"] = []

        # Add entry
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "action": action,
        }
        if details:
            entry["details"] = details

        data["entries"].append(entry)

        # Write back
        with open(session_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

        return [TextContent(type="text", text=f"✅ Logged: {action}")]
    except Exception as e:
        return [TextContent(type="text", text=f"❌ Error logging: {e}")]


async def _check_known_issues_impl(tool_name: str = "", error_text: str = "") -> list[TextContent]:
    """
    Check memory for known fixes before or after an error.

    Searches learned patterns and tool fixes for matching issues.
    Use this when a tool fails to see if we've solved this before.

    Args:
        tool_name: Name of the tool that failed (e.g., "bonfire_deploy")
        error_text: Error message text to match against patterns

    Returns:
        Known issues and fixes, or empty if none found.
    """
    matches = []
    error_lower = error_text.lower() if error_text else ""
    tool_lower = tool_name.lower() if tool_name else ""

    # Load patterns from memory
    patterns = _load_patterns_from_memory()

    # Check all pattern types
    pattern_types = [
        "error_patterns",
        "auth_patterns",
        "bonfire_patterns",
        "pipeline_patterns",
        "jira_cli_patterns",
    ]
    for pattern_type in pattern_types:
        pattern_matches = _check_pattern_matches(patterns.get(pattern_type, []), pattern_type, error_lower, tool_lower)
        matches.extend(pattern_matches)

    # Load and check tool fixes
    tool_fixes = _load_tool_fixes_from_memory()
    for fix in tool_fixes:
        if tool_name and fix.get("tool_name", "").lower() == tool_lower:
            matches.append(
                {
                    "source": "tool_fixes",
                    "tool_name": fix.get("tool_name"),
                    "error_pattern": fix.get("error_pattern", ""),
                    "root_cause": fix.get("root_cause", ""),
                    "fix_applied": fix.get("fix_applied", ""),
                    "date_learned": fix.get("date_learned", ""),
                }
            )
        elif error_text:
            fix_pattern = fix.get("error_pattern", "").lower()
            if fix_pattern and fix_pattern in error_lower:
                matches.append(
                    {
                        "source": "tool_fixes",
                        "tool_name": fix.get("tool_name"),
                        "error_pattern": fix.get("error_pattern", ""),
                        "root_cause": fix.get("root_cause", ""),
                        "fix_applied": fix.get("fix_applied", ""),
                        "date_learned": fix.get("date_learned", ""),
                    }
                )

    if not matches:
        return [
            TextContent(
                type="text",
                text="No known issues found matching your query.\n\n"
                "If you fix this issue, save it with:\n"
                f"`learn_tool_fix('{tool_name}', '<error_pattern>', '<cause>', '<fix>')`",
            )
        ]

    # Format matches using helper
    lines = _format_known_issue_matches(matches)
    return [TextContent(type="text", text="\n".join(lines))]


async def _learn_tool_fix_impl(
    tool_name: str,
    error_pattern: str,
    root_cause: str,
    fix_description: str,
) -> list[TextContent]:
    """
    Save a fix to memory after it works.

    Use this after successfully fixing a tool error to remember the solution.
    The next time this pattern appears, check_known_issues() will show the fix.

    Args:
        tool_name: Name of the tool that failed (e.g., "bonfire_deploy")
        error_pattern: The error pattern to match (e.g., "manifest unknown")
        root_cause: Why it failed (e.g., "Short SHA doesn't exist in Quay")
        fix_description: What fixed it (e.g., "Use full 40-char SHA")

    Returns:
        Confirmation of the saved fix.
    """
    fixes_file = MEMORY_DIR / "learned" / "tool_fixes.yaml"
    fixes_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        # Load existing or create new
        if fixes_file.exists():
            with open(fixes_file) as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {"tool_fixes": [], "common_mistakes": {}}

        if "tool_fixes" not in data:
            data["tool_fixes"] = []

        # Add new fix
        new_fix = {
            "tool_name": tool_name,
            "error_pattern": error_pattern,
            "root_cause": root_cause,
            "fix_applied": fix_description,
            "date_learned": datetime.now().strftime("%Y-%m-%d"),
            "times_prevented": 0,
        }

        # Check for duplicates
        for existing in data["tool_fixes"]:
            if existing.get("tool_name") == tool_name and existing.get("error_pattern") == error_pattern:
                # Update existing instead of adding duplicate
                existing["root_cause"] = root_cause
                existing["fix_applied"] = fix_description
                existing["date_learned"] = new_fix["date_learned"]

                with open(fixes_file, "w") as f:
                    yaml.dump(data, f, default_flow_style=False)

                return [
                    TextContent(
                        type="text",
                        text=f"✅ Updated existing fix for `{tool_name}`\n\n"
                        f"**Pattern:** `{error_pattern}`\n"
                        f"**Root cause:** {root_cause}\n"
                        f"**Fix:** {fix_description}\n\n"
                        "Next time this pattern appears, you'll be reminded of the fix.",
                    )
                ]

        data["tool_fixes"].append(new_fix)

        # Write back
        with open(fixes_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

        return [
            TextContent(
                type="text",
                text=f"✅ Saved tool fix to memory!\n\n"
                f"**Tool:** `{tool_name}`\n"
                f"**Pattern:** `{error_pattern}`\n"
                f"**Root cause:** {root_cause}\n"
                f"**Fix:** {fix_description}\n\n"
                "Next time this pattern appears, you'll be reminded of the fix.",
            )
        ]
    except Exception as e:
        return [TextContent(type="text", text=f"❌ Error saving fix: {e}")]


async def _memory_stats_impl() -> list[TextContent]:
    """
    Get memory system statistics and health metrics.

    Provides visibility into:
    - File sizes and last modified times
    - Auto-heal success rates
    - Pattern counts by category
    - Session activity
    - Storage usage by directory

    Returns:
        Comprehensive memory health dashboard.
    """
    try:
        stats = {
            "files": {},
            "auto_heal": {},
            "patterns": {},
            "sessions": {},
            "storage": {},
        }

        # Collect statistics using helper functions
        stats["files"], total_size = _collect_file_stats()
        stats["auto_heal"] = _collect_autoheal_stats()
        stats["patterns"] = _collect_pattern_stats()

        # Session activity
        sessions_dir = MEMORY_DIR / "sessions"
        if sessions_dir.exists():
            session_files = list(sessions_dir.glob("*.yaml"))
            today = datetime.now().strftime("%Y-%m-%d")
            today_file = sessions_dir / f"{today}.yaml"

            today_actions = 0
            if today_file.exists():
                with open(today_file) as f:
                    today_data = yaml.safe_load(f) or {}
                    today_actions = len(today_data.get("entries", []))

            stats["sessions"] = {
                "total_session_files": len(session_files),
                "today_actions": today_actions,
                "today_date": today,
            }

        # Storage breakdown by directory
        for subdir in ["state", "learned", "sessions", "backups"]:
            dir_path = MEMORY_DIR / subdir
            if dir_path.exists():
                dir_size = sum(f.stat().st_size for f in dir_path.rglob("*.yaml"))
                stats["storage"][subdir] = round(dir_size / 1024, 2)

        stats["storage"]["total_kb"] = round(total_size / 1024, 2)

        # Format output using helper
        lines = _format_memory_stats(stats)
        return [TextContent(type="text", text="\n".join(lines))]

    except Exception as e:
        return [TextContent(type="text", text=f"❌ Error generating stats: {e}")]


def register_memory_tools(server: "FastMCP") -> int:
    """Register memory tools with the MCP server."""
    registry = ToolRegistry(server)

    @registry.tool()
    async def memory_read(ctx: Context, key: str = "") -> list[TextContent]:
        """
        Read from persistent memory.

        Memory stores context that persists across Claude sessions:
        - state/current_work.yaml - Active issues, branches, MRs (workspace-specific)
        - state/environments.yaml - Stage/prod health status
        - learned/patterns.yaml - Error patterns and solutions
        - learned/runbooks.yaml - Procedures that worked

        Args:
            key: Memory key to read (e.g., "state/current_work", "learned/patterns")
                 Leave empty to list available memory files.

        Returns:
            Memory contents or list of available memory files.
        """
        # Use workspace-aware path resolution for project-specific keys
        return await _memory_read_impl(key, ctx)

    @auto_heal()
    @registry.tool()
    async def memory_write(ctx: Context, key: str, content: str) -> list[TextContent]:
        """
        Write to persistent memory.

        Updates a memory file with new content. Use this to save:
        - Current work state (what you're working on)
        - Learned patterns (solutions that worked)
        - Session notes (context for next session)

        Args:
            key: Memory key to write (e.g., "state/current_work", "learned/patterns")
            content: YAML content to write

        Returns:
            Confirmation of the write.
        """
        return await _memory_write_impl(key, content, ctx)

    @auto_heal()
    @registry.tool()
    async def memory_update(ctx: Context, key: str, path: str, value: str) -> list[TextContent]:
        """
        Update a specific field in memory.

        Updates a single field in a YAML memory file without rewriting everything.

        Args:
            key: Memory file (e.g., "state/current_work")
            path: Dot-separated path to the field (e.g., "active_issues", "notes")
            value: New value (as YAML string)

        Returns:
            Confirmation of the update.
        """
        return await _memory_update_impl(key, path, value, ctx)

    @auto_heal()
    @registry.tool()
    async def memory_append(ctx: Context, key: str, list_path: str, item: str) -> list[TextContent]:
        """
        Append an item to a list in memory.

        Useful for adding to lists like active_issues, follow_ups, recent_alerts.

        Args:
            key: Memory file (e.g., "state/current_work")
            list_path: Path to the list (e.g., "active_issues", "follow_ups")
            item: Item to append (as YAML string)

        Returns:
            Confirmation of the append.
        """
        return await _memory_append_impl(key, list_path, item, ctx)

    @registry.tool()
    async def memory_query(ctx: Context, key: str, query: str) -> list[TextContent]:
        """
        Query memory using JSONPath expressions.

        This allows querying specific data without reading entire memory files.
        Useful for filtering large lists or extracting nested values.

        Args:
            key: Memory file (e.g., "state/current_work", "learned/patterns")
            query: JSONPath query expression

        JSONPath Examples:
            - `$.active_issues[0]` - First active issue
            - `$.active_issues[?(@.status=='In Progress')]` - Issues in progress
            - `$.active_issues[*].key` - All issue keys
            - `$.environments.stage.status` - Stage environment status
            - `$.error_patterns[?(@.pattern =~ /auth.*/i)]` - Patterns matching regex

        Returns:
            Matching data as YAML.
        """
        return await _memory_query_impl(key, query, ctx)

    @auto_heal()
    @registry.tool()
    async def memory_session_log(ctx: Context, action: str, details: str = "") -> list[TextContent]:
        """
        Log an action to today's session log.

        Creates a running log of what was done during this session.
        Useful for handoff to future sessions.

        Args:
            action: What was done (e.g., "Started work on AAP-12345")
            details: Additional details (optional)

        Returns:
            Confirmation of the log entry.
        """
        return await _memory_session_log_impl(action, details)

    @registry.tool()
    async def check_known_issues(ctx: Context, tool_name: str = "", error_text: str = "") -> list[TextContent]:
        """
        Check memory for known fixes before or after an error.

        Searches learned patterns and tool fixes for matching issues.
        Use this when a tool fails to see if we've solved this before.

        Args:
            tool_name: Name of the tool that failed (e.g., "bonfire_deploy")
            error_text: Error message text to match against patterns

        Returns:
            Known issues and fixes, or empty if none found.
        """
        return await _check_known_issues_impl(tool_name, error_text)

    @auto_heal()
    @registry.tool()
    async def learn_tool_fix(
        ctx: Context,
        tool_name: str,
        error_pattern: str,
        root_cause: str,
        fix_description: str,
    ) -> list[TextContent]:
        """
        Save a fix to memory after it works.

        Use this after successfully fixing a tool error to remember the solution.
        The next time this pattern appears, check_known_issues() will show the fix.

        Args:
            tool_name: Name of the tool that failed (e.g., "bonfire_deploy")
            error_pattern: The error pattern to match (e.g., "manifest unknown")
            root_cause: Why it failed (e.g., "Short SHA doesn't exist in Quay")
            fix_description: What fixed it (e.g., "Use full 40-char SHA")

        Returns:
            Confirmation of the saved fix.
        """
        return await _learn_tool_fix_impl(tool_name, error_pattern, root_cause, fix_description)

    @registry.tool()
    async def memory_stats(ctx: Context) -> list[TextContent]:
        """
        Get memory system statistics and health metrics.

        Provides visibility into:
        - File sizes and last modified times
        - Auto-heal success rates
        - Pattern counts by category
        - Session activity
        - Storage usage by directory

        Returns:
            Comprehensive memory health dashboard.
        """
        return await _memory_stats_impl()

    return registry.count
