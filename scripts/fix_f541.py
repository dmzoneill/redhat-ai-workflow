#!/usr/bin/env python3
"""Fix F541 errors - convert f-strings without placeholders to regular strings."""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def fix_f541_in_file(file_path: Path) -> int:
    """Fix f-strings without placeholders in a file.

    Returns:
        Number of fixes made
    """
    content = file_path.read_text()
    original = content
    fixes = 0

    # Pattern: f"string" or f'string' with no {placeholders}
    # Only replace if there are no curly braces inside
    patterns = [
        (r'f"([^"{}]*)"', r'"\1"'),  # f"text" -> "text"
        (r"f'([^'{}]*)'", r"'\1'"),  # f'text' -> 'text'
    ]

    for pattern, replacement in patterns:
        new_content = re.sub(pattern, replacement, content)
        if new_content != content:
            fixes += len(re.findall(pattern, content))
            content = new_content

    if content != original:
        file_path.write_text(content)
        return fixes
    return 0


def main():
    """Fix F541 errors in all Python files."""

    # Files with F541 errors from CI log
    files_to_fix = [
        "scripts/analyze_skill_tool_usage.py",
        "scripts/reorganize_tools.py",
        "scripts/reorganize_tools_final.py",
        "scripts/reorganize_tools_smart.py",
        "tool_modules/aa_dev_workflow/src/tools_basic.py",
    ]

    total_fixes = 0

    for file_rel in files_to_fix:
        file_path = PROJECT_ROOT / file_rel
        if file_path.exists():
            fixes = fix_f541_in_file(file_path)
            if fixes > 0:
                print(f"✅ Fixed {fixes} f-strings in {file_rel}")
                total_fixes += fixes
        else:
            print(f"⚠️ File not found: {file_rel}")

    print(f"\n✅ Total f-strings fixed: {total_fixes}")


if __name__ == "__main__":
    main()
