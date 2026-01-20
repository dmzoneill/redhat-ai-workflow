"""Resource Handlers - Data sources the AI can read.

Provides MCP resources for:
- Memory state (current work, learned patterns)
- Configuration (agents, skills, repositories)
"""

from pathlib import Path
from typing import TYPE_CHECKING

import yaml

# Support both package import and direct loading
try:
    from .constants import MEMORY_DIR, PERSONAS_DIR, SKILLS_DIR
except ImportError:
    TOOL_MODULES_DIR = Path(__file__).parent.parent.parent
    PROJECT_DIR = TOOL_MODULES_DIR.parent
    PERSONAS_DIR = PROJECT_DIR / "personas"
    MEMORY_DIR = PROJECT_DIR / "memory"
    SKILLS_DIR = PROJECT_DIR / "skills"

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


async def _get_current_work() -> str:
    """Get current work state resource for the current project."""
    # Import here to avoid circular imports
    try:
        from tool_modules.aa_workflow.src.chat_context import get_project_work_state_path
    except ImportError:
        try:
            from .chat_context import get_project_work_state_path
        except ImportError:
            from chat_context import get_project_work_state_path

    work_file = get_project_work_state_path()
    if work_file.exists():
        return work_file.read_text()
    return "# No current work tracked for this project\nactive_issues: []\nopen_mrs: []\nfollow_ups: []"


async def _get_patterns() -> str:
    """Get learned error patterns resource."""
    patterns_file = MEMORY_DIR / "learned" / "patterns.yaml"
    if patterns_file.exists():
        return patterns_file.read_text()
    return "# No patterns recorded yet\npatterns: []"


async def _get_runbooks() -> str:
    """Get learned runbooks resource."""
    runbooks_file = MEMORY_DIR / "learned" / "runbooks.yaml"
    if runbooks_file.exists():
        return runbooks_file.read_text()
    return "# No runbooks recorded yet\nrunbooks: {}"


async def _get_service_quirks() -> str:
    """Get service quirks resource."""
    quirks_file = MEMORY_DIR / "learned" / "service_quirks.yaml"
    if quirks_file.exists():
        return quirks_file.read_text()
    return "# No service quirks recorded yet\nservices: {}"


async def _get_environments() -> str:
    """Get environment health status resource."""
    env_file = MEMORY_DIR / "state" / "environments.yaml"
    if env_file.exists():
        return env_file.read_text()
    return "# No environment state\nenvironments: {}"


async def _get_personas() -> str:
    """Get available persona configurations resource."""
    personas = []
    if PERSONAS_DIR.exists():
        for f in PERSONAS_DIR.glob("*.yaml"):
            try:
                with open(f) as fp:
                    data = yaml.safe_load(fp)
                personas.append(
                    {
                        "name": data.get("name", f.stem),
                        "description": data.get("description", ""),
                        "tools": data.get("tools", []),
                        "skills": data.get("skills", []),
                    }
                )
            except Exception:
                pass
    return yaml.dump({"personas": personas}, default_flow_style=False)


async def _get_skills() -> str:
    """Get available skill definitions resource."""
    skills = []
    if SKILLS_DIR.exists():
        for f in SKILLS_DIR.glob("*.yaml"):
            try:
                with open(f) as fp:
                    data = yaml.safe_load(fp)
                skills.append(
                    {
                        "name": data.get("name", f.stem),
                        "description": data.get("description", ""),
                        "inputs": [i.get("name") for i in data.get("inputs", [])],
                    }
                )
            except Exception:
                pass
    return yaml.dump({"skills": skills}, default_flow_style=False)


def _get_repositories(load_config_fn) -> str:
    """Get configured repositories resource."""
    config = load_config_fn()
    repos = config.get("repositories", {})
    return yaml.dump({"repositories": repos}, default_flow_style=False)


def register_resources(server: "FastMCP", load_config_fn) -> int:
    """Register resources with the MCP server.

    Args:
        server: The FastMCP server instance
        load_config_fn: Function to load config.json
    """

    @server.resource("memory://state/current_work")
    async def resource_current_work() -> str:
        """Current work state - active issues, branches, MRs."""
        return await _get_current_work()

    @server.resource("memory://learned/patterns")
    async def resource_patterns() -> str:
        """Known error patterns and solutions."""
        return await _get_patterns()

    @server.resource("memory://learned/runbooks")
    async def resource_runbooks() -> str:
        """Learned runbooks and operational procedures."""
        return await _get_runbooks()

    @server.resource("memory://learned/service_quirks")
    async def resource_service_quirks() -> str:
        """Service quirks and tribal knowledge."""
        return await _get_service_quirks()

    @server.resource("memory://state/environments")
    async def resource_environments() -> str:
        """Environment health status (stage, prod, ephemeral)."""
        return await _get_environments()

    @server.resource("config://personas")
    async def resource_personas() -> str:
        """Available persona configurations."""
        return await _get_personas()

    @server.resource("config://skills")
    async def resource_skills() -> str:
        """Available skill definitions."""
        return await _get_skills()

    @server.resource("config://repositories")
    async def resource_repositories() -> str:
        """Configured repositories from config.json."""
        return _get_repositories(load_config_fn)

    return 8  # Number of registered resources
