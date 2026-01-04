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
    tool_count = 0

    @server.tool()
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

    tool_count += 1

    @server.tool()
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

    tool_count += 1

    @server.tool()
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

    tool_count += 1

    @server.tool()
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

    tool_count += 1

    @server.tool()
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

    tool_count += 1

    return tool_count
