#!/usr/bin/env python3
"""
Generate skill graph data for neural network visualization.

Extracts:
- Skill nodes (name, description, inputs, outputs)
- Tool dependencies (which tools each skill uses)
- Skill-to-skill connections (nested skill_run calls)
- Intent keywords (from description and inputs)
- Persona mappings (which personas use which skills)

Outputs JSON for D3.js force-directed graph visualization.
"""

import json
import re
from pathlib import Path

import yaml


def load_personas(personas_dir: Path) -> dict:
    """Load all persona YAML files and extract skill mappings."""
    personas = {}

    for path in personas_dir.glob("*.yaml"):
        try:
            with open(path) as f:
                persona = yaml.safe_load(f)

            if not persona or not isinstance(persona, dict):
                continue

            name = persona.get("name", path.stem)
            skills = persona.get("skills", [])
            tools = persona.get("tools", [])

            personas[name] = {
                "name": name,
                "description": persona.get("description", ""),
                "skills": skills,
                "tools": tools,
            }
        except Exception as e:
            print(f"Error parsing persona {path}: {e}")

    return personas


def extract_intent_keywords(skill: dict) -> list[str]:
    """Extract intent keywords from skill description and inputs."""
    keywords = set()

    # From description
    desc = skill.get("description", "")
    # Common intent patterns
    intent_patterns = [
        r"\b(create|make|build|generate)\b",
        r"\b(deploy|release|ship|push)\b",
        r"\b(review|check|validate|verify)\b",
        r"\b(investigate|debug|troubleshoot|fix)\b",
        r"\b(start|begin|resume|work)\b",
        r"\b(close|finish|complete|end)\b",
        r"\b(monitor|watch|alert|notify)\b",
        r"\b(search|find|lookup|query)\b",
        r"\b(sync|update|refresh)\b",
        r"\b(cleanup|clean|remove|delete)\b",
    ]

    for pattern in intent_patterns:
        matches = re.findall(pattern, desc.lower())
        keywords.update(matches)

    # From input names
    for inp in skill.get("inputs", []):
        name = inp.get("name", "")
        if name in ["issue_key", "mr_id", "branch", "namespace", "environment"]:
            keywords.add(name.replace("_", " "))

    return list(keywords)[:5]  # Limit to top 5


def extract_tools_used(skill: dict) -> list[str]:
    """Extract tool names from skill steps."""
    tools = set()

    for step in skill.get("steps", []):
        tool = step.get("tool")
        if tool:
            # Normalize tool names
            if tool.startswith("persona_"):
                continue  # Skip persona loading
            tools.add(tool)

    return list(tools)


def extract_nested_skills(skill: dict) -> list[str]:
    """Extract skill_run calls (skill-to-skill connections)."""
    nested = set()

    for step in skill.get("steps", []):
        tool = step.get("tool")
        if tool == "skill_run":
            args = step.get("args", {})
            skill_name = args.get("skill_name")
            if skill_name:
                nested.add(skill_name)

    return list(nested)


def extract_explicit_links(skill: dict) -> dict:
    """Extract explicit skill relationships from links: metadata."""
    links = skill.get("links", {})
    return {
        "depends_on": (
            links.get("depends_on", [])
            if isinstance(links.get("depends_on"), list)
            else []
        ),
        "validates": (
            links.get("validates", [])
            if isinstance(links.get("validates"), list)
            else []
        ),
        "validated_by": (
            links.get("validated_by", [])
            if isinstance(links.get("validated_by"), list)
            else []
        ),
        "chains_to": (
            links.get("chains_to", [])
            if isinstance(links.get("chains_to"), list)
            else []
        ),
        "provides_context_for": (
            links.get("provides_context_for", [])
            if isinstance(links.get("provides_context_for"), list)
            else []
        ),
    }


def extract_outputs(skill: dict) -> list[str]:
    """Extract output types from skill."""
    outputs = []

    for output in skill.get("outputs", []):
        name = output.get("name", "")
        if name:
            outputs.append(name)

    # Also check step outputs for key results
    for step in skill.get("steps", []):
        output = step.get("output")
        if output and output in ["summary", "result", "briefing", "report"]:
            outputs.append(output)

    return list(set(outputs))[:3]


def categorize_skill(name: str, description: str) -> str:
    """Categorize skill into groups for coloring."""
    desc_lower = description.lower()

    if any(x in name for x in ["mr", "pr", "review", "commit"]):
        return "code"
    elif any(x in name for x in ["deploy", "ephemeral", "release", "konflux"]):
        return "deploy"
    elif any(x in name for x in ["jira", "issue", "sprint"]):
        return "jira"
    elif any(x in name for x in ["alert", "investigate", "debug", "prod"]):
        return "incident"
    elif any(x in name for x in ["coffee", "beer", "standup", "summary"]):
        return "daily"
    elif any(x in name for x in ["memory", "knowledge", "learn"]):
        return "memory"
    elif any(x in name for x in ["slack", "notify", "email"]):
        return "comms"
    elif any(x in desc_lower for x in ["clean", "sync", "refresh"]):
        return "maintenance"
    else:
        return "other"


def parse_skill_file(path: Path) -> dict | None:
    """Parse a single skill YAML file."""
    try:
        with open(path) as f:
            skill = yaml.safe_load(f)

        if not skill or not isinstance(skill, dict):
            return None

        name = skill.get("name", path.stem)
        description = skill.get("description", "")

        return {
            "id": name,
            "name": name,
            "description": description[:200] if description else "",
            "category": categorize_skill(name, description),
            "intents": extract_intent_keywords(skill),
            "tools": extract_tools_used(skill),
            "nested_skills": extract_nested_skills(skill),
            "explicit_links": extract_explicit_links(skill),
            "outputs": extract_outputs(skill),
            "version": skill.get("version", "1.0"),
            "input_count": len(skill.get("inputs", [])),
            "step_count": len(skill.get("steps", [])),
        }
    except Exception as e:
        print(f"Error parsing {path}: {e}")
        return None


def generate_graph_data(skills_dir: Path, personas_dir: Path) -> dict:
    """Generate full graph data structure."""
    nodes = []
    links = []
    tool_nodes = {}
    intent_nodes = {}

    # Load personas first
    personas = load_personas(personas_dir)

    # Build skill -> personas mapping
    skill_to_personas = {}
    for persona_name, persona_data in personas.items():
        for skill_name in persona_data.get("skills", []):
            if skill_name not in skill_to_personas:
                skill_to_personas[skill_name] = []
            skill_to_personas[skill_name].append(persona_name)

    # Parse all skills
    skill_files = list(skills_dir.glob("*.yaml"))
    skills = {}

    for path in skill_files:
        skill = parse_skill_file(path)
        if skill:
            skills[skill["id"]] = skill
            # Get personas that use this skill
            skill_personas = skill_to_personas.get(skill["id"], [])
            nodes.append(
                {
                    "id": skill["id"],
                    "type": "skill",
                    "category": skill["category"],
                    "label": skill["name"].replace("_", " ").title(),
                    "description": skill["description"],
                    "tools": skill["tools"],
                    "intents": skill["intents"],
                    "outputs": skill["outputs"],
                    "personas": skill_personas,  # Which personas use this skill
                    "size": 8 + min(skill["step_count"], 20),  # Size by complexity
                }
            )

    # Create skill-to-skill links from runtime calls (skill_run)
    for skill_id, skill in skills.items():
        for nested in skill["nested_skills"]:
            if nested in skills:
                links.append(
                    {
                        "source": skill_id,
                        "target": nested,
                        "type": "calls",
                        "strength": 0.8,
                    }
                )

    # Create skill-to-skill links from explicit links: metadata
    link_type_config = {
        "depends_on": {"strength": 0.9, "type": "depends_on"},
        "validates": {"strength": 0.7, "type": "validates"},
        "validated_by": {"strength": 0.6, "type": "validated_by"},
        "chains_to": {"strength": 0.5, "type": "chains_to"},
        "provides_context_for": {"strength": 0.4, "type": "provides_context"},
    }

    for skill_id, skill in skills.items():
        for link_type, config in link_type_config.items():
            for target in skill["explicit_links"].get(link_type, []):
                if target in skills:
                    # Avoid duplicate links (already captured by nested_skills/calls)
                    existing = any(
                        lnk["source"] == skill_id and lnk["target"] == target
                        for lnk in links
                    )
                    if not existing:
                        links.append(
                            {
                                "source": skill_id,
                                "target": target,
                                "type": config["type"],
                                "strength": config["strength"],
                            }
                        )

    # Create tool nodes and links
    all_tools = set()
    for skill in skills.values():
        all_tools.update(skill["tools"])

    for tool in all_tools:
        tool_id = f"tool_{tool}"
        tool_nodes[tool] = tool_id
        nodes.append(
            {
                "id": tool_id,
                "type": "tool",
                "category": "tool",
                "label": tool.replace("_", " "),
                "size": 4,
            }
        )

    # Link skills to tools
    for skill_id, skill in skills.items():
        for tool in skill["tools"]:
            tool_id = f"tool_{tool}"
            links.append(
                {
                    "source": skill_id,
                    "target": tool_id,
                    "type": "uses",
                    "strength": 0.3,
                }
            )

    # Create intent nodes (aggregate common intents)
    intent_counts = {}
    for skill in skills.values():
        for intent in skill["intents"]:
            intent_counts[intent] = intent_counts.get(intent, 0) + 1

    # Only create nodes for intents used by multiple skills
    for intent, count in intent_counts.items():
        if count >= 2:
            intent_id = f"intent_{intent.replace(' ', '_')}"
            intent_nodes[intent] = intent_id
            nodes.append(
                {
                    "id": intent_id,
                    "type": "intent",
                    "category": "intent",
                    "label": intent.title(),
                    "size": 5 + count,
                }
            )

    # Link intents to skills
    for skill_id, skill in skills.items():
        for intent in skill["intents"]:
            if intent in intent_nodes:
                intent_id = intent_nodes[intent]
                links.append(
                    {
                        "source": intent_id,
                        "target": skill_id,
                        "type": "triggers",
                        "strength": 0.5,
                    }
                )

    # Calculate statistics
    categories = {}
    for skill in skills.values():
        cat = skill["category"]
        categories[cat] = categories.get(cat, 0) + 1

    # Link type statistics
    link_type_counts = {}
    for link in links:
        lt = link["type"]
        link_type_counts[lt] = link_type_counts.get(lt, 0) + 1

    skills_with_links = sum(
        1
        for s in skills.values()
        if any(s["explicit_links"].get(lt) for lt in link_type_config)
    )

    # Build persona data for the visualization
    persona_data = {}
    for name, data in personas.items():
        persona_data[name] = {
            "name": name,
            "description": data.get("description", ""),
            "skill_count": len(data.get("skills", [])),
            "skills": data.get("skills", []),
        }

    return {
        "nodes": nodes,
        "links": links,
        "personas": persona_data,
        "stats": {
            "skill_count": len(skills),
            "tool_count": len(all_tools),
            "intent_count": len(intent_nodes),
            "link_count": len(links),
            "persona_count": len(personas),
            "categories": categories,
            "link_types": link_type_counts,
            "skills_with_links": skills_with_links,
        },
    }


def main():
    """Generate skill graph JSON."""
    # Find skills directory
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    skills_dir = project_root / "skills"
    personas_dir = project_root / "personas"

    if not skills_dir.exists():
        print(f"Skills directory not found: {skills_dir}")
        return

    print(f"Parsing skills from: {skills_dir}")
    print(f"Parsing personas from: {personas_dir}")

    graph_data = generate_graph_data(skills_dir, personas_dir)

    # Output to docs/slides for the visualization
    output_dir = project_root / "docs" / "slides"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "skill_graph_data.json"
    with open(output_file, "w") as f:
        json.dump(graph_data, f, indent=2)

    print(f"\nGenerated: {output_file}")
    print("Stats:")
    for key, value in graph_data["stats"].items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
