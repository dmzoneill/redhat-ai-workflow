"""
Context Resolver for AI Workflow Bot.

Extracts repository, issue, and MR context from messages and URLs.
Used by the Slack bot to determine which repo to operate on.

Usage:
    from scripts.common.context_resolver import ContextResolver

    resolver = ContextResolver()
    ctx = resolver.from_message("can you review https://gitlab.cee.redhat.com/org/repo/-/merge_requests/123")
    print(ctx.repo_path)  # /home/user/src/repo
    print(ctx.mr_id)      # 123
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ResolvedContext:
    """Context resolved from a message or URL."""

    # Jira context
    issue_key: Optional[str] = None
    jira_project: Optional[str] = None

    # Repository context
    repo_name: Optional[str] = None
    repo_path: Optional[str] = None
    gitlab_project: Optional[str] = None
    default_branch: Optional[str] = None

    # MR/PR context
    mr_id: Optional[str] = None
    mr_url: Optional[str] = None

    # GitLab issue context
    gitlab_issue_id: Optional[str] = None

    # Branch context
    branch_name: Optional[str] = None

    # Confidence and source
    confidence: str = "none"  # none, low, medium, high
    source: str = "unknown"  # url, issue_key, branch, explicit

    # Ambiguity - multiple matches
    alternatives: list = field(default_factory=list)

    def is_valid(self) -> bool:
        """Check if we have enough context to operate."""
        return bool(self.repo_path or self.gitlab_project)

    def needs_clarification(self) -> bool:
        """Check if user needs to clarify which repo."""
        return len(self.alternatives) > 1

    def to_dict(self) -> dict:
        """Convert to dictionary for skill inputs."""
        return {
            "issue_key": self.issue_key,
            "repo": self.repo_path,
            "project": self.gitlab_project,
            "mr_id": self.mr_id,
            "branch": self.branch_name,
        }


class ContextResolver:
    """
    Resolves context from messages, URLs, and issue keys.

    Uses config.json to map:
    - Issue key prefixes (AAP, APPSRE) → repositories
    - GitLab project paths → local directories
    - Repository names → full config
    """

    CONFIG_PATHS = [
        Path.cwd() / "config.json",
        Path(__file__).parent.parent.parent / "config.json",
        Path.home() / "src/redhat-ai-workflow/config.json",
    ]

    def __init__(self, config_path: Optional[Path] = None):
        self.config = self._load_config(config_path)
        self.repos = self.config.get("repositories", {})
        self._build_indexes()

    def _load_config(self, config_path: Optional[Path] = None) -> Dict[str, Any]:
        """Load config.json from known paths."""
        paths = [config_path] if config_path else self.CONFIG_PATHS

        for path in paths:
            if path and path.exists():
                try:
                    with open(path) as f:
                        result: Dict[str, Any] = json.load(f)
                        return result
                except Exception:
                    continue
        return {}

    def _build_indexes(self) -> None:
        """Build lookup indexes for fast resolution."""
        # Jira project → repo names (may be multiple)
        self.jira_to_repos: Dict[str, List[str]] = {}

        # GitLab project path → repo name
        self.gitlab_to_repo: Dict[str, str] = {}

        # Repo name → config
        self.repo_configs: Dict[str, Dict[str, Any]] = {}

        for repo_name, cfg in self.repos.items():
            self.repo_configs[repo_name] = cfg

            # Index by Jira project
            jira_proj = cfg.get("jira_project")
            if jira_proj:
                if jira_proj not in self.jira_to_repos:
                    self.jira_to_repos[jira_proj] = []
                self.jira_to_repos[jira_proj].append(repo_name)

            # Index by GitLab path
            gitlab_path = cfg.get("gitlab")
            if gitlab_path:
                self.gitlab_to_repo[gitlab_path] = repo_name

    def from_message(self, message: str) -> ResolvedContext:
        """
        Extract context from a Slack message.

        Checks (in order of priority):
        1. Full GitLab URLs
        2. Jira issue keys
        3. Repository names mentioned
        4. Branch names matching issue patterns
        """
        ctx = ResolvedContext()

        # 1. Check for GitLab MR URLs
        mr_match = re.search(r"https?://[^/\s]+/(.+?)/-/merge_requests/(\d+)", message)
        if mr_match:
            gitlab_project = mr_match.group(1)
            mr_id = mr_match.group(2)
            ctx.gitlab_project = gitlab_project
            ctx.mr_id = mr_id
            ctx.mr_url = mr_match.group(0)
            ctx.source = "url"
            ctx.confidence = "high"

            # Resolve to local repo
            if gitlab_project in self.gitlab_to_repo:
                repo_name = self.gitlab_to_repo[gitlab_project]
                cfg = self.repo_configs.get(repo_name, {})
                ctx.repo_name = repo_name
                ctx.repo_path = cfg.get("path")
                ctx.default_branch = cfg.get("default_branch", "main")

            return ctx

        # 2. Check for GitLab issue URLs
        issue_match = re.search(r"https?://[^/\s]+/(.+?)/-/issues/(\d+)", message)
        if issue_match:
            gitlab_project = issue_match.group(1)
            ctx.gitlab_project = gitlab_project
            ctx.gitlab_issue_id = issue_match.group(2)
            ctx.source = "url"
            ctx.confidence = "high"

            if gitlab_project in self.gitlab_to_repo:
                repo_name = self.gitlab_to_repo[gitlab_project]
                cfg = self.repo_configs.get(repo_name, {})
                ctx.repo_name = repo_name
                ctx.repo_path = cfg.get("path")

            return ctx

        # 3. Check for Jira issue keys
        issue_match = re.search(r"\b([A-Z]+-\d+)\b", message)
        if issue_match:
            issue_key = issue_match.group(1).upper()
            project_prefix = issue_key.split("-")[0]

            ctx.issue_key = issue_key
            ctx.jira_project = project_prefix
            ctx.source = "issue_key"

            # Find repos for this Jira project
            matching_repos = self.jira_to_repos.get(project_prefix, [])

            if len(matching_repos) == 1:
                # Single match - high confidence
                repo_name = matching_repos[0]
                cfg = self.repo_configs.get(repo_name, {})
                ctx.repo_name = repo_name
                ctx.repo_path = cfg.get("path")
                ctx.gitlab_project = cfg.get("gitlab")
                ctx.default_branch = cfg.get("default_branch", "main")
                ctx.confidence = "high"
            elif len(matching_repos) > 1:
                # Multiple matches - need clarification
                ctx.confidence = "low"
                ctx.alternatives = [
                    {
                        "name": r,
                        "path": self.repo_configs[r].get("path"),
                        "gitlab": self.repo_configs[r].get("gitlab"),
                    }
                    for r in matching_repos
                ]
            else:
                ctx.confidence = "low"

            return ctx

        # 4. Check for explicit repo names
        for repo_name in self.repos.keys():
            # Match repo name with word boundaries
            pattern = rf"\b{re.escape(repo_name)}\b"
            if re.search(pattern, message, re.IGNORECASE):
                cfg = self.repo_configs.get(repo_name, {})
                ctx.repo_name = repo_name
                ctx.repo_path = cfg.get("path")
                ctx.gitlab_project = cfg.get("gitlab")
                ctx.jira_project = cfg.get("jira_project")
                ctx.default_branch = cfg.get("default_branch", "main")
                ctx.source = "explicit"
                ctx.confidence = "medium"
                return ctx

        # 5. Check for branch patterns (e.g., AAP-12345-fix-something)
        branch_match = re.search(r"\b([A-Z]+-\d+[-a-z0-9]+)\b", message, re.IGNORECASE)
        if branch_match:
            branch = branch_match.group(1)
            # Extract issue key from branch
            issue_match = re.match(r"([A-Z]+-\d+)", branch, re.IGNORECASE)
            if issue_match:
                ctx.branch_name = branch
                ctx.issue_key = issue_match.group(1).upper()
                ctx.jira_project = ctx.issue_key.split("-")[0]
                ctx.source = "branch"
                ctx.confidence = "medium"

                # Resolve repo from issue
                matching_repos = self.jira_to_repos.get(ctx.jira_project, [])
                if len(matching_repos) == 1:
                    repo_name = matching_repos[0]
                    cfg = self.repo_configs.get(repo_name, {})
                    ctx.repo_name = repo_name
                    ctx.repo_path = cfg.get("path")
                    ctx.gitlab_project = cfg.get("gitlab")

        return ctx

    def from_issue_key(self, issue_key: str) -> ResolvedContext:
        """Resolve context from just an issue key."""
        return self.from_message(issue_key)

    def from_gitlab_url(self, url: str) -> ResolvedContext:
        """Resolve context from a GitLab URL."""
        return self.from_message(url)

    def from_repo_name(self, repo_name: str) -> ResolvedContext:
        """Resolve context from an explicit repo name."""
        ctx = ResolvedContext()

        if repo_name in self.repo_configs:
            cfg = self.repo_configs[repo_name]
            ctx.repo_name = repo_name
            ctx.repo_path = cfg.get("path")
            ctx.gitlab_project = cfg.get("gitlab")
            ctx.jira_project = cfg.get("jira_project")
            ctx.default_branch = cfg.get("default_branch", "main")
            ctx.source = "explicit"
            ctx.confidence = "high"

        return ctx

    def get_repo_path(self, gitlab_project: str) -> Optional[str]:
        """Get local repo path from GitLab project path."""
        if gitlab_project in self.gitlab_to_repo:
            repo_name = self.gitlab_to_repo[gitlab_project]
            return self.repo_configs.get(repo_name, {}).get("path")
        return None

    def get_repo_for_issue(self, issue_key: str) -> Optional[str]:
        """Get primary repo path for a Jira issue key."""
        project = issue_key.split("-")[0].upper()
        repos = self.jira_to_repos.get(project, [])
        if repos:
            return self.repo_configs.get(repos[0], {}).get("path")
        return None

    def list_repos_for_project(self, jira_project: str) -> list[dict]:
        """List all repos associated with a Jira project."""
        repos = self.jira_to_repos.get(jira_project.upper(), [])
        return [
            {
                "name": r,
                "path": self.repo_configs[r].get("path"),
                "gitlab": self.repo_configs[r].get("gitlab"),
            }
            for r in repos
        ]

    def format_clarification(self, ctx: ResolvedContext) -> str:
        """Format a message asking user to clarify which repo."""
        if not ctx.needs_clarification():
            return ""

        lines = ["which repo is this for?"]
        for alt in ctx.alternatives:
            name = alt["name"]
            gitlab = alt.get("gitlab", "")
            lines.append(f"• `{name}` ({gitlab})")

        return "\n".join(lines)


# Convenience function for quick resolution
def resolve_context(message: str) -> ResolvedContext:
    """Quick context resolution from a message."""
    return ContextResolver().from_message(message)


def get_repo_path(gitlab_project: str) -> Optional[str]:
    """Quick lookup of repo path from GitLab project."""
    return ContextResolver().get_repo_path(gitlab_project)
