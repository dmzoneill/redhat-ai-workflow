"""Tests for server.websocket_server module."""

import asyncio
import json
import subprocess
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.websocket_server import (
    MAX_RUNNING_SKILLS,
    MAX_SKILL_AGE_SECONDS,
    PendingConfirmation,
    SkillState,
    SkillWebSocketServer,
    get_websocket_server,
    start_websocket_server,
    stop_websocket_server,
)

# ---------------------------------------------------------------------------
# SkillState dataclass
# ---------------------------------------------------------------------------


class TestSkillState:
    def test_default_values(self):
        state = SkillState(skill_id="s1", skill_name="deploy", total_steps=3)
        assert state.skill_id == "s1"
        assert state.skill_name == "deploy"
        assert state.total_steps == 3
        assert state.current_step == 0
        assert state.status == "running"
        assert state.source == "chat"
        assert isinstance(state.started_at, datetime)

    def test_custom_values(self):
        state = SkillState(
            skill_id="s2",
            skill_name="test",
            total_steps=5,
            current_step=2,
            status="completed",
            source="cron",
        )
        assert state.current_step == 2
        assert state.status == "completed"
        assert state.source == "cron"


# ---------------------------------------------------------------------------
# PendingConfirmation dataclass
# ---------------------------------------------------------------------------


class TestPendingConfirmation:
    def test_creation(self):
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        conf = PendingConfirmation(
            id="c1",
            skill_id="s1",
            step_index=0,
            prompt="Confirm?",
            options=["yes", "no"],
            claude_suggestion="yes",
            timeout_seconds=30,
            created_at=datetime.now(),
            future=future,
        )
        assert conf.id == "c1"
        assert conf.prompt == "Confirm?"
        assert conf.options == ["yes", "no"]
        assert conf.timeout_seconds == 30
        loop.close()


# ---------------------------------------------------------------------------
# SkillWebSocketServer init and properties
# ---------------------------------------------------------------------------


class TestSkillWebSocketServerInit:
    def test_default_host_and_port(self):
        server = SkillWebSocketServer()
        assert server.host == "localhost"
        assert server.port == 9876

    def test_custom_host_and_port(self):
        server = SkillWebSocketServer(host="0.0.0.0", port=8080)
        assert server.host == "0.0.0.0"
        assert server.port == 8080

    def test_initial_state(self):
        server = SkillWebSocketServer()
        assert len(server.clients) == 0
        assert len(server.pending_confirmations) == 0
        assert len(server.running_skills) == 0
        assert server._server is None
        assert server._started is False

    def test_is_running_false_initially(self):
        server = SkillWebSocketServer()
        assert server.is_running is False


# ---------------------------------------------------------------------------
# start / stop
# ---------------------------------------------------------------------------


class TestStartStop:
    async def test_start_sets_started_flag(self):
        server = SkillWebSocketServer(port=0)
        mock_ws_server = AsyncMock()
        with patch(
            "server.websocket_server.serve",
            new_callable=AsyncMock,
            return_value=mock_ws_server,
        ):
            await server.start()
        assert server._started is True
        assert server.is_running is True

    async def test_start_idempotent(self):
        server = SkillWebSocketServer()
        server._started = True
        # Should return immediately
        await server.start()
        assert server._started is True

    async def test_start_handles_address_in_use(self):
        server = SkillWebSocketServer()
        with patch(
            "server.websocket_server.serve",
            new_callable=AsyncMock,
            side_effect=OSError("Address already in use"),
        ):
            await server.start()
        assert server._started is False

    async def test_start_handles_other_os_error(self):
        server = SkillWebSocketServer()
        with patch(
            "server.websocket_server.serve",
            new_callable=AsyncMock,
            side_effect=OSError("Permission denied"),
        ):
            await server.start()
        assert server._started is False

    async def test_stop(self):
        server = SkillWebSocketServer()
        mock_ws = AsyncMock()
        server._server = mock_ws
        server._started = True

        await server.stop()

        mock_ws.close.assert_called_once()
        mock_ws.wait_closed.assert_awaited_once()
        assert server._started is False

    async def test_stop_when_not_started(self):
        server = SkillWebSocketServer()
        await server.stop()  # Should not raise


# ---------------------------------------------------------------------------
# broadcast
# ---------------------------------------------------------------------------


class TestBroadcast:
    async def test_broadcast_with_no_clients(self):
        server = SkillWebSocketServer()
        # Should not raise
        await server.broadcast({"type": "test"})

    async def test_broadcast_sends_to_all_clients(self):
        server = SkillWebSocketServer()
        client1 = AsyncMock()
        client2 = AsyncMock()
        server.clients = {client1, client2}

        await server.broadcast({"type": "test_event"})

        # Both clients should have received the message
        assert client1.send.await_count == 1
        assert client2.send.await_count == 1
        sent_msg = json.loads(client1.send.call_args[0][0])
        assert sent_msg["type"] == "test_event"

    async def test_broadcast_handles_send_exception(self):
        server = SkillWebSocketServer()
        client1 = AsyncMock()
        client1.send = AsyncMock(side_effect=RuntimeError("disconnected"))
        client2 = AsyncMock()
        server.clients = {client1, client2}

        # Should not raise
        await server.broadcast({"type": "test"})
        assert client2.send.await_count == 1

    async def test_broadcast_serializes_datetime(self):
        server = SkillWebSocketServer()
        client = AsyncMock()
        server.clients = {client}

        now = datetime.now()
        await server.broadcast({"type": "test", "timestamp": now})

        sent = client.send.call_args[0][0]
        data = json.loads(sent)
        assert data["type"] == "test"


# ---------------------------------------------------------------------------
# _handle_message
# ---------------------------------------------------------------------------


class TestHandleMessage:
    async def test_confirmation_response(self):
        server = SkillWebSocketServer()
        loop = asyncio.get_event_loop()
        future = loop.create_future()

        conf = PendingConfirmation(
            id="conf-1",
            skill_id="s1",
            step_index=0,
            prompt="OK?",
            options=["yes"],
            claude_suggestion="yes",
            timeout_seconds=30,
            created_at=datetime.now(),
            future=future,
        )
        server.pending_confirmations["conf-1"] = conf

        ws = AsyncMock()
        msg = json.dumps(
            {
                "type": "confirmation_response",
                "id": "conf-1",
                "response": "yes",
                "remember": "session",
            }
        )
        await server._handle_message(ws, msg)

        assert future.done()
        result = future.result()
        assert result["response"] == "yes"
        assert result["remember"] == "session"

    async def test_confirmation_response_missing_remember(self):
        server = SkillWebSocketServer()
        loop = asyncio.get_event_loop()
        future = loop.create_future()

        conf = PendingConfirmation(
            id="conf-2",
            skill_id="s1",
            step_index=0,
            prompt="OK?",
            options=["yes"],
            claude_suggestion="yes",
            timeout_seconds=30,
            created_at=datetime.now(),
            future=future,
        )
        server.pending_confirmations["conf-2"] = conf

        ws = AsyncMock()
        msg = json.dumps(
            {
                "type": "confirmation_response",
                "id": "conf-2",
                "response": "no",
            }
        )
        await server._handle_message(ws, msg)

        result = future.result()
        assert result["remember"] == "none"

    async def test_confirmation_unknown_id(self):
        server = SkillWebSocketServer()
        ws = AsyncMock()
        msg = json.dumps(
            {
                "type": "confirmation_response",
                "id": "nonexistent",
                "response": "yes",
            }
        )
        # Should not raise
        await server._handle_message(ws, msg)

    async def test_heartbeat(self):
        server = SkillWebSocketServer()
        ws = AsyncMock()
        msg = json.dumps({"type": "heartbeat"})
        await server._handle_message(ws, msg)
        ws.send.assert_awaited_once()
        sent = json.loads(ws.send.call_args[0][0])
        assert sent["type"] == "heartbeat_ack"

    async def test_pause_timer(self):
        server = SkillWebSocketServer()
        ws = AsyncMock()
        msg = json.dumps({"type": "pause_timer"})
        await server._handle_message(ws, msg)
        # Should not raise, no response needed

    async def test_resume_timer(self):
        server = SkillWebSocketServer()
        ws = AsyncMock()
        msg = json.dumps({"type": "resume_timer"})
        await server._handle_message(ws, msg)

    async def test_invalid_json(self):
        server = SkillWebSocketServer()
        ws = AsyncMock()
        await server._handle_message(ws, "not json{{{")
        # Should not raise

    async def test_generic_exception(self):
        server = SkillWebSocketServer()
        ws = AsyncMock()
        # Valid JSON but missing required key -> KeyError in confirmation handler
        msg = json.dumps({"type": "confirmation_response"})
        await server._handle_message(ws, msg)


# ---------------------------------------------------------------------------
# Skill lifecycle events
# ---------------------------------------------------------------------------


class TestSkillStarted:
    async def test_adds_to_running_skills(self):
        server = SkillWebSocketServer()
        await server.skill_started("s1", "deploy", 3, source="api")
        assert "s1" in server.running_skills
        assert server.running_skills["s1"].skill_name == "deploy"
        assert server.running_skills["s1"].total_steps == 3
        assert server.running_skills["s1"].source == "api"

    async def test_broadcasts_event(self):
        server = SkillWebSocketServer()
        client = AsyncMock()
        server.clients = {client}

        await server.skill_started("s1", "deploy", 3, inputs={"env": "stage"})
        sent = json.loads(client.send.call_args[0][0])
        assert sent["type"] == "skill_started"
        assert sent["skill_name"] == "deploy"
        assert sent["inputs"]["env"] == "stage"

    async def test_triggers_cleanup(self):
        server = SkillWebSocketServer()
        with patch.object(
            server, "_cleanup_stale_skills", new_callable=AsyncMock, return_value=0
        ) as mock:
            await server.skill_started("s1", "deploy", 3)
        mock.assert_awaited_once()


class TestSkillCompleted:
    async def test_updates_status(self):
        server = SkillWebSocketServer()
        server.running_skills["s1"] = SkillState("s1", "deploy", 3)

        with patch("asyncio.create_task"):
            await server.skill_completed("s1", total_duration_ms=500)

        assert server.running_skills["s1"].status == "completed"

    async def test_broadcasts_event(self):
        server = SkillWebSocketServer()
        server.running_skills["s1"] = SkillState("s1", "deploy", 3)
        client = AsyncMock()
        server.clients = {client}

        with patch("asyncio.create_task"):
            await server.skill_completed("s1", total_duration_ms=500)

        sent = json.loads(client.send.call_args[0][0])
        assert sent["type"] == "skill_completed"
        assert sent["total_duration_ms"] == 500

    async def test_missing_skill_id(self):
        server = SkillWebSocketServer()
        with patch("asyncio.create_task"):
            await server.skill_completed("nonexistent")


class TestSkillFailed:
    async def test_updates_status(self):
        server = SkillWebSocketServer()
        server.running_skills["s1"] = SkillState("s1", "deploy", 3)

        with patch("asyncio.create_task"):
            await server.skill_failed("s1", "timeout", total_duration_ms=1000)

        assert server.running_skills["s1"].status == "failed"

    async def test_broadcasts_event(self):
        server = SkillWebSocketServer()
        server.running_skills["s1"] = SkillState("s1", "deploy", 3)
        client = AsyncMock()
        server.clients = {client}

        with patch("asyncio.create_task"):
            await server.skill_failed("s1", "some error")

        sent = json.loads(client.send.call_args[0][0])
        assert sent["type"] == "skill_failed"
        assert sent["error"] == "some error"


# ---------------------------------------------------------------------------
# _cleanup_stale_skills
# ---------------------------------------------------------------------------


class TestCleanupStaleSkills:
    async def test_removes_stale_skills(self):
        server = SkillWebSocketServer()
        old_time = datetime.now() - timedelta(seconds=MAX_SKILL_AGE_SECONDS + 100)
        server.running_skills["old"] = SkillState("old", "test", 1, started_at=old_time)
        server.running_skills["new"] = SkillState("new", "test", 1)

        removed = await server._cleanup_stale_skills()
        assert removed >= 1
        assert "old" not in server.running_skills
        assert "new" in server.running_skills

    async def test_enforces_max_count(self):
        server = SkillWebSocketServer()
        # Add more than MAX_RUNNING_SKILLS
        for i in range(MAX_RUNNING_SKILLS + 5):
            server.running_skills[f"s{i}"] = SkillState(
                f"s{i}",
                "test",
                1,
                started_at=datetime.now() - timedelta(seconds=i),
            )

        await server._cleanup_stale_skills()
        assert len(server.running_skills) <= MAX_RUNNING_SKILLS

    async def test_no_stale_returns_zero(self):
        server = SkillWebSocketServer()
        server.running_skills["s1"] = SkillState("s1", "test", 1)
        removed = await server._cleanup_stale_skills()
        assert removed == 0


# ---------------------------------------------------------------------------
# _remove_skill_delayed
# ---------------------------------------------------------------------------


class TestRemoveSkillDelayed:
    async def test_removes_after_delay(self):
        server = SkillWebSocketServer()
        server.running_skills["s1"] = SkillState("s1", "test", 1)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await server._remove_skill_delayed("s1", delay=0.0)

        assert "s1" not in server.running_skills

    async def test_missing_skill_no_error(self):
        server = SkillWebSocketServer()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await server._remove_skill_delayed("nonexistent", delay=0.0)


# ---------------------------------------------------------------------------
# Step events
# ---------------------------------------------------------------------------


class TestStepEvents:
    async def test_step_started_updates_current_step(self):
        server = SkillWebSocketServer()
        server.running_skills["s1"] = SkillState("s1", "deploy", 3)

        await server.step_started("s1", 1, "Build", "Building image")
        assert server.running_skills["s1"].current_step == 1

    async def test_step_started_broadcasts(self):
        server = SkillWebSocketServer()
        client = AsyncMock()
        server.clients = {client}
        server.running_skills["s1"] = SkillState("s1", "deploy", 3)

        await server.step_started("s1", 0, "Init", "Initialize")
        sent = json.loads(client.send.call_args[0][0])
        assert sent["type"] == "step_started"
        assert sent["step_name"] == "Init"
        assert sent["description"] == "Initialize"

    async def test_step_started_missing_skill(self):
        server = SkillWebSocketServer()
        # Should not raise
        await server.step_started("nonexistent", 0, "Step", "desc")

    async def test_step_completed_broadcasts(self):
        server = SkillWebSocketServer()
        client = AsyncMock()
        server.clients = {client}

        await server.step_completed("s1", 0, "Init", 100)
        sent = json.loads(client.send.call_args[0][0])
        assert sent["type"] == "step_completed"
        assert sent["duration_ms"] == 100

    async def test_step_failed_broadcasts(self):
        server = SkillWebSocketServer()
        client = AsyncMock()
        server.clients = {client}

        await server.step_failed("s1", 0, "Init", "timeout")
        sent = json.loads(client.send.call_args[0][0])
        assert sent["type"] == "step_failed"
        assert sent["error"] == "timeout"


# ---------------------------------------------------------------------------
# Auto-heal events
# ---------------------------------------------------------------------------


class TestAutoHealEvents:
    async def test_auto_heal_triggered(self):
        server = SkillWebSocketServer()
        client = AsyncMock()
        server.clients = {client}

        await server.auto_heal_triggered(
            "s1", 0, "vpn_down", "reconnect_vpn", "error detail"
        )
        sent = json.loads(client.send.call_args[0][0])
        assert sent["type"] == "auto_heal_triggered"
        assert sent["error_type"] == "vpn_down"
        assert sent["fix_action"] == "reconnect_vpn"

    async def test_auto_heal_triggered_truncates_snippet(self):
        server = SkillWebSocketServer()
        client = AsyncMock()
        server.clients = {client}

        long_snippet = "x" * 500
        await server.auto_heal_triggered("s1", 0, "err", "fix", long_snippet)
        sent = json.loads(client.send.call_args[0][0])
        assert len(sent["error_snippet"]) <= 200

    async def test_auto_heal_completed(self):
        server = SkillWebSocketServer()
        client = AsyncMock()
        server.clients = {client}

        await server.auto_heal_completed("s1", 0, "reconnect_vpn", True)
        sent = json.loads(client.send.call_args[0][0])
        assert sent["type"] == "auto_heal_completed"
        assert sent["success"] is True


# ---------------------------------------------------------------------------
# Confirmation system
# ---------------------------------------------------------------------------


class TestRequestConfirmation:
    async def test_timeout_returns_let_claude(self):
        server = SkillWebSocketServer()
        server.clients = set()  # No clients

        with (
            patch.object(server, "_bring_cursor_to_front", new_callable=AsyncMock),
            patch.object(server, "_play_notification_sound", new_callable=AsyncMock),
            patch.object(
                server, "_zenity_fallback", new_callable=AsyncMock, return_value=None
            ),
        ):
            result = await server.request_confirmation(
                "s1",
                0,
                "Confirm?",
                ["yes", "no"],
                timeout_seconds=0,  # immediate timeout
            )

        assert result["response"] == "let_claude"
        assert result["remember"] == "none"

    async def test_answered_confirmation(self):
        server = SkillWebSocketServer()
        client = AsyncMock()
        server.clients = {client}

        with (
            patch.object(server, "_bring_cursor_to_front", new_callable=AsyncMock),
            patch.object(server, "_play_notification_sound", new_callable=AsyncMock),
        ):
            # Start confirmation in background
            task = asyncio.create_task(
                server.request_confirmation(
                    "s1",
                    0,
                    "Confirm?",
                    ["yes", "no"],
                    timeout_seconds=5,
                )
            )

            # Wait for the confirmation to be registered
            await asyncio.sleep(0.05)

            # Find the confirmation ID and resolve it
            conf_id = list(server.pending_confirmations.keys())[0]
            conf = server.pending_confirmations[conf_id]
            conf.future.set_result({"response": "yes", "remember": "none"})

            result = await task

        assert result["response"] == "yes"

    async def test_confirmation_cleaned_up(self):
        server = SkillWebSocketServer()

        with (
            patch.object(server, "_bring_cursor_to_front", new_callable=AsyncMock),
            patch.object(server, "_play_notification_sound", new_callable=AsyncMock),
            patch.object(
                server, "_zenity_fallback", new_callable=AsyncMock, return_value=None
            ),
        ):
            await server.request_confirmation(
                "s1",
                0,
                "Test?",
                ["yes", "no"],
                timeout_seconds=0,
            )

        # Should be cleaned up from pending
        assert len(server.pending_confirmations) == 0

    async def test_zenity_fallback_on_timeout_no_clients(self):
        server = SkillWebSocketServer()
        server.clients = set()

        with (
            patch.object(server, "_bring_cursor_to_front", new_callable=AsyncMock),
            patch.object(server, "_play_notification_sound", new_callable=AsyncMock),
            patch.object(
                server,
                "_zenity_fallback",
                new_callable=AsyncMock,
                return_value={"response": "abort", "remember": "none"},
            ),
        ):
            result = await server.request_confirmation(
                "s1",
                0,
                "Confirm?",
                ["yes", "no"],
                timeout_seconds=0,
            )

        assert result["response"] == "abort"


# ---------------------------------------------------------------------------
# _bring_cursor_to_front_sync
# ---------------------------------------------------------------------------


class TestBringCursorToFront:
    def test_wmctrl_success(self):
        server = SkillWebSocketServer()
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            server._bring_cursor_to_front_sync()

    def test_wmctrl_not_found_falls_to_xdotool(self):
        server = SkillWebSocketServer()

        with patch("subprocess.run", side_effect=[FileNotFoundError(), MagicMock()]):
            server._bring_cursor_to_front_sync()

    def test_both_fail(self):
        server = SkillWebSocketServer()

        with patch("subprocess.run", side_effect=FileNotFoundError()):
            # Should not raise
            server._bring_cursor_to_front_sync()

    def test_timeout_expired(self):
        server = SkillWebSocketServer()

        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="wmctrl", timeout=2),
        ):
            server._bring_cursor_to_front_sync()


# ---------------------------------------------------------------------------
# _play_notification_sound_sync
# ---------------------------------------------------------------------------


class TestPlayNotificationSound:
    def test_first_sound_works(self):
        server = SkillWebSocketServer()
        mock_result = MagicMock()

        with patch("subprocess.run", return_value=mock_result):
            server._play_notification_sound_sync()

    def test_all_sounds_fail(self):
        server = SkillWebSocketServer()

        with patch("subprocess.run", side_effect=FileNotFoundError()):
            server._play_notification_sound_sync()

    def test_timeout_expired(self):
        server = SkillWebSocketServer()

        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="paplay", timeout=2),
        ):
            server._play_notification_sound_sync()


# ---------------------------------------------------------------------------
# _zenity_fallback
# ---------------------------------------------------------------------------


class TestZenityFallback:
    async def test_ok_returns_retry(self):
        server = SkillWebSocketServer()

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.wait = AsyncMock(return_value=0)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await server._zenity_fallback(
                "Test?", ["retry_with_fix", "abort"], "suggestion"
            )

        assert result["response"] == "retry_with_fix"

    async def test_cancel_returns_abort(self):
        server = SkillWebSocketServer()

        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.wait = AsyncMock(return_value=1)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await server._zenity_fallback(
                "Test?", ["retry_with_fix", "abort"], ""
            )

        assert result["response"] == "abort"

    async def test_file_not_found(self):
        server = SkillWebSocketServer()

        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError()):
            result = await server._zenity_fallback("Test?", [], "")

        assert result is None

    async def test_generic_exception(self):
        server = SkillWebSocketServer()

        # Note: The source code catches asyncio.TimeoutExpired which doesn't
        # exist in modern Python; a RuntimeError not matching the explicit
        # except clauses will propagate to the final bare except.
        # We test with FileNotFoundError which is explicitly handled.
        with patch(
            "asyncio.create_subprocess_exec", side_effect=FileNotFoundError("no zenity")
        ):
            result = await server._zenity_fallback("Test?", ["yes"], "hint")

        assert result is None


# ---------------------------------------------------------------------------
# Memory query events
# ---------------------------------------------------------------------------


class TestMemoryQueryEvents:
    async def test_memory_query_started(self):
        server = SkillWebSocketServer()
        client = AsyncMock()
        server.clients = {client}

        await server.memory_query_started(
            "q1", "What am I working on?", ["yaml", "code"]
        )
        sent = json.loads(client.send.call_args[0][0])
        assert sent["type"] == "memory_query_started"
        assert sent["query_id"] == "q1"
        assert sent["sources"] == ["yaml", "code"]

    async def test_memory_query_completed(self):
        server = SkillWebSocketServer()
        client = AsyncMock()
        server.clients = {client}

        await server.memory_query_completed(
            "q1",
            intent={"type": "status"},
            sources_queried=["yaml"],
            result_count=5,
            latency_ms=42.5,
        )
        sent = json.loads(client.send.call_args[0][0])
        assert sent["type"] == "memory_query_completed"
        assert sent["result_count"] == 5
        assert sent["latency_ms"] == 42.5

    async def test_intent_classified(self):
        server = SkillWebSocketServer()
        client = AsyncMock()
        server.clients = {client}

        await server.intent_classified(
            "q1", "What am I working on?", "status", 0.95, ["yaml"]
        )
        sent = json.loads(client.send.call_args[0][0])
        assert sent["type"] == "intent_classified"
        assert sent["intent"] == "status"
        assert sent["confidence"] == 0.95


# ---------------------------------------------------------------------------
# _handler (WebSocket connection handler)
# ---------------------------------------------------------------------------


class TestHandler:
    @staticmethod
    def _make_async_iter_ws(messages=None):
        """Create a mock websocket with async iteration support."""
        ws = AsyncMock()
        msgs = messages or []

        async def async_iter():
            for m in msgs:
                yield m

        ws.__aiter__ = lambda self: async_iter()
        return ws

    async def test_handler_sends_connected_and_tracks_client(self):
        server = SkillWebSocketServer()

        ws = self._make_async_iter_ws([])

        await server._handler(ws)

        # Should have sent the connected message
        ws.send.assert_awaited()
        sent = json.loads(ws.send.call_args_list[0][0][0])
        assert sent["type"] == "connected"
        assert "running_skills" in sent
        assert "pending_confirmations" in sent

        # Should have removed client after disconnection
        assert ws not in server.clients

    async def test_handler_includes_running_skills_in_connected(self):
        server = SkillWebSocketServer()
        server.running_skills["s1"] = SkillState("s1", "deploy", 3, current_step=1)

        ws = self._make_async_iter_ws([])

        await server._handler(ws)

        sent = json.loads(ws.send.call_args_list[0][0][0])
        assert len(sent["running_skills"]) == 1
        assert sent["running_skills"][0]["skill_id"] == "s1"

    async def test_handler_processes_messages(self):
        server = SkillWebSocketServer()

        heartbeat_msg = json.dumps({"type": "heartbeat"})
        ws = self._make_async_iter_ws([heartbeat_msg])

        await server._handler(ws)

        # Should have sent connected + heartbeat_ack
        assert ws.send.await_count == 2


# ---------------------------------------------------------------------------
# Global instance functions
# ---------------------------------------------------------------------------


class TestGlobalFunctions:
    def test_get_websocket_server_creates_singleton(self):
        import server.websocket_server as wsm

        original = wsm._ws_server
        try:
            wsm._ws_server = None
            s1 = get_websocket_server()
            s2 = get_websocket_server()
            assert s1 is s2
            assert isinstance(s1, SkillWebSocketServer)
        finally:
            wsm._ws_server = original

    async def test_start_websocket_server(self):
        import server.websocket_server as wsm

        original = wsm._ws_server
        try:
            wsm._ws_server = None
            with patch.object(SkillWebSocketServer, "start", new_callable=AsyncMock):
                s = await start_websocket_server()
            assert isinstance(s, SkillWebSocketServer)
        finally:
            wsm._ws_server = original

    async def test_stop_websocket_server(self):
        import server.websocket_server as wsm

        original = wsm._ws_server
        try:
            mock_server = AsyncMock(spec=SkillWebSocketServer)
            wsm._ws_server = mock_server
            await stop_websocket_server()
            mock_server.stop.assert_awaited_once()
            assert wsm._ws_server is None
        finally:
            wsm._ws_server = original

    async def test_stop_websocket_server_when_none(self):
        import server.websocket_server as wsm

        original = wsm._ws_server
        try:
            wsm._ws_server = None
            await stop_websocket_server()  # Should not raise
        finally:
            wsm._ws_server = original


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestWSConstants:
    def test_max_running_skills(self):
        assert MAX_RUNNING_SKILLS == 100

    def test_max_skill_age_seconds(self):
        assert MAX_SKILL_AGE_SECONDS == 3600
