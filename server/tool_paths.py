"""Tool Path Resolution - Shared utilities for tool module path resolution.

This module centralizes the logic for resolving tool module file paths,
eliminating duplication between main.py and persona_loader.py.

Usage:
    from server.tool_paths import get_tools_file_path, TOOL_MODULES_DIR

    path = get_tools_file_path("git")  # Returns aa_git/src/tools_core.py or fallback
    path = get_tools_file_path("git_basic")  # Returns aa_git/src/tools_basic.py
"""

from pathlib import Path

# Directory structure:
# ai-workflow/
#   server/         <- This file is here
#     tool_paths.py
#   tool_modules/   <- Tool modules are here
#     aa_git/
#     aa_jira/
#     ...
PROJECT_DIR = Path(__file__).parent.parent  # ai-workflow root
TOOL_MODULES_DIR = PROJECT_DIR / "tool_modules"

# Tool file naming conventions
TOOLS_FILE = "tools.py"
TOOLS_CORE_FILE = "tools_core.py"
TOOLS_BASIC_FILE = "tools_basic.py"
TOOLS_EXTRA_FILE = "tools_extra.py"
TOOLS_STYLE_FILE = "tools_style.py"


def get_tools_file_path(module_name: str) -> Path:
    """
    Determine the correct tools file path for a tool module name.

    Handles _core, _basic, _extra, and _style suffixes properly:
    - k8s_core -> aa_k8s/src/tools_core.py
    - k8s_basic -> aa_k8s/src/tools_basic.py
    - k8s_extra -> aa_k8s/src/tools_extra.py
    - slack_style -> aa_slack/src/tools_style.py
    - workflow -> aa_workflow/src/tools_core.py (if exists) or tools_basic.py fallback

    Args:
        module_name: Tool module name (e.g., "git", "git_core", "git_basic", "git_extra")

    Returns:
        Path to the tools file
    """
    if module_name.endswith("_core"):
        base_name = module_name[:-5]  # Remove "_core"
        module_dir = TOOL_MODULES_DIR / f"aa_{base_name}"
        return module_dir / "src" / TOOLS_CORE_FILE
    elif module_name.endswith("_basic"):
        base_name = module_name[:-6]  # Remove "_basic"
        module_dir = TOOL_MODULES_DIR / f"aa_{base_name}"
        return module_dir / "src" / TOOLS_BASIC_FILE
    elif module_name.endswith("_extra"):
        base_name = module_name[:-6]  # Remove "_extra"
        module_dir = TOOL_MODULES_DIR / f"aa_{base_name}"
        return module_dir / "src" / TOOLS_EXTRA_FILE
    elif module_name.endswith("_style"):
        base_name = module_name[:-6]  # Remove "_style"
        module_dir = TOOL_MODULES_DIR / f"aa_{base_name}"
        return module_dir / "src" / TOOLS_STYLE_FILE
    else:
        # For non-suffixed modules, try tools_core.py first (new default),
        # then tools_basic.py, then tools.py
        module_dir = TOOL_MODULES_DIR / f"aa_{module_name}"
        tools_core = module_dir / "src" / TOOLS_CORE_FILE
        if tools_core.exists():
            return tools_core
        tools_basic = module_dir / "src" / TOOLS_BASIC_FILE
        if tools_basic.exists():
            return tools_basic
        # Fallback to legacy tools.py
        return module_dir / "src" / TOOLS_FILE


def get_module_dir(module_name: str) -> Path:
    """
    Get the directory for a tool module.

    Args:
        module_name: Base module name (without _core/_basic/_extra suffix)

    Returns:
        Path to the module directory (e.g., tool_modules/aa_git)
    """
    # Strip any suffix to get base name
    base_name = module_name
    for suffix in ("_core", "_basic", "_extra", "_style"):
        if module_name.endswith(suffix):
            base_name = module_name[: -len(suffix)]
            break
    return TOOL_MODULES_DIR / f"aa_{base_name}"
