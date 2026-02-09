#!/usr/bin/env python3
"""
Analyze all skills to extract tool usage and categorize tools into basic/extra.
"""

import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set

import yaml

# Project root
PROJECT_ROOT = Path(__file__).parent.parent


def extract_tools_from_skill(skill_path: Path) -> Set[str]:
    """Extract all MCP tool calls from a skill YAML file."""
    tools_used = set()

    try:
        with open(skill_path, "r", encoding="utf-8") as f:
            skill = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Error: File not found: {skill_path}")
        return tools_used
    except yaml.YAMLError as e:
        print(f"Error parsing {skill_path}: {e}")
        return tools_used

    # Extract tools from steps
    steps = skill.get("steps", [])
    for step in steps:
        # Direct tool calls
        if "tool" in step:
            tool_name = step["tool"]
            tools_used.add(tool_name)

        # Tool calls in compute blocks (less common but possible)
        if "compute" in step:
            # Look for patterns like tool_name(...) or "tool_name"
            # This is heuristic-based
            # Common pattern: tool: function_name in YAML or call in Python
            pass

    return tools_used


def analyze_all_skills() -> Dict[str, Set[str]]:
    """Analyze all skills and return tool usage by module."""
    skills_dir = PROJECT_ROOT / "skills"
    all_tools_used = set()
    skill_tool_map = {}

    for skill_file in skills_dir.glob("*.yaml"):
        tools = extract_tools_from_skill(skill_file)
        skill_tool_map[skill_file.name] = tools
        all_tools_used.update(tools)

    # Organize by module
    module_tools = defaultdict(lambda: {"used": set(), "all": set()})

    # Map tool names to modules based on naming convention
    # aa_git tools: git_*
    # aa_gitlab tools: gitlab_*
    # aa_jira tools: jira_*
    # etc.

    for tool in all_tools_used:
        prefix = tool.split("_")[0] if "_" in tool else tool
        module = f"aa_{prefix}"
        module_tools[module]["used"].add(tool)

    return {
        "skills": skill_tool_map,
        "all_tools": all_tools_used,
        "by_module": module_tools,
    }


def get_all_tools_from_modules() -> Dict[str, List[str]]:
    """Get all available tools from each module by reading the source files."""
    tool_modules_dir = PROJECT_ROOT / "tool_modules"
    module_tools = {}

    for module_dir in tool_modules_dir.iterdir():
        if not module_dir.is_dir() or not module_dir.name.startswith("aa_"):
            continue

        module_name = module_dir.name
        tools = []

        # Check for src/tools.py, src/tools_basic.py, src/tools_extra.py
        src_dir = module_dir / "src"
        if not src_dir.exists():
            continue

        for tools_file in src_dir.glob("tools*.py"):
            try:
                with open(tools_file, "r", encoding="utf-8") as f:
                    content = f.read()
            except OSError as e:
                print(f"Warning: Could not read {tools_file}: {e}")
                continue

            # Extract function names with @registry.tool() decorator
            # Pattern: @registry.tool()\n    async def function_name(
            # or @auto_heal()\n    @registry.tool()\n    async def function_name(

            # Look for async def followed by function name that appears after @registry.tool() or @mcp.tool()
            lines = content.split("\n")
            for i, line in enumerate(lines):
                # Check if line has registry.tool() or mcp.tool()
                if (
                    "@registry.tool()" in line
                    or "@registry.tool(" in line
                    or "@mcp.tool()" in line
                    or "@mcp.tool(" in line
                ):
                    # Look ahead for the next 'def ' or 'async def'
                    for j in range(i + 1, min(i + 5, len(lines))):
                        next_line = lines[j]
                        match = re.match(r"\s*(?:async\s+)?def\s+(\w+)\s*\(", next_line)
                        if match:
                            tools.append(match.group(1))
                            break

        module_tools[module_name] = sorted(set(tools))

    return module_tools


def generate_report(analysis: Dict, all_tools: Dict[str, List[str]]) -> str:
    """Generate a comprehensive report."""
    report = []
    report.append("# Skill Tool Usage Analysis\n")
    report.append(f"**Total Skills Analyzed:** {len(analysis['skills'])}\n")
    report.append(f"**Total Unique Tools Used:** {len(analysis['all_tools'])}\n\n")

    # Per-skill breakdown
    report.append("## Tools Used Per Skill\n")
    for skill_name, tools in sorted(analysis["skills"].items()):
        report.append(f"### {skill_name}")
        report.append(f"- **Tool Count:** {len(tools)}")
        if tools:
            report.append(f"- **Tools:** {', '.join(sorted(tools))}")
        else:
            report.append("- **Tools:** (none - all compute steps)")
        report.append("")

    # Module breakdown
    report.append("\n## Tool Usage by Module\n")

    for module_name in sorted(all_tools.keys()):
        available_tools = set(all_tools[module_name])
        used_tools = set()

        # Find which tools from this module are used in skills
        for tool in analysis["all_tools"]:
            if tool in available_tools:
                used_tools.add(tool)

        unused_tools = available_tools - used_tools

        report.append(f"### {module_name}")
        report.append(f"- **Total Tools:** {len(available_tools)}")
        report.append(f"- **Used in Skills:** {len(used_tools)}")
        report.append(f"- **Unused:** {len(unused_tools)}")
        report.append(
            f"- **Used Tools:** {', '.join(sorted(used_tools)) if used_tools else '(none)'}"
        )
        report.append(
            f"- **Unused Tools:** {', '.join(sorted(unused_tools)) if unused_tools else '(none)'}"
        )
        report.append("")

    # Summary statistics
    report.append("\n## Summary Statistics\n")
    total_tools = sum(len(tools) for tools in all_tools.values())
    total_used = len(analysis["all_tools"])
    total_unused = total_tools - total_used

    report.append(f"- **Total Tools Available:** {total_tools}")
    report.append(f"- **Tools Used in Skills:** {total_used}")
    report.append(f"- **Tools Unused:** {total_unused}")
    if total_tools > 0:
        report.append(f"- **Usage Rate:** {(total_used / total_tools * 100):.1f}%")
    else:
        report.append("- **Usage Rate:** N/A (no tools found)")

    return "\n".join(report)


def main():
    print("Analyzing skills...")
    analysis = analyze_all_skills()

    print("Discovering tools from modules...")
    all_tools = get_all_tools_from_modules()

    print("Generating report...")
    report = generate_report(analysis, all_tools)

    # Save report
    output_file = PROJECT_ROOT / ".claude" / "skill-tool-usage-report.md"
    try:
        output_file.parent.mkdir(exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n✅ Report saved to: {output_file}")
    except OSError as e:
        print(f"\n❌ Failed to save report: {e}")
        print("\n--- Report ---")
        print(report)
    print("\n📊 Quick Stats:")
    print(f"   - Skills analyzed: {len(analysis['skills'])}")
    print(f"   - Unique tools used: {len(analysis['all_tools'])}")
    print(f"   - Modules found: {len(all_tools)}")


if __name__ == "__main__":
    main()
