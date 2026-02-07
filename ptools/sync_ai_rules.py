#!/usr/bin/env python3
"""
Sync AI rules from single source of truth to all targets.

Source: docs/ai-rules/*.md
Targets:
  - .cursorrules (concatenated markdown - Cursor)
  - CLAUDE.md (with @import statements - Claude Code)
  - AGENTS.md (cross-tool standard - Codex, OpenCode, Amp)
  - GEMINI.md (concatenated markdown - Gemini CLI)
  - .github/copilot-instructions.md (concatenated markdown - GitHub Copilot)

Also syncs slash commands via sync_commands.py.

Usage:
    python ptools/sync_ai_rules.py              # Sync everything
    python ptools/sync_ai_rules.py --dry-run    # Preview changes
    python ptools/sync_ai_rules.py --rules-only # Skip command sync
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Directories
PROJECT_ROOT = Path(__file__).parent.parent
AI_RULES_DIR = PROJECT_ROOT / "docs" / "ai-rules"
CURSORRULES_FILE = PROJECT_ROOT / ".cursorrules"
CLAUDE_MD_FILE = PROJECT_ROOT / "CLAUDE.md"
AGENTS_MD_FILE = PROJECT_ROOT / "AGENTS.md"
GEMINI_MD_FILE = PROJECT_ROOT / "GEMINI.md"
COPILOT_MD_FILE = PROJECT_ROOT / ".github" / "copilot-instructions.md"

# Header for generated files
GENERATED_HEADER = """<!--
  ╔═══════════════════════════════════════════════════════════════════════════╗
  ║  AUTO-GENERATED FILE - DO NOT EDIT DIRECTLY                               ║
  ║                                                                           ║
  ║  Source: docs/ai-rules/                                                   ║
  ║  Sync:   make sync-ai-rules                                               ║
  ║  Generated: {timestamp}                                            ║
  ╚═══════════════════════════════════════════════════════════════════════════╝
-->

"""


def get_rule_files() -> list[Path]:
    """Get all rule files in order (sorted by filename)."""
    if not AI_RULES_DIR.exists():
        print(f"❌ AI rules directory not found: {AI_RULES_DIR}")
        sys.exit(1)

    # Get all .md files except README
    files = [f for f in sorted(AI_RULES_DIR.glob("*.md")) if f.name != "README.md"]

    if not files:
        print(f"❌ No rule files found in {AI_RULES_DIR}")
        sys.exit(1)

    return files


def generate_cursorrules(rule_files: list[Path], dry_run: bool = False) -> bool:
    """Generate .cursorrules by concatenating all rule files."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = GENERATED_HEADER.format(timestamp=timestamp)

    content_parts = [header]

    for rule_file in rule_files:
        content = rule_file.read_text().strip()
        content_parts.append(content)
        content_parts.append("\n")  # Separator between files

    new_content = "\n".join(content_parts)

    # Check if changed
    if CURSORRULES_FILE.exists():
        existing = CURSORRULES_FILE.read_text()
        # Compare without timestamp line
        existing_body = "\n".join(existing.split("\n")[8:])  # Skip header
        new_body = "\n".join(new_content.split("\n")[8:])
        if existing_body == new_body:
            print("  ⏭️  .cursorrules (unchanged)")
            return False

    if dry_run:
        print("  📝 .cursorrules (would update)")
    else:
        CURSORRULES_FILE.write_text(new_content)
        print("  ✅ .cursorrules (updated)")

    return True


def generate_claude_md(rule_files: list[Path], dry_run: bool = False) -> bool:
    """Generate CLAUDE.md with @import statements."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = GENERATED_HEADER.format(timestamp=timestamp)

    # Build @import statements
    imports = []
    for rule_file in rule_files:
        rel_path = rule_file.relative_to(PROJECT_ROOT)
        imports.append(f"@import {rel_path}")

    content = header + "\n".join(imports) + "\n"

    # Check if changed
    if CLAUDE_MD_FILE.exists():
        existing = CLAUDE_MD_FILE.read_text()
        existing_body = "\n".join(existing.split("\n")[8:])
        new_body = "\n".join(content.split("\n")[8:])
        if existing_body == new_body:
            print("  ⏭️  CLAUDE.md (unchanged)")
            return False

    if dry_run:
        print("  📝 CLAUDE.md (would update)")
    else:
        CLAUDE_MD_FILE.write_text(content)
        print("  ✅ CLAUDE.md (updated)")

    return True


def generate_agents_md(rule_files: list[Path], dry_run: bool = False) -> bool:
    """Generate AGENTS.md (cross-tool standard format).

    AGENTS.md is similar to CLAUDE.md but uses a slightly different format
    that's compatible with multiple AI coding tools.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # AGENTS.md uses full content (like .cursorrules) for maximum compatibility
    header = f"""<!--
  AGENTS.md - Cross-tool AI assistant configuration

  This file follows the agents.md standard for AI coding assistants.
  Compatible with: Claude Code, Cursor, Codex, Gemini, Copilot, OpenCode, Amp, and others.

  Source: docs/ai-rules/
  Generated: {timestamp}
-->

"""

    content_parts = [header]

    for rule_file in rule_files:
        content = rule_file.read_text().strip()
        content_parts.append(content)
        content_parts.append("\n")

    new_content = "\n".join(content_parts)

    # Check if changed
    if AGENTS_MD_FILE.exists():
        existing = AGENTS_MD_FILE.read_text()
        existing_body = "\n".join(existing.split("\n")[10:])  # Skip header
        new_body = "\n".join(new_content.split("\n")[10:])
        if existing_body == new_body:
            print("  ⏭️  AGENTS.md (unchanged)")
            return False

    if dry_run:
        print("  📝 AGENTS.md (would update)")
    else:
        AGENTS_MD_FILE.write_text(new_content)
        print("  ✅ AGENTS.md (updated)")

    return True


def generate_gemini_md(rule_files: list[Path], dry_run: bool = False) -> bool:
    """Generate GEMINI.md for Gemini CLI.

    Gemini CLI reads GEMINI.md from the project root for context.
    Uses full concatenated content (like .cursorrules).
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    header = f"""<!--
  GEMINI.md - Gemini CLI AI assistant configuration

  Project-level context for Gemini CLI.
  See also: AGENTS.md, CLAUDE.md, .cursorrules

  Source: docs/ai-rules/
  Generated: {timestamp}
-->

"""

    content_parts = [header]

    for rule_file in rule_files:
        content = rule_file.read_text().strip()
        content_parts.append(content)
        content_parts.append("\n")

    new_content = "\n".join(content_parts)

    # Check if changed
    if GEMINI_MD_FILE.exists():
        existing = GEMINI_MD_FILE.read_text()
        existing_body = "\n".join(existing.split("\n")[10:])  # Skip header
        new_body = "\n".join(new_content.split("\n")[10:])
        if existing_body == new_body:
            print("  ⏭️  GEMINI.md (unchanged)")
            return False

    if dry_run:
        print("  📝 GEMINI.md (would update)")
    else:
        GEMINI_MD_FILE.write_text(new_content)
        print("  ✅ GEMINI.md (updated)")

    return True


def generate_copilot_md(rule_files: list[Path], dry_run: bool = False) -> bool:
    """Generate .github/copilot-instructions.md for GitHub Copilot.

    GitHub Copilot reads .github/copilot-instructions.md for
    repository-wide custom instructions.
    Uses full concatenated content.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    header = f"""<!--
  copilot-instructions.md - GitHub Copilot custom instructions

  Repository-wide instructions for GitHub Copilot.
  See also: AGENTS.md, CLAUDE.md, GEMINI.md, .cursorrules

  Source: docs/ai-rules/
  Generated: {timestamp}
-->

"""

    content_parts = [header]

    for rule_file in rule_files:
        content = rule_file.read_text().strip()
        content_parts.append(content)
        content_parts.append("\n")

    new_content = "\n".join(content_parts)

    # Ensure .github directory exists
    COPILOT_MD_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Check if changed
    if COPILOT_MD_FILE.exists():
        existing = COPILOT_MD_FILE.read_text()
        existing_body = "\n".join(existing.split("\n")[10:])  # Skip header
        new_body = "\n".join(new_content.split("\n")[10:])
        if existing_body == new_body:
            print("  ⏭️  .github/copilot-instructions.md (unchanged)")
            return False

    if dry_run:
        print("  📝 .github/copilot-instructions.md (would update)")
    else:
        COPILOT_MD_FILE.write_text(new_content)
        print("  ✅ .github/copilot-instructions.md (updated)")

    return True


def sync_commands(dry_run: bool = False) -> bool:
    """Run sync_commands.py to sync slash commands."""
    sync_script = PROJECT_ROOT / "ptools" / "sync_commands.py"

    if not sync_script.exists():
        print("  ⚠️  sync_commands.py not found, skipping command sync")
        return False

    cmd = [sys.executable, str(sync_script)]
    if dry_run:
        cmd.append("--dry-run")
    cmd.append("--quiet")

    print("\n🔄 Syncing slash commands...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  ❌ Command sync failed: {result.stderr}")
        return False

    # Parse output for summary
    for line in result.stdout.split("\n"):
        if "Created:" in line or "Updated:" in line or "Unchanged:" in line:
            print(f"  {line.strip()}")

    return True


def main():
    parser = argparse.ArgumentParser(description="Sync AI rules from docs/ai-rules/ to all targets")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--rules-only",
        action="store_true",
        help="Only sync rules, skip command sync",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )

    args = parser.parse_args()

    print("\n🔄 Syncing AI Rules")
    print("   Source: docs/ai-rules/")

    if args.dry_run:
        print("   Mode: DRY RUN (no changes will be made)\n")
    else:
        print()

    # Get rule files
    rule_files = get_rule_files()

    if args.verbose:
        print(f"📁 Found {len(rule_files)} rule files:")
        for f in rule_files:
            print(f"   - {f.name}")
        print()

    # Generate targets
    print("📝 Generating target files:")

    changes = []
    changes.append(generate_cursorrules(rule_files, args.dry_run))
    changes.append(generate_claude_md(rule_files, args.dry_run))
    changes.append(generate_agents_md(rule_files, args.dry_run))
    changes.append(generate_gemini_md(rule_files, args.dry_run))
    changes.append(generate_copilot_md(rule_files, args.dry_run))

    # Sync commands
    if not args.rules_only:
        sync_commands(args.dry_run)

    # Summary
    changed_count = sum(changes)
    total_targets = len(changes)
    print("\n📊 Summary:")
    print(f"   Rule files: {len(rule_files)}")
    print(f"   Targets updated: {changed_count}/{total_targets}")

    if args.dry_run and changed_count:
        print("\n💡 Run without --dry-run to apply changes")

    return 0


if __name__ == "__main__":
    sys.exit(main())
