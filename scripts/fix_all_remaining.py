#!/usr/bin/env python3
"""Fix all remaining linting errors comprehensively."""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def fix_e501_line_length(file_path: Path) -> bool:
    """Fix E501 line-too-long errors."""
    content = file_path.read_text()
    original = content

    # Split the long regex pattern across multiple lines
    if "fix_e304_final.py" in str(file_path):
        old_pattern = (
            r'    pattern = r"(\n    )@(?:auto_heal|auto_heal_stage|'
            r'auto_heal_konflux|auto_heal_ephemeral)\([^\)]*\)[^\n]*\n\n(    # =+.*?=+\n)"'
        )
        new_pattern = """    pattern = (
        r"(\\n    )@(?:auto_heal|auto_heal_stage|auto_heal_konflux|"
        r"auto_heal_ephemeral)\\([^\\)]*\\)[^\\n]*\\n\\n(    # =+.*?=+\\n)"
    )"""
        content = content.replace(old_pattern, new_pattern)

    if content != original:
        file_path.write_text(content)
        return True
    return False


def fix_f541_fstrings(file_path: Path) -> bool:
    """Fix F541 f-strings without placeholders."""
    content = file_path.read_text()
    original = content

    # Pattern: f"string" or f'string' with no {placeholders}
    patterns = [
        (r'f"([^"{}]*)"', r'"\1"'),
        (r"f'([^'{}]*)'", r"'\1'"),
    ]

    for pattern, replacement in patterns:
        content = re.sub(pattern, replacement, content)

    if content != original:
        file_path.write_text(content)
        return True
    return False


def fix_f401_imports(file_path: Path, imports_to_remove: list[str]) -> bool:
    """Remove unused imports."""
    content = file_path.read_text()
    lines = content.split("\n")
    new_lines = []

    for line in lines:
        skip = False
        modified_line = line

        for imp in imports_to_remove:
            if f"import {imp}" == line.strip():
                skip = True
                break
            elif f"from {imp}" in line:
                skip = True
                break
            elif f", {imp}" in line:
                modified_line = modified_line.replace(f", {imp}", "")
            elif f"{imp}," in line:
                modified_line = modified_line.replace(f"{imp},", "")

        if not skip:
            new_lines.append(modified_line)

    new_content = "\n".join(new_lines)
    if new_content != content:
        file_path.write_text(new_content)
        return True
    return False


def fix_e304_blank_lines(file_path: Path) -> bool:
    """Fix E304 blank lines after decorators."""
    content = file_path.read_text()
    original = content

    # Remove stray decorator before comment separator
    pattern1 = (
        r"(\n    )@(?:auto_heal|auto_heal_stage|auto_heal_konflux|"
        r"auto_heal_ephemeral)\([^\)]*\)[^\n]*\n\n(    # =+.*?=+\n)"
    )
    content = re.sub(pattern1, r"\1\2", content)

    # Remove blank line between comment separator and decorator
    pattern2 = r"(    # =+.*?=+)\n\n(    @(?:auto_heal|registry))"
    content = re.sub(pattern2, r"\1\n\2", content)

    if content != original:
        file_path.write_text(content)
        return True
    return False


def add_missing_import(file_path: Path, import_line: str) -> bool:
    """Add missing import after existing imports."""
    content = file_path.read_text()

    # Check if import already exists
    if import_line in content:
        return False

    lines = content.split("\n")
    new_lines = []
    added = False

    for i, line in enumerate(lines):
        new_lines.append(line)
        # Add after the last "from .tools_basic import" line
        if "from .tools_basic import" in line and not added:
            # Check if next line is blank or a different import
            if i + 1 < len(lines) and not lines[i + 1].startswith("from .tools_basic"):
                new_lines.append(import_line)
                added = True

    if added:
        file_path.write_text("\n".join(new_lines))
        return True
    return False


def main():
    """Fix all remaining linting errors."""

    fixes_applied = 0

    # Fix E501 line too long
    file = PROJECT_ROOT / "scripts/fix_e304_final.py"
    if file.exists() and fix_e501_line_length(file):
        print(f"✅ Fixed E501 in {file.relative_to(PROJECT_ROOT)}")
        fixes_applied += 1

    # Fix F541 f-strings
    f541_files = [
        "scripts/update_module_imports.py",
        "scripts/verify_tool_split.py",
    ]
    for rel_path in f541_files:
        file = PROJECT_ROOT / rel_path
        if file.exists() and fix_f541_fstrings(file):
            print(f"✅ Fixed F541 in {rel_path}")
            fixes_applied += 1

    # Fix F401 unused imports
    f401_fixes = {
        "tool_modules/aa_git/src/tools_extra.py": ["os", "truncate_output"],
        "tool_modules/aa_gitlab/src/tools_extra.py": ["truncate_output"],
        "tool_modules/aa_jira/src/tools_extra.py": ["get_project_root"],
        "tool_modules/aa_k8s/src/tools_extra.py": ["truncate_output"],
        "tool_modules/aa_kibana/src/tools_extra.py": ["datetime", "timedelta"],
    }
    for rel_path, imports in f401_fixes.items():
        file = PROJECT_ROOT / rel_path
        if file.exists() and fix_f401_imports(file, imports):
            print(f"✅ Fixed F401 in {rel_path}")
            fixes_applied += 1

    # Fix E304 blank lines
    e304_files = [
        "tool_modules/aa_git/src/tools_extra.py",
        "tool_modules/aa_gitlab/src/tools_extra.py",
        "tool_modules/aa_jira/src/tools_extra.py",
        "tool_modules/aa_k8s/src/tools_extra.py",
        "tool_modules/aa_kibana/src/tools_extra.py",
    ]
    for rel_path in e304_files:
        file = PROJECT_ROOT / rel_path
        if file.exists() and fix_e304_blank_lines(file):
            print(f"✅ Fixed E304 in {rel_path}")
            fixes_applied += 1

    # Fix F821 undefined names
    kibana_file = PROJECT_ROOT / "tool_modules/aa_kibana/src/tools_extra.py"
    if kibana_file.exists():
        if add_missing_import(kibana_file, "from .tools_basic import kibana_search_logs"):
            print("✅ Added kibana_search_logs import to tools_extra.py")
            fixes_applied += 1

    print(f"\n✅ Total fixes applied: {fixes_applied}")


if __name__ == "__main__":
    main()
