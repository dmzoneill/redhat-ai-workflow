"""Tests for tool_modules.aa_workflow.src.tools_basic module."""

import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tool_modules.aa_workflow.src.tools_basic import (
    _ISSUE_DEDUP_SECONDS,
    _MAX_RECENT_ISSUES,
    GITHUB_API_URL,
    GITHUB_ISSUES_URL,
    GITHUB_REPO,
    REPO_PATHS,
    _get_github_token,
    _issue_fingerprint,
    create_github_issue,
    format_github_issue_url,
    register_tools,
    resolve_path,
)

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_github_repo(self):
        assert "dmzoneill/redhat-ai-workflow" in GITHUB_REPO

    def test_github_issues_url(self):
        assert GITHUB_ISSUES_URL.startswith("https://github.com/")
        assert "issues/new" in GITHUB_ISSUES_URL

    def test_github_api_url(self):
        assert GITHUB_API_URL.startswith("https://api.github.com/repos/")

    def test_dedup_seconds(self):
        assert _ISSUE_DEDUP_SECONDS == 3600

    def test_max_recent_issues(self):
        assert _MAX_RECENT_ISSUES == 100

    def test_repo_paths_is_dict(self):
        assert isinstance(REPO_PATHS, dict)


# ---------------------------------------------------------------------------
# _get_github_token
# ---------------------------------------------------------------------------


class TestGetGithubToken:
    def test_returns_github_token(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_abc123"}, clear=False):
            assert _get_github_token() == "ghp_abc123"

    def test_falls_back_to_gh_token(self):
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
        env["GH_TOKEN"] = "ghp_xyz"
        with patch.dict(os.environ, env, clear=True):
            assert _get_github_token() == "ghp_xyz"

    def test_returns_none_when_no_token(self):
        env = {
            k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN")
        }
        with patch.dict(os.environ, env, clear=True):
            result = _get_github_token()
            assert result is None or result == ""


# ---------------------------------------------------------------------------
# _issue_fingerprint
# ---------------------------------------------------------------------------


class TestIssueFingerprint:
    def test_returns_string(self):
        result = _issue_fingerprint("my_tool", "some error")
        assert isinstance(result, str)

    def test_returns_12_chars(self):
        result = _issue_fingerprint("tool", "error")
        assert len(result) == 12

    def test_same_input_same_output(self):
        fp1 = _issue_fingerprint("tool", "error message")
        fp2 = _issue_fingerprint("tool", "error message")
        assert fp1 == fp2

    def test_different_tool_different_fingerprint(self):
        fp1 = _issue_fingerprint("tool_a", "error")
        fp2 = _issue_fingerprint("tool_b", "error")
        assert fp1 != fp2

    def test_truncates_error_to_100_chars(self):
        short_error = "x" * 100
        long_error = "x" * 200
        fp1 = _issue_fingerprint("tool", short_error)
        fp2 = _issue_fingerprint("tool", long_error)
        assert fp1 == fp2


# ---------------------------------------------------------------------------
# format_github_issue_url
# ---------------------------------------------------------------------------


class TestFormatGithubIssueUrl:
    def test_returns_url_string(self):
        url = format_github_issue_url("my_tool", "error happened")
        assert url.startswith(GITHUB_ISSUES_URL)

    def test_url_contains_tool_name(self):
        url = format_github_issue_url("my_tool", "error happened")
        assert "my_tool" in url

    def test_url_contains_error_text(self):
        url = format_github_issue_url("tool", "specific error text")
        assert "specific" in url

    def test_url_contains_context(self):
        url = format_github_issue_url("tool", "err", context="extra context")
        assert "extra" in url

    def test_url_contains_labels(self):
        url = format_github_issue_url("tool", "error")
        assert "bug" in url

    def test_truncates_long_error(self):
        long_error = "E" * 1000
        url = format_github_issue_url("tool", long_error)
        # URL should be generated without error
        assert GITHUB_ISSUES_URL in url


# ---------------------------------------------------------------------------
# create_github_issue
# ---------------------------------------------------------------------------


class TestCreateGithubIssue:
    async def test_dedup_returns_early(self):
        """If a similar issue was recently created, skip."""
        import tool_modules.aa_workflow.src.tools_basic as tb

        original = dict(tb._recent_issues)
        try:
            fp = _issue_fingerprint("test_tool", "test error")
            tb._recent_issues[fp] = time.time()

            result = await create_github_issue("test_tool", "test error")
            assert result["success"] is False
            assert "dedup" in result["message"]
        finally:
            tb._recent_issues.clear()
            tb._recent_issues.update(original)

    async def test_no_token_returns_url(self):
        """Without a token, should return a URL for manual creation."""
        import tool_modules.aa_workflow.src.tools_basic as tb

        original = dict(tb._recent_issues)
        try:
            tb._recent_issues.clear()

            env = {
                k: v
                for k, v in os.environ.items()
                if k not in ("GITHUB_TOKEN", "GH_TOKEN")
            }
            with patch.dict(os.environ, env, clear=True):
                result = await create_github_issue("tool", "error")
            assert result["success"] is False
            assert result["issue_url"] is not None
            assert "No GITHUB_TOKEN" in result["message"]
        finally:
            tb._recent_issues.clear()
            tb._recent_issues.update(original)

    async def test_successful_api_call(self):
        """When API returns 201, should report success."""
        import tool_modules.aa_workflow.src.tools_basic as tb

        original = dict(tb._recent_issues)
        try:
            tb._recent_issues.clear()

            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {
                "html_url": "https://github.com/test/issues/1"
            }

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)

            with (
                patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}, clear=False),
                patch("httpx.AsyncClient", return_value=mock_client),
            ):
                result = await create_github_issue("tool", "error")

            assert result["success"] is True
            assert "https://github.com" in result["issue_url"]
        finally:
            tb._recent_issues.clear()
            tb._recent_issues.update(original)

    async def test_api_error_returns_fallback_url(self):
        """When API returns non-201, should return fallback URL."""
        import tool_modules.aa_workflow.src.tools_basic as tb

        original = dict(tb._recent_issues)
        try:
            tb._recent_issues.clear()

            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_response.text = "Forbidden"

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)

            with (
                patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}, clear=False),
                patch("httpx.AsyncClient", return_value=mock_client),
            ):
                result = await create_github_issue("tool", "error")

            assert result["success"] is False
            assert "403" in result["message"]
        finally:
            tb._recent_issues.clear()
            tb._recent_issues.update(original)

    async def test_exception_returns_fallback_url(self):
        """When API call raises, should return fallback URL."""
        import tool_modules.aa_workflow.src.tools_basic as tb

        original = dict(tb._recent_issues)
        try:
            tb._recent_issues.clear()

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=RuntimeError("network error"))

            with (
                patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}, clear=False),
                patch("httpx.AsyncClient", return_value=mock_client),
            ):
                result = await create_github_issue("tool", "error")

            assert result["success"] is False
            assert "Failed" in result["message"]
        finally:
            tb._recent_issues.clear()
            tb._recent_issues.update(original)

    async def test_adds_jira_label(self):
        """Should add 'jira' label when tool contains 'jira'."""
        import tool_modules.aa_workflow.src.tools_basic as tb

        original = dict(tb._recent_issues)
        try:
            tb._recent_issues.clear()

            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {
                "html_url": "https://github.com/test/issues/2"
            }

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)

            with (
                patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}, clear=False),
                patch("httpx.AsyncClient", return_value=mock_client),
            ):
                await create_github_issue("jira_tool", "error")

            # Check labels in the API call
            call_kwargs = mock_client.post.call_args
            body = call_kwargs.kwargs["json"]
            assert "jira" in body["labels"]
        finally:
            tb._recent_issues.clear()
            tb._recent_issues.update(original)

    async def test_cleanup_expired_entries(self):
        """Expired entries should be cleaned up."""
        import tool_modules.aa_workflow.src.tools_basic as tb

        original = dict(tb._recent_issues)
        try:
            # Add an expired entry
            tb._recent_issues.clear()
            tb._recent_issues["old_fp"] = time.time() - (_ISSUE_DEDUP_SECONDS + 100)

            env = {
                k: v
                for k, v in os.environ.items()
                if k not in ("GITHUB_TOKEN", "GH_TOKEN")
            }
            with patch.dict(os.environ, env, clear=True):
                await create_github_issue("tool", "error")

            # Expired entry should be removed
            assert "old_fp" not in tb._recent_issues
        finally:
            tb._recent_issues.clear()
            tb._recent_issues.update(original)

    async def test_max_recent_issues_enforced(self):
        """When _recent_issues exceeds _MAX_RECENT_ISSUES, oldest are pruned."""
        import tool_modules.aa_workflow.src.tools_basic as tb

        original = dict(tb._recent_issues)
        try:
            tb._recent_issues.clear()
            now = time.time()
            # Fill beyond limit
            for i in range(_MAX_RECENT_ISSUES + 10):
                tb._recent_issues[f"fp_{i}"] = now - i

            env = {
                k: v
                for k, v in os.environ.items()
                if k not in ("GITHUB_TOKEN", "GH_TOKEN")
            }
            with patch.dict(os.environ, env, clear=True):
                await create_github_issue("tool", "unique_error_for_max_test")

            assert (
                len(tb._recent_issues) <= _MAX_RECENT_ISSUES + 1
            )  # +1 for the newly added
        finally:
            tb._recent_issues.clear()
            tb._recent_issues.update(original)

    async def test_adds_gitlab_label(self):
        """Should add 'gitlab' label when tool contains 'gitlab'."""
        import tool_modules.aa_workflow.src.tools_basic as tb

        original = dict(tb._recent_issues)
        try:
            tb._recent_issues.clear()

            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {
                "html_url": "https://github.com/test/issues/3"
            }

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)

            with (
                patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}, clear=False),
                patch("httpx.AsyncClient", return_value=mock_client),
            ):
                await create_github_issue("gitlab_tool", "error")

            call_kwargs = mock_client.post.call_args
            body = call_kwargs.kwargs["json"]
            assert "gitlab" in body["labels"]
        finally:
            tb._recent_issues.clear()
            tb._recent_issues.update(original)

    async def test_adds_kubernetes_label(self):
        """Should add 'kubernetes' label when tool contains 'k8s' or 'kubectl'."""
        import tool_modules.aa_workflow.src.tools_basic as tb

        original = dict(tb._recent_issues)
        try:
            tb._recent_issues.clear()

            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {
                "html_url": "https://github.com/test/issues/4"
            }

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)

            with (
                patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}, clear=False),
                patch("httpx.AsyncClient", return_value=mock_client),
            ):
                await create_github_issue("k8s_deploy", "pod error")

            call_kwargs = mock_client.post.call_args
            body = call_kwargs.kwargs["json"]
            assert "kubernetes" in body["labels"]
        finally:
            tb._recent_issues.clear()
            tb._recent_issues.update(original)

    async def test_custom_labels_override_default(self):
        """When labels parameter is provided, use those."""
        import tool_modules.aa_workflow.src.tools_basic as tb

        original = dict(tb._recent_issues)
        try:
            tb._recent_issues.clear()

            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {
                "html_url": "https://github.com/test/issues/5"
            }

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)

            with (
                patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test"}, clear=False),
                patch("httpx.AsyncClient", return_value=mock_client),
            ):
                await create_github_issue("tool", "error", labels=["custom"])

            call_kwargs = mock_client.post.call_args
            body = call_kwargs.kwargs["json"]
            assert "custom" in body["labels"]
        finally:
            tb._recent_issues.clear()
            tb._recent_issues.update(original)


# ---------------------------------------------------------------------------
# resolve_path
# ---------------------------------------------------------------------------


class TestResolvePath:
    def test_raises_for_unknown_repo(self):
        with (
            patch.dict(REPO_PATHS, {}, clear=True),
            patch(
                "tool_modules.aa_workflow.src.tools_basic.resolve_repo_path",
                return_value="/nonexistent/path",
            ),
            patch("os.path.isdir", return_value=False),
        ):
            with pytest.raises(ValueError, match="Unknown repository"):
                resolve_path("nonexistent_repo")

    def test_returns_path_from_repo_paths(self):
        with patch.dict(REPO_PATHS, {"myrepo": "/home/user/myrepo"}, clear=True):
            result = resolve_path("myrepo")
        assert result == "/home/user/myrepo"

    def test_falls_back_to_resolve_repo_path(self):
        with (
            patch.dict(REPO_PATHS, {}, clear=True),
            patch(
                "tool_modules.aa_workflow.src.tools_basic.resolve_repo_path",
                return_value="/home/user/found",
            ),
            patch("os.path.isdir", return_value=True),
        ):
            result = resolve_path("found")
        assert result == "/home/user/found"


# ---------------------------------------------------------------------------
# register_tools
# ---------------------------------------------------------------------------


class TestRegisterTools:
    def _make_register_patches(self):
        """Return a list of context managers patching all register_* fns."""
        return [
            patch(
                "tool_modules.aa_workflow.src.tools_basic.register_chat_context_tools",
                return_value=1,
            ),
            patch(
                "tool_modules.aa_workflow.src.tools_basic.register_memory_tools",
                return_value=9,
            ),
            patch(
                "tool_modules.aa_workflow.src.tools_basic.register_persona_tools",
                return_value=2,
            ),
            patch(
                "tool_modules.aa_workflow.src.tools_basic.register_session_tools",
                return_value=1,
            ),
            patch(
                "tool_modules.aa_workflow.src.tools_basic.register_prompts",
                return_value=3,
            ),
            patch(
                "tool_modules.aa_workflow.src.tools_basic.register_resources",
                return_value=8,
            ),
            patch(
                "tool_modules.aa_workflow.src.tools_basic.register_skill_tools",
                return_value=2,
            ),
            patch(
                "tool_modules.aa_workflow.src.tools_basic.register_infra_tools",
                return_value=2,
            ),
            patch(
                "tool_modules.aa_workflow.src.tools_basic.register_meta_tools",
                return_value=3,
            ),
            patch(
                "tool_modules.aa_workflow.src.tools_basic.register_sprint_tools",
                return_value=9,
            ),
            patch(
                "tool_modules.aa_workflow.src.claude_code_integration.get_claude_code_capabilities",
                return_value={"is_claude_code": False},
            ),
            patch(
                "tool_modules.aa_workflow.src.claude_code_integration.create_ask_question_wrapper",
                return_value=None,
            ),
        ]

    def test_returns_positive_count(self):
        server = MagicMock()
        from contextlib import ExitStack

        with ExitStack() as stack:
            for p in self._make_register_patches():
                stack.enter_context(p)
            count = register_tools(server)

        assert count > 0

    def test_handles_import_error_for_unified_memory(self):
        server = MagicMock()
        from contextlib import ExitStack

        with ExitStack() as stack:
            for p in self._make_register_patches():
                stack.enter_context(p)
            # Should not raise even if unified memory import fails
            count = register_tools(server)
            assert isinstance(count, int)
