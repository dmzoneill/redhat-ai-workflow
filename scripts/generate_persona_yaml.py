#!/usr/bin/env python3
"""Generate and validate persona YAML files.

This script dynamically discovers available tool modules and skills,
then validates or regenerates persona YAML files.

Features:
- Discovers all tool modules from tool_modules/aa_*/src/tools*.py
- Discovers all skills from skills/*.yaml
- Validates that modules/skills in personas exist
- Regenerates personas without hardcoded tool counts

Usage:
    # Validate all personas
    python scripts/generate_persona_yaml.py --validate

    # Regenerate a specific persona
    python scripts/generate_persona_yaml.py --regenerate admin

    # Regenerate all personas
    python scripts/generate_persona_yaml.py --regenerate-all

    # List available modules and skills
    python scripts/generate_persona_yaml.py --list
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
TOOL_MODULES_DIR = PROJECT_ROOT / "tool_modules"
SKILLS_DIR = PROJECT_ROOT / "skills"
PERSONAS_DIR = PROJECT_ROOT / "personas"


def discover_tool_modules() -> dict[str, list[str]]:
    """Discover all tool modules and their variants.

    Scans tool_modules/aa_*/src/ for tools*.py files.

    Returns:
        Dict mapping base module name to list of available variants.
        Example: {"git": ["git", "git_core", "git_basic", "git_extra"]}
    """
    modules: dict[str, list[str]] = {}

    if not TOOL_MODULES_DIR.exists():
        print(f"Warning: Tool modules directory not found: {TOOL_MODULES_DIR}")
        return modules

    for module_dir in sorted(TOOL_MODULES_DIR.iterdir()):
        if not module_dir.is_dir() or not module_dir.name.startswith("aa_"):
            continue

        # Extract base name (e.g., "aa_git" -> "git")
        base_name = module_dir.name[3:]
        src_dir = module_dir / "src"

        if not src_dir.exists():
            continue

        variants = []

        # Check for each variant
        if (src_dir / "tools.py").exists():
            variants.append(base_name)
        if (src_dir / "tools_core.py").exists():
            variants.append(f"{base_name}_core")
        if (src_dir / "tools_basic.py").exists():
            variants.append(f"{base_name}_basic")
        if (src_dir / "tools_extra.py").exists():
            variants.append(f"{base_name}_extra")
        if (src_dir / "tools_style.py").exists():
            variants.append(f"{base_name}_style")

        if variants:
            modules[base_name] = variants

    return modules


def get_all_module_names() -> set[str]:
    """Get flat set of all available module names (including variants and base names).

    The persona loader accepts:
    - Base names: "git" -> resolves to git_basic or git_core
    - Explicit variants: "git_core", "git_basic", "git_extra"

    So we include both base names and all variants.
    """
    modules = discover_tool_modules()
    all_names = set()
    for base_name, variants in modules.items():
        # Include the base name (persona loader resolves it)
        all_names.add(base_name)
        # Include all explicit variants
        all_names.update(variants)
    return all_names


def discover_skills() -> list[str]:
    """Discover all available skills from skills/*.yaml and skills/**/*.yaml.

    Handles both flat skills (skills/coffee.yaml) and nested skills
    (skills/performance/collect_daily.yaml -> "performance/collect_daily").

    Returns:
        Sorted list of skill names/paths (without .yaml extension).
    """
    if not SKILLS_DIR.exists():
        print(f"Warning: Skills directory not found: {SKILLS_DIR}")
        return []

    skills = []

    # Top-level skills
    for skill_file in SKILLS_DIR.glob("*.yaml"):
        skills.append(skill_file.stem)

    # Nested skills (e.g., performance/collect_daily)
    for subdir in SKILLS_DIR.iterdir():
        if subdir.is_dir() and not subdir.name.startswith("."):
            for skill_file in subdir.glob("*.yaml"):
                # Format as "subdir/skill_name"
                skills.append(f"{subdir.name}/{skill_file.stem}")

    return sorted(skills)


def load_persona(persona_name: str) -> dict | None:
    """Load a persona YAML file.

    Args:
        persona_name: Name of the persona (without .yaml extension)

    Returns:
        Parsed YAML dict or None if not found
    """
    persona_file = PERSONAS_DIR / f"{persona_name}.yaml"
    if not persona_file.exists():
        return None

    try:
        with open(persona_file) as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"Error parsing {persona_file}: {e}")
        return None


def validate_persona(persona_name: str) -> list[str]:
    """Validate a persona's modules and skills exist.

    Args:
        persona_name: Name of the persona to validate

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []
    persona = load_persona(persona_name)

    if persona is None:
        return [f"Persona '{persona_name}' not found"]

    available_modules = get_all_module_names()
    available_skills = set(discover_skills())

    # Validate tools/modules
    tools = persona.get("tools", [])
    for tool in tools:
        # Extract module name (strip comments)
        module_name = tool.split("#")[0].strip() if isinstance(tool, str) else str(tool)
        module_name = module_name.strip("- ").strip()

        if module_name and module_name not in available_modules:
            errors.append(f"Unknown module: '{module_name}'")

    # Validate skills
    skills = persona.get("skills", [])
    for skill in skills:
        # Extract skill name (strip comments)
        skill_name = (
            skill.split("#")[0].strip() if isinstance(skill, str) else str(skill)
        )
        skill_name = skill_name.strip("- ").strip()

        if skill_name and skill_name not in available_skills:
            errors.append(f"Unknown skill: '{skill_name}'")

    return errors


def validate_all_personas() -> dict[str, list[str]]:
    """Validate all personas.

    Returns:
        Dict mapping persona name to list of errors
    """
    results = {}

    for persona_file in sorted(PERSONAS_DIR.glob("*.yaml")):
        persona_name = persona_file.stem
        errors = validate_persona(persona_name)
        if errors:
            results[persona_name] = errors

    return results


def regenerate_persona(persona_name: str, dry_run: bool = False) -> bool:
    """Regenerate a persona YAML file.

    Removes hardcoded tool counts while preserving structure and comments.

    Args:
        persona_name: Name of the persona to regenerate
        dry_run: If True, print changes without writing

    Returns:
        True if successful, False otherwise
    """
    persona_file = PERSONAS_DIR / f"{persona_name}.yaml"
    if not persona_file.exists():
        print(f"Error: Persona '{persona_name}' not found")
        return False

    # Read original content
    original_content = persona_file.read_text()

    # Remove tool counts from comments (e.g., "# 18 tools - " -> "# ")
    # Pattern: "# <number> tools - <description>" -> "# <description>"
    modified_content = re.sub(
        r"#\s*~?\d+\s*tools?\s*-\s*",
        "# ",
        original_content,
    )

    # Remove standalone total lines (e.g., "# Total: ~78 tools")
    modified_content = re.sub(
        r"\n#\s*Total:\s*~?\d+\s*tools?\s*\n",
        "\n",
        modified_content,
    )

    # Add header comment if not present
    if "# Auto-validated:" not in modified_content:
        # Find the first non-comment line after the header
        lines = modified_content.split("\n")
        header_end = 0
        for i, line in enumerate(lines):
            if line.strip() and not line.strip().startswith("#"):
                header_end = i
                break

        # Insert validation timestamp after header comments
        timestamp = datetime.now().strftime("%Y-%m-%d")
        validation_comment = f"# Auto-validated: {timestamp}\n# Use tool_list() to discover available tools\n"

        # Only add if there's a header
        if header_end > 0:
            lines.insert(header_end, validation_comment)
            modified_content = "\n".join(lines)

    if dry_run:
        if original_content != modified_content:
            print(f"\n=== {persona_name}.yaml (changes) ===")
            print(
                modified_content[:500] + "..."
                if len(modified_content) > 500
                else modified_content
            )
        else:
            print(f"{persona_name}.yaml: No changes needed")
        return True

    # Write modified content
    if original_content != modified_content:
        persona_file.write_text(modified_content)
        print(f"Updated: {persona_file}")
        return True
    else:
        print(f"No changes: {persona_file}")
        return True


def regenerate_all_personas(dry_run: bool = False) -> int:
    """Regenerate all persona YAML files.

    Args:
        dry_run: If True, print changes without writing

    Returns:
        Number of personas updated
    """
    updated = 0

    for persona_file in sorted(PERSONAS_DIR.glob("*.yaml")):
        persona_name = persona_file.stem
        if regenerate_persona(persona_name, dry_run):
            updated += 1

    return updated


def list_available() -> None:
    """List all available modules and skills."""
    modules = discover_tool_modules()
    skills = discover_skills()

    print("=" * 60)
    print("AVAILABLE TOOL MODULES")
    print("=" * 60)
    print(f"\nTotal: {len(modules)} base modules\n")

    for base_name, variants in sorted(modules.items()):
        print(f"  {base_name}:")
        for variant in variants:
            suffix = variant.replace(base_name, "") or "(base)"
            print(f"    - {variant} {suffix}")

    print("\n" + "=" * 60)
    print("AVAILABLE SKILLS")
    print("=" * 60)
    print(f"\nTotal: {len(skills)} skills\n")

    # Group skills by prefix
    grouped: dict[str, list[str]] = {}
    for skill in skills:
        if "_" in skill:
            prefix = skill.split("_")[0]
        else:
            prefix = "general"
        grouped.setdefault(prefix, []).append(skill)

    for prefix, skill_list in sorted(grouped.items()):
        print(f"  {prefix}:")
        for skill in skill_list[:10]:  # Limit display
            print(f"    - {skill}")
        if len(skill_list) > 10:
            print(f"    ... and {len(skill_list) - 10} more")


def main():
    parser = argparse.ArgumentParser(
        description="Generate and validate persona YAML files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --validate              Validate all personas
  %(prog)s --regenerate admin      Regenerate admin persona
  %(prog)s --regenerate-all        Regenerate all personas
  %(prog)s --list                  List available modules and skills
  %(prog)s --dry-run --regenerate-all  Preview changes without writing
        """,
    )

    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate all personas (check modules/skills exist)",
    )
    parser.add_argument(
        "--regenerate",
        metavar="PERSONA",
        help="Regenerate a specific persona",
    )
    parser.add_argument(
        "--regenerate-all",
        action="store_true",
        help="Regenerate all personas",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available modules and skills",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing files",
    )

    args = parser.parse_args()

    # Default to --list if no args
    if not any([args.validate, args.regenerate, args.regenerate_all, args.list]):
        args.list = True

    if args.list:
        list_available()

    if args.validate:
        print("\n" + "=" * 60)
        print("VALIDATING PERSONAS")
        print("=" * 60 + "\n")

        errors = validate_all_personas()
        if errors:
            print("Validation errors found:\n")
            for persona, persona_errors in errors.items():
                print(f"  {persona}.yaml:")
                for error in persona_errors:
                    print(f"    - {error}")
            print(f"\n{len(errors)} persona(s) have errors")
            sys.exit(1)
        else:
            persona_count = len(list(PERSONAS_DIR.glob("*.yaml")))
            print(f"All {persona_count} personas are valid!")

    if args.regenerate:
        print(f"\nRegenerating {args.regenerate}...")
        success = regenerate_persona(args.regenerate, dry_run=args.dry_run)
        sys.exit(0 if success else 1)

    if args.regenerate_all:
        print("\n" + "=" * 60)
        print("REGENERATING ALL PERSONAS")
        print("=" * 60 + "\n")

        if args.dry_run:
            print("(Dry run - no files will be modified)\n")

        updated = regenerate_all_personas(dry_run=args.dry_run)
        print(f"\nProcessed {updated} persona(s)")


if __name__ == "__main__":
    main()
