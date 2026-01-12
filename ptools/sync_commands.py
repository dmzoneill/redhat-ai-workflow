#!/usr/bin/env python3
"""
Sync commands between Cursor and Claude Code formats.

Cursor commands: .cursor/commands/*.md (plain markdown)
Claude Code commands: .claude/commands/*.md (markdown with YAML frontmatter)

Usage:
    python ptools/sync_commands.py              # Sync all commands
    python ptools/sync_commands.py --dry-run   # Show what would be done
    python ptools/sync_commands.py --reverse   # Claude Code -> Cursor
"""

import argparse
import re
import sys
from pathlib import Path

# Directories
PROJECT_ROOT = Path(__file__).parent.parent
CURSOR_COMMANDS = PROJECT_ROOT / ".cursor" / "commands"
CLAUDE_COMMANDS = PROJECT_ROOT / ".claude" / "commands"


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
    parser.add_argument("--quiet", "-q", action="store_true", help="Only show summary")

    args = parser.parse_args()

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
