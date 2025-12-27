"""Resource Handlers - Data sources the AI can read.

Provides MCP resources for:
- Memory state (current work, learned patterns)
- Configuration (agents, skills, repositories)
"""

from typing import TYPE_CHECKING

import yaml

from .constants import AGENTS_DIR, MEMORY_DIR, SKILLS_DIR

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_resources(server: "FastMCP", load_config_fn) -> int:
    """Register resources with the MCP server.

    Args:
        server: The FastMCP server instance
        load_config_fn: Function to load config.json
    """
    resource_count = 0

    @server.resource("memory://state/current_work")
    async def resource_current_work() -> str:
        """Current work state - active issues, branches, MRs."""
        work_file = MEMORY_DIR / "state" / "current_work.yaml"
        if work_file.exists():
            return work_file.read_text()
        return "# No current work tracked\nactive_issues: []\nopen_mrs: []\nfollow_ups: []"

    resource_count += 1

    @server.resource("memory://learned/patterns")
    async def resource_patterns() -> str:
        """Known error patterns and solutions."""
        patterns_file = MEMORY_DIR / "learned" / "patterns.yaml"
        if patterns_file.exists():
            return patterns_file.read_text()
        return "# No patterns recorded yet\npatterns: []"

    resource_count += 1

    @server.resource("config://agents")
    async def resource_agents() -> str:
        """Available agent configurations."""
        agents = []
        if AGENTS_DIR.exists():
            for f in AGENTS_DIR.glob("*.yaml"):
                try:
                    with open(f) as fp:
                        data = yaml.safe_load(fp)
                    agents.append(
                        {
                            "name": data.get("name", f.stem),
                            "description": data.get("description", ""),
                            "tools": data.get("tools", []),
                            "skills": data.get("skills", []),
                        }
                    )
                except Exception:
                    pass
        return yaml.dump({"agents": agents}, default_flow_style=False)

    resource_count += 1

    @server.resource("config://skills")
    async def resource_skills() -> str:
        """Available skill definitions."""
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

    resource_count += 1

    @server.resource("config://repositories")
    async def resource_repositories() -> str:
        """Configured repositories from config.json."""
        config = load_config_fn()
        repos = config.get("repositories", {})
        return yaml.dump({"repositories": repos}, default_flow_style=False)

    resource_count += 1

    return resource_count
