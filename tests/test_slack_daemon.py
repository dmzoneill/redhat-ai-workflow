"""Tests for the Slack daemon split (services/slack daemon modules)."""

import sys
import types
from types import SimpleNamespace
from typing import ClassVar
from unittest import mock

import pytest

from scripts.common.command_registry import CommandType
from services.slack import command_handler, daemon_messages, daemon_startup, errors, response_builder, slack_config
from services.slack.daemon import SlackDaemon


class FakeSession:
    """Slack session stand-in with scripted API replies."""

    replies: ClassVar[dict] = {}

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.sent: list[dict] = []

    async def validate_session(self):
        """Return or raise the next scripted validate result."""
        result = self.replies.get("validate", [{"user": "dave"}]).pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def get_client_counts(self):
        """Scripted client.counts reply."""
        return self._reply("counts")

    async def get_channel_sections(self):
        """Scripted sidebar reply."""
        return self._reply("sections")

    async def get_conversations_list(self, **_kwargs):
        """Scripted conversations.list reply."""
        return self._reply("convs", [])

    async def send_message(self, **kwargs):
        """Record a sent message."""
        self.sent.append(kwargs)
        return {"ts": "200.0"}

    def _reply(self, key, default=None):
        result = self.replies.get(key, default if default is not None else {"ok": False})
        if isinstance(result, Exception):
            raise result
        return result


def fake_generator(notifier=None):
    """ResponseGenerator stand-in with a mock Claude agent."""
    agent = mock.MagicMock(model="claude", use_vertex=False)
    agent.process_message = mock.AsyncMock(return_value="investigated")
    return SimpleNamespace(notifier=notifier, claude_agent=agent, generate=mock.AsyncMock(return_value=("reply", True)))


def _private(obj, name):
    """Read a private attribute by name (tests only)."""
    return getattr(obj, name)


def _msg(**overrides):
    fields = {
        "id": "m1",
        "timestamp": "100.1",
        "thread_ts": None,
        "channel_id": "C1",
        "channel_name": "general",
        "user_id": "U1",
        "user_name": "bob",
        "text": "hello",
        "raw_message": {},
        "is_dm": False,
        "is_mention": False,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _state_db():
    db = mock.MagicMock()
    db.was_notified = mock.AsyncMock(return_value=False)
    for name in ("mark_message_processed", "mark_notified", "set_last_processed_ts"):
        setattr(db, name, mock.AsyncMock())
    return db


@pytest.fixture(name="settings")
def settings_fixture(monkeypatch):
    """Empty slack settings, patchable per test."""
    monkeypatch.setattr(slack_config.SETTINGS, "slack", {})
    return slack_config.SETTINGS


@pytest.fixture(name="daemon")
def daemon_fixture(settings, monkeypatch):
    """A SlackDaemon with fake Slack client modules, Claude and session."""
    del settings
    FakeSession.replies = {}
    monkeypatch.setattr(daemon_startup, "ResponseGenerator", fake_generator)
    monkeypatch.setitem(sys.modules, "src.slack_client", types.SimpleNamespace(SlackSession=FakeSession))
    monkeypatch.setitem(sys.modules, "src.listener", types.SimpleNamespace(ListenerConfig=SimpleNamespace))
    monkeypatch.setitem(sys.modules, "services.slack.dbus", types.SimpleNamespace(MessageRecord=SimpleNamespace))
    d = SlackDaemon()
    d.conn.session = FakeSession()
    d.conn.state_db = _state_db()
    return d


# ---------------------------------------------------------------- config


def test_get_slack_config_nested_env_and_default(settings, monkeypatch):
    """Dotted keys read nested values; env vars override; missing keys fall back."""
    settings.slack = {"auth": {"xoxc_token": "cfg"}, "flat": 3}
    assert slack_config.get_slack_config("auth.xoxc_token") == "cfg"
    assert slack_config.get_slack_config("flat.deeper", "dflt") == "dflt"
    assert slack_config.get_slack_config("missing", 7) == 7
    monkeypatch.setenv("SLACK_TEST_TOKEN", "env")
    assert slack_config.get_slack_config("auth.xoxc_token", env_var="SLACK_TEST_TOKEN") == "env"


def test_module_config_names_track_reload(settings):
    """CONFIG/SLACK_CONFIG on the daemon module follow the live settings."""
    daemon_module = sys.modules[SlackDaemon.__module__]
    settings.slack = {"x": 1}
    assert daemon_module.SLACK_CONFIG == {"x": 1}
    assert slack_config.SLACK_CONFIG is settings.slack
    with pytest.raises(AttributeError):
        _private(daemon_module, "NOPE")


def test_refresh_credentials_reloads_on_success(monkeypatch, tmp_path):
    """A successful refresh reloads config; a failing one does not."""
    script = tmp_path / "scripts" / "get_slack_creds.py"
    script.parent.mkdir()
    script.write_text("", encoding="utf-8")
    monkeypatch.setattr(slack_config, "PROJECT_ROOT", tmp_path)
    reload = mock.Mock()
    monkeypatch.setattr(slack_config.SETTINGS, "reload", reload)

    monkeypatch.setattr(slack_config.subprocess, "run", mock.Mock(return_value=mock.Mock(returncode=0)))
    assert slack_config.refresh_slack_credentials() is True
    reload.assert_called_once()

    failing = mock.Mock(returncode=1, stderr="nope", stdout="")
    monkeypatch.setattr(slack_config.subprocess, "run", mock.Mock(return_value=failing))
    assert slack_config.refresh_slack_credentials() is False
    assert reload.call_count == 1


def test_refresh_credentials_missing_script(monkeypatch, tmp_path):
    """No refresh script means no refresh."""
    monkeypatch.setattr(slack_config, "PROJECT_ROOT", tmp_path)
    assert slack_config.refresh_slack_credentials() is False


def test_slack_errors_cover_runtime_failures():
    """The recoverable errors include OS, value and timeout failures, not BaseException."""
    for exc in (OSError, ValueError, TimeoutError, KeyError):
        assert issubclass(exc, errors.SLACK_ERRORS)
    assert ImportError in errors.IMPORT_OR_SLACK_ERRORS
    assert not issubclass(KeyboardInterrupt, errors.IMPORT_OR_SLACK_ERRORS)


# ---------------------------------------------------------------- command handler


def _handler(monkeypatch, command, info=None):
    handler = command_handler.CommandHandler(claude_agent=mock.MagicMock())
    handler.claude_agent.process_message = mock.AsyncMock(return_value="ran")
    parsed = mock.MagicMock(is_command=True, command=command)
    parsed.to_skill_inputs.return_value = {"a": 1}
    handler.parser = mock.MagicMock()
    handler.parser.parse.return_value = parsed
    handler.parser.is_help_command.side_effect = lambda p: p.command == "help"
    handler.parser.is_status_command.side_effect = lambda p: p.command == "status"
    handler.registry = mock.MagicMock()
    handler.registry.get_command.return_value = info
    handler.router = mock.MagicMock()
    for module in (command_handler.jira_commands, command_handler.system_commands, command_handler.meet_commands):
        for name in dir(module):
            if name.startswith("handle_"):
                monkeypatch.setattr(module, name, mock.AsyncMock(return_value=f"{module.__name__}.{name}"))
    return handler


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("help", "system_commands.handle_help"),
        ("status", "system_commands.handle_status"),
        ("list", "system_commands.handle_list"),
        ("jira", "jira_commands.handle_jira"),
        ("who", "jira_commands.handle_who"),
        ("meet", "meet_commands.handle_meet"),
    ],
)
async def test_command_routes(monkeypatch, command, expected):
    """Built-in commands go to their handler module and the reply is routed."""
    handler = _handler(monkeypatch, command)
    response, should_send = await handler.handle(_msg(text=f"@me {command}"), mock.MagicMock(auto_respond=True))
    assert response.endswith(expected)
    assert should_send is True
    handler.router.route.assert_called_once()


async def test_skill_tool_and_unknown(monkeypatch):
    """Other commands run as skills or tools through Claude; unknown ones explain themselves."""
    skill = _handler(monkeypatch, "deploy", mock.MagicMock(contextual=False, command_type=CommandType.SKILL))
    assert (await skill.handle(_msg(), mock.MagicMock()))[0] == "ran"
    prompt, context = skill.claude_agent.process_message.call_args.args
    assert 'skill_run("deploy", \'{"a": 1}\')' in prompt
    assert context["purpose"] == "skill_execution"

    tool = _handler(monkeypatch, "grep", mock.MagicMock(contextual=False, command_type=CommandType.TOOL))
    await tool.handle(_msg(), mock.MagicMock())
    assert tool.claude_agent.process_message.call_args.args[1]["tool_name"] == "grep"

    unknown = _handler(monkeypatch, "nope")
    assert "Unknown command: `nope`" in (await unknown.handle(_msg(), mock.MagicMock()))[0]


async def test_command_error_and_non_command(monkeypatch):
    """Handler failures become an error reply; non-commands are ignored."""
    handler = _handler(monkeypatch, "jira")
    monkeypatch.setattr(command_handler.jira_commands, "handle_jira", mock.AsyncMock(side_effect=ValueError("bad")))
    assert await handler.handle(_msg(), mock.MagicMock()) == ("\u274c Error: bad", True)

    handler.parser.parse.return_value = mock.MagicMock(is_command=False)
    assert await handler.handle(_msg(), mock.MagicMock()) == (None, False)


async def test_call_dbus_parses_and_reports_errors(monkeypatch):
    """D-Bus replies decode JSON; failures come back as an error dict."""
    iface = mock.MagicMock(call_ping=mock.AsyncMock(return_value='{"ok": 1}'))
    bus = mock.MagicMock()
    bus.introspect = mock.AsyncMock()
    bus.get_proxy_object.return_value.get_interface.return_value = iface
    message_bus = mock.MagicMock()
    message_bus.return_value.connect = mock.AsyncMock(return_value=bus)
    monkeypatch.setitem(sys.modules, "dbus_next.aio", types.SimpleNamespace(MessageBus=message_bus))
    assert await command_handler.call_dbus("s", "/p", "i", "Ping") == {"ok": 1}
    iface.call_ping.return_value = "plain"
    assert await command_handler.call_dbus("s", "/p", "i", "Ping", ["x"]) == {"result": "plain"}

    message_bus.return_value.connect = mock.AsyncMock(side_effect=OSError("no bus"))
    assert await command_handler.call_dbus("s", "/p", "i", "Ping") == {"error": "no bus"}


# ---------------------------------------------------------------- start-up


def test_config_list(settings):
    """List settings accept comma-separated strings."""
    settings.slack = {"listener": {"a": " x, ,y ", "b": ["Q"], "k": "Foo,Bar"}}
    assert daemon_startup.config_list("listener.a") == ["x", "y"]
    assert daemon_startup.config_list("listener.b") == ["Q"]
    assert daemon_startup.config_list("listener.k", lower=True) == ["foo", "bar"]
    assert not daemon_startup.config_list("listener.missing")


@pytest.mark.parametrize(
    ("replies", "expected"),
    [
        ({"counts": {"ok": True, "ims": [{"id": "D1"}, {"id": "D1"}], "mpims": [{"id": "C7"}]}}, ["D1", "C7"]),
        (
            {"sections": {"ok": True, "channel_sections": [{"channel_ids_page": {"channel_ids": ["D1", "C2", "G3"]}}]}},
            ["D1", "G3"],
        ),
        ({"convs": [{"id": "D1"}, {"id": "G2", "is_archived": True}]}, ["D1"]),
        ({"counts": OSError("x"), "sections": OSError("y"), "convs": RuntimeError("enterprise_is_restricted")}, []),
    ],
)
async def test_discover_dm_channels(daemon, replies, expected):
    """Discovery falls through client.counts, the sidebar and conversations.list."""
    FakeSession.replies = replies
    assert await daemon.discover_dm_channels() == expected


async def test_listener_config(daemon, settings):
    """Listener config merges discovered DMs and honours command-line poll overrides."""
    settings.slack = {"listener": {"watched_channels": "C1", "watched_keywords": "Foo", "poll_interval_max": 20}}
    FakeSession.replies = {"counts": {"ok": True, "ims": [{"id": "D1"}, {"id": "C1"}]}}
    daemon.options.poll_interval_min = 2.0
    config = await daemon.init_listener_config()
    assert config.watched_channels == ["C1", "D1"]
    assert config.watched_keywords == ["foo"]
    assert (config.poll_interval_min, config.poll_interval_max) == (2.0, 20)


async def test_auth_success_and_retry(daemon, settings, monkeypatch):
    """Sign-in uses configured credentials and retries once after a refresh."""
    settings.slack = {"auth": {"xoxc_token": "t", "d_cookie": "c"}}
    refresh = mock.Mock(return_value=True)
    monkeypatch.setattr(daemon_startup, "refresh_slack_credentials", refresh)
    FakeSession.replies = {"validate": [ValueError("expired"), {"user": "dave"}]}
    assert await daemon.init_slack_auth() is True
    assert daemon.conn.session.kwargs["xoxc_token"] == "t"
    refresh.assert_called_once()


async def test_auth_missing_credentials(daemon, monkeypatch):
    """Missing credentials fail after one refresh attempt."""
    monkeypatch.setattr(daemon_startup, "refresh_slack_credentials", mock.Mock(return_value=False))
    assert await daemon.init_slack_auth() is False


# ---------------------------------------------------------------- message handling


async def test_message_reply_in_thread(daemon):
    """A normal allowed message gets a threaded reply and is marked processed."""
    daemon.parts.channel_permissions.should_respond = mock.Mock(return_value=(True, ""))
    await daemon.process_message(_msg())
    assert daemon.conn.session.sent == [
        {"channel_id": "C1", "text": "reply", "thread_ts": "100.1", "typing_delay": True}
    ]
    daemon.conn.state_db.set_last_processed_ts.assert_awaited_once_with("C1", "200.0", "general")
    daemon.conn.state_db.mark_message_processed.assert_awaited_once_with("m1")


async def test_message_not_allowed_is_recorded_skipped(daemon):
    """A reply the channel rules forbid is recorded as skipped and not sent."""
    daemon.parts.channel_permissions.should_respond = mock.Mock(return_value=(False, "muted"))
    handler = mock.MagicMock()
    vars(daemon)["_dbus_handler"] = handler
    await daemon.process_message(_msg())
    assert not daemon.conn.session.sent
    record = handler.history.add.call_args.args[0]
    assert record.status == "skipped"


async def test_debug_mode_redirects_reply(daemon):
    """Debug mode sends replies to the self-DM with a header and no thread."""
    daemon.options.debug_mode = True
    daemon.options.debug_redirect_channel = "D9"
    daemon.parts.channel_permissions.should_respond = mock.Mock(return_value=(True, ""))
    await daemon.process_message(_msg(channel_id="D2"))
    sent = daemon.conn.session.sent[0]
    assert (sent["channel_id"], sent["thread_ts"]) == ("D9", None)
    assert sent["text"].startswith("🐛 *DEBUG MODE* - Would have sent to #general")


async def test_alert_is_investigated(daemon):
    """Auto-investigated alerts go to Claude and skip the normal reply."""
    detector = daemon.parts.alert_detector
    detector.is_alert_message = mock.Mock(return_value=True)
    detector.get_alert_info = mock.Mock(return_value="prod")
    detector.should_auto_investigate = mock.Mock(return_value=True)
    await daemon.process_message(_msg(text="FIRING"))
    prompt = daemon.parts.response_generator.claude_agent.process_message.call_args.args[0]
    assert "from the unknown environment" in prompt
    assert 'thread_ts: "100.1"' in prompt
    daemon.parts.response_generator.generate.assert_not_awaited()


async def test_command_message(daemon):
    """@me commands are answered by the command handler."""
    handler = mock.MagicMock()
    handler.is_command.return_value = True
    handler.handle = mock.AsyncMock(return_value=("done", True))
    daemon.conn.command_handler = handler
    await daemon.process_message(_msg(channel_id="D3"))
    assert daemon.conn.session.sent[0]["text"] == "done"
    daemon.parts.response_generator.generate.assert_not_awaited()


def test_alert_helpers():
    """Alert info is always a dict and the prompt names the reply target."""
    assert not daemon_messages.as_alert_info(None)
    assert daemon_messages.as_alert_info("stage") == {"environment": "stage"}
    prompt = daemon_messages.alert_prompt(_msg(), {"environment": "e"}, "D9", None, "PFX")
    assert "null (no threading)" in prompt
    assert '- text: "PFX" + (your' in prompt


# ---------------------------------------------------------------- daemon


async def test_health_and_stats(daemon):
    """Health reflects the listener and connections; stats read the listener."""
    daemon.conn.listener = mock.MagicMock(is_running=True, stats={"polls": 3})
    daemon.conn.state_db.get_pending_messages = mock.AsyncMock(return_value=[1, 2])
    health = await daemon.health_check()
    assert health["checks"]["listener_active"] is True
    stats = await daemon.get_service_stats()
    assert (stats["polls"], stats["messages_pending"], stats["listener_running"]) == (3, 2, True)


def test_constructor_options_and_status(daemon, capsys):
    """Keyword options land in SlackDaemonOptions; the start-up summary prints them."""
    assert SlackDaemon(dry_run=True, poll_interval_max=30.0).options.poll_interval_max == 30.0
    daemon.options.dry_run = True
    _private(daemon, "_print_startup_status")(
        SimpleNamespace(watched_channels=["D1", "G2", "C3"], watched_keywords=[], self_dm_channel="")
    )
    out = capsys.readouterr().out
    assert "1 channels, 1 DMs, 1 group DMs (MPDMs)" in out
    assert "DRY RUN MODE" in out
    with pytest.raises(TypeError):
        SlackDaemon(bogus=True)


# ---------------------------------------------------------------- response builder


def test_modulate_response_truncates_long_replies():
    """Replies over the classification limit are cut with a truncation note."""
    limited = SimpleNamespace(max_response_length=100)
    assert response_builder.ResponseGenerator.modulate_response("x" * 150, limited) == "x" * 50 + "\n\n_...truncated_"
    assert response_builder.ResponseGenerator.modulate_response("short", limited) == "short"
    assert response_builder.ResponseGenerator.modulate_response(None, limited) is None


async def test_generate_is_silent_on_claude_errors():
    """A failing Claude call yields no reply instead of an error message."""
    generator = object.__new__(response_builder.ResponseGenerator)
    generator.notifier = response_builder.DesktopNotifier(enabled=False)
    generator.claude_agent = mock.MagicMock(process_message=mock.AsyncMock(side_effect=RuntimeError("down")))
    classification = mock.MagicMock(max_response_length=0, auto_respond=True, require_review=False)
    assert await generator.generate(_msg(), classification) == (None, False)

    generator.claude_agent.process_message = mock.AsyncMock(return_value="hi")
    assert await generator.generate(_msg(thread_ts="9.9"), classification) == ("hi", True)
    assert generator.claude_agent.process_message.call_args.kwargs["conversation_id"] == "C1:9.9"


def test_notifier_rate_limit_and_send(monkeypatch):
    """Notifications go through libnotify until the per-window limit is reached."""
    notify = mock.MagicMock()
    monkeypatch.setattr(response_builder, "_NOTIFY", notify)
    notifier = response_builder.DesktopNotifier(enabled=False)
    notifier.enabled = True
    for _ in range(notifier.RATE_LIMIT_MAX + 2):
        notifier.error("boom")
    assert notify.Notification.new.call_count == notifier.RATE_LIMIT_MAX
