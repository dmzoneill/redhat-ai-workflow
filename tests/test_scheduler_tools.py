"""Tests for tool_modules/aa_workflow/src/scheduler_tools.py"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP
from mcp.types import TextContent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tc_text(result):
    """Extract text from a list[TextContent] result."""
    assert isinstance(result, list)
    assert len(result) >= 1
    return result[0].text


# ---------------------------------------------------------------------------
# Module-level helpers (_get_schedules_config / _update_schedules_config)
# ---------------------------------------------------------------------------


def test_get_schedules_config():
    with patch(
        "tool_modules.aa_workflow.src.scheduler_tools.config_manager"
    ) as mock_cm:
        from tool_modules.aa_workflow.src.scheduler_tools import _get_schedules_config

        mock_cm.get.return_value = {"jobs": []}
        assert _get_schedules_config() == {"jobs": []}
        mock_cm.get.assert_called_once_with("schedules", default={})


def test_update_schedules_config():
    with patch(
        "tool_modules.aa_workflow.src.scheduler_tools.config_manager"
    ) as mock_cm:
        from tool_modules.aa_workflow.src.scheduler_tools import (
            _update_schedules_config,
        )

        _update_schedules_config({"jobs": []})
        mock_cm.update_section.assert_called_once_with(
            "schedules", {"jobs": []}, merge=False, flush=True
        )
        assert mock_cm.update_section.call_count == 1


# ---------------------------------------------------------------------------
# register_scheduler_tools – returns count of tools registered
# ---------------------------------------------------------------------------


def test_register_returns_count():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager"),
    ):
        from tool_modules.aa_workflow.src.scheduler_tools import (
            register_scheduler_tools,
        )

        server = MagicMock(spec=FastMCP)
        # Make server.tool() return a passthrough decorator
        server.tool.return_value = lambda fn: fn
        count = register_scheduler_tools(server)
        # 8 tools: list, add, remove, enable, run_now, status, notifications, scheduler_toggle
        assert count == 8


# ---------------------------------------------------------------------------
# cron_list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cron_list_scheduler_disabled():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager") as mock_sm,
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager") as mock_cm,
    ):
        from tool_modules.aa_workflow.src.scheduler_tools import (
            register_scheduler_tools,
        )

        mock_sm.is_service_enabled.return_value = False
        mock_cm.get.return_value = {}

        server = MagicMock(spec=FastMCP)
        server.tool.return_value = lambda fn: fn
        register_scheduler_tools(server)

        # Import the cron_list that was just defined
        from tool_modules.aa_workflow.src.scheduler_tools import (
            register_scheduler_tools,
        )

        # We need to call the tool directly, but it's a local function.
        # Let's capture it via the registry.
        captured_tools = {}

        def make_decorator(**kwargs):
            def decorator(fn):
                captured_tools[fn.__name__] = fn
                return fn

            return decorator

        server2 = MagicMock()
        server2.tool = make_decorator
        register_scheduler_tools(server2)

        result = await captured_tools["cron_list"]()
        text = _tc_text(result)
        assert "disabled" in text.lower() or "Disabled" in text or "disabled" in text


@pytest.mark.asyncio
async def test_cron_list_no_jobs():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager") as mock_sm,
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager") as mock_cm,
    ):
        mock_sm.is_service_enabled.return_value = True
        mock_cm.get.return_value = {"jobs": []}

        captured = {}

        def make_dec(**kw):
            def dec(fn):
                captured[fn.__name__] = fn
                return fn

            return dec

        server = MagicMock(spec=FastMCP)
        server.tool = make_dec

        from tool_modules.aa_workflow.src.scheduler_tools import (
            register_scheduler_tools,
        )

        register_scheduler_tools(server)

        result = await captured["cron_list"]()
        text = _tc_text(result)
        assert "No scheduled jobs" in text


@pytest.mark.asyncio
async def test_cron_list_with_cron_job():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager") as mock_sm,
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager") as mock_cm,
    ):
        mock_sm.is_service_enabled.return_value = True
        mock_sm.is_job_enabled.return_value = True
        mock_cm.get.return_value = {
            "timezone": "US/Eastern",
            "default_retry": {"max_attempts": 3, "backoff": "linear"},
            "jobs": [
                {
                    "name": "morning_coffee",
                    "skill": "coffee",
                    "cron": "30 8 * * 1-5",
                    "notify": ["slack"],
                    "persona": "dev",
                    "retry": {"max_attempts": 2, "retry_on": ["auth"]},
                    "inputs": {"brew": "espresso"},
                }
            ],
        }

        captured = {}

        def make_dec(**kw):
            def dec(fn):
                captured[fn.__name__] = fn
                return fn

            return dec

        server = MagicMock(spec=FastMCP)
        server.tool = make_dec

        from tool_modules.aa_workflow.src.scheduler_tools import (
            register_scheduler_tools,
        )

        register_scheduler_tools(server)

        result = await captured["cron_list"]()
        text = _tc_text(result)
        assert "morning_coffee" in text
        assert "coffee" in text
        assert "30 8 * * 1-5" in text
        assert "slack" in text
        assert "dev" in text
        assert "espresso" in text
        assert "US/Eastern" in text
        assert "3 attempts" in text or "linear" in text


@pytest.mark.asyncio
async def test_cron_list_poll_job():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager") as mock_sm,
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager") as mock_cm,
    ):
        mock_sm.is_service_enabled.return_value = True
        mock_sm.is_job_enabled.return_value = False
        mock_cm.get.return_value = {
            "jobs": [
                {
                    "name": "stale_prs",
                    "skill": "pr_reminder",
                    "trigger": "poll",
                    "poll_interval": "1h",
                    "condition": "gitlab_stale_prs",
                    "notify": [],
                    "retry": False,
                }
            ],
        }

        captured = {}

        def make_dec(**kw):
            def dec(fn):
                captured[fn.__name__] = fn
                return fn

            return dec

        server = MagicMock(spec=FastMCP)
        server.tool = make_dec

        from tool_modules.aa_workflow.src.scheduler_tools import (
            register_scheduler_tools,
        )

        register_scheduler_tools(server)

        result = await captured["cron_list"]()
        text = _tc_text(result)
        assert "stale_prs" in text
        assert "Poll" in text
        assert "1h" in text
        assert "disabled" in text.lower()


@pytest.mark.asyncio
async def test_cron_list_default_retry_badge():
    """Job with retry=None should show 'default'."""
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager") as mock_sm,
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager") as mock_cm,
    ):
        mock_sm.is_service_enabled.return_value = True
        mock_sm.is_job_enabled.return_value = True
        mock_cm.get.return_value = {
            "jobs": [
                {"name": "j", "skill": "s", "cron": "* * * * *", "notify": []},
            ],
        }

        captured = {}

        def make_dec(**kw):
            def dec(fn):
                captured[fn.__name__] = fn
                return fn

            return dec

        server = MagicMock(spec=FastMCP)
        server.tool = make_dec

        from tool_modules.aa_workflow.src.scheduler_tools import (
            register_scheduler_tools,
        )

        register_scheduler_tools(server)

        result = await captured["cron_list"]()
        text = _tc_text(result)
        assert "default" in text.lower()


# ---------------------------------------------------------------------------
# cron_add
# ---------------------------------------------------------------------------


def _build_captured_tools():
    """Helper that builds captured tools dict by registering tools."""
    captured = {}

    def make_dec(**kw):
        def dec(fn):
            captured[fn.__name__] = fn
            return fn

        return dec

    server = MagicMock(spec=FastMCP)
    server.tool = make_dec

    from tool_modules.aa_workflow.src.scheduler_tools import register_scheduler_tools

    register_scheduler_tools(server)
    return captured, server


@pytest.mark.asyncio
async def test_cron_add_empty_name():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager"),
    ):
        captured, _ = _build_captured_tools()
        result = await captured["cron_add"](name="", skill="x", cron="* * * * *")
        assert "required" in _tc_text(result).lower()


@pytest.mark.asyncio
async def test_cron_add_empty_skill():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager"),
    ):
        captured, _ = _build_captured_tools()
        result = await captured["cron_add"](name="j", skill="", cron="* * * * *")
        assert "required" in _tc_text(result).lower()


@pytest.mark.asyncio
async def test_cron_add_no_schedule():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager"),
    ):
        captured, _ = _build_captured_tools()
        result = await captured["cron_add"](name="j", skill="s")
        assert "required" in _tc_text(result).lower()


@pytest.mark.asyncio
async def test_cron_add_invalid_cron():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager"),
    ):
        captured, _ = _build_captured_tools()
        result = await captured["cron_add"](name="j", skill="s", cron="bad_cron")
        assert "Invalid cron" in _tc_text(result)


@pytest.mark.asyncio
async def test_cron_add_invalid_json():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager"),
    ):
        captured, _ = _build_captured_tools()
        result = await captured["cron_add"](
            name="j", skill="s", cron="* * * * *", inputs="not-json"
        )
        assert "Invalid inputs JSON" in _tc_text(result)


@pytest.mark.asyncio
async def test_cron_add_duplicate_name():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager") as mock_cm,
    ):
        mock_cm.get.return_value = {"jobs": [{"name": "dup"}]}
        captured, _ = _build_captured_tools()
        result = await captured["cron_add"](name="dup", skill="s", cron="* * * * *")
        assert "already exists" in _tc_text(result)


@pytest.mark.asyncio
async def test_cron_add_cron_success():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager") as mock_sm,
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager") as mock_cm,
    ):
        mock_cm.get.return_value = {}
        captured, _ = _build_captured_tools()
        result = await captured["cron_add"](
            name="test_job",
            skill="coffee",
            cron="30 8 * * 1-5",
            notify="slack,desktop",
            inputs='{"brew": "espresso"}',
            retry_max_attempts=3,
            retry_on="auth,network",
        )
        text = _tc_text(result)
        assert "test_job" in text
        assert "coffee" in text
        assert "30 8 * * 1-5" in text
        mock_cm.update_section.assert_called_once()
        mock_sm.set_job_enabled.assert_called_once_with("test_job", True)


@pytest.mark.asyncio
async def test_cron_add_poll_success():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager") as mock_cm,
    ):
        mock_cm.get.return_value = {}
        captured, _ = _build_captured_tools()
        result = await captured["cron_add"](
            name="poller", skill="check", poll_interval="30m", poll_condition="cond"
        )
        text = _tc_text(result)
        assert "poller" in text
        assert "30m" in text
        assert "cond" in text


@pytest.mark.asyncio
async def test_cron_add_retry_disabled():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager") as mock_cm,
    ):
        mock_cm.get.return_value = {}
        captured, _ = _build_captured_tools()
        result = await captured["cron_add"](
            name="nr", skill="s", cron="* * * * *", retry_max_attempts=0
        )
        text = _tc_text(result)
        assert "disabled" in text.lower()


@pytest.mark.asyncio
async def test_cron_add_default_retry():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager") as mock_cm,
    ):
        mock_cm.get.return_value = {}
        captured, _ = _build_captured_tools()
        result = await captured["cron_add"](name="dr", skill="s", cron="* * * * *")
        text = _tc_text(result)
        assert "default" in text.lower()


# ---------------------------------------------------------------------------
# cron_remove
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cron_remove_not_found():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager") as mock_cm,
    ):
        mock_cm.get.return_value = {"jobs": []}
        captured, _ = _build_captured_tools()
        result = await captured["cron_remove"](name="nonexistent")
        assert "not found" in _tc_text(result).lower()


@pytest.mark.asyncio
async def test_cron_remove_success():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager") as mock_cm,
    ):
        mock_cm.get.return_value = {"jobs": [{"name": "target"}, {"name": "keep"}]}
        captured, _ = _build_captured_tools()
        result = await captured["cron_remove"](name="target")
        text = _tc_text(result)
        assert "Removed" in text
        assert "target" in text
        mock_cm.update_section.assert_called_once()
        saved = mock_cm.update_section.call_args[0][1]
        assert len(saved["jobs"]) == 1
        assert saved["jobs"][0]["name"] == "keep"


# ---------------------------------------------------------------------------
# cron_enable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cron_enable_not_found():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager") as mock_cm,
    ):
        mock_cm.get.return_value = {"jobs": []}
        captured, _ = _build_captured_tools()
        result = await captured["cron_enable"](name="nope")
        assert "not found" in _tc_text(result).lower()


@pytest.mark.asyncio
async def test_cron_enable_enable():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager") as mock_sm,
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager") as mock_cm,
    ):
        mock_cm.get.return_value = {"jobs": [{"name": "j"}]}
        captured, _ = _build_captured_tools()
        result = await captured["cron_enable"](name="j", enabled=True)
        text = _tc_text(result)
        assert "enabled" in text.lower()
        mock_sm.set_job_enabled.assert_called_once_with("j", True, flush=True)


@pytest.mark.asyncio
async def test_cron_enable_disable():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager") as mock_cm,
    ):
        mock_cm.get.return_value = {"jobs": [{"name": "j"}]}
        captured, _ = _build_captured_tools()
        result = await captured["cron_enable"](name="j", enabled=False)
        text = _tc_text(result)
        assert "disabled" in text.lower()


# ---------------------------------------------------------------------------
# cron_run_now
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cron_run_now_no_scheduler_no_job():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager") as mock_cm,
    ):
        mock_cm.get.return_value = {"jobs": []}

        mock_sched_module = MagicMock()
        mock_sched_module.get_scheduler.return_value = None

        with patch.dict(
            "sys.modules", {"tool_modules.aa_workflow.src.scheduler": mock_sched_module}
        ):
            captured, server = _build_captured_tools()
            result = await captured["cron_run_now"](name="nope")
        assert "not found" in _tc_text(result).lower()


@pytest.mark.asyncio
async def test_cron_run_now_no_scheduler_executes_skill():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager") as mock_cm,
    ):
        mock_cm.get.return_value = {
            "jobs": [{"name": "j", "skill": "coffee", "inputs": {"brew": "latte"}}]
        }

        mock_sched_module = MagicMock()
        mock_sched_module.get_scheduler.return_value = None

        with patch.dict(
            "sys.modules", {"tool_modules.aa_workflow.src.scheduler": mock_sched_module}
        ):
            captured, server = _build_captured_tools()
            mock_result = MagicMock()
            mock_result.content = [TextContent(type="text", text="done")]
            server.call_tool = AsyncMock(return_value=mock_result)
            result = await captured["cron_run_now"](name="j")
        text = _tc_text(result)
        assert "done" in text or "executed" in text.lower()


@pytest.mark.asyncio
async def test_cron_run_now_with_scheduler_success():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager"),
    ):
        captured, _ = _build_captured_tools()

        mock_scheduler = AsyncMock()
        mock_scheduler.run_job_now.return_value = {"success": True}

        mock_sched_module = MagicMock()
        mock_sched_module.get_scheduler.return_value = mock_scheduler

        with patch.dict(
            "sys.modules", {"tool_modules.aa_workflow.src.scheduler": mock_sched_module}
        ):
            result = await captured["cron_run_now"](name="j")
        text = _tc_text(result)
        assert "success" in text.lower()


@pytest.mark.asyncio
async def test_cron_run_now_with_scheduler_failure():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager"),
    ):
        captured, _ = _build_captured_tools()

        mock_scheduler = AsyncMock()
        mock_scheduler.run_job_now.return_value = {"success": False, "error": "boom"}

        mock_sched_module = MagicMock()
        mock_sched_module.get_scheduler.return_value = mock_scheduler

        with patch.dict(
            "sys.modules", {"tool_modules.aa_workflow.src.scheduler": mock_sched_module}
        ):
            result = await captured["cron_run_now"](name="j")
        text = _tc_text(result)
        assert "boom" in text


# ---------------------------------------------------------------------------
# cron_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cron_status_no_scheduler():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager") as mock_sm,
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager") as mock_cm,
    ):
        mock_sm.is_service_enabled.return_value = True
        mock_cm.get.return_value = {"timezone": "UTC", "jobs": [{"name": "a"}]}
        captured, _ = _build_captured_tools()

        mock_sched_module = MagicMock()
        mock_sched_module.get_scheduler.return_value = None

        with patch.dict(
            "sys.modules", {"tool_modules.aa_workflow.src.scheduler": mock_sched_module}
        ):
            result = await captured["cron_status"]()
        text = _tc_text(result)
        assert "not started" in text.lower()
        assert "1" in text  # total jobs


@pytest.mark.asyncio
async def test_cron_status_with_scheduler_and_executions():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager") as mock_sm,
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager") as mock_cm,
    ):
        mock_sm.is_service_enabled.return_value = True
        mock_cm.get.return_value = {
            "timezone": "US/Pacific",
            "default_retry": {"max_attempts": 2, "backoff": "exponential"},
            "jobs": [],
        }
        captured, _ = _build_captured_tools()

        scheduler = MagicMock()
        scheduler.get_status.return_value = {
            "running": True,
            "cron_jobs": 2,
            "poll_jobs": 1,
            "recent_executions": [
                {
                    "timestamp": "2025-01-01T10:00:00",
                    "job_name": "j1",
                    "success": True,
                    "duration_ms": 100,
                    "retry": {
                        "retried": True,
                        "attempts": 2,
                        "remediation_applied": "re-auth",
                    },
                },
                {
                    "timestamp": "2025-01-01T11:00:00",
                    "job_name": "j2",
                    "success": False,
                    "duration_ms": 200,
                    "error": "timeout",
                    "retry": {"retried": True, "attempts": 3},
                },
            ],
        }

        mock_sched_module = MagicMock()
        mock_sched_module.get_scheduler.return_value = scheduler

        with patch.dict(
            "sys.modules", {"tool_modules.aa_workflow.src.scheduler": mock_sched_module}
        ):
            result = await captured["cron_status"]()
        text = _tc_text(result)
        assert "j1" in text
        assert "j2" in text
        assert "re-auth" in text
        assert "timeout" in text
        assert "Retry Summary" in text


# ---------------------------------------------------------------------------
# cron_notifications
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cron_notifications_no_engine():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager"),
    ):
        captured, _ = _build_captured_tools()

        mock_ne_module = MagicMock()
        mock_ne_module.get_notification_engine.return_value = None

        with patch.dict(
            "sys.modules",
            {"tool_modules.aa_workflow.src.notification_engine": mock_ne_module},
        ):
            result = await captured["cron_notifications"]()
        text = _tc_text(result)
        assert "not initialized" in text.lower()


@pytest.mark.asyncio
async def test_cron_notifications_empty():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager"),
    ):
        captured, _ = _build_captured_tools()

        engine = MagicMock()
        engine.get_recent_notifications.return_value = []
        mock_ne_module = MagicMock()
        mock_ne_module.get_notification_engine.return_value = engine

        with patch.dict(
            "sys.modules",
            {"tool_modules.aa_workflow.src.notification_engine": mock_ne_module},
        ):
            result = await captured["cron_notifications"]()
        text = _tc_text(result)
        assert "No recent" in text


@pytest.mark.asyncio
async def test_cron_notifications_with_data():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager"),
    ):
        captured, _ = _build_captured_tools()

        engine = MagicMock()
        engine.get_recent_notifications.return_value = [
            {
                "timestamp": "2025-01-01T10:00:00",
                "title": "Coffee done",
                "success": True,
                "job_name": "coffee",
                "message": "Brewed OK",
            },
            {
                "timestamp": "2025-01-01T11:00:00",
                "title": "Alert",
                "success": False,
                "job_name": "",
                "message": "x" * 300,  # will be truncated
            },
        ]
        mock_ne_module = MagicMock()
        mock_ne_module.get_notification_engine.return_value = engine

        with patch.dict(
            "sys.modules",
            {"tool_modules.aa_workflow.src.notification_engine": mock_ne_module},
        ):
            result = await captured["cron_notifications"](limit=5)
        text = _tc_text(result)
        assert "Coffee done" in text
        assert "Alert" in text
        assert "..." in text  # truncated message


# ---------------------------------------------------------------------------
# cron_scheduler_toggle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_toggle_enable_no_scheduler():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager") as mock_sm,
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager"),
    ):
        captured, _ = _build_captured_tools()

        mock_sched_module = MagicMock()
        mock_sched_module.get_scheduler.return_value = None

        with patch.dict(
            "sys.modules", {"tool_modules.aa_workflow.src.scheduler": mock_sched_module}
        ):
            result = await captured["cron_scheduler_toggle"](enabled=True)
        text = _tc_text(result)
        assert "enabled" in text.lower()
        assert "next server restart" in text.lower()
        mock_sm.set_service_enabled.assert_called_with("scheduler", True, flush=True)


@pytest.mark.asyncio
async def test_scheduler_toggle_enable_already_running():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager"),
    ):
        captured, _ = _build_captured_tools()

        scheduler = MagicMock()
        scheduler.is_running = True
        config = MagicMock()
        config.get_cron_jobs.return_value = [1, 2]
        config.get_poll_jobs.return_value = [3]
        scheduler.config = config

        mock_sched_module = MagicMock()
        mock_sched_module.get_scheduler.return_value = scheduler

        with patch.dict(
            "sys.modules", {"tool_modules.aa_workflow.src.scheduler": mock_sched_module}
        ):
            result = await captured["cron_scheduler_toggle"](enabled=True)
        text = _tc_text(result)
        assert "already running" in text.lower()
        scheduler.reload_config.assert_called_once()


@pytest.mark.asyncio
async def test_scheduler_toggle_enable_start():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager"),
    ):
        captured, _ = _build_captured_tools()

        scheduler = AsyncMock()
        scheduler.is_running = False
        config_cls = MagicMock()
        config_instance = MagicMock()
        config_instance.get_cron_jobs.return_value = []
        config_instance.get_poll_jobs.return_value = []
        config_cls.return_value = config_instance
        scheduler.config = MagicMock(__class__=config_cls)
        scheduler.config.__class__ = config_cls

        mock_sched_module = MagicMock()
        mock_sched_module.get_scheduler.return_value = scheduler

        with patch.dict(
            "sys.modules", {"tool_modules.aa_workflow.src.scheduler": mock_sched_module}
        ):
            result = await captured["cron_scheduler_toggle"](enabled=True)
        text = _tc_text(result)
        assert "enabled" in text.lower()
        assert "started" in text.lower()


@pytest.mark.asyncio
async def test_scheduler_toggle_disable_running():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager"),
    ):
        captured, _ = _build_captured_tools()

        scheduler = AsyncMock()
        scheduler.is_running = True

        mock_sched_module = MagicMock()
        mock_sched_module.get_scheduler.return_value = scheduler

        with patch.dict(
            "sys.modules", {"tool_modules.aa_workflow.src.scheduler": mock_sched_module}
        ):
            result = await captured["cron_scheduler_toggle"](enabled=False)
        text = _tc_text(result)
        assert "disabled" in text.lower()
        assert "stopped" in text.lower()
        scheduler.stop.assert_called_once()


@pytest.mark.asyncio
async def test_scheduler_toggle_disable_not_running():
    with (
        patch("tool_modules.aa_workflow.src.scheduler_tools.state_manager"),
        patch("tool_modules.aa_workflow.src.scheduler_tools.config_manager"),
    ):
        captured, _ = _build_captured_tools()

        scheduler = MagicMock()
        scheduler.is_running = False

        mock_sched_module = MagicMock()
        mock_sched_module.get_scheduler.return_value = scheduler

        with patch.dict(
            "sys.modules", {"tool_modules.aa_workflow.src.scheduler": mock_sched_module}
        ):
            result = await captured["cron_scheduler_toggle"](enabled=False)
        text = _tc_text(result)
        assert "disabled" in text.lower()
        assert "was not running" in text.lower()
