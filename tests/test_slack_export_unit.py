"""Unit tests for scripts/common/slack_export.py

Named test_slack_export_unit.py to clearly distinguish from scripts/slack_export_test.py (manual smoke test).
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.common.slack_export import (
    MEMORY_DIR,
    PROJECT_ROOT,
    STYLE_DIR,
    create_slack_session,
    export_messages_to_jsonl,
    get_conversations_with_fallback,
    get_slack_config,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    """Tests for Module Constants."""

    def test_project_root_exists(self):
        """Project root exists."""

        assert PROJECT_ROOT.exists()

    def test_memory_dir_path(self):
        """Memory dir path."""

        assert MEMORY_DIR == PROJECT_ROOT / "memory"

    def test_style_dir_path(self):
        """Style dir path."""

        assert STYLE_DIR == MEMORY_DIR / "style"


# ---------------------------------------------------------------------------
# get_slack_config
# ---------------------------------------------------------------------------


class TestGetSlackConfig:
    """Tests for Get Slack Config."""

    @patch(
        "server.utils.load_config",
        return_value={"slack": {"auth": {"xoxc_token": "tok"}}},
    )
    def test_returns_slack_section(self, _mock_load):
        """Returns slack section."""

        result = get_slack_config()
        assert result == {"auth": {"xoxc_token": "tok"}}

    @patch("server.utils.load_config", return_value={})
    def test_returns_empty_when_no_slack(self, _mock_load):
        """Returns empty when no slack."""

        result = get_slack_config()
        assert result == {}

    @patch("server.utils.load_config", side_effect=ValueError("fail"))
    def test_returns_empty_on_generic_error(self, _mock_load):
        """Returns empty on generic error."""

        result = get_slack_config()
        assert result == {}


# ---------------------------------------------------------------------------
# create_slack_session
# ---------------------------------------------------------------------------


class TestCreateSlackSession:
    """Tests for Create Slack Session."""

    @pytest.mark.asyncio
    async def test_creates_session_with_valid_creds(self):
        """Creates session with valid creds."""

        mock_session = MagicMock()
        mock_session.validate_session = AsyncMock()
        mock_session.user_id = "U001"
        mock_slack_session_cls = MagicMock(return_value=mock_session)

        with (
            patch(
                "server.utils.load_config",
                return_value={
                    "slack": {
                        "auth": {
                            "xoxc_token": "xoxc-test",
                            "d_cookie": "cookie",
                            "workspace_id": "W123",
                            "enterprise_id": "E456",
                        }
                    }
                },
            ),
            patch.dict(
                "sys.modules",
                {"slack_client": MagicMock(SlackSession=mock_slack_session_cls)},
            ),
        ):
            result = await create_slack_session()
            assert result is mock_session
            mock_slack_session_cls.assert_called_once_with(
                xoxc_token="xoxc-test",
                d_cookie="cookie",
                workspace_id="W123",
                enterprise_id="E456",
            )

    @pytest.mark.asyncio
    async def test_returns_none_without_token(self):
        """Returns none without token."""

        mock_slack_session_cls = MagicMock()
        with (
            patch("server.utils.load_config", return_value={"slack": {"auth": {}}}),
            patch.dict(
                "sys.modules",
                {"slack_client": MagicMock(SlackSession=mock_slack_session_cls)},
            ),
        ):
            result = await create_slack_session()
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_with_empty_token(self):
        """Returns none with empty token."""

        mock_slack_session_cls = MagicMock()
        with (
            patch(
                "server.utils.load_config",
                return_value={"slack": {"auth": {"xoxc_token": ""}}},
            ),
            patch.dict(
                "sys.modules",
                {"slack_client": MagicMock(SlackSession=mock_slack_session_cls)},
            ),
        ):
            result = await create_slack_session()
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_validation_failure(self):
        """Returns none on validation failure."""

        mock_session = MagicMock()
        mock_session.validate_session = AsyncMock(side_effect=ValueError("invalid"))
        mock_slack_session_cls = MagicMock(return_value=mock_session)

        with (
            patch(
                "server.utils.load_config",
                return_value={"slack": {"auth": {"xoxc_token": "tok"}}},
            ),
            patch.dict(
                "sys.modules",
                {"slack_client": MagicMock(SlackSession=mock_slack_session_cls)},
            ),
        ):
            result = await create_slack_session(validate=True)
            assert result is None

    @pytest.mark.asyncio
    async def test_skip_validation(self):
        """Skip validation."""

        mock_session = MagicMock()
        mock_slack_session_cls = MagicMock(return_value=mock_session)

        with (
            patch(
                "server.utils.load_config",
                return_value={"slack": {"auth": {"xoxc_token": "tok"}}},
            ),
            patch.dict(
                "sys.modules",
                {"slack_client": MagicMock(SlackSession=mock_slack_session_cls)},
            ),
        ):
            result = await create_slack_session(validate=False)
            assert result is mock_session
            mock_session.validate_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_auth_key(self):
        """Missing auth key."""

        mock_slack_session_cls = MagicMock()
        with (
            patch("server.utils.load_config", return_value={"slack": {}}),
            patch.dict(
                "sys.modules",
                {"slack_client": MagicMock(SlackSession=mock_slack_session_cls)},
            ),
        ):
            result = await create_slack_session()
            assert result is None


# ---------------------------------------------------------------------------
# get_conversations_with_fallback
# ---------------------------------------------------------------------------


class TestGetConversationsWithFallback:
    """Tests for Get Conversations With Fallback."""

    @pytest.mark.asyncio
    async def test_primary_api_success(self):
        """Primary api success."""

        session = MagicMock()
        session.get_user_conversations = AsyncMock(
            return_value=[
                {"id": "C1"},
                {"id": "C2"},
            ]
        )
        result = await get_conversations_with_fallback(session)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_enterprise_fallback_with_dicts(self):
        """Enterprise fallback with dicts."""

        session = MagicMock()
        session.get_user_conversations = AsyncMock(side_effect=ValueError("enterprise_is_restricted"))
        session.get_client_counts = AsyncMock(
            return_value={
                "ok": True,
                "ims": [{"id": "D1"}, {"id": "D2"}],
                "mpims": [{"id": "G1"}],
                "channels": [{"id": "C1"}],
            }
        )
        result = await get_conversations_with_fallback(session)
        assert len(result) == 4
        ids = {c["id"] for c in result}
        assert ids == {"D1", "D2", "G1", "C1"}

    @pytest.mark.asyncio
    async def test_enterprise_fallback_with_strings(self):
        """Enterprise fallback with strings."""

        session = MagicMock()
        session.get_user_conversations = AsyncMock(side_effect=ValueError("enterprise_is_restricted"))
        session.get_client_counts = AsyncMock(
            return_value={
                "ok": True,
                "ims": ["D1"],
                "mpims": ["G1"],
                "channels": ["C1"],
            }
        )
        result = await get_conversations_with_fallback(session)
        assert len(result) == 3
        ids = {c["id"] for c in result}
        assert ids == {"D1", "G1", "C1"}

    @pytest.mark.asyncio
    async def test_non_enterprise_error_raises(self):
        """Non enterprise error raises."""

        session = MagicMock()
        session.get_user_conversations = AsyncMock(side_effect=ValueError("some other error"))
        with pytest.raises(ValueError, match="some other error"):
            await get_conversations_with_fallback(session)

    @pytest.mark.asyncio
    async def test_fallback_also_fails(self):
        """Fallback also fails."""

        session = MagicMock()
        session.get_user_conversations = AsyncMock(side_effect=ValueError("enterprise_is_restricted"))
        session.get_client_counts = AsyncMock(side_effect=ValueError("counts failed"))
        result = await get_conversations_with_fallback(session)
        assert result == []

    @pytest.mark.asyncio
    async def test_fallback_not_ok(self):
        """Fallback not ok."""

        session = MagicMock()
        session.get_user_conversations = AsyncMock(side_effect=ValueError("enterprise_is_restricted"))
        session.get_client_counts = AsyncMock(return_value={"ok": False})
        result = await get_conversations_with_fallback(session)
        assert result == []

    @pytest.mark.asyncio
    async def test_custom_types_and_limit(self):
        """Custom types and limit."""

        session = MagicMock()
        session.get_user_conversations = AsyncMock(return_value=[])
        result = await get_conversations_with_fallback(session, types="im", limit=10)
        session.get_user_conversations.assert_awaited_once_with(types="im", limit=10)
        assert result == []


# ---------------------------------------------------------------------------
# export_messages_to_jsonl
# ---------------------------------------------------------------------------


class TestExportMessagesToJsonl:
    """Tests for Export Messages To Jsonl."""

    @pytest.mark.asyncio
    async def test_exports_messages(self, tmp_path):
        """Exports messages."""

        output_file = tmp_path / "export" / "messages.jsonl"
        session = MagicMock()
        session.user_id = "U001"
        session.get_conversation_history = AsyncMock(
            return_value=[
                {"user": "U001", "text": "hello", "ts": "1"},
                {"user": "U002", "text": "bye", "ts": "2"},
            ]
        )
        convos = [{"id": "C1"}]

        stats = await export_messages_to_jsonl(session, convos, output_file)
        assert stats["message_count"] == 1
        assert stats["conversation_count"] == 1
        lines = output_file.read_text().strip().split("\n")
        assert len(lines) == 1
        msg = json.loads(lines[0])
        assert msg["text"] == "hello"

    @pytest.mark.asyncio
    async def test_skips_conversations_without_user_messages(self, tmp_path):
        """Skips conversations without user messages."""

        output_file = tmp_path / "messages.jsonl"
        session = MagicMock()
        session.user_id = "U001"
        session.get_conversation_history = AsyncMock(
            return_value=[
                {"user": "U002", "text": "other"},
            ]
        )
        convos = [{"id": "C1"}]

        stats = await export_messages_to_jsonl(session, convos, output_file)
        assert stats["message_count"] == 0
        assert stats["skipped_conversations"] == 1

    @pytest.mark.asyncio
    async def test_handles_fetch_error(self, tmp_path):
        """Handles fetch error."""

        output_file = tmp_path / "messages.jsonl"
        session = MagicMock()
        session.user_id = "U001"
        session.get_conversation_history = AsyncMock(side_effect=ValueError("channel_not_found"))
        convos = [{"id": "C1"}]

        stats = await export_messages_to_jsonl(session, convos, output_file)
        assert stats["message_count"] == 0
        assert stats["skipped_conversations"] == 1
        assert len(stats["errors"]) == 1

    @pytest.mark.asyncio
    async def test_skips_conversations_without_id(self, tmp_path):
        """Skips conversations without id."""

        output_file = tmp_path / "messages.jsonl"
        session = MagicMock()
        session.user_id = "U001"
        session.get_conversation_history = AsyncMock(return_value=[])
        convos = [{"name": "no-id"}, {"id": "C1"}]

        stats = await export_messages_to_jsonl(session, convos, output_file)
        session.get_conversation_history.assert_awaited_once()
        assert stats["conversation_count"] >= 0

    @pytest.mark.asyncio
    async def test_custom_user_id(self, tmp_path):
        """Custom user id."""

        output_file = tmp_path / "messages.jsonl"
        session = MagicMock()
        session.user_id = "U001"
        session.get_conversation_history = AsyncMock(
            return_value=[
                {"user": "U999", "text": "custom user msg"},
            ]
        )
        convos = [{"id": "C1"}]

        stats = await export_messages_to_jsonl(session, convos, output_file, user_id="U999")
        assert stats["message_count"] == 1

    @pytest.mark.asyncio
    async def test_multiple_conversations(self, tmp_path):
        """Multiple conversations."""

        output_file = tmp_path / "messages.jsonl"
        session = MagicMock()
        session.user_id = "U001"
        session.get_conversation_history = AsyncMock(
            return_value=[
                {"user": "U001", "text": "msg"},
            ]
        )
        convos = [{"id": "C1"}, {"id": "C2"}, {"id": "C3"}]

        stats = await export_messages_to_jsonl(session, convos, output_file)
        assert stats["message_count"] == 3
        assert stats["conversation_count"] == 3

    @pytest.mark.asyncio
    async def test_creates_parent_directories(self, tmp_path):
        """Creates parent directories."""

        output_file = tmp_path / "deep" / "nested" / "dir" / "messages.jsonl"
        session = MagicMock()
        session.user_id = "U001"
        session.get_conversation_history = AsyncMock(return_value=[])
        convos = []

        await export_messages_to_jsonl(session, convos, output_file)
        assert output_file.parent.exists()

    @pytest.mark.asyncio
    async def test_months_parameter(self, tmp_path):
        """Months parameter."""

        output_file = tmp_path / "messages.jsonl"
        session = MagicMock()
        session.user_id = "U001"
        session.get_conversation_history = AsyncMock(return_value=[])
        convos = [{"id": "C1"}]

        await export_messages_to_jsonl(session, convos, output_file, months=3)
        call_kwargs = session.get_conversation_history.call_args[1]
        oldest = float(call_kwargs["oldest"])
        assert oldest > 0
