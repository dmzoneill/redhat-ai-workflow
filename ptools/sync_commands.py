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
import importlib
import logging
import re
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

logger = logging.getLogger(__name__)


def _optional_yaml() -> ModuleType | None:
    """Return the PyYAML module, or None when it isn't installed."""
    try:
        return importlib.import_module("yaml")
    except ImportError:
        return None


yaml = _optional_yaml()

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
            if line.startswith("##"):
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
        except (AttributeError, IndexError, TypeError) as exc:
            logger.debug("Suppressed error: %s", exc)

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
        f"name: {metadata['name']}",
        f'description: "{metadata["description"]}"',
    ]

    if metadata["arguments"]:
        frontmatter_lines.append("arguments:")
        for arg in metadata["arguments"]:
            frontmatter_lines.append(f"  - name: {arg['name']}")
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


def claude_to_cursor(content: str, _filename: str = "") -> str:
    """Convert Claude Code command to Cursor format (remove frontmatter).

    Takes the same (content, filename) arguments as cursor_to_claude so
    sync_commands() can call either converter; the filename is unused.
    """
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


def _skill_command_names(skill_file: Path) -> tuple[str, str, str]:
    """Return (skill_name, full_skill_name, command_name) for a skill file."""
    rel = skill_file.relative_to(SKILLS_DIR)
    if len(rel.parts) > 1:
        # Subdirectory skill like performance/collect_daily.yaml
        skill_name = str(rel.with_suffix("")).replace("/", "-")
        full_skill_name = str(rel.with_suffix("")).replace("-", "/")
    else:
        skill_name = skill_file.stem
        full_skill_name = skill_file.stem
    return skill_name, full_skill_name, skill_name.replace("_", "-")


def _input_specs(inputs) -> list[dict]:
    """Normalise skill inputs (list or dict format) to a list of dicts."""
    if isinstance(inputs, list):
        return [{"name": inp.get("name", "param"), **inp} for inp in inputs]
    if isinstance(inputs, dict):
        return [{**(spec if isinstance(spec, dict) else {}), "name": name} for name, spec in inputs.items()]
    return []


def _skill_run_lines(full_skill_name: str, specs: list[dict]) -> list[str]:
    """Return the fenced skill_run() example for a command."""
    input_parts = [
        f'"{spec["name"]}": "${spec["name"].upper()}"' if spec.get("required", False) else f'"{spec["name"]}": ""'
        for spec in specs
    ]
    inputs_json = "{" + ", ".join(input_parts) + "}"
    return ["```text", f"skill_run(\"{full_skill_name}\", '{inputs_json}')", "```"]


def _parameter_lines(specs: list[dict]) -> list[str]:
    """Return the markdown parameter table for a command."""
    lines = [
        "",
        "## Parameters",
        "",
        "| Parameter | Description | Required |",
        "|-----------|-------------|----------|",
    ]
    for spec in specs:
        desc = spec.get("description", "")
        if spec.get("default", ""):
            desc += f" (default: {spec['default']})"
        required = "Yes" if spec.get("required", False) else "No"
        lines.append(f"| `{spec['name']}` | {desc} | {required} |")
    return lines


def _render_command(skill: dict, skill_name: str, full_skill_name: str) -> str:
    """Render the Cursor command markdown for a loaded skill definition."""
    name = skill.get("name", skill_name)
    description = skill.get("description", f"Run the {name} skill").strip()
    inputs = skill.get("inputs", [])
    specs = _input_specs(inputs)

    lines = [
        f"# {name.replace('_', ' ').replace('-', ' ').title()}",
        "",
        description.split("\n")[0].strip(),
        "",
        "## Instructions",
        "",
        *_skill_run_lines(full_skill_name, specs),
        "",
        "## What It Does",
        "",
        *(line.strip() for line in description.split("\n")),
    ]
    if inputs:
        lines.extend(_parameter_lines(specs))
    lines.append("")
    return "\n".join(lines)


def generate_missing_commands(dry_run: bool = False, verbose: bool = True) -> int:
    """Generate Cursor commands for skills that don't have commands."""
    if yaml is None:
        print("❌ PyYAML not installed. Run: uv add pyyaml")
        return 0

    existing_commands = {f.stem for f in CURSOR_COMMANDS.glob("*.md")}
    created = 0

    for skill_file in sorted(SKILLS_DIR.glob("**/*.yaml")):
        skill_name, full_skill_name, command_name = _skill_command_names(skill_file)
        if command_name in existing_commands:
            continue

        try:
            with open(skill_file, encoding="utf-8") as f:
                skill = yaml.safe_load(f)
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
            if verbose:
                print(f"  ⚠️  Error loading {skill_file.name}: {e}")
            continue

        if not skill:
            continue

        if verbose:
            print(f"  ✨ {command_name}.md (generated from {skill_file.name})")
        if not dry_run:
            (CURSOR_COMMANDS / f"{command_name}.md").write_text(_render_command(skill, skill_name, full_skill_name))
        created += 1

    return created


def sync_commands(
    source_dir: Path,
    target_dir: Path,
    converter: Callable[[str, str], str],
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


def _run_generate_missing(dry_run: bool, quiet: bool) -> int:
    """Run --generate-missing mode and return the exit status."""
    if yaml is None:
        print("❌ PyYAML not installed. Run: uv add pyyaml")
        return 1
    print("\n🔧 Generating commands for skills without commands")
    print(f"   Skills: {SKILLS_DIR.relative_to(PROJECT_ROOT)}")
    print(f"   Target: {CURSOR_COMMANDS.relative_to(PROJECT_ROOT)}")

    if dry_run:
        print("   Mode: DRY RUN (no changes will be made)\n")
    else:
        print()

    # Ensure target directory exists
    if not dry_run:
        CURSOR_COMMANDS.mkdir(parents=True, exist_ok=True)

    created = generate_missing_commands(dry_run=dry_run, verbose=not quiet)

    print(f"\n📊 Generated: {created} new commands")

    if dry_run and created:
        print("\n💡 Run without --dry-run to create the commands")

    return 0


def main() -> int:
    """Parse arguments, run the requested sync and return the exit status.

    Returns 1 when the sync can't run (PyYAML missing for
    --generate-missing, or the source directory missing), otherwise 0.
    """
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
        return _run_generate_missing(args.dry_run, args.quiet)

    converter: Callable[[str, str], str]
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

    if not source_dir.exists():
        print(f"❌ Source directory does not exist: {source_dir}")
        return 1

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
