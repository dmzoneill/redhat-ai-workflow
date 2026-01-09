#!/usr/bin/env python3
"""
Update __init__.py and server.py files to import from tools_basic instead of tools.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def update_file_imports(file_path: Path):
    """Update imports in a Python file."""
    if not file_path.exists():
        return False

    with open(file_path, "r") as f:
        content = f.read()

    original = content

    # Replace various import patterns
    content = (
        content.replace("from .tools import", "from .tools_basic import")
        .replace("from . import tools", "from . import tools_basic as tools")
        .replace("import tools", "import tools_basic as tools")
    )

    if content != original:
        with open(file_path, "w") as f:
            f.write(content)
        return True

    return False


def main():
    print("=" * 70)
    print("UPDATING MODULE IMPORTS")
    print("=" * 70)

    modules_dir = PROJECT_ROOT / "tool_modules"
    updated_files = []

    for module_dir in sorted(modules_dir.glob("aa_*")):
        if not module_dir.is_dir():
            continue

        src_dir = module_dir / "src"
        if not src_dir.exists():
            continue

        # Check if this module has tools_basic.py
        if not (src_dir / "tools_basic.py").exists():
            continue

        module_name = module_dir.name
        print(f"\n📦 {module_name}")

        # Update __init__.py
        init_file = src_dir / "__init__.py"
        if update_file_imports(init_file):
            print("   ✅ Updated __init__.py")
            updated_files.append(str(init_file))
        else:
            print("   ℹ️  __init__.py already correct or doesn't exist")

        # Update server.py
        server_file = src_dir / "server.py"
        if update_file_imports(server_file):
            print("   ✅ Updated server.py")
            updated_files.append(str(server_file))
        else:
            print("   ℹ️  server.py already correct or doesn't exist")

    print("\n" + "=" * 70)
    print(f"✅ Updated {len(updated_files)} files")
    print("=" * 70)


if __name__ == "__main__":
    main()
