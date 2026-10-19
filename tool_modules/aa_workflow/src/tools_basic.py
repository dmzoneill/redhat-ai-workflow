"""Workflow MCP Server - High-level workflow and local development tools.

Provides workflow coordination and local development tools:
- workflow_start_work: Get context to start working on a Jira issue
- workflow_check_deploy_readiness: Check if MR is ready to deploy
- workflow_review_feedback: Get review comments on an MR
- lint_python: Run Python linters (black, flake8, isort)
- lint_yaml: Validate YAML files
- lint_dockerfile: Lint Dockerfiles with hadolint
- test_run: Run tests (pytest/npm)
- test_coverage: Get coverage report
- security_scan: Run security scanning (bandit/npm audit)
- precommit_run: Run pre-commit hooks
"""

import hashlib
import logging
import os
import platform
import sys
import time
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING, cast

import httpx

if TYPE_CHECKING:
    from fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
# pylint: disable-next=wrong-import-position
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization


# Setup project path for server imports
from server.utils import (  # pylint: disable=wrong-import-position
    load_config,
    resolve_repo_path,
    run_cmd_full,
)

logger = logging.getLogger(__name__)


REPOS_CONFIG = load_config()
# Repos are stored as dict: {"name": {"path": "...", ...}}
repos_data = REPOS_CONFIG.get("repositories", {})
if isinstance(repos_data, dict):
    REPO_PATHS = {
        name: info.get("path", "")
        for name, info in repos_data.items()
        if info.get("path")
    }
else:
    REPO_PATHS = {}

# GitHub configuration for error reporting - single source of truth in constants.py
try:
    from . import constants as _workflow_constants
except ImportError:
    import constants as _workflow_constants  # type: ignore[no-redef]

GITHUB_API_URL = _workflow_constants.GITHUB_API_URL
GITHUB_ISSUES_URL = _workflow_constants.GITHUB_ISSUES_URL
GITHUB_REPO = _workflow_constants.GITHUB_REPO

# Track recently created issues to avoid duplicates (in-memory cache)
_recent_issues: dict[str, float] = {}
_ISSUE_DEDUP_SECONDS = 3600  # Don't create duplicate issues within 1 hour
_MAX_RECENT_ISSUES = 100  # Prevent unbounded memory growth


def _get_github_token() -> str | None:
    """Get GitHub token from environment."""
    return os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")


def _issue_fingerprint(tool: str, error: str) -> str:
    """Create a fingerprint for deduplication."""
    # Use first 100 chars of error to group similar errors
    content = f"{tool}:{error[:100]}"
    return hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()[:12]


# pylint: disable-next=too-many-locals
async def create_github_issue(
    tool: str,
    error: str,
    context: str = "",
    skill: str = "",
    labels: list[str] | None = None,
) -> dict:
    """
    Create a GitHub issue for a tool/skill failure.

    Returns:
        dict with 'success', 'issue_url', and 'message'
    """
    # Check for duplicate
    fingerprint = _issue_fingerprint(tool, error)
    now = time.time()

    # Cleanup: remove expired entries and enforce max size
    global _recent_issues  # pylint: disable=global-statement
    _recent_issues = {
        k: v for k, v in _recent_issues.items() if now - v < _ISSUE_DEDUP_SECONDS
    }
    if len(_recent_issues) > _MAX_RECENT_ISSUES:
        # Keep only the most recent entries
        sorted_items = sorted(_recent_issues.items(), key=lambda x: x[1], reverse=True)
        _recent_issues = dict(sorted_items[:_MAX_RECENT_ISSUES])

    if fingerprint in _recent_issues:
        last_created = _recent_issues[fingerprint]
        if now - last_created < _ISSUE_DEDUP_SECONDS:
            return {
                "success": False,
                "issue_url": None,
                "message": f"Similar issue recently created (dedup: {fingerprint})",
            }

    # Check for GitHub token
    token = _get_github_token()
    if not token:
        # Fall back to URL generation
        url = format_github_issue_url(tool, error, context)
        return {
            "success": False,
            "issue_url": url,
            "message": "No GITHUB_TOKEN - use this link to create manually",
        }

    # Build issue body
    body = f"""## 🐛 Automated Error Report

**Tool/Skill:** `{tool}`
{f"**Skill:** `{skill}`" if skill else ""}

### Error
```
{error[:1000]}
```

### Context
{context[:500] if context else "No additional context provided"}

### Environment
- **Python:** {sys.version.split()[0]}
- **Platform:** {platform.system()} {platform.release()}
- **Fingerprint:** `{fingerprint}`

---
*This issue was automatically created by AI Workflow error tracking.*
"""

    # Determine labels
    issue_labels = labels or ["bug", "automated"]
    if "jira" in tool.lower() or "rh-issue" in error.lower():
        issue_labels.append("jira")
    if "gitlab" in tool.lower():
        issue_labels.append("gitlab")
    if "k8s" in tool.lower() or "kubectl" in tool.lower():
        issue_labels.append("kubernetes")

    # Create the issue
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GITHUB_API_URL,
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "AI-Workflow-Error-Reporter",
                },
                json={
                    "title": f"[Auto] Tool Error: {tool}",
                    "body": body,
                    "labels": issue_labels,
                },
                timeout=30.0,
            )

            if response.status_code == 201:
                data = response.json()
                issue_url = data.get("html_url", "")
                _recent_issues[fingerprint] = now

                logger.info("Created GitHub issue: %s", issue_url)
                return {
                    "success": True,
                    "issue_url": issue_url,
                    "message": f"Issue created: {issue_url}",
                }
            logger.warning(
                "Failed to create issue: %s - %s",
                response.status_code,
                response.text[:200],
            )
            url = format_github_issue_url(tool, error, context)
            return {
                "success": False,
                "issue_url": url,
                "message": f"API error {response.status_code} - use link to create manually",
            }

    # GitHub or the network can fail in ways we turn into a manual-create link.
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error creating GitHub issue: %s", e)
        url = format_github_issue_url(tool, error, context)
        return {
            "success": False,
            "issue_url": url,
            "message": f"Failed: {e} - use link to create manually",
        }


def format_github_issue_url(tool: str, error: str, context: str = "") -> str:
    """Generate a pre-filled GitHub issue URL for tool errors."""
    title = f"Tool Error: {tool}"
    body = f"""## Error Report

**Tool:** `{tool}`
**Error:**
```
{error[:500]}
```

**Context:**
{context[:200] if context else "No additional context"}

**Environment:**
- AI Workflow version: (please fill in)
- Python version: (please fill in)

**Steps to reproduce:**
1. (describe what you were doing)

**Expected behavior:**
(what should have happened)
"""
    params = urllib.parse.urlencode(
        {"title": title, "body": body, "labels": "bug,tool-error"}
    )
    return f"{GITHUB_ISSUES_URL}?{params}"


# ==================== Helper Functions ====================

# run_cmd is imported from server.utils as run_cmd_full
run_cmd = run_cmd_full


def resolve_path(repo: str) -> str:
    """Resolve repo name to path."""
    if repo in REPO_PATHS:
        return cast(str, REPO_PATHS[repo])
    # Try shared resolver
    resolved = resolve_repo_path(repo)
    if os.path.isdir(resolved):
        return resolved
    raise ValueError(f"Unknown repository: {repo}")


# ==================== MODULAR TOOL REGISTRATION ====================

# Import register functions from extracted modules
# Support both package import and direct loading
_TOOLS_DIR = Path(__file__).parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

try:
    from .chat_context import register_chat_context_tools
    from .infra_tools import register_infra_tools
    from .memory_tools import register_memory_tools
    from .meta_tools import register_meta_tools
    from .persona_tools import register_persona_tools
    from .resources import register_resources
    from .session_tools import register_prompts, register_session_tools
    from .skill_engine import register_skill_tools
    from .sprint_tools import register_sprint_tools
except ImportError:
    from chat_context import register_chat_context_tools  # type: ignore[no-redef]
    from infra_tools import register_infra_tools  # type: ignore[no-redef]
    from memory_tools import register_memory_tools  # type: ignore[no-redef]
    from meta_tools import register_meta_tools  # type: ignore[no-redef]
    from persona_tools import register_persona_tools  # type: ignore[no-redef]
    from resources import register_resources  # type: ignore[no-redef]
    from session_tools import (  # type: ignore[no-redef]
        register_prompts,
        register_session_tools,
    )
    from skill_engine import register_skill_tools  # type: ignore[no-redef]
    from sprint_tools import register_sprint_tools  # type: ignore[no-redef]


def register_tools(server: "FastMCP") -> int:
    """
    Register core workflow tools with the MCP server.

    This function registers only CORE tools needed by all personas:
    - memory_tools: 9 tools for persistent context storage
    - persona_tools: 2 tools for persona management
    - session_tools: 1 tool + 3 prompts for session management
    - resources: 8 MCP resources for config/state
    - skill_engine: 2 tools for skill execution (with Claude Code integration)
    - infra_tools: 2 tools for VPN/Kube auth
    - meta_tools: 3 tools for dynamic tool loading

    Total: ~18 tools (down from 36)

    Extra tools (in tools_extra.py, load via workflow_extra):
    - knowledge_tools: 6 tools for project knowledge management
    - project_tools: 5 tools for project configuration
    - scheduler_tools: 7 tools for cron job management
    """
    tool_count = 0

    # Detect Claude Code and set up AskUserQuestion integration
    try:
        from .claude_code_integration import (  # pylint: disable=import-outside-toplevel
            create_ask_question_wrapper,
            get_claude_code_capabilities,
        )

        capabilities = get_claude_code_capabilities()
        logger.info("Claude Code detection: %s", capabilities)

        # Create AskUserQuestion wrapper if available
        ask_question_fn = create_ask_question_wrapper(server)
        if ask_question_fn:
            logger.info(
                "✅ AskUserQuestion integration enabled - using native Claude Code UI"
            )
        else:
            logger.info(
                "ℹ️  AskUserQuestion not available - using CLI fallback for skill errors"
            )
    except ImportError:
        logger.debug("Claude Code integration module not available")
        ask_question_fn = None

    # Register CORE tools only (19 tools + 9 sprint tools + unified memory)
    tool_count += register_chat_context_tools(server)
    tool_count += register_memory_tools(server)
    tool_count += register_persona_tools(server)
    tool_count += register_session_tools(server)
    tool_count += register_prompts(server)
    tool_count += register_resources(server, load_config)
    tool_count += register_skill_tools(server, create_github_issue, ask_question_fn)
    tool_count += register_infra_tools(server)
    tool_count += register_meta_tools(server, create_github_issue)
    tool_count += register_sprint_tools(server)

    # Register unified memory abstraction tools
    try:
        # pylint: disable-next=import-outside-toplevel
        from .memory_unified import register_tools as register_unified_memory_tools

        tool_count += register_unified_memory_tools(server)
        logger.info("✅ Unified memory abstraction tools registered")
    except ImportError as e:
        logger.warning("Unified memory tools not available: %s", e)

    logger.info("Registered %s core workflow tools", tool_count)
    return tool_count
