#!/usr/bin/env python3
"""
Reorganize tool modules to split tools into tools_basic.py and tools_extra.py
based on usage in skills.

This script:
1. Reads the analysis from skill-tool-usage-report.md
2. For each module, splits tools into used (basic) and unused (extra)
3. Creates tools_basic.py and tools_extra.py files
4. Updates __init__.py and server.py to import from the correct files
5. Preserves all tool code exactly as-is (just moving between files)
"""

import os
import re
import shutil
from pathlib import Path
from typing import Dict, Set

# Project root
PROJECT_ROOT = Path(__file__).parent.parent


def parse_analysis_report() -> Dict[str, Dict[str, Set[str]]]:
    """Parse the skill-tool-usage-report.md to get used/unused tools per module."""
    report_file = PROJECT_ROOT / ".claude" / "skill-tool-usage-report.md"

    with open(report_file, "r") as f:
        content = f.read()

    # Extract module sections
    module_data = {}
    lines = content.split("\n")

    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for module headers like "### aa_git"
        if line.startswith("### aa_"):
            module_name = line.replace("### ", "").strip()

            # Extract used and unused tools from next few lines
            used_tools = set()
            unused_tools = set()

            for j in range(i + 1, min(i + 10, len(lines))):
                next_line = lines[j]

                if next_line.startswith("- **Used Tools:**"):
                    tools_str = next_line.replace("- **Used Tools:**", "").strip()
                    if tools_str and tools_str != "(none)":
                        used_tools = set(t.strip() for t in tools_str.split(","))

                elif next_line.startswith("- **Unused Tools:**"):
                    tools_str = next_line.replace("- **Unused Tools:**", "").strip()
                    if tools_str and tools_str != "(none)":
                        unused_tools = set(t.strip() for t in tools_str.split(","))

                # Stop at next module
                elif next_line.startswith("###"):
                    break

            module_data[module_name] = {
                "used": used_tools,
                "unused": unused_tools,
            }

        i += 1

    return module_data


def extract_tool_function(content: str, tool_name: str) -> str | None:
    """Extract the complete function definition for a tool from source code."""
    lines = content.split("\n")

    # Find the tool definition
    tool_start = None
    for i, line in enumerate(lines):
        # Look for @registry.tool() or @mcp.tool() followed by def tool_name
        if "@registry.tool()" in line or "@registry.tool(" in line or "@mcp.tool()" in line or "@mcp.tool(" in line:
            # Look ahead for the function definition
            for j in range(i + 1, min(i + 10, len(lines))):
                next_line = lines[j]
                match = re.match(r"\s*(?:async\s+)?def\s+(\w+)\s*\(", next_line)
                if match and match.group(1) == tool_name:
                    # Found it! Now extract the complete function
                    tool_start = i
                    break

            if tool_start is not None:
                break

    if tool_start is None:
        return None

    # Extract from decorator to end of function
    # Find the function body by looking for the next function or end of file
    indent = None
    func_lines = []

    for i in range(tool_start, len(lines)):
        line = lines[i]

        # Capture the function
        if indent is None:
            # Find the function def line to get indent
            if re.match(r"\s*(?:async\s+)?def\s+" + tool_name, line):
                indent = len(line) - len(line.lstrip())
            func_lines.append(line)
        else:
            # Check if we've reached the next function at same or lower indent
            if line.strip() and not line.startswith(" " * (indent + 1)) and line.strip() != "":
                # Check if it's a decorator or function definition
                if line.strip().startswith("@") or re.match(r"\s*(?:async\s+)?def\s+", line):
                    # Don't include, we're done
                    break
            func_lines.append(line)

    return "\n".join(func_lines)


def split_module_tools(module_name: str, used_tools: Set[str], unused_tools: Set[str]):
    """Split a module's tools into basic and extra files."""
    module_dir = PROJECT_ROOT / "tool_modules" / module_name / "src"

    if not module_dir.exists():
        print(f"⚠️  Module {module_name} src/ dir not found, skipping")
        return

    # Check current structure
    has_basic_extra = (module_dir / "tools_basic.py").exists()
    has_single_tools = (module_dir / "tools.py").exists()

    if not has_basic_extra and not has_single_tools:
        print(f"⚠️  Module {module_name} has no tools files, skipping")
        return

    print(f"\n📦 Processing {module_name}")
    print(f"   Used tools: {len(used_tools)}, Unused tools: {len(unused_tools)}")

    if has_basic_extra:
        print("   ℹ️  Already has basic/extra split - skipping reorganization")
        print("      (Manual review recommended to verify correct split)")
        return

    if has_single_tools:
        print("   🔧 Splitting tools.py into basic/extra")

        # Read the current tools.py
        tools_file = module_dir / "tools.py"
        with open(tools_file, "r") as f:
            content = f.read()

        # Extract header/imports section (everything before first @tool decorator)
        lines = content.split("\n")
        header_lines = []

        for line in lines:
            if "@mcp.tool()" in line or "@registry.tool()" in line:
                break
            header_lines.append(line)

        header = "\n".join(header_lines)

        # Extract each tool's code
        all_tools = used_tools | unused_tools
        tool_code = {}

        for tool_name in all_tools:
            code = extract_tool_function(content, tool_name)
            if code:
                tool_code[tool_name] = code
            else:
                print(f"      ⚠️  Could not extract code for {tool_name}")

        # Build basic file
        basic_lines = [header.rstrip()]
        basic_lines.append("\n\n# ==================== USED TOOLS (from skills analysis) ====================\n")

        for tool_name in sorted(used_tools):
            if tool_name in tool_code:
                basic_lines.append(tool_code[tool_name])
                basic_lines.append("\n")

        # Build extra file
        extra_lines = [header.rstrip()]
        extra_lines.append("\n\n# ==================== UNUSED TOOLS (from skills analysis) ====================\n")

        for tool_name in sorted(unused_tools):
            if tool_name in tool_code:
                extra_lines.append(tool_code[tool_name])
                extra_lines.append("\n")

        # Write new files
        if used_tools:
            with open(module_dir / "tools_basic.py", "w") as f:
                f.write("\n".join(basic_lines))
            print(f"      ✅ Created tools_basic.py with {len(used_tools)} tools")

        if unused_tools:
            with open(module_dir / "tools_extra.py", "w") as f:
                f.write("\n".join(extra_lines))
            print(f"      ✅ Created tools_extra.py with {len(unused_tools)} tools")

        # Backup original tools.py
        backup_file = module_dir / "tools.py.backup"
        shutil.copy(tools_file, backup_file)
        print("      📁 Backed up original to tools.py.backup")

        # Remove original tools.py
        os.remove(tools_file)
        print("      🗑️  Removed tools.py")


def update_server_py(module_name: str):
    """Update server.py to import from tools_basic instead of tools."""
    server_file = PROJECT_ROOT / "tool_modules" / module_name / "src" / "server.py"

    if not server_file.exists():
        return

    with open(server_file, "r") as f:
        content = f.read()

    # Replace "from . import tools" with "from . import tools_basic as tools"
    # or "from .tools import" with "from .tools_basic import"
    updated = content.replace("from . import tools", "from . import tools_basic as tools").replace(
        "from .tools import", "from .tools_basic import"
    )

    if updated != content:
        with open(server_file, "w") as f:
            f.write(updated)
        print("      ✅ Updated server.py imports")


def main():
    print("=" * 70)
    print("TOOL MODULE REORGANIZATION")
    print("=" * 70)
    print("\nThis script will reorganize tool modules based on skill usage analysis.")
    print("Modules will be split into tools_basic.py (used) and tools_extra.py (unused).\n")

    # Parse analysis
    print("📊 Reading analysis report...")
    module_data = parse_analysis_report()

    print(f"   Found {len(module_data)} modules to process\n")

    # Process each module
    for module_name, data in sorted(module_data.items()):
        used_tools = data["used"]
        unused_tools = data["unused"]

        # Skip modules with no tools
        if not used_tools and not unused_tools:
            continue

        split_module_tools(module_name, used_tools, unused_tools)
        update_server_py(module_name)

    print("\n" + "=" * 70)
    print("✅ REORGANIZATION COMPLETE")
    print("=" * 70)
    print("\nNext steps:")
    print("1. Review the changes in each module")
    print("2. Run tests to verify everything works")
    print("3. Commit the changes")
    print("\nBackup files (*.backup) have been created for safety.")


if __name__ == "__main__":
    main()
