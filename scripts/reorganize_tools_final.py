#!/usr/bin/env python3
"""
Final tool reorganization script.

This script reorganizes ALL tool modules based on actual skill usage analysis.
It rebuilds tools_basic.py and tools_extra.py from tools.py for each module.
"""

import ast
import shutil
from pathlib import Path
from typing import Dict, Set

PROJECT_ROOT = Path(__file__).parent.parent


def parse_analysis_report() -> Dict[str, Dict[str, Set[str]]]:
    """Parse the skill-tool-usage-report.md."""
    report_file = PROJECT_ROOT / ".claude" / "skill-tool-usage-report.md"

    with open(report_file, "r") as f:
        content = f.read()

    module_data = {}
    lines = content.split("\n")

    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("### aa_"):
            module_name = line.replace("### ", "").strip()
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

                elif next_line.startswith("###"):
                    break

            module_data[module_name] = {
                "used": used_tools,
                "unused": unused_tools,
            }

        i += 1

    return module_data


def extract_tool_function_ast(source_code: str, tool_name: str) -> str | None:
    """
    Extract a complete tool function using AST parsing.
    This is more robust than regex-based extraction.
    """
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return None

    # Find the function node
    source_lines = source_code.split("\n")

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            if node.name == tool_name:
                # Get the line numbers for this function
                start_line = node.lineno - 1  # 0-indexed
                end_line = node.end_lineno  # Inclusive, 1-indexed

                # Look backwards to find decorators
                decorator_start = start_line
                for i in range(start_line - 1, -1, -1):
                    line = source_lines[i].strip()
                    if line.startswith("@"):
                        decorator_start = i
                    elif line and not line.startswith("#"):
                        # Hit a non-decorator, non-comment line
                        break

                # Extract the complete function with decorators
                func_lines = source_lines[decorator_start:end_line]
                return "\n".join(func_lines)

    return None


def split_tools_file(module_name: str, used_tools: Set[str], unused_tools: Set[str]) -> bool:
    """Split a module's tools.py into basic and extra files."""
    module_dir = PROJECT_ROOT / "tool_modules" / module_name / "src"
    tools_file = module_dir / "tools.py"

    if not tools_file.exists():
        print("   ⚠️  No tools.py found, skipping")
        return False

    # Read the source file
    with open(tools_file, "r") as f:
        source_code = f.read()

    # Extract the module header (imports, helper functions, etc.)
    # Everything before the first @tool decorated function
    lines = source_code.split("\n")
    header_end = 0

    for i, line in enumerate(lines):
        if "@registry.tool()" in line or "@mcp.tool()" in line:
            header_end = i
            break

    header = "\n".join(lines[:header_end])

    # Extract each tool function
    all_tools = used_tools | unused_tools
    tool_functions = {}
    failed_tools = []

    for tool_name in all_tools:
        func_code = extract_tool_function_ast(source_code, tool_name)
        if func_code:
            tool_functions[tool_name] = func_code
        else:
            failed_tools.append(tool_name)

    if failed_tools:
        print(f"   ⚠️  Failed to extract: {failed_tools}")

    # Build tools_basic.py
    basic_content = [header.rstrip()]
    basic_content.append("\n\n# ==================== TOOLS USED IN SKILLS ====================\n")

    for tool_name in sorted(used_tools):
        if tool_name in tool_functions:
            basic_content.append("\n" + tool_functions[tool_name] + "\n")

    # Build tools_extra.py
    extra_content = [header.rstrip()]
    extra_content.append("\n\n# ==================== TOOLS NOT USED IN SKILLS ====================\n")

    for tool_name in sorted(unused_tools):
        if tool_name in tool_functions:
            extra_content.append("\n" + tool_functions[tool_name] + "\n")

    # Backup existing files
    import time

    timestamp = int(time.time())
    backup_dir = module_dir / "backup"
    backup_dir.mkdir(exist_ok=True)

    # Backup tools.py
    shutil.copy(tools_file, backup_dir / f"tools.py.{int(timestamp)}")

    # Backup tools_basic.py and tools_extra.py if they exist
    if (module_dir / "tools_basic.py").exists():
        shutil.copy(
            module_dir / "tools_basic.py",
            backup_dir / f"tools_basic.py.{int(timestamp)}",
        )
    if (module_dir / "tools_extra.py").exists():
        shutil.copy(
            module_dir / "tools_extra.py",
            backup_dir / f"tools_extra.py.{int(timestamp)}",
        )

    # Write new files
    if used_tools:
        with open(module_dir / "tools_basic.py", "w") as f:
            f.write("\n".join(basic_content))
        print(f"   ✅ Created tools_basic.py ({len(used_tools)} tools)")

    if unused_tools:
        with open(module_dir / "tools_extra.py", "w") as f:
            f.write("\n".join(extra_content))
        print(f"   ✅ Created tools_extra.py ({len(unused_tools)} tools)")

    # Remove old tools.py
    tools_file.unlink()
    print("   🗑️  Removed tools.py (backed up to backup/)")

    return True


def update_module_imports(module_name: str):
    """Update __init__.py and server.py to use tools_basic."""
    module_dir = PROJECT_ROOT / "tool_modules" / module_name / "src"

    # Update server.py
    server_file = module_dir / "server.py"
    if server_file.exists():
        with open(server_file, "r") as f:
            content = f.read()

        # Replace imports
        updated = content.replace("from . import tools", "from . import tools_basic as tools").replace(
            "from .tools import", "from .tools_basic import"
        )

        if updated != content:
            with open(server_file, "w") as f:
                f.write(updated)
            print("   ✅ Updated server.py imports")


def main():
    print("=" * 80)
    print(" TOOL MODULE REORGANIZATION - FINAL VERSION")
    print("=" * 80)
    print("\nThis script reorganizes ALL tool modules based on skill usage analysis.")
    print("It will:")
    print("  1. Backup existing files to backup/ subdirectory")
    print("  2. Create tools_basic.py with USED tools")
    print("  3. Create tools_extra.py with UNUSED tools")
    print("  4. Remove old tools.py")
    print("  5. Update imports in server.py")
    print("\n" + "=" * 80 + "\n")

    # Parse analysis
    module_data = parse_analysis_report()

    # Process each module
    for module_name, data in sorted(module_data.items()):
        used_tools = data["used"]
        unused_tools = data["unused"]

        # Skip modules with no tools
        if not used_tools and not unused_tools:
            continue

        print(f"📦 {module_name}")
        print(f"   Used: {len(used_tools)}, Unused: {len(unused_tools)}")

        # Split the tools file
        success = split_tools_file(module_name, used_tools, unused_tools)

        if success:
            # Update imports
            update_module_imports(module_name)

        print()

    print("=" * 80)
    print("✅ REORGANIZATION COMPLETE")
    print("=" * 80)
    print("\nNext steps:")
    print("  1. Review the changes")
    print("  2. Run smoke tests: python scripts/smoke_test_tools.py")
    print("  3. Run full test suite: pytest")
    print("  4. Commit the changes")


if __name__ == "__main__":
    main()
