#!/usr/bin/env python3
"""Fix remaining F401 unused imports."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def fix_file(file_path: Path, removals: dict[str, list[str]]) -> bool:
    """Remove specified imports from a file.

    Args:
        file_path: Path to the file
        removals: Dict of import lines to search for and items to remove

    Returns:
        True if file was modified
    """
    content = file_path.read_text()
    original = content
    lines = content.split("\n")
    new_lines = []

    for line in lines:
        skip_line = False
        modified_line = line

        for import_pattern, items_to_remove in removals.items():
            if import_pattern in line:
                # Handle different import styles
                if "from" in line and "import" in line:
                    # from X import Y, Z
                    for item in items_to_remove:
                        # Remove item from import list
                        modified_line = modified_line.replace(f", {item}", "")
                        modified_line = modified_line.replace(f"{item}, ", "")
                        modified_line = modified_line.replace(f"{item}", "")

                    # If line is now empty (only "from X import"), skip it
                    if modified_line.strip().endswith("import") or modified_line.strip().endswith("import "):
                        skip_line = True
                elif line.strip().startswith("import"):
                    # import X
                    for item in items_to_remove:
                        if item in line:
                            skip_line = True

        if not skip_line:
            # Clean up any double commas or trailing commas
            modified_line = modified_line.replace(",,", ",")
            modified_line = modified_line.replace(", )", ")")
            modified_line = modified_line.strip()
            if modified_line:
                new_lines.append(modified_line)
        else:
            # Keep blank line if original was blank
            if not line.strip():
                new_lines.append("")

    new_content = "\n".join(new_lines)
    if new_content != original:
        file_path.write_text(new_content)
        return True
    return False


def main():
    """Fix F401 errors in specific files."""

    fixes = {
        "tool_modules/aa_git/src/tools_extra.py": {
            "import os": ["os"],
            "from server.utils import": ["truncate_output"],
        },
        "tool_modules/aa_gitlab/src/tools_extra.py": {
            "from server.utils import": ["truncate_output"],
        },
        "tool_modules/aa_jira/src/tools_extra.py": {
            "from server.utils import": ["get_project_root"],
        },
        "tool_modules/aa_k8s/src/tools_extra.py": {
            "from server.utils import": ["truncate_output"],
        },
        "tool_modules/aa_kibana/src/tools_extra.py": {
            "from datetime import": ["datetime", "timedelta"],
        },
    }

    total_fixed = 0

    for file_rel, removals in fixes.items():
        file_path = PROJECT_ROOT / file_rel
        if file_path.exists():
            if fix_file(file_path, removals):
                print(f"✅ Fixed {file_rel}")
                total_fixed += 1
        else:
            print(f"⚠️ File not found: {file_rel}")

    print(f"\n✅ Total files fixed: {total_fixed}")


if __name__ == "__main__":
    main()
