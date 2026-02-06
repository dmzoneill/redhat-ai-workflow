"""
Command Registry for Slack @me Commands.

Provides dynamic discovery of available commands from skills and tools.
No hardcoding - reads from skills/*.yaml and tool modules at runtime.

Usage:
    registry = CommandRegistry()
    commands = registry.list_commands()
    help_text = registry.get_command_help("create_jira_issue")
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills"
TOOL_MODULES_DIR = PROJECT_ROOT / "tool_modules"


class CommandType(str, Enum):
    """Type of command."""

    SKILL = "skill"
    TOOL = "tool"
    BUILTIN = "builtin"


@dataclass
class CommandInfo:
    """Information about an available command."""

    name: str
    description: str
    command_type: CommandType
    category: str = ""

    # For skills
    inputs: list[dict[str, Any]] = field(default_factory=list)

    # For tools
    parameters: dict[str, Any] = field(default_factory=dict)

    # Examples
    examples: list[str] = field(default_factory=list)

    # Source file
    source: str = ""

    # Whether it supports contextual execution
    contextual: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "type": self.command_type.value,
            "category": self.category,
            "inputs": self.inputs,
            "parameters": self.parameters,
            "examples": self.examples,
            "contextual": self.contextual,
        }


@dataclass
class CommandHelp:
    """Detailed help for a command."""

    name: str
    description: str
    command_type: CommandType

    # Usage
    usage: str = ""
    examples: list[str] = field(default_factory=list)

    # For skills
    inputs: list[dict[str, Any]] = field(default_factory=list)
    outputs: list[dict[str, Any]] = field(default_factory=list)

    # For tools
    parameters: dict[str, Any] = field(default_factory=dict)

    # Related commands
    related: list[str] = field(default_factory=list)

    def format_slack(self) -> str:
        """Format help for Slack display."""
        lines = [f"*`{self.name}`* - {self.description}"]
        lines.append(f"Type: _{self.command_type.value}_")

        if self.usage:
            lines.append(f"\n*Usage:*\n```{self.usage}```")

        if self.inputs:
            lines.append("\n*Inputs:*")
            for inp in self.inputs:
                required = " (required)" if inp.get("required") else ""
                default = f" [default: {inp.get('default')}]" if "default" in inp else ""
                lines.append(f"• `{inp['name']}`{required}: {inp.get('description', '')}{default}")

        if self.parameters:
            props = self.parameters.get("properties", {})
            if props:
                lines.append("\n*Parameters:*")
                required_params = self.parameters.get("required", [])
                for name, info in props.items():
                    required = " (required)" if name in required_params else ""
                    lines.append(f"• `{name}`{required}: {info.get('description', info.get('type', ''))}")

        if self.examples:
            lines.append("\n*Examples:*")
            for ex in self.examples[:3]:
                lines.append(f"```{ex}```")

        if self.related:
            lines.append(f"\n_Related: {', '.join(self.related)}_")

        return "\n".join(lines)

    def format_text(self) -> str:
        """Format help for plain text display."""
        lines = [f"{self.name} - {self.description}", f"Type: {self.command_type.value}"]

        if self.usage:
            lines.append(f"\nUsage: {self.usage}")

        if self.inputs:
            lines.append("\nInputs:")
            for inp in self.inputs:
                required = " (required)" if inp.get("required") else ""
                lines.append(f"  {inp['name']}{required}: {inp.get('description', '')}")

        if self.examples:
            lines.append("\nExamples:")
            for ex in self.examples[:3]:
                lines.append(f"  {ex}")

        return "\n".join(lines)


class CommandRegistry:
    """
    Registry for discovering available commands.

    Dynamically discovers skills from YAML files and tools from
    tool modules without hardcoding.
    """

    # Skills that work well with contextual execution
    CONTEXTUAL_SKILLS = {
        "create_jira_issue",
        "investigate_alert",
        "investigate_slack_alert",
        "summarize",
        "debug_prod",
    }

    # Built-in commands
    BUILTIN_COMMANDS = {
        "help": CommandInfo(
            name="help",
            description="Show available commands or help for a specific command",
            command_type=CommandType.BUILTIN,
            examples=["@me help", "@me help create_jira_issue"],
        ),
        "status": CommandInfo(
            name="status",
            description="Show bot status and capabilities",
            command_type=CommandType.BUILTIN,
            examples=["@me status"],
        ),
        "list": CommandInfo(
            name="list",
            description="List all available skills and tools",
            command_type=CommandType.BUILTIN,
            examples=["@me list", "@me list skills", "@me list tools"],
        ),
        "watch": CommandInfo(
            name="watch",
            description="Show this channel's ID for adding to watch list",
            command_type=CommandType.BUILTIN,
            examples=["@me watch"],
        ),
        # Jira commands
        "jira": CommandInfo(
            name="jira",
            description="Create a Jira issue from thread context",
            command_type=CommandType.BUILTIN,
            category="jira",
            contextual=True,
            examples=["@me jira", "@me jira bug", "@me jira task", "@me jira subtask AAP-12345"],
        ),
        # Search commands
        "search": CommandInfo(
            name="search",
            description="Search Slack messages, code, or Jira",
            command_type=CommandType.BUILTIN,
            category="search",
            examples=["@me search billing errors", "@me search code auth handler", "@me search jira AAP billing"],
        ),
        "who": CommandInfo(
            name="who",
            description="Look up a Slack user by name or email",
            command_type=CommandType.BUILTIN,
            category="search",
            examples=["@me who @daoneill", "@me who john.smith@redhat.com"],
        ),
        "find": CommandInfo(
            name="find",
            description="Find a Slack channel by name",
            command_type=CommandType.BUILTIN,
            category="search",
            examples=["@me find #aap-analytics", "@me find alerts"],
        ),
        # Cursor chat commands
        "cursor": CommandInfo(
            name="cursor",
            description="Create a Cursor chat from thread context",
            command_type=CommandType.BUILTIN,
            category="cursor",
            contextual=True,
            examples=["@me cursor", "@me cursor chat from thread", "@me cursor AAP-12345"],
        ),
        # Sprint bot commands
        "sprint": CommandInfo(
            name="sprint",
            description="Control the sprint bot - list/approve/start issues",
            command_type=CommandType.BUILTIN,
            category="sprint",
            examples=["@me sprint issues", "@me sprint approve AAP-12345", "@me sprint start AAP-12345"],
        ),
        # Meet bot commands
        "meet": CommandInfo(
            name="meet",
            description="Control the meet bot - join/leave meetings, get captions",
            command_type=CommandType.BUILTIN,
            category="meet",
            examples=["@me meet join", "@me meet leave", "@me meet captions", "@me meet list"],
        ),
        # Cron commands
        "cron": CommandInfo(
            name="cron",
            description="Control the cron scheduler - run/list jobs",
            command_type=CommandType.BUILTIN,
            category="cron",
            examples=["@me cron list", "@me cron run coffee", "@me cron history"],
        ),
        # Research commands
        "research": CommandInfo(
            name="research",
            description="Research a topic in Slack and build knowledge",
            command_type=CommandType.BUILTIN,
            category="research",
            examples=["@me research billing errors", "@me research deep auth issues"],
        ),
        "learn": CommandInfo(
            name="learn",
            description="Learn from the current thread and save to knowledge base",
            command_type=CommandType.BUILTIN,
            category="research",
            contextual=True,
            examples=["@me learn", "@me learn billing patterns"],
        ),
        "knowledge": CommandInfo(
            name="knowledge",
            description="Query or list saved knowledge",
            command_type=CommandType.BUILTIN,
            category="research",
            examples=["@me knowledge billing", "@me knowledge list", "@me knowledge delete billing-errors"],
        ),
    }

    def __init__(
        self,
        skills_dir: Path | None = None,
        tool_modules_dir: Path | None = None,
    ):
        """
        Initialize the registry.

        Args:
            skills_dir: Directory containing skill YAML files
            tool_modules_dir: Directory containing tool modules
        """
        self.skills_dir = skills_dir or SKILLS_DIR
        self.tool_modules_dir = tool_modules_dir or TOOL_MODULES_DIR

        # Caches
        self._skills_cache: dict[str, CommandInfo] | None = None
        self._tools_cache: dict[str, CommandInfo] | None = None

    def list_commands(
        self,
        filter_text: str = "",
        command_type: CommandType | None = None,
        category: str = "",
    ) -> list[CommandInfo]:
        """
        List available commands.

        Args:
            filter_text: Filter commands by name/description
            command_type: Filter by command type (skill, tool, builtin)
            category: Filter by category

        Returns:
            List of matching commands
        """
        commands: list[CommandInfo] = []

        # Add built-in commands
        if command_type is None or command_type == CommandType.BUILTIN:
            commands.extend(self.BUILTIN_COMMANDS.values())

        # Add skills
        if command_type is None or command_type == CommandType.SKILL:
            commands.extend(self._get_skills().values())

        # Add tools
        if command_type is None or command_type == CommandType.TOOL:
            commands.extend(self._get_tools().values())

        # Apply filters
        if filter_text:
            filter_lower = filter_text.lower()
            commands = [c for c in commands if filter_lower in c.name.lower() or filter_lower in c.description.lower()]

        if category:
            commands = [c for c in commands if c.category == category]

        # Sort by type then name
        commands.sort(key=lambda c: (c.command_type.value, c.name))

        return commands

    def get_command(self, name: str) -> CommandInfo | None:
        """
        Get a specific command by name.

        Args:
            name: Command name

        Returns:
            CommandInfo or None if not found
        """
        name = name.lower().replace("-", "_")

        # Check built-in
        if name in self.BUILTIN_COMMANDS:
            return self.BUILTIN_COMMANDS[name]

        # Check skills
        skills = self._get_skills()
        if name in skills:
            return skills[name]

        # Check tools
        tools = self._get_tools()
        if name in tools:
            return tools[name]

        return None

    def get_command_help(self, name: str) -> CommandHelp | None:
        """
        Get detailed help for a command.

        Args:
            name: Command name

        Returns:
            CommandHelp or None if not found
        """
        cmd = self.get_command(name)
        if not cmd:
            return None

        help_info = CommandHelp(
            name=cmd.name,
            description=cmd.description,
            command_type=cmd.command_type,
            inputs=cmd.inputs,
            parameters=cmd.parameters,
            examples=cmd.examples,
        )

        # Build usage string
        if cmd.command_type == CommandType.SKILL:
            help_info.usage = self._build_skill_usage(cmd)
        elif cmd.command_type == CommandType.TOOL:
            help_info.usage = self._build_tool_usage(cmd)
        else:
            help_info.usage = f"@me {cmd.name}"

        # Find related commands
        help_info.related = self._find_related(cmd)

        return help_info

    def _get_skills(self) -> dict[str, CommandInfo]:
        """Load skills from YAML files."""
        if self._skills_cache is not None:
            return self._skills_cache

        self._skills_cache = {}

        if not self.skills_dir.exists():
            logger.warning(f"Skills directory not found: {self.skills_dir}")
            return self._skills_cache

        for skill_file in self.skills_dir.glob("*.yaml"):
            try:
                with open(skill_file) as f:
                    skill_data = yaml.safe_load(f)

                if not skill_data:
                    continue

                name = skill_data.get("name", skill_file.stem)
                description = skill_data.get("description", "")

                # Clean up description (remove markdown, take first line)
                if description:
                    description = description.strip().split("\n")[0]
                    description = re.sub(r"\*+", "", description)  # Remove bold markers

                inputs = skill_data.get("inputs", [])

                # Check if this skill is contextual
                contextual = name in self.CONTEXTUAL_SKILLS

                # Build examples
                examples = [f"@me {name}"]
                if inputs:
                    required_inputs = [i for i in inputs if i.get("required")]
                    if required_inputs:
                        args = " ".join(f"--{i['name']}=<value>" for i in required_inputs[:2])
                        examples.append(f"@me {name} {args}")

                self._skills_cache[name] = CommandInfo(
                    name=name,
                    description=description,
                    command_type=CommandType.SKILL,
                    category=self._categorize_skill(name, skill_data),
                    inputs=inputs,
                    examples=examples,
                    source=str(skill_file),
                    contextual=contextual,
                )

            except Exception as e:
                logger.warning(f"Failed to load skill {skill_file}: {e}")

        return self._skills_cache

    def _get_tools(self) -> dict[str, CommandInfo]:
        """Discover tools from tool modules."""
        if self._tools_cache is not None:
            return self._tools_cache

        self._tools_cache = {}

        if not self.tool_modules_dir.exists():
            logger.warning(f"Tool modules directory not found: {self.tool_modules_dir}")
            return self._tools_cache

        # Scan tool modules
        for module_dir in self.tool_modules_dir.iterdir():
            if not module_dir.is_dir() or not module_dir.name.startswith("aa_"):
                continue

            src_dir = module_dir / "src"
            if not src_dir.exists():
                continue

            # Look for tools_basic.py and tools_extra.py
            for tools_file in ["tools_basic.py", "tools_extra.py", "tools.py"]:
                tools_path = src_dir / tools_file
                if tools_path.exists():
                    self._parse_tools_file(tools_path, module_dir.name[3:])

        return self._tools_cache

    def _parse_tools_file(self, filepath: Path, module_name: str) -> None:
        """Parse a tools file to extract tool definitions."""
        try:
            content = filepath.read_text()

            # Find async def functions with docstrings
            # Pattern: async def tool_name(...): """docstring"""
            pattern = re.compile(
                r'async def (\w+)\s*\([^)]*\)\s*(?:->.*?)?\s*:\s*"""([^"]*?)"""',
                re.MULTILINE | re.DOTALL,
            )

            for match in pattern.finditer(content):
                func_name = match.group(1)
                docstring = match.group(2).strip()

                # Skip internal functions
                if func_name.startswith("_"):
                    continue

                # Extract first line of docstring as description
                description = docstring.split("\n")[0].strip()

                if self._tools_cache is None:
                    self._tools_cache = {}
                self._tools_cache[func_name] = CommandInfo(
                    name=func_name,
                    description=description,
                    command_type=CommandType.TOOL,
                    category=module_name,
                    examples=[f"@me {func_name}"],
                    source=str(filepath),
                )

        except Exception as e:
            logger.warning(f"Failed to parse tools file {filepath}: {e}")

    def _categorize_skill(self, name: str, data: dict) -> str:
        """Categorize a skill based on name and content."""
        name_lower = name.lower()

        if "jira" in name_lower:
            return "jira"
        elif "mr" in name_lower or "pr" in name_lower or "review" in name_lower:
            return "gitlab"
        elif "alert" in name_lower or "investigate" in name_lower:
            return "monitoring"
        elif "deploy" in name_lower or "release" in name_lower:
            return "deployment"
        elif "memory" in name_lower:
            return "memory"
        elif "slack" in name_lower:
            return "slack"
        else:
            return "general"

    def _build_skill_usage(self, cmd: CommandInfo) -> str:
        """Build usage string for a skill."""
        parts = [f"@me {cmd.name}"]

        for inp in cmd.inputs:
            if inp.get("required"):
                parts.append(f"--{inp['name']}=<{inp.get('type', 'value')}>")

        return " ".join(parts)

    def _build_tool_usage(self, cmd: CommandInfo) -> str:
        """Build usage string for a tool."""
        return f"@me {cmd.name} [--arg=value ...]"

    def _find_related(self, cmd: CommandInfo) -> list[str]:
        """Find related commands."""
        related = []

        # Find commands in same category
        if cmd.category:
            for other in self.list_commands():
                if other.name != cmd.name and other.category == cmd.category:
                    related.append(other.name)
                    if len(related) >= 3:
                        break

        return related

    def format_list(self, commands: list[CommandInfo], format_type: str = "slack") -> str:
        """
        Format a list of commands for display.

        Args:
            commands: List of commands to format
            format_type: "slack" or "text"

        Returns:
            Formatted string
        """
        if format_type == "slack":
            return self._format_slack_list(commands)
        return self._format_text_list(commands)

    def _format_slack_list(self, commands: list[CommandInfo]) -> str:
        """Format command list for Slack."""
        lines = ["*Available Commands*\n"]

        # Group by type
        by_type: dict[CommandType, list[CommandInfo]] = {}
        for cmd in commands:
            by_type.setdefault(cmd.command_type, []).append(cmd)

        type_labels = {
            CommandType.BUILTIN: "Built-in",
            CommandType.SKILL: "Skills",
            CommandType.TOOL: "Tools",
        }

        for cmd_type in [CommandType.BUILTIN, CommandType.SKILL, CommandType.TOOL]:
            if cmd_type in by_type:
                lines.append(f"\n*{type_labels[cmd_type]}:*")
                for cmd in by_type[cmd_type][:20]:  # Limit display
                    contextual = " 🧵" if cmd.contextual else ""
                    lines.append(f"• `{cmd.name}`{contextual} - {cmd.description[:60]}")

                if len(by_type[cmd_type]) > 20:
                    lines.append(f"  _...and {len(by_type[cmd_type]) - 20} more_")

        lines.append("\n_Use `@me help <command>` for details. 🧵 = supports thread context_")

        return "\n".join(lines)

    def _format_text_list(self, commands: list[CommandInfo]) -> str:
        """Format command list as plain text."""
        lines = ["Available Commands", "=" * 40]

        for cmd in commands:
            lines.append(f"{cmd.name} ({cmd.command_type.value}): {cmd.description}")

        return "\n".join(lines)

    def clear_cache(self) -> None:
        """Clear cached data."""
        self._skills_cache = None
        self._tools_cache = None


# Singleton instance
_registry: CommandRegistry | None = None


def get_registry() -> CommandRegistry:
    """Get the global command registry instance."""
    global _registry
    if _registry is None:
        _registry = CommandRegistry()
    return _registry


def list_commands(filter_text: str = "") -> list[CommandInfo]:
    """Convenience function to list commands."""
    return get_registry().list_commands(filter_text)


def get_command_help(name: str) -> CommandHelp | None:
    """Convenience function to get command help."""
    return get_registry().get_command_help(name)
