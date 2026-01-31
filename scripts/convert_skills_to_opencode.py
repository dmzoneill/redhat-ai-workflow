#!/usr/bin/env python3
"""
Convert MCP YAML skills to OpenCode-compatible SKILL.md format.

This script reads skills from ./skills/*.yaml and generates:
- .opencode/skills/<name>/SKILL.md (OpenCode format)
- .claude/skills/<name>/SKILL.md (Claude Code compatible)

OpenCode skills are instruction-based (not executable), so they tell
the AI to invoke the MCP skill_run tool with the appropriate parameters.
"""

import os
import re
import yaml
from pathlib import Path
from typing import Dict, Any, List


def sanitize_skill_name(name: str) -> str:
    """
    Convert skill name to OpenCode format.
    
    OpenCode requires:
    - Lowercase alphanumeric with single hyphen separators
    - No consecutive hyphens
    - 1-64 characters
    """
    # Convert underscores to hyphens
    name = name.replace('_', '-')
    # Remove any non-alphanumeric except hyphens
    name = re.sub(r'[^a-z0-9-]', '', name.lower())
    # Replace consecutive hyphens with single hyphen
    name = re.sub(r'-+', '-', name)
    # Remove leading/trailing hyphens
    name = name.strip('-')
    # Truncate to 64 chars
    return name[:64]


def format_inputs_table(inputs: List[Dict[str, Any]]) -> str:
    """Generate markdown table for inputs."""
    if not inputs:
        return "This skill has no inputs.\n"
    
    lines = [
        "| Input | Type | Required | Default | Description |",
        "|-------|------|----------|---------|-------------|"
    ]
    
    for inp in inputs:
        name = inp.get('name', '')
        type_ = inp.get('type', 'string')
        required = 'Yes' if inp.get('required', False) else 'No'
        default = inp.get('default', '')
        if default == '':
            default = '-'
        elif isinstance(default, bool):
            default = str(default).lower()
        desc = inp.get('description', '').replace('\n', ' ')
        
        lines.append(f"| `{name}` | {type_} | {required} | `{default}` | {desc} |")
    
    return '\n'.join(lines) + '\n'


def extract_tools_used(steps: List[Dict[str, Any]]) -> List[str]:
    """Extract unique tool names from skill steps."""
    tools = set()
    for step in steps:
        if 'tool' in step:
            tools.add(step['tool'])
    return sorted(tools)


def generate_skill_md(skill_data: Dict[str, Any], yaml_filename: str) -> str:
    """Generate SKILL.md content from YAML skill data."""
    
    name = skill_data.get('name', '')
    description = skill_data.get('description', '').strip()
    version = skill_data.get('version', '1.0')
    inputs = skill_data.get('inputs', [])
    steps = skill_data.get('steps', [])
    
    # Extract first sentence for short description
    short_desc = description.split('\n')[0].strip()
    if short_desc.endswith('.'):
        short_desc = short_desc[:-1]
    
    # Build tools list
    tools = extract_tools_used(steps)
    tools_section = ""
    if tools:
        tools_section = "\n## MCP Tools Used\n\n"
        for tool in tools:
            tools_section += f"- `{tool}`\n"
    
    # Generate example JSON for inputs
    if inputs:
        example_json = "{\n"
        for inp in inputs:
            inp_name = inp.get('name', '')
            example_value = inp.get('default', '')
            if example_value == '':
                if inp.get('type') == 'boolean':
                    example_value = 'true'
                elif inp.get('type') == 'number':
                    example_value = '1'
                else:
                    example_value = f'"example-{inp_name}"'
            elif isinstance(example_value, bool):
                example_value = str(example_value).lower()
            elif isinstance(example_value, str) and example_value:
                example_value = f'"{example_value}"'
            
            example_json += f'  "{inp_name}": {example_value}'
            if inp != inputs[-1]:
                example_json += ','
            example_json += '\n'
        example_json += "}"
    else:
        example_json = "{}"
    
    # Build markdown
    md = f"""---
name: {sanitize_skill_name(name)}
description: {short_desc}
license: MIT
compatibility: opencode
metadata:
  version: "{version}"
  source: {yaml_filename}
  executable: "true"
---

# {name}

{description}

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("{name}", '{example_json}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

"""
    
    # Add step descriptions
    for i, step in enumerate(steps, 1):
        step_desc = step.get('description', step.get('name', f'Step {i}'))
        md += f"{i}. **{step_desc}**\n"
    
    md += f"""
## Inputs

{format_inputs_table(inputs)}

## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the {name} skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("{name}", '{example_json}')
```

### Via Command (if configured)

```
/{name.replace('_', '-')}
```
{tools_section}
## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/{yaml_filename}`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/{name}.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
"""
    
    return md


def convert_skill(yaml_path: Path, output_base: Path, format_type: str = "opencode"):
    """Convert a single YAML skill to SKILL.md format."""
    
    # Read YAML
    with open(yaml_path, 'r') as f:
        skill_data = yaml.safe_load(f)
    
    if not skill_data or 'name' not in skill_data:
        print(f"⚠️  Skipping {yaml_path.name}: No 'name' field found")
        return
    
    skill_name = skill_data['name']
    sanitized_name = sanitize_skill_name(skill_name)
    
    # Generate SKILL.md content
    skill_md = generate_skill_md(skill_data, yaml_path.name)
    
    # Create output directory
    if format_type == "opencode":
        output_dir = output_base / ".opencode" / "skills" / sanitized_name
    else:  # claude
        output_dir = output_base / ".claude" / "skills" / sanitized_name
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Write SKILL.md
    output_file = output_dir / "SKILL.md"
    with open(output_file, 'w') as f:
        f.write(skill_md)
    
    print(f"✓ {skill_name} → {output_file}")


def main():
    """Convert all YAML skills to OpenCode format."""
    
    # Paths
    project_root = Path(__file__).parent.parent
    skills_dir = project_root / "skills"
    
    if not skills_dir.exists():
        print(f"❌ Skills directory not found: {skills_dir}")
        return
    
    # Get all YAML files
    yaml_files = sorted(skills_dir.glob("*.yaml"))
    
    if not yaml_files:
        print(f"❌ No YAML skills found in {skills_dir}")
        return
    
    print(f"Found {len(yaml_files)} skills to convert\n")
    
    # Convert to both formats
    print("Converting to OpenCode format (.opencode/skills/)...")
    for yaml_file in yaml_files:
        try:
            convert_skill(yaml_file, project_root, "opencode")
        except Exception as e:
            print(f"❌ Error converting {yaml_file.name}: {e}")
    
    print("\nConverting to Claude Code format (.claude/skills/)...")
    for yaml_file in yaml_files:
        try:
            convert_skill(yaml_file, project_root, "claude")
        except Exception as e:
            print(f"❌ Error converting {yaml_file.name}: {e}")
    
    print("\n✅ Conversion complete!")
    print("\nGenerated files:")
    print("  - .opencode/skills/<name>/SKILL.md (OpenCode format)")
    print("  - .claude/skills/<name>/SKILL.md (Claude Code compatible)")
    print("\nThese skills tell the AI to invoke your MCP skill engine.")


if __name__ == "__main__":
    main()
