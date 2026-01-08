"""Memory Tools - Persistent context storage across sessions.

Provides tools for reading, writing, and managing persistent memory:
- memory_read: Read memory files
- memory_write: Write complete memory files
- memory_update: Update specific fields
- memory_append: Append to lists
- memory_session_log: Log session actions
"""

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from mcp.types import TextContent

from server.tool_registry import ToolRegistry

# Support both package import and direct loading
try:
    from .constants import MEMORY_DIR
except ImportError:
    TOOL_MODULES_DIR = Path(__file__).parent.parent.parent
    PROJECT_DIR = TOOL_MODULES_DIR.parent
    MEMORY_DIR = PROJECT_DIR / "memory"

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_memory_tools(server: "FastMCP") -> int:
    """Register memory tools with the MCP server."""
    registry = ToolRegistry(server)

    @registry.tool()
    async def memory_read(key: str = "") -> list[TextContent]:
        """
        Read from persistent memory.

        Memory stores context that persists across Claude sessions:
        - state/current_work.yaml - Active issues, branches, MRs
        - state/environments.yaml - Stage/prod health status
        - learned/patterns.yaml - Error patterns and solutions
        - learned/runbooks.yaml - Procedures that worked

        Args:
            key: Memory key to read (e.g., "state/current_work", "learned/patterns")
                 Leave empty to list available memory files.

        Returns:
            Memory contents or list of available memory files.
        """
        if not key:
            # List available memory
            lines = ["## Available Memory\n"]
            for subdir in ["state", "learned", "sessions"]:
                d = MEMORY_DIR / subdir
                if d.exists():
                    lines.append(f"### {subdir}/")
                    for f in d.glob("*.yaml"):
                        lines.append(f"- {subdir}/{f.stem}")
            return [TextContent(type="text", text="\n".join(lines))]

        # Handle with or without .yaml extension
        if not key.endswith(".yaml"):
            key = f"{key}.yaml"

        memory_file = MEMORY_DIR / key
        if not memory_file.exists():
            return [
                TextContent(
                    type="text",
                    text=f"❌ Memory not found: {key}\n\n" "Use memory_read() without args to see available memory.",
                )
            ]

        try:
            content = memory_file.read_text()
            return [TextContent(type="text", text=f"## Memory: {key}\n\n```yaml\n{content}\n```")]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Error reading memory: {e}")]

    @registry.tool()
    async def memory_write(key: str, content: str) -> list[TextContent]:
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
        # Handle with or without .yaml extension
        if not key.endswith(".yaml"):
            key = f"{key}.yaml"

        memory_file = MEMORY_DIR / key

        # Ensure parent directory exists
        memory_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Validate YAML
            yaml.safe_load(content)

            # Write to file
            memory_file.write_text(content)

            return [TextContent(type="text", text=f"✅ Memory saved: {key}")]
        except yaml.YAMLError as e:
            return [TextContent(type="text", text=f"❌ Invalid YAML: {e}")]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Error writing memory: {e}")]

    @registry.tool()
    async def memory_update(key: str, path: str, value: str) -> list[TextContent]:
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
        if not key.endswith(".yaml"):
            key = f"{key}.yaml"

        memory_file = MEMORY_DIR / key
        if not memory_file.exists():
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

            return [TextContent(type="text", text=f"✅ Updated {key}: {path} = {value}")]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Error updating memory: {e}")]

    @registry.tool()
    async def memory_append(key: str, list_path: str, item: str) -> list[TextContent]:
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
        if not key.endswith(".yaml"):
            key = f"{key}.yaml"

        memory_file = MEMORY_DIR / key
        if not memory_file.exists():
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

            return [TextContent(type="text", text=f"✅ Appended to {key}: {list_path}")]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Error appending to memory: {e}")]

    @registry.tool()
    async def memory_session_log(action: str, details: str = "") -> list[TextContent]:
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

    @registry.tool()
    async def check_known_issues(tool_name: str = "", error_text: str = "") -> list[TextContent]:
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

        # Check learned/patterns.yaml
        patterns_file = MEMORY_DIR / "learned" / "patterns.yaml"
        if patterns_file.exists():
            try:
                with open(patterns_file) as f:
                    patterns = yaml.safe_load(f) or {}

                # Check error_patterns
                for pattern in patterns.get("error_patterns", []):
                    pattern_text = pattern.get("pattern", "").lower()
                    if pattern_text and (pattern_text in error_lower or pattern_text in tool_lower):
                        matches.append(
                            {
                                "source": "error_patterns",
                                "pattern": pattern.get("pattern"),
                                "meaning": pattern.get("meaning", ""),
                                "fix": pattern.get("fix", ""),
                                "commands": pattern.get("commands", []),
                            }
                        )

                # Check auth_patterns
                for pattern in patterns.get("auth_patterns", []):
                    pattern_text = pattern.get("pattern", "").lower()
                    if pattern_text and pattern_text in error_lower:
                        matches.append(
                            {
                                "source": "auth_patterns",
                                "pattern": pattern.get("pattern"),
                                "meaning": pattern.get("meaning", ""),
                                "fix": pattern.get("fix", ""),
                                "commands": pattern.get("commands", []),
                            }
                        )

                # Check bonfire_patterns
                for pattern in patterns.get("bonfire_patterns", []):
                    pattern_text = pattern.get("pattern", "").lower()
                    if pattern_text and (pattern_text in error_lower or "bonfire" in tool_lower):
                        matches.append(
                            {
                                "source": "bonfire_patterns",
                                "pattern": pattern.get("pattern"),
                                "meaning": pattern.get("meaning", ""),
                                "fix": pattern.get("fix", ""),
                                "commands": pattern.get("commands", []),
                            }
                        )

                # Check pipeline_patterns
                for pattern in patterns.get("pipeline_patterns", []):
                    pattern_text = pattern.get("pattern", "").lower()
                    if pattern_text and pattern_text in error_lower:
                        matches.append(
                            {
                                "source": "pipeline_patterns",
                                "pattern": pattern.get("pattern"),
                                "meaning": pattern.get("meaning", ""),
                                "fix": pattern.get("fix", ""),
                                "commands": pattern.get("commands", []),
                            }
                        )

                # Check jira_cli_patterns
                for pattern in patterns.get("jira_cli_patterns", []):
                    pattern_text = pattern.get("pattern", "").lower()
                    if pattern_text and (
                        pattern_text in error_lower or pattern_text in tool_lower or "jira" in tool_lower
                    ):
                        matches.append(
                            {
                                "source": "jira_cli_patterns",
                                "pattern": pattern.get("pattern"),
                                "description": pattern.get("description", ""),
                                "solution": pattern.get("solution", ""),
                            }
                        )

            except Exception:
                pass

        # Check learned/tool_fixes.yaml
        fixes_file = MEMORY_DIR / "learned" / "tool_fixes.yaml"
        if fixes_file.exists():
            try:
                with open(fixes_file) as f:
                    fixes = yaml.safe_load(f) or {}

                for fix in fixes.get("tool_fixes", []):
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

            except Exception:
                pass

        if not matches:
            return [
                TextContent(
                    type="text",
                    text="No known issues found matching your query.\n\n"
                    "If you fix this issue, save it with:\n"
                    f"`learn_tool_fix('{tool_name}', '<error_pattern>', '<cause>', '<fix>')`",
                )
            ]

        # Format matches
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
                if match.get("meaning"):
                    lines.append(f"**Meaning:** {match.get('meaning')}")
                if match.get("fix"):
                    lines.append(f"**Fix:** {match.get('fix')}")
                if match.get("commands"):
                    lines.append("**Commands to try:**")
                    for cmd in match.get("commands", [])[:3]:
                        lines.append(f"- `{cmd}`")
            lines.append("")

        return [TextContent(type="text", text="\n".join(lines))]

    @registry.tool()
    async def learn_tool_fix(
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

    return registry.count
