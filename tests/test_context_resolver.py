"""Tests for scripts/common/context_resolver.py - Context extraction from messages/URLs."""

import json
from pathlib import Path
from unittest.mock import patch

from scripts.common.context_resolver import (
    ContextResolver,
    ResolvedContext,
    get_repo_path,
    resolve_context,
)

# ==================== ResolvedContext ====================


class TestResolvedContext:
    def test_defaults(self):
        ctx = ResolvedContext()
        assert ctx.issue_key is None
        assert ctx.confidence == "none"
        assert ctx.source == "unknown"
        assert ctx.alternatives == []

    def test_is_valid_with_repo_path(self):
        ctx = ResolvedContext(repo_path="/home/user/src/repo")
        assert ctx.is_valid() is True

    def test_is_valid_with_gitlab_project(self):
        ctx = ResolvedContext(gitlab_project="org/repo")
        assert ctx.is_valid() is True

    def test_is_valid_empty(self):
        ctx = ResolvedContext()
        assert ctx.is_valid() is False

    def test_needs_clarification_no_alternatives(self):
        ctx = ResolvedContext()
        assert ctx.needs_clarification() is False

    def test_needs_clarification_one_alternative(self):
        ctx = ResolvedContext(alternatives=[{"name": "repo1"}])
        assert ctx.needs_clarification() is False

    def test_needs_clarification_multiple(self):
        ctx = ResolvedContext(alternatives=[{"name": "a"}, {"name": "b"}])
        assert ctx.needs_clarification() is True

    def test_to_dict(self):
        ctx = ResolvedContext(
            issue_key="AAP-123",
            repo_path="/home/user/src/repo",
            gitlab_project="org/repo",
            mr_id="42",
            branch_name="fix-bug",
        )
        d = ctx.to_dict()
        assert d["issue_key"] == "AAP-123"
        assert d["repo"] == "/home/user/src/repo"
        assert d["project"] == "org/repo"
        assert d["mr_id"] == "42"
        assert d["branch"] == "fix-bug"


# ==================== ContextResolver - setup ====================


SAMPLE_CONFIG = {
    "repositories": {
        "backend": {
            "path": "/home/user/src/backend",
            "gitlab": "org/backend",
            "jira_project": "AAP",
            "default_branch": "main",
        },
        "frontend": {
            "path": "/home/user/src/frontend",
            "gitlab": "org/frontend",
            "jira_project": "AAP",
            "default_branch": "main",
        },
        "infra": {
            "path": "/home/user/src/infra",
            "gitlab": "ops/infra",
            "jira_project": "APPSRE",
            "default_branch": "master",
        },
    }
}


def make_resolver(config=None):
    """Create a ContextResolver with mocked config loading."""
    if config is None:
        config = SAMPLE_CONFIG
    with patch.object(ContextResolver, "_load_config", return_value=config):
        return ContextResolver()


# ==================== _load_config ====================


class TestLoadConfig:
    def test_load_from_specified_path(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"repositories": {"x": {}}}))
        resolver = ContextResolver(config_path=cfg_file)
        assert "x" in resolver.repos

    def test_load_no_file(self):
        with patch.object(
            ContextResolver, "CONFIG_PATHS", [Path("/nonexistent/config.json")]
        ):
            resolver = ContextResolver()
            assert resolver.repos == {}

    def test_load_bad_json(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("not-json{{{")
        resolver = ContextResolver(config_path=cfg_file)
        assert resolver.repos == {}


# ==================== _build_indexes ====================


class TestBuildIndexes:
    def test_jira_to_repos_index(self):
        resolver = make_resolver()
        # AAP maps to both backend and frontend
        assert len(resolver.jira_to_repos["AAP"]) == 2
        assert "backend" in resolver.jira_to_repos["AAP"]
        assert "frontend" in resolver.jira_to_repos["AAP"]
        # APPSRE maps to infra
        assert resolver.jira_to_repos["APPSRE"] == ["infra"]

    def test_gitlab_to_repo_index(self):
        resolver = make_resolver()
        assert resolver.gitlab_to_repo["org/backend"] == "backend"
        assert resolver.gitlab_to_repo["org/frontend"] == "frontend"
        assert resolver.gitlab_to_repo["ops/infra"] == "infra"


# ==================== from_message - GitLab MR URLs ====================


class TestFromMessageMRUrl:
    def test_mr_url_known_project(self):
        resolver = make_resolver()
        ctx = resolver.from_message(
            "please review https://gitlab.cee.redhat.com/org/backend/-/merge_requests/42"
        )
        assert ctx.mr_id == "42"
        assert ctx.gitlab_project == "org/backend"
        assert ctx.repo_name == "backend"
        assert ctx.repo_path == "/home/user/src/backend"
        assert ctx.confidence == "high"
        assert ctx.source == "url"
        assert ctx.mr_url is not None

    def test_mr_url_unknown_project(self):
        resolver = make_resolver()
        ctx = resolver.from_message(
            "look at https://gitlab.cee.redhat.com/other/repo/-/merge_requests/99"
        )
        assert ctx.mr_id == "99"
        assert ctx.gitlab_project == "other/repo"
        assert ctx.repo_name is None
        assert ctx.confidence == "high"


# ==================== from_message - GitLab issue URLs ====================


class TestFromMessageIssueUrl:
    def test_gitlab_issue_url_known(self):
        resolver = make_resolver()
        ctx = resolver.from_message(
            "check https://gitlab.cee.redhat.com/ops/infra/-/issues/55"
        )
        assert ctx.gitlab_issue_id == "55"
        assert ctx.gitlab_project == "ops/infra"
        assert ctx.repo_name == "infra"
        assert ctx.confidence == "high"

    def test_gitlab_issue_url_unknown(self):
        resolver = make_resolver()
        ctx = resolver.from_message(
            "see https://gitlab.cee.redhat.com/unknown/proj/-/issues/10"
        )
        assert ctx.gitlab_issue_id == "10"
        assert ctx.repo_name is None


# ==================== from_message - Jira issue keys ====================


class TestFromMessageJiraKey:
    def test_single_repo_match(self):
        resolver = make_resolver()
        ctx = resolver.from_message("working on APPSRE-555")
        assert ctx.issue_key == "APPSRE-555"
        assert ctx.jira_project == "APPSRE"
        assert ctx.repo_name == "infra"
        assert ctx.repo_path == "/home/user/src/infra"
        assert ctx.confidence == "high"

    def test_multiple_repo_match(self):
        resolver = make_resolver()
        ctx = resolver.from_message("look at AAP-123")
        assert ctx.issue_key == "AAP-123"
        assert ctx.jira_project == "AAP"
        assert ctx.confidence == "low"
        assert len(ctx.alternatives) == 2

    def test_unknown_jira_project(self):
        resolver = make_resolver()
        ctx = resolver.from_message("UNKNOWN-99 needs work")
        assert ctx.issue_key == "UNKNOWN-99"
        assert ctx.confidence == "low"
        assert len(ctx.alternatives) == 0


# ==================== from_message - explicit repo names ====================


class TestFromMessageExplicitRepo:
    def test_repo_name_in_message(self):
        resolver = make_resolver()
        ctx = resolver.from_message("deploy the backend service")
        assert ctx.repo_name == "backend"
        assert ctx.confidence == "medium"
        assert ctx.source == "explicit"

    def test_no_match(self):
        resolver = make_resolver()
        ctx = resolver.from_message("hello world")
        assert ctx.repo_name is None
        assert ctx.confidence in ("none", "low", "medium")


# ==================== from_message - branch patterns ====================


class TestFromMessageBranch:
    def test_branch_pattern_single_repo(self):
        resolver = make_resolver()
        ctx = resolver.from_message("I pushed to APPSRE-100-fix-auth")
        # The jira key APPSRE-100 should match first (step 3) since it also matches \b([A-Z]+-\d+)\b
        assert ctx.issue_key == "APPSRE-100"

    def test_branch_no_jira_match_first(self):
        """Branch pattern only fires if no jira key matches directly."""
        resolver = make_resolver()
        # A branch with a made-up project that doesn't match any jira key
        ctx = resolver.from_message("checkout ZZZZ-55-fix-thing")
        # Step 3 matches the jira key ZZZZ-55
        assert ctx.issue_key == "ZZZZ-55"


# ==================== from_issue_key ====================


class TestFromIssueKey:
    def test_delegates_to_from_message(self):
        resolver = make_resolver()
        ctx = resolver.from_issue_key("APPSRE-42")
        assert ctx.issue_key == "APPSRE-42"
        assert ctx.source == "issue_key"


# ==================== from_gitlab_url ====================


class TestFromGitlabUrl:
    def test_delegates_to_from_message(self):
        resolver = make_resolver()
        ctx = resolver.from_gitlab_url(
            "https://gitlab.cee.redhat.com/org/backend/-/merge_requests/10"
        )
        assert ctx.mr_id == "10"


# ==================== from_repo_name ====================


class TestFromRepoName:
    def test_known_repo(self):
        resolver = make_resolver()
        ctx = resolver.from_repo_name("infra")
        assert ctx.repo_name == "infra"
        assert ctx.repo_path == "/home/user/src/infra"
        assert ctx.gitlab_project == "ops/infra"
        assert ctx.jira_project == "APPSRE"
        assert ctx.default_branch == "master"
        assert ctx.confidence == "high"

    def test_unknown_repo(self):
        resolver = make_resolver()
        ctx = resolver.from_repo_name("nonexistent")
        assert ctx.repo_name is None
        assert ctx.confidence == "none"


# ==================== get_repo_path ====================


class TestGetRepoPath:
    def test_known_gitlab_project(self):
        resolver = make_resolver()
        assert resolver.get_repo_path("org/backend") == "/home/user/src/backend"

    def test_unknown_gitlab_project(self):
        resolver = make_resolver()
        assert resolver.get_repo_path("unknown/repo") is None


# ==================== get_repo_for_issue ====================


class TestGetRepoForIssue:
    def test_known_issue(self):
        resolver = make_resolver()
        path = resolver.get_repo_for_issue("APPSRE-42")
        assert path == "/home/user/src/infra"

    def test_aap_returns_first_match(self):
        resolver = make_resolver()
        path = resolver.get_repo_for_issue("AAP-1")
        # First match is backend
        assert path == "/home/user/src/backend"

    def test_unknown_issue(self):
        resolver = make_resolver()
        assert resolver.get_repo_for_issue("UNKNOWN-1") is None


# ==================== list_repos_for_project ====================


class TestListReposForProject:
    def test_multiple_repos(self):
        resolver = make_resolver()
        repos = resolver.list_repos_for_project("AAP")
        assert len(repos) == 2
        names = [r["name"] for r in repos]
        assert "backend" in names
        assert "frontend" in names

    def test_single_repo(self):
        resolver = make_resolver()
        repos = resolver.list_repos_for_project("APPSRE")
        assert len(repos) == 1
        assert repos[0]["name"] == "infra"

    def test_no_repos(self):
        resolver = make_resolver()
        repos = resolver.list_repos_for_project("UNKNOWN")
        assert repos == []

    def test_case_insensitive(self):
        resolver = make_resolver()
        repos = resolver.list_repos_for_project("appsre")
        # The code does .upper() so this should still work
        assert len(repos) == 1


# ==================== format_clarification ====================


class TestFormatClarification:
    def test_no_clarification_needed(self):
        resolver = make_resolver()
        ctx = ResolvedContext()
        assert resolver.format_clarification(ctx) == ""

    def test_clarification_needed(self):
        resolver = make_resolver()
        ctx = ResolvedContext(
            alternatives=[
                {"name": "backend", "gitlab": "org/backend"},
                {"name": "frontend", "gitlab": "org/frontend"},
            ]
        )
        msg = resolver.format_clarification(ctx)
        assert "which repo" in msg
        assert "backend" in msg
        assert "frontend" in msg


# ==================== Convenience functions ====================


class TestConvenienceFunctions:
    def test_resolve_context(self):
        with patch.object(ContextResolver, "_load_config", return_value=SAMPLE_CONFIG):
            ctx = resolve_context("look at APPSRE-99")
            assert ctx.issue_key == "APPSRE-99"

    def test_get_repo_path_func(self):
        with patch.object(ContextResolver, "_load_config", return_value=SAMPLE_CONFIG):
            path = get_repo_path("org/backend")
            assert path == "/home/user/src/backend"

    def test_get_repo_path_func_unknown(self):
        with patch.object(ContextResolver, "_load_config", return_value=SAMPLE_CONFIG):
            path = get_repo_path("unknown/repo")
            assert path is None
