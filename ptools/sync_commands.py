#!/usr/bin/env python3
"""
Sync commands between Cursor and Claude Code formats.

Cursor commands: .cursor/commands/*.md (plain markdown)
Claude Code commands: .claude/commands/*.md (markdown with YAML frontmatter)

Usage:
    python ptools/sync_commands.py                    # Sync all commands
    python ptools/sync_commands.py --dry-run         # Show what would be done
    python ptools/sync_commands.py --reverse         # Claude Code -> Cursor
    python ptools/sync_commands.py --generate-missing # Generate commands for skills without commands
"""

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

# Directories
PROJECT_ROOT = Path(__file__).parent.parent
CURSOR_COMMANDS = PROJECT_ROOT / ".cursor" / "commands"
CLAUDE_COMMANDS = PROJECT_ROOT / ".claude" / "commands"
SKILLS_DIR = PROJECT_ROOT / "skills"


def extract_command_metadata(content: str, filename: str) -> dict:
    """Extract metadata from a Cursor command markdown file."""
    lines = content.strip().split("\n")

    # Get title from first H1
    title = filename.replace("-", " ").replace(".md", "").title()
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            # Remove emoji prefix if present
            title = re.sub(r"^[^\w\s]+\s*", "", title)
            break

    # Get description from first paragraph after title
    description = ""
    in_description = False
    for line in lines:
        if line.startswith("# "):
            in_description = True
            continue
        if in_description:
            if line.strip() and not line.startswith("#"):
                description = line.strip()
                break
            elif line.startswith("##"):
                break

    # Extract arguments from skill_run calls
    arguments = []
    skill_match = re.search(r'skill_run\([^,]+,\s*[\'"]({[^}]+})[\'"]', content)
    if skill_match:
        try:
            # Parse the JSON-like string to find argument names
            args_str = skill_match.group(1)
            # Find all "key": patterns
            arg_names = re.findall(r'"(\w+)":', args_str)
            for arg in arg_names:
                # Check if there's a placeholder like $JIRA_KEY
                if f"${arg.upper()}" in content or f"${arg.upper().replace('_', '')}" in content:
                    arguments.append({"name": arg, "required": True})
                else:
                    arguments.append({"name": arg, "required": False})
        except Exception:
            pass

    return {
        "name": filename.replace(".md", ""),
        "title": title,
        "description": description or f"Run the {title} command",
        "arguments": arguments,
    }


def cursor_to_claude(content: str, filename: str) -> str:
    """Convert Cursor command to Claude Code format (add frontmatter)."""
    metadata = extract_command_metadata(content, filename)

    # Build YAML frontmatter
    frontmatter_lines = [
        "---",
        f'name: {metadata["name"]}',
        f'description: "{metadata["description"]}"',
    ]

    if metadata["arguments"]:
        frontmatter_lines.append("arguments:")
        for arg in metadata["arguments"]:
            frontmatter_lines.append(f'  - name: {arg["name"]}')
            if arg["required"]:
                frontmatter_lines.append("    required: true")

    frontmatter_lines.append("---")
    frontmatter_lines.append("")

    frontmatter = "\n".join(frontmatter_lines)

    # Check if content already has frontmatter
    if content.strip().startswith("---"):
        # Already has frontmatter, skip
        return content

    return frontmatter + content


def claude_to_cursor(content: str) -> str:
    """Convert Claude Code command to Cursor format (remove frontmatter)."""
    if not content.strip().startswith("---"):
        return content

    # Find the second --- and remove everything before it
    lines = content.split("\n")
    frontmatter_end = -1
    frontmatter_count = 0

    for i, line in enumerate(lines):
        if line.strip() == "---":
            frontmatter_count += 1
            if frontmatter_count == 2:
                frontmatter_end = i
                break

    if frontmatter_end > 0:
        start_idx = frontmatter_end + 1
        return "\n".join(lines[start_idx:]).strip() + "\n"

    return content


def generate_missing_commands(dry_run: bool = False, verbose: bool = True) -> int:
    """Generate Cursor commands for skills that don't have commands."""
    if yaml is None:
        print("❌ PyYAML not installed. Run: uv add pyyaml")
        return 0

    # Get existing commands
    existing_commands = {f.stem for f in CURSOR_COMMANDS.glob("*.md")}

    created = 0

    for skill_file in sorted(SKILLS_DIR.glob("**/*.yaml")):
        rel = skill_file.relative_to(SKILLS_DIR)

        # Determine skill name and command name
        if len(rel.parts) > 1:
            # Subdirectory skill like performance/collect_daily.yaml
            skill_name = str(rel.with_suffix("")).replace("/", "-")
            full_skill_name = str(rel.with_suffix("")).replace("-", "/")
        else:
            skill_name = skill_file.stem
            full_skill_name = skill_file.stem

        command_name = skill_name.replace("_", "-")

        # Skip if command already exists
        if command_name in existing_commands:
            continue

        # Load skill definition
        try:
            with open(skill_file) as f:
                skill = yaml.safe_load(f)
        except Exception as e:
            if verbose:
                print(f"  ⚠️  Error loading {skill_file.name}: {e}")
            continue

        if not skill:
            continue

        # Extract skill info
        name = skill.get("name", skill_name)
        description = skill.get("description", f"Run the {name} skill").strip()
        short_desc = description.split("\n")[0].strip()
        inputs = skill.get("inputs", [])

        # Build command content
        lines = [
            f"# {name.replace('_', ' ').replace('-', ' ').title()}",
            "",
            short_desc,
            "",
            "## Instructions",
            "",
        ]

        # Build skill_run call
        if inputs:
            input_parts = []
            # Handle both list format and dict format for inputs
            if isinstance(inputs, list):
                for inp in inputs:
                    inp_name = inp.get("name", "param")
                    inp_required = inp.get("required", False)
                    if inp_required:
                        input_parts.append(f'"{inp_name}": "${inp_name.upper()}"')
                    else:
                        input_parts.append(f'"{inp_name}": ""')
            elif isinstance(inputs, dict):
                for inp_name, inp_def in inputs.items():
                    inp_required = inp_def.get("required", False) if isinstance(inp_def, dict) else False
                    if inp_required:
                        input_parts.append(f'"{inp_name}": "${inp_name.upper()}"')
                    else:
                        input_parts.append(f'"{inp_name}": ""')
            inputs_json = "{" + ", ".join(input_parts) + "}"
            lines.append("```text")
            lines.append(f"skill_run(\"{full_skill_name}\", '{inputs_json}')")
            lines.append("```")
        else:
            lines.append("```text")
            lines.append(f"skill_run(\"{full_skill_name}\", '{{}}')")
            lines.append("```")

        lines.append("")
        lines.append("## What It Does")
        lines.append("")

        # Add full description
        for line in description.split("\n"):
            lines.append(line.strip())

        # Add parameters section if there are inputs
        if inputs:
            lines.append("")
            lines.append("## Parameters")
            lines.append("")
            lines.append("| Parameter | Description | Required |")
            lines.append("|-----------|-------------|----------|")
            # Handle both list format and dict format for inputs
            if isinstance(inputs, list):
                for inp in inputs:
                    inp_name = inp.get("name", "param")
                    inp_desc = inp.get("description", "")
                    inp_required = "Yes" if inp.get("required", False) else "No"
                    inp_default = inp.get("default", "")
                    if inp_default:
                        inp_desc += f" (default: {inp_default})"
                    lines.append(f"| `{inp_name}` | {inp_desc} | {inp_required} |")
            elif isinstance(inputs, dict):
                for inp_name, inp_def in inputs.items():
                    if isinstance(inp_def, dict):
                        inp_desc = inp_def.get("description", "")
                        inp_required = "Yes" if inp_def.get("required", False) else "No"
                        inp_default = inp_def.get("default", "")
                        if inp_default:
                            inp_desc += f" (default: {inp_default})"
                    else:
                        inp_desc = ""
                        inp_required = "No"
                    lines.append(f"| `{inp_name}` | {inp_desc} | {inp_required} |")

        lines.append("")

        # Write command file
        command_file = CURSOR_COMMANDS / f"{command_name}.md"
        if verbose:
            print(f"  ✨ {command_name}.md (generated from {skill_file.name})")

        if not dry_run:
            command_file.write_text("\n".join(lines))

        created += 1

    return created


def sync_commands(
    source_dir: Path,
    target_dir: Path,
    converter: callable,
    dry_run: bool = False,
    verbose: bool = True,
) -> tuple[int, int, int]:
    """Sync commands from source to target directory."""
    created = 0
    updated = 0
    skipped = 0

    if not source_dir.exists():
        print(f"❌ Source directory does not exist: {source_dir}")
        return 0, 0, 0

    # Ensure target directory exists
    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    for source_file in sorted(source_dir.glob("*.md")):
        target_file = target_dir / source_file.name

        # Read source content
        source_content = source_file.read_text()

        # Convert to target format
        target_content = converter(source_content, source_file.name)

        # Check if target exists and is different
        if target_file.exists():
            existing_content = target_file.read_text()
            if existing_content == target_content:
                skipped += 1
                if verbose:
                    print(f"  ⏭️  {source_file.name} (unchanged)")
                continue
            else:
                if verbose:
                    print(f"  📝 {source_file.name} (updated)")
                updated += 1
        else:
            if verbose:
                print(f"  ✨ {source_file.name} (created)")
            created += 1

        # Write target file
        if not dry_run:
            target_file.write_text(target_content)

    return created, updated, skipped


def main():
    parser = argparse.ArgumentParser(description="Sync commands between Cursor and Claude Code formats")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="Sync from Claude Code to Cursor (remove frontmatter)",
    )
    parser.add_argument(
        "--generate-missing",
        action="store_true",
        help="Generate Cursor commands for skills that don't have commands",
    )
    parser.add_argument("--quiet", "-q", action="store_true", help="Only show summary")

    args = parser.parse_args()

    # Handle generate-missing mode
    if args.generate_missing:
        print("\n🔧 Generating commands for skills without commands")
        print(f"   Skills: {SKILLS_DIR.relative_to(PROJECT_ROOT)}")
        print(f"   Target: {CURSOR_COMMANDS.relative_to(PROJECT_ROOT)}")

        if args.dry_run:
            print("   Mode: DRY RUN (no changes will be made)\n")
        else:
            print()

        # Ensure target directory exists
        if not args.dry_run:
            CURSOR_COMMANDS.mkdir(parents=True, exist_ok=True)

        created = generate_missing_commands(dry_run=args.dry_run, verbose=not args.quiet)

        print(f"\n📊 Generated: {created} new commands")

        if args.dry_run and created:
            print("\n💡 Run without --dry-run to create the commands")

        return 0

    if args.reverse:
        source_dir = CLAUDE_COMMANDS
        target_dir = CURSOR_COMMANDS
        converter = claude_to_cursor
        direction = "Claude Code → Cursor"
    else:
        source_dir = CURSOR_COMMANDS
        target_dir = CLAUDE_COMMANDS
        converter = cursor_to_claude
        direction = "Cursor → Claude Code"

    print(f"\n🔄 Syncing commands: {direction}")
    print(f"   Source: {source_dir.relative_to(PROJECT_ROOT)}")
    print(f"   Target: {target_dir.relative_to(PROJECT_ROOT)}")

    if args.dry_run:
        print("   Mode: DRY RUN (no changes will be made)\n")
    else:
        print()

    created, updated, skipped = sync_commands(
        source_dir=source_dir,
        target_dir=target_dir,
        converter=converter,
        dry_run=args.dry_run,
        verbose=not args.quiet,
    )

    print("\n📊 Summary:")
    print(f"   Created: {created}")
    print(f"   Updated: {updated}")
    print(f"   Unchanged: {skipped}")
    print(f"   Total: {created + updated + skipped}")

    if args.dry_run and (created or updated):
        print("\n💡 Run without --dry-run to apply changes")

    return 0


if __name__ == "__main__":
    sys.exit(main())
