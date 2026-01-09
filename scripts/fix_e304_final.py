#!/usr/bin/env python3
"""Fix E304 errors - remove stray decorators before comment separators."""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def fix_e304_in_file(file_path: Path) -> int:
    """Fix E304 errors by removing stray decorators before comment separators.

    Pattern to fix:
        @auto_heal()

        # ==================== TOOLS USED IN SKILLS ====================
        @auto_heal()

    Should become:
        # ==================== TOOLS USED IN SKILLS ====================
        @auto_heal()

    Returns:
        Number of fixes made
    """
    content = file_path.read_text()
    original = content

    # Pattern: decorator + blank line + comment separator
    # Remove the decorator and blank line before the comment separator
    pattern = (
        r"(\n    )@(?:auto_heal|auto_heal_stage|auto_heal_konflux|"
        r"auto_heal_ephemeral)\([^\)]*\)[^\n]*\n\n(    # =+.*?=+\n)"
    )

    new_content = re.sub(pattern, r"\1\2", content)

    if new_content != original:
        file_path.write_text(new_content)
        return content.count("\n") - new_content.count("\n")
    return 0


def main():
    """Fix E304 errors in all tool module files."""

    tool_modules = [
        "tool_modules/aa_alertmanager/src/tools_basic.py",
        "tool_modules/aa_alertmanager/src/tools_extra.py",
        "tool_modules/aa_appinterface/src/tools_basic.py",
        "tool_modules/aa_appinterface/src/tools_extra.py",
        "tool_modules/aa_bonfire/src/tools_basic.py",
        "tool_modules/aa_bonfire/src/tools_extra.py",
        "tool_modules/aa_dev_workflow/src/tools_extra.py",
        "tool_modules/aa_git/src/tools_basic.py",
        "tool_modules/aa_git/src/tools_extra.py",
        "tool_modules/aa_gitlab/src/tools_basic.py",
        "tool_modules/aa_gitlab/src/tools_extra.py",
        "tool_modules/aa_jira/src/tools_basic.py",
        "tool_modules/aa_jira/src/tools_extra.py",
        "tool_modules/aa_k8s/src/tools_basic.py",
        "tool_modules/aa_k8s/src/tools_extra.py",
        "tool_modules/aa_kibana/src/tools_basic.py",
        "tool_modules/aa_kibana/src/tools_extra.py",
        "tool_modules/aa_konflux/src/tools_basic.py",
        "tool_modules/aa_konflux/src/tools_extra.py",
        "tool_modules/aa_lint/src/tools_basic.py",
        "tool_modules/aa_lint/src/tools_extra.py",
        "tool_modules/aa_prometheus/src/tools_basic.py",
        "tool_modules/aa_prometheus/src/tools_extra.py",
        "tool_modules/aa_quay/src/tools_basic.py",
        "tool_modules/aa_quay/src/tools_extra.py",
        "tool_modules/aa_slack/src/tools_basic.py",
        "tool_modules/aa_slack/src/tools_extra.py",
    ]

    total_fixes = 0

    for file_rel in tool_modules:
        file_path = PROJECT_ROOT / file_rel
        if file_path.exists():
            fixes = fix_e304_in_file(file_path)
            if fixes > 0:
                print(f"✅ Fixed {file_rel}")
                total_fixes += 1
        else:
            print(f"⚠️ File not found: {file_rel}")

    print(f"\n✅ Total files fixed: {total_fixes}")


if __name__ == "__main__":
    main()
