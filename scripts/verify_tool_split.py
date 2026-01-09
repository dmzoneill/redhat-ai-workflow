#!/usr/bin/env python3
"""
Verify that existing tools_basic/tools_extra splits match the analysis.
"""

import re
from pathlib import Path
from typing import Set

PROJECT_ROOT = Path(__file__).parent.parent


def get_tools_from_file(file_path: Path) -> Set[str]:
    """Extract tool names from a Python file."""
    if not file_path.exists():
        return set()

    with open(file_path, "r") as f:
        content = f.read()

    tools = set()
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if "@registry.tool()" in line or "@registry.tool(" in line or "@mcp.tool()" in line or "@mcp.tool(" in line:
            # Look ahead for the function definition
            for j in range(i + 1, min(i + 5, len(lines))):
                next_line = lines[j]
                match = re.match(r"\s*(?:async\s+)?def\s+(\w+)\s*\(", next_line)
                if match:
                    tools.add(match.group(1))
                    break

    return tools


def parse_analysis_report() -> dict:
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


def main():
    print("=" * 70)
    print("VERIFYING EXISTING TOOL SPLITS")
    print("=" * 70)

    analysis = parse_analysis_report()

    modules_with_split = ["aa_bonfire", "aa_git", "aa_gitlab", "aa_jira", "aa_k8s", "aa_konflux", "aa_prometheus"]

    print("\nChecking modules that already have basic/extra split...\n")

    mismatches = []

    for module_name in modules_with_split:
        module_dir = PROJECT_ROOT / "tool_modules" / module_name / "src"

        basic_file = module_dir / "tools_basic.py"
        extra_file = module_dir / "tools_extra.py"

        # Get tools from files
        tools_in_basic = get_tools_from_file(basic_file)
        tools_in_extra = get_tools_from_file(extra_file)

        # Get expected from analysis
        expected_data = analysis.get(module_name, {})
        expected_in_basic = expected_data.get("used", set())
        expected_in_extra = expected_data.get("unused", set())

        print(f"📦 {module_name}")
        print(f"   Basic: {len(tools_in_basic)} tools (expected {len(expected_in_basic)})")
        print(f"   Extra: {len(tools_in_extra)} tools (expected {len(expected_in_extra)})")

        # Check for mismatches
        only_in_basic = tools_in_basic - expected_in_basic
        only_in_extra = tools_in_extra - expected_in_extra
        missing_from_basic = expected_in_basic - tools_in_basic
        missing_from_extra = expected_in_extra - tools_in_extra

        if only_in_basic or only_in_extra or missing_from_basic or missing_from_extra:
            mismatches.append(module_name)
            print("   ⚠️  MISMATCH DETECTED:")

            if only_in_basic:
                print(f"      - In basic but should be extra: {only_in_basic}")
            if missing_from_basic:
                print(f"      - Missing from basic: {missing_from_basic}")
            if only_in_extra:
                print(f"      - In extra but should be basic: {only_in_extra}")
            if missing_from_extra:
                print(f"      - Missing from extra: {missing_from_extra}")
        else:
            print("   ✅ Split matches analysis")

        print()

    print("=" * 70)
    if mismatches:
        print(f"⚠️  {len(mismatches)} module(s) have mismatches:")
        for m in mismatches:
            print(f"   - {m}")
        print("\nThese modules need to be re-split based on the analysis.")
    else:
        print("✅ All existing splits match the analysis!")

    print("=" * 70)


if __name__ == "__main__":
    main()
