"""Shared constants for workflow tools."""

from pathlib import Path

# Base directories
TOOL_MODULES_DIR = Path(__file__).parent.parent.parent
PROJECT_DIR = TOOL_MODULES_DIR.parent

# Feature directories
MEMORY_DIR = PROJECT_DIR / "memory"
PERSONAS_DIR = PROJECT_DIR / "personas"
SKILLS_DIR = PROJECT_DIR / "skills"

# GitHub configuration for error reporting
GITHUB_REPO = "dmzoneill/redhat-ai-workflow"
GITHUB_ISSUES_URL = f"https://github.com/{GITHUB_REPO}/issues/new"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/issues"
