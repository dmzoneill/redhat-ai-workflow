"""Tests for scripts/common/context_extractor.py - Slack context extraction."""

import json
from unittest.mock import AsyncMock

import pytest

from scripts.common.context_extractor import (
    ContextExtractor,
    ConversationContext,
    extract_context,
)

# ==================== ConversationContext ====================


class TestConversationContext:
    """Tests for the ConversationContext dataclass."""

    def test_defaults(self):
        ctx = ConversationContext()
        assert ctx.channel_id == ""
        assert ctx.thread_ts is None
        assert ctx.message_count == 0
        assert ctx.jira_issues == []
        assert ctx.gitlab_mrs == []
        assert ctx.gitlab_issues == []
        assert ctx.mentioned_users == []
        assert ctx.urls == []
        assert ctx.messages == []
        assert ctx.raw_text == ""
        assert ctx.summary == ""
        assert ctx.inferred_type == ""
        assert ctx.inferred_priority == ""
        assert ctx.key_topics == []
        assert ctx.confidence == "low"

    def test_is_valid_empty(self):
        ctx = ConversationContext()
        assert ctx.is_valid() is False

    def test_is_valid_with_messages(self):
        ctx = ConversationContext(messages=[{"user": "U1", "text": "hi"}])
        assert ctx.is_valid() is True

    def test_is_valid_with_jira_issues(self):
        ctx = ConversationContext(jira_issues=["AAP-1234"])
        assert ctx.is_valid() is True

    def test_is_valid_with_summary(self):
        ctx = ConversationContext(summary="Some summary text")
        assert ctx.is_valid() is True

    def test_to_dict(self):
        ctx = ConversationContext(
            channel_id="C123",
            thread_ts="1234.5678",
            message_count=5,
            jira_issues=["AAP-100"],
            mentioned_users=["U999"],
            urls=["https://example.com"],
            summary="Test summary",
            inferred_type="bug",
            inferred_priority="high",
            key_topics=["billing"],
            raw_text="hello world",
        )
        d = ctx.to_dict()
        assert d["channel_id"] == "C123"
        assert d["thread_ts"] == "1234.5678"
        assert d["message_count"] == 5
        assert d["jira_issues"] == ["AAP-100"]
        assert d["mentioned_users"] == ["U999"]
        assert d["urls"] == ["https://example.com"]
        assert d["summary"] == "Test summary"
        assert d["inferred_type"] == "bug"
        assert d["inferred_priority"] == "high"
        assert d["key_topics"] == ["billing"]
        assert d["raw_text"] == "hello world"

    def test_to_dict_truncates_raw_text(self):
        long_text = "x" * 3000
        ctx = ConversationContext(raw_text=long_text)
        d = ctx.to_dict()
        assert len(d["raw_text"]) == 2000

    def test_to_dict_empty_raw_text(self):
        ctx = ConversationContext(raw_text="")
        d = ctx.to_dict()
        assert d["raw_text"] == ""

    # ---- to_skill_inputs ----

    def test_to_skill_inputs_create_jira_issue_minimal(self):
        ctx = ConversationContext()
        inputs = ctx.to_skill_inputs("create_jira_issue")
        assert inputs["summary"] == "Issue from Slack conversation"
        assert "description" in inputs
        assert inputs["slack_format"] is True

    def test_to_skill_inputs_create_jira_issue_full(self):
        ctx = ConversationContext(
            channel_id="C123",
            summary="Fix the login bug",
            inferred_type="bug",
            inferred_priority="critical",
            jira_issues=["AAP-100", "AAP-200"],
            key_topics=["auth", "login"],
            urls=["https://example.com/mr/1"],
        )
        inputs = ctx.to_skill_inputs("create_jira_issue")
        assert inputs["summary"] == "Fix the login bug"
        assert inputs["issue_type"] == "Bug"
        assert inputs["priority"] == "Highest"
        assert inputs["link_to"] == "AAP-100"
        assert inputs["slack_format"] is True

    def test_to_skill_inputs_create_jira_issue_type_mapping(self):
        for itype, expected in [
            ("feature", "Story"),
            ("task", "Task"),
            ("question", "Task"),
        ]:
            ctx = ConversationContext(inferred_type=itype)
            inputs = ctx.to_skill_inputs("create_jira_issue")
            assert inputs["issue_type"] == expected

    def test_to_skill_inputs_create_jira_issue_priority_mapping(self):
        for priority, expected in [
            ("high", "High"),
            ("medium", "Medium"),
            ("low", "Low"),
        ]:
            ctx = ConversationContext(inferred_priority=priority)
            inputs = ctx.to_skill_inputs("create_jira_issue")
            assert inputs["priority"] == expected

    def test_to_skill_inputs_create_jira_issue_unknown_type(self):
        ctx = ConversationContext(inferred_type="epic")
        inputs = ctx.to_skill_inputs("create_jira_issue")
        assert inputs["issue_type"] == "Task"

    def test_to_skill_inputs_create_jira_issue_unknown_priority(self):
        ctx = ConversationContext(inferred_priority="urgent")
        inputs = ctx.to_skill_inputs("create_jira_issue")
        assert inputs["priority"] == "Medium"

    def test_to_skill_inputs_investigate_alert(self):
        ctx = ConversationContext(raw_text="Alert fired", summary="Disk full")
        inputs = ctx.to_skill_inputs("investigate_alert")
        assert inputs["context"] == "Alert fired"
        assert inputs["summary"] == "Disk full"

    def test_to_skill_inputs_start_work(self):
        ctx = ConversationContext(
            jira_issues=["AAP-500"],
            gitlab_mrs=[{"id": "42", "project": "org/repo", "url": "http://x"}],
        )
        inputs = ctx.to_skill_inputs("start_work")
        assert inputs["issue_key"] == "AAP-500"
        assert inputs["mr_id"] == "42"
        assert inputs["project"] == "org/repo"

    def test_to_skill_inputs_review_pr(self):
        ctx = ConversationContext(jira_issues=["AAP-600"])
        inputs = ctx.to_skill_inputs("review_pr")
        assert inputs["issue_key"] == "AAP-600"

    def test_to_skill_inputs_unknown_skill(self):
        ctx = ConversationContext(jira_issues=["AAP-700"])
        inputs = ctx.to_skill_inputs("unknown_skill")
        assert inputs == {}

    # ---- _build_jira_description ----

    def test_build_jira_description_full(self):
        ctx = ConversationContext(
            channel_id="C123",
            summary="Bug in billing",
            key_topics=["billing", "vCPU"],
            jira_issues=["AAP-100"],
            urls=["https://example.com"],
        )
        desc = ctx._build_jira_description()
        assert "## Summary" in desc
        assert "Bug in billing" in desc
        assert "## Topics" in desc
        assert "billing, vCPU" in desc
        assert "## Related Issues" in desc
        assert "AAP-100" in desc
        assert "## References" in desc
        assert "https://example.com" in desc
        assert "C123" in desc

    def test_build_jira_description_minimal(self):
        ctx = ConversationContext(channel_id="C999")
        desc = ctx._build_jira_description()
        assert "C999" in desc
        assert "## Summary" not in desc

    def test_build_jira_description_limits_urls(self):
        urls = [f"https://example.com/{i}" for i in range(10)]
        ctx = ConversationContext(channel_id="C1", urls=urls)
        desc = ctx._build_jira_description()
        # Only first 5 urls should appear
        assert "https://example.com/4" in desc
        assert "https://example.com/5" not in desc


# ==================== ContextExtractor Entity Extraction ====================


class TestContextExtractorEntities:
    """Tests for entity extraction from raw text."""

    def setup_method(self):
        self.extractor = ContextExtractor()

    def test_extract_jira_issues(self):
        ctx = self.extractor.extract_from_text("Look at AAP-1234 and also AAP-5678")
        assert "AAP-1234" in ctx.jira_issues
        assert "AAP-5678" in ctx.jira_issues

    def test_extract_jira_issues_deduplication(self):
        ctx = self.extractor.extract_from_text("AAP-100 again AAP-100 and AAP-200")
        assert ctx.jira_issues == ["AAP-100", "AAP-200"]

    def test_extract_gitlab_mrs(self):
        text = "Check https://gitlab.example.com/org/repo/-/merge_requests/42"
        ctx = self.extractor.extract_from_text(text)
        assert len(ctx.gitlab_mrs) == 1
        assert ctx.gitlab_mrs[0]["project"] == "org/repo"
        assert ctx.gitlab_mrs[0]["id"] == "42"

    def test_extract_gitlab_issues(self):
        text = "See https://gitlab.example.com/org/repo/-/issues/99"
        ctx = self.extractor.extract_from_text(text)
        assert len(ctx.gitlab_issues) == 1
        assert ctx.gitlab_issues[0]["project"] == "org/repo"
        assert ctx.gitlab_issues[0]["id"] == "99"

    def test_extract_urls_excludes_gitlab(self):
        text = (
            "MR: https://gitlab.example.com/org/repo/-/merge_requests/42 "
            "also https://docs.example.com/page"
        )
        ctx = self.extractor.extract_from_text(text)
        assert len(ctx.gitlab_mrs) == 1
        # The general URL for the docs page should be present
        found_docs = any("docs.example.com" in u for u in ctx.urls)
        assert found_docs

    def test_extract_urls_deduplication(self):
        text = "https://a.com/1 https://a.com/1 https://a.com/2"
        ctx = self.extractor.extract_from_text(text)
        urls_with_a = [u for u in ctx.urls if "a.com" in u]
        assert len(urls_with_a) == 2

    def test_extract_slack_users(self):
        text = "Hey <@U12ABC> can you check with <@U99XYZ>?"
        ctx = self.extractor.extract_from_text(text)
        assert "U12ABC" in ctx.mentioned_users
        assert "U99XYZ" in ctx.mentioned_users

    def test_extract_slack_users_deduplication(self):
        text = "<@U111> and <@U111> again"
        ctx = self.extractor.extract_from_text(text)
        assert ctx.mentioned_users == ["U111"]

    def test_url_strips_trailing_punctuation(self):
        text = "See https://example.com/page."
        ctx = self.extractor.extract_from_text(text)
        found = [u for u in ctx.urls if u == "https://example.com/page"]
        assert len(found) == 1

    def test_no_entities_in_empty_text(self):
        ctx = self.extractor.extract_from_text("")
        assert ctx.jira_issues == []
        assert ctx.gitlab_mrs == []
        assert ctx.urls == []
        assert ctx.mentioned_users == []


# ==================== ContextExtractor Simple Summary ====================


class TestContextExtractorSimpleSummary:
    """Tests for _simple_summary."""

    def setup_method(self):
        self.extractor = ContextExtractor()

    def test_simple_summary_extracts_first_line(self):
        text = "user1: This is a longer message about the billing issue\nuser2: Yeah"
        summary = self.extractor._simple_summary(text)
        assert "This is a longer message" in summary

    def test_simple_summary_skips_short_lines(self):
        text = (
            "user1: ok\nuser2: This is a much longer and more meaningful message here"
        )
        summary = self.extractor._simple_summary(text)
        assert "meaningful message" in summary

    def test_simple_summary_truncates_long_content(self):
        text = "user1: " + "a" * 200
        summary = self.extractor._simple_summary(text)
        assert len(summary) <= 103  # 100 chars + "..."
        assert summary.endswith("...")

    def test_simple_summary_fallback(self):
        text = "short"
        summary = self.extractor._simple_summary(text)
        assert summary == "Issue from Slack conversation"

    def test_simple_summary_empty(self):
        summary = self.extractor._simple_summary("")
        assert summary == "Issue from Slack conversation"


# ==================== ContextExtractor Confidence ====================


class TestContextExtractorConfidence:
    """Tests for _assess_confidence."""

    def setup_method(self):
        self.extractor = ContextExtractor()

    def test_low_confidence(self):
        ctx = ConversationContext()
        assert self.extractor._assess_confidence(ctx) == "low"

    def test_medium_confidence(self):
        ctx = ConversationContext(
            summary="test",
            jira_issues=["AAP-1"],
        )
        # summary=2 + jira=2 = 4 -> medium
        assert self.extractor._assess_confidence(ctx) == "medium"

    def test_high_confidence(self):
        ctx = ConversationContext(
            summary="test",
            jira_issues=["AAP-1"],
            message_count=5,
            inferred_type="bug",
        )
        # summary=2 + jira=2 + messages>=3=1 + type=1 = 6 -> high
        assert self.extractor._assess_confidence(ctx) == "high"

    def test_high_confidence_with_topics(self):
        ctx = ConversationContext(
            summary="test",
            jira_issues=["AAP-1"],
            key_topics=["billing"],
        )
        # summary=2 + jira=2 + topics=1 = 5 -> high
        assert self.extractor._assess_confidence(ctx) == "high"


# ==================== ContextExtractor extract_from_text ====================


class TestExtractFromText:
    """Tests for the synchronous extract_from_text method."""

    def test_extract_from_text_basic(self):
        extractor = ContextExtractor()
        ctx = extractor.extract_from_text(
            "user1: Please look at AAP-1234 and fix the billing bug"
        )
        assert "AAP-1234" in ctx.jira_issues
        assert ctx.summary != ""
        assert ctx.confidence in ("low", "medium", "high")

    def test_extract_from_text_with_multiple_entities(self):
        extractor = ContextExtractor()
        text = (
            "user1: Check AAP-100 and https://example.com/docs\n"
            "user2: Also <@U123> should review https://gitlab.com/org/repo/-/merge_requests/55"
        )
        ctx = extractor.extract_from_text(text)
        assert "AAP-100" in ctx.jira_issues
        assert len(ctx.gitlab_mrs) == 1
        assert "U123" in ctx.mentioned_users


# ==================== ContextExtractor async extract ====================


class TestContextExtractorAsyncExtract:
    """Tests for the async extract method."""

    @pytest.mark.asyncio
    async def test_extract_no_slack_client(self):
        extractor = ContextExtractor(slack_client=None)
        ctx = await extractor.extract("C123")
        assert ctx.channel_id == "C123"
        assert ctx.message_count == 0

    @pytest.mark.asyncio
    async def test_extract_with_thread(self):
        slack = AsyncMock()
        slack.get_thread_replies.return_value = [
            {"user": "U1", "text": "Bug in AAP-100", "ts": "1.1"},
            {"user": "U2", "text": "Agreed, high priority", "ts": "1.2"},
        ]
        extractor = ContextExtractor(slack_client=slack)
        ctx = await extractor.extract("C123", thread_ts="1.0")
        assert ctx.message_count == 2
        assert "AAP-100" in ctx.jira_issues
        slack.get_thread_replies.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_extract_without_thread(self):
        slack = AsyncMock()
        slack.get_channel_history.return_value = [
            {"user": "U1", "text": "Hello there", "ts": "2.1"},
        ]
        extractor = ContextExtractor(slack_client=slack)
        ctx = await extractor.extract("C123")
        assert ctx.message_count == 1
        slack.get_channel_history.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_extract_excludes_command_message(self):
        slack = AsyncMock()
        slack.get_channel_history.return_value = [
            {"user": "U1", "text": "@me do something", "ts": "3.0"},
            {"user": "U2", "text": "Context message", "ts": "3.1"},
        ]
        extractor = ContextExtractor(slack_client=slack)
        ctx = await extractor.extract(
            "C123", message_ts="3.0", exclude_command_message=True
        )
        assert ctx.message_count == 1
        assert ctx.messages[0]["text"] == "Context message"

    @pytest.mark.asyncio
    async def test_extract_keeps_command_message(self):
        slack = AsyncMock()
        slack.get_channel_history.return_value = [
            {"user": "U1", "text": "@me do something", "ts": "3.0"},
            {"user": "U2", "text": "Context message", "ts": "3.1"},
        ]
        extractor = ContextExtractor(slack_client=slack)
        ctx = await extractor.extract(
            "C123", message_ts="3.0", exclude_command_message=False
        )
        assert ctx.message_count == 2

    @pytest.mark.asyncio
    async def test_extract_empty_messages(self):
        slack = AsyncMock()
        slack.get_channel_history.return_value = []
        extractor = ContextExtractor(slack_client=slack)
        ctx = await extractor.extract("C123")
        assert ctx.message_count == 0
        assert ctx.confidence == "low"

    @pytest.mark.asyncio
    async def test_extract_slack_error(self):
        slack = AsyncMock()
        slack.get_channel_history.side_effect = RuntimeError("API error")
        extractor = ContextExtractor(slack_client=slack)
        ctx = await extractor.extract("C123")
        assert ctx.message_count == 0

    @pytest.mark.asyncio
    async def test_extract_with_claude_summarization(self):
        slack = AsyncMock()
        slack.get_channel_history.return_value = [
            {"user": "U1", "text": "Billing is broken", "ts": "4.0"},
        ]
        claude = AsyncMock()
        claude.process_message.return_value = json.dumps(
            {
                "summary": "Billing module is failing",
                "type": "bug",
                "priority": "high",
                "topics": ["billing", "payments"],
            }
        )
        extractor = ContextExtractor(slack_client=slack, claude_agent=claude)
        ctx = await extractor.extract("C123")
        assert ctx.summary == "Billing module is failing"
        assert ctx.inferred_type == "bug"
        assert ctx.inferred_priority == "high"
        assert ctx.key_topics == ["billing", "payments"]

    @pytest.mark.asyncio
    async def test_extract_claude_failure_falls_back(self):
        slack = AsyncMock()
        slack.get_channel_history.return_value = [
            {
                "user": "U1",
                "text": "Something is wrong with the billing system now",
                "ts": "5.0",
            },
        ]
        claude = AsyncMock()
        claude.process_message.side_effect = RuntimeError("Claude down")
        extractor = ContextExtractor(slack_client=slack, claude_agent=claude)
        ctx = await extractor.extract("C123")
        # Falls back to _simple_summary
        assert ctx.summary != ""

    @pytest.mark.asyncio
    async def test_extract_claude_invalid_json(self):
        slack = AsyncMock()
        slack.get_channel_history.return_value = [
            {
                "user": "U1",
                "text": "Check the auth module for the login issue we discussed",
                "ts": "6.0",
            },
        ]
        claude = AsyncMock()
        claude.process_message.return_value = "Not valid JSON at all"
        extractor = ContextExtractor(slack_client=slack, claude_agent=claude)
        ctx = await extractor.extract("C123")
        # No JSON found, so summary remains empty from Claude path
        # but confidence is set
        assert ctx.confidence in ("low", "medium", "high")


# ==================== extract_context convenience ====================


class TestExtractContextFunction:
    """Tests for the module-level extract_context convenience function."""

    @pytest.mark.asyncio
    async def test_extract_context_no_clients(self):
        ctx = await extract_context(channel_id="C999")
        assert ctx.channel_id == "C999"
        assert ctx.message_count == 0

    @pytest.mark.asyncio
    async def test_extract_context_with_slack(self):
        slack = AsyncMock()
        slack.get_channel_history.return_value = [
            {"user": "U1", "text": "Test message AAP-999", "ts": "7.0"},
        ]
        ctx = await extract_context(
            channel_id="C777",
            slack_client=slack,
        )
        assert ctx.channel_id == "C777"
        assert "AAP-999" in ctx.jira_issues


# ==================== _build_raw_text ====================


class TestBuildRawText:
    """Tests for _build_raw_text."""

    def test_build_raw_text(self):
        extractor = ContextExtractor()
        messages = [
            {"user": "U1", "text": "Hello"},
            {"user": "U2", "text": "World"},
        ]
        text = extractor._build_raw_text(messages)
        assert text == "U1: Hello\nU2: World"

    def test_build_raw_text_skips_empty(self):
        extractor = ContextExtractor()
        messages = [
            {"user": "U1", "text": "Hello"},
            {"user": "U2", "text": ""},
            {"user": "U3", "text": "Bye"},
        ]
        text = extractor._build_raw_text(messages)
        assert "U2" not in text

    def test_build_raw_text_missing_fields(self):
        extractor = ContextExtractor()
        messages = [{"foo": "bar"}]
        text = extractor._build_raw_text(messages)
        assert text == ""
