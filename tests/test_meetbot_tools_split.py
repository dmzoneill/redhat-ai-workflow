"""Tests for the split meet-bot tools modules: registration, shared state and helpers."""

import importlib
import inspect
import sys
import types
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

pytest.importorskip("fastmcp")
pytest.importorskip("googleapiclient")
pytest.importorskip("playwright")

_PKG = "tool_modules.aa_meet_bot.src"
_SPLIT_MODULES = (
    "meet_bot_state",
    "meet_bot_core_tools",
    "meet_notes_tools",
    "meet_notes_maintenance",
    "meet_notes_export",
    "tools_basic",
)

EXPECTED_TOOLS = [
    ("meet_bot_status", ""),
    ("meet_bot_setup_devices", ""),
    ("meet_bot_approve_meeting", "meeting_url, title, start_time"),
    ("meet_bot_join_meeting", "meeting_url, meeting_id"),
    ("meet_bot_leave_meeting", ""),
    ("meet_bot_get_captions", "last_n"),
    ("meet_bot_test_avatar", ""),
    ("meet_bot_synthesize_speech", "text, output_filename"),
    ("meet_bot_generate_video", "audio_path, output_filename"),
    ("meet_bot_respond", "text"),
    ("meet_bot_preload_jira", "project"),
    ("meet_bot_ask_llm", "question, speaker"),
    ("meet_bot_full_response", "question, speaker"),
    ("meet_notes_start_scheduler", ""),
    ("meet_notes_stop_scheduler", ""),
    ("meet_notes_scheduler_status", ""),
    ("meet_notes_add_calendar", "calendar_id, name, auto_join"),
    ("meet_notes_remove_calendar", "calendar_id"),
    ("meet_notes_list_calendars", ""),
    ("meet_notes_join_now", "meet_url, title, duration_minutes, grace_period_minutes"),
    ("meet_notes_leave", "session_id"),
    ("meet_notes_leave_all", ""),
    ("meet_notes_active", ""),
    ("meet_notes_cleanup", ""),
    ("meet_notes_force_cleanup", ""),
    ("meet_notes_cleanup_audio", ""),
    ("meet_notes_cleanup_all_devices", ""),
    ("meet_notes_list_meetings", "days, calendar_id"),
    ("meet_notes_get_transcript", "meeting_id"),
    ("meet_notes_search", "query, meeting_id"),
    ("meet_notes_stats", ""),
    ("meet_notes_export_state", ""),
    ("meet_send_message", "text, session_id"),
    ("meet_voice_pipeline_status", ""),
]


@pytest.fixture(name="mods")
def fixture_mods(monkeypatch):
    """Import the split modules, stubbing voice_pipeline if it cannot be imported."""
    try:
        importlib.import_module("tool_modules.aa_meet_bot.src.voice_pipeline")
    except ValueError:
        stub = types.ModuleType(f"{_PKG}.voice_pipeline")
        stub.get_pipeline_manager = lambda: None
        stub.VoicePipelineConfig = dict
        monkeypatch.setitem(sys.modules, f"{_PKG}.voice_pipeline", stub)
    for name in _SPLIT_MODULES:
        monkeypatch.delitem(sys.modules, f"{_PKG}.{name}", raising=False)
    loaded = SimpleNamespace(
        meet_bot_state=importlib.import_module("tool_modules.aa_meet_bot.src.meet_bot_state"),
        meet_bot_core_tools=importlib.import_module("tool_modules.aa_meet_bot.src.meet_bot_core_tools"),
        meet_notes_tools=importlib.import_module("tool_modules.aa_meet_bot.src.meet_notes_tools"),
        meet_notes_maintenance=importlib.import_module("tool_modules.aa_meet_bot.src.meet_notes_maintenance"),
        meet_notes_export=importlib.import_module("tool_modules.aa_meet_bot.src.meet_notes_export"),
        tools_basic=importlib.import_module("tool_modules.aa_meet_bot.src.tools_basic"),
    )
    state = loaded.meet_bot_state
    monkeypatch.setattr(state, "BOT", state.BOT.__class__())
    monkeypatch.setattr(state, "NOTES", state.NOTES.__class__())
    for name in _SPLIT_MODULES[1:]:
        module = getattr(loaded, name)
        for attr in ("BOT", "NOTES"):
            if hasattr(module, attr):
                monkeypatch.setattr(module, attr, getattr(state, attr))
    return loaded


def _capture_registration(mods, monkeypatch):
    """Run register_tools against a capturing registry; return {name: function}."""
    tools: dict = {}

    def make_registry(_server):
        def tool(**_kwargs):
            def decorator(func):
                tools[func.__name__] = func
                return func

            return decorator

        return SimpleNamespace(tool=tool, count=0)

    async def no_cleanup():
        return None

    tb = mods.tools_basic
    monkeypatch.setattr(tb, "ToolRegistry", make_registry)
    monkeypatch.setattr(tb, "_start_periodic_cleanup", lambda: None)
    monkeypatch.setattr(tb, "_run_startup_cleanup", no_cleanup)
    tb.register_tools(SimpleNamespace())
    return tools


async def test_register_tools_names_order_and_signatures(mods, monkeypatch):
    """All 34 tools register in the original order with unchanged parameters and docstrings."""
    tools = _capture_registration(mods, monkeypatch)
    assert [(name, ", ".join(inspect.signature(func).parameters)) for name, func in tools.items()] == EXPECTED_TOOLS
    assert all(inspect.getdoc(func) for func in tools.values())


async def test_tool_wrappers_forward_arguments(mods, monkeypatch):
    """A registered tool forwards its arguments to its implementation."""
    seen = {}

    async def fake_impl(query, meeting_id):
        seen.update(query=query, meeting_id=meeting_id)
        return "ok"

    monkeypatch.setattr(mods.tools_basic, "_meet_notes_search_impl", fake_impl)
    tools = _capture_registration(mods, monkeypatch)
    assert await tools["meet_notes_search"](query="q") == "ok"
    assert seen == {"query": "q", "meeting_id": 0}


def test_local_now_is_naive_local_time(mods):
    """local_now() matches naive datetime.now() so it compares with stored timestamps."""
    now = mods.meet_bot_state.local_now()
    assert now.tzinfo is None
    assert abs(now - datetime.now(UTC).astimezone().replace(tzinfo=None)) < timedelta(seconds=5)


def test_active_controller_ids(mods):
    """Controller ids are collected through the manager's public API."""
    bots = {
        "a": SimpleNamespace(controller_instance_id=lambda: "meet-bot-1"),
        "b": SimpleNamespace(controller_instance_id=lambda: None),
    }
    mods.meet_bot_state.NOTES.bot_manager = SimpleNamespace(get_active_session_ids=lambda: list(bots), get_bot=bots.get)
    assert mods.meet_bot_state.active_controller_ids() == {"meet-bot-1"}
    mods.meet_bot_state.NOTES.bot_manager = None
    assert not mods.meet_bot_state.active_controller_ids()


@pytest.mark.parametrize(
    ("approved", "url", "meeting_id", "expected"),
    [
        ({}, "", "", ("", "❌ No meeting URL provided and no approved meetings")),
        (
            {"abc-defg-hij": {"url": "https://meet.google.com/abc-defg-hij"}},
            "",
            "",
            ("https://meet.google.com/abc-defg-hij", None),
        ),
        (
            {},
            "",
            "abc-defg-hij",
            (
                "https://meet.google.com/abc-defg-hij",
                "❌ Meeting abc-defg-hij not approved. Use `meet_bot_approve_meeting` first.",
            ),
        ),
        ({}, "https://example.com/x", "", ("https://example.com/x", None)),
    ],
)
def test_resolve_join_url(mods, approved, url, meeting_id, expected):
    """Join URL selection and the approval check behave as before."""
    mods.meet_bot_state.BOT.approved_meetings.update(approved)
    assert vars(mods.meet_bot_core_tools)["_resolve_join_url"](url, meeting_id) == expected


async def test_approve_meeting_caps_list(mods):
    """Approving beyond the limit drops the oldest approvals."""
    state = mods.meet_bot_state
    for i in range(state.MAX_APPROVED_MEETINGS):
        state.BOT.approved_meetings[f"old-{i}"] = {"approved_at": f"2020-01-01T00:00:{i:02d}"}
    result = await vars(mods.meet_bot_core_tools)["_meet_bot_approve_meeting_impl"](
        "https://meet.google.com/abc-defg-hij"
    )
    assert result.startswith("✅ Meeting approved")
    assert len(state.BOT.approved_meetings) == state.MAX_APPROVED_MEETINGS
    assert "old-0" not in state.BOT.approved_meetings
    assert "abc-defg-hij" in state.BOT.approved_meetings


async def test_start_voice_pipeline_without_devices(mods):
    """No pipe or sink means the voice pipeline is reported as failed."""
    controller = SimpleNamespace(get_pipe_path=lambda: None, get_audio_devices=lambda: None)
    status = await vars(mods.meet_bot_core_tools)["_start_voice_pipeline"](controller)
    assert status == "Failed (no audio devices)"


def test_event_meet_url(mods):
    """Only video entry points count as Meet links."""
    meet_url = vars(mods.meet_notes_export)["_event_meet_url"]
    event = {"conferenceData": {"entryPoints": [{"entryPointType": "phone"}, {"entryPointType": "video", "uri": "u"}]}}
    assert meet_url(event) == "u"
    assert meet_url({}) is None


def test_calendar_meetings(mods):
    """Calendar events are mapped to UI entries; events without Meet links are skipped."""
    events = {
        "items": [
            {
                "id": "1",
                "summary": "Standup",
                "start": {"dateTime": "s"},
                "end": {"date": "e"},
                "conferenceData": {"entryPoints": [{"entryPointType": "video", "uri": "u"}]},
                "attendees": [{"email": f"p{i}@x"} for i in range(7)],
            },
            {"id": "2", "start": {}, "end": {}},
        ]
    }
    request = SimpleNamespace(execute=lambda: events)
    service = SimpleNamespace(events=lambda: SimpleNamespace(list=lambda **_kwargs: request))
    cal = SimpleNamespace(calendar_id="c", name="Team", auto_join=True)
    result = vars(mods.meet_notes_export)["_calendar_meetings"](service, cal, "a", "b")
    assert result == [
        {
            "id": "1",
            "title": "Standup",
            "url": "u",
            "startTime": "s",
            "endTime": "e",
            "organizer": "",
            "attendees": [f"p{i}@x" for i in range(5)],
            "status": "pending",
            "calendarName": "Team",
        }
    ]


def test_target_bot(mods):
    """Message target: explicit session, first active session, or an error."""
    target = vars(mods.meet_notes_export)["_target_bot"]
    bot = object()
    manager = SimpleNamespace(get_bot={"s1": bot}.get, get_active_session_ids=lambda: ["s1"])
    assert target(manager, "s1") == (bot, None)
    assert target(manager, "") == (bot, None)
    assert target(manager, "nope") == (None, "❌ Meeting session not found: nope")
    empty = SimpleNamespace(get_bot={}.get, get_active_session_ids=list)
    assert target(empty, "") == (None, "❌ No active meetings. Join a meeting first.")


async def test_cleanup_reports_hung_instances(mods, monkeypatch):
    """meet_notes_cleanup uses the controllers' public timestamps."""
    now = mods.meet_bot_state.local_now()
    controller = SimpleNamespace(
        get_instance_info=lambda: {"browser_pid": 1, "meeting_url": "m"},
        created_at=now - timedelta(minutes=90),
        last_activity=now - timedelta(minutes=45),
    )
    monkeypatch.setattr(
        mods.meet_notes_maintenance.GoogleMeetController, "get_all_instances", staticmethod(lambda: {"i1": controller})
    )
    result = await vars(mods.meet_notes_maintenance)["_meet_notes_cleanup_impl"]()
    assert "🟡 Possibly hung" in result
    assert "1 potentially hung instance(s) found" in result


def test_public_accessors():
    """NotesBot.controller and GoogleMeetController.created_at expose the private fields."""
    notes_bot = importlib.import_module("tool_modules.aa_meet_bot.src.notes_bot")
    browser_controller = importlib.import_module("tool_modules.aa_meet_bot.src.browser_controller")
    bot = notes_bot.NotesBot.__new__(notes_bot.NotesBot)
    vars(bot)["_controller"] = "c"
    assert bot.controller == "c"
    created = object()
    controller = browser_controller.GoogleMeetController.__new__(browser_controller.GoogleMeetController)
    vars(controller)["_created_at"] = created
    assert controller.created_at is created
    assert browser_controller.GoogleMeetController.SELECTORS["leave_button"]
