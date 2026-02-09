"""Shared constants for workflow tools."""

from pathlib import Path

# Base directories
TOOL_MODULES_DIR = Path(__file__).parent.parent.parent
PROJECT_DIR = TOOL_MODULES_DIR.parent

# Feature directories
MEMORY_DIR = PROJECT_DIR / "memory"
PERSONAS_DIR = PROJECT_DIR / "personas"
SKILLS_DIR = PROJECT_DIR / "skills"
KNOWLEDGE_DIR = MEMORY_DIR / "knowledge" / "personas"


# GitHub configuration for error reporting - read from config.json with fallback
def _load_github_repo() -> str:
    """Load GitHub repo from config.json, falling back to hardcoded default."""
    try:
        from scripts.common.config_loader import load_config

        config = load_config()
        repo = config.get("github", {}).get("repo")
        if isinstance(repo, str) and repo:
            return repo
    except ImportError:
        pass
    return "dmzoneill/redhat-ai-workflow"


GITHUB_REPO = _load_github_repo()
GITHUB_ISSUES_URL = f"https://github.com/{GITHUB_REPO}/issues/new"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/issues"
