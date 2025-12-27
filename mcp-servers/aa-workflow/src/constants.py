"""Shared constants for workflow tools."""

from pathlib import Path

# Base directories
SERVERS_DIR = Path(__file__).parent.parent.parent
PROJECT_DIR = SERVERS_DIR.parent

# Feature directories
MEMORY_DIR = PROJECT_DIR / "memory"
AGENTS_DIR = PROJECT_DIR / "agents"
SKILLS_DIR = PROJECT_DIR / "skills"

# GitHub configuration for error reporting
GITHUB_REPO = "dmzoneill/redhat-ai-workflow"
GITHUB_ISSUES_URL = f"https://github.com/{GITHUB_REPO}/issues/new"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/issues"
