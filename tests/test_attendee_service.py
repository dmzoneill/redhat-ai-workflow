"""Tests for the meet-bot attendee service: wire compatibility and IPC behaviour."""

import asyncio
import dataclasses
import json
from types import SimpleNamespace

import pytest

from tool_modules.aa_meet_bot.src import attendee_service
from tool_modules.aa_meet_bot.src.attendee_service import (
    AttendeeDataClient,
    AttendeeDataService,
    EnrichedAttendee,
    MeetingState,
)


def _legacy_post_init(self):
    """Same rules as the original EnrichedAttendee.__post_init__."""
    words = self.name.split()[:2] if self.name else []
    self.initials = self.initials or "".join(w[0].upper() for w in words if w)
    self.color_hue = self.color_hue or hash(self.name) % 360


# The original @dataclass EnrichedAttendee, rebuilt field-for-field as the reference.
LegacyAttendee = dataclasses.make_dataclass(
    "EnrichedAttendee",
    [
        ("name", str),
        ("email", "str | None", None),
        ("github_username", "str | None", None),
        ("slack_id", "str | None", None),
        ("team", "str | None", None),
        ("role", "str | None", None),
        ("photo_path", "str | None", None),
        ("display_name", "str | None", None),
        ("initials", str, ""),
        ("color_hue", int, 0),
    ],
    namespace={"__post_init__": _legacy_post_init},
)

FULL = {
    "name": "Ada Lovelace",
    "email": "ada@example.com",
    "github_username": "ada",
    "slack_id": "U123",
    "team": "Engines",
    "role": "Analyst",
    "photo_path": "/tmp/ada.png",
    "display_name": "Ada",
    "initials": "AL",
    "color_hue": 42,
}

CASES = [
    ((), {"name": "Ada Lovelace"}),
    ((), {"name": "Ada Lovelace", "email": "ada@example.com"}),
    ((), dict(FULL)),
    ((), {"name": "", "color_hue": 7}),
    ((), {"name": "single", "initials": "", "color_hue": 0}),
    (("Grace Brewster Hopper", "g@example.com"), {"team": "Navy"}),
    (tuple(FULL.values()), {}),
]


@pytest.mark.parametrize(("args", "kwargs"), CASES)
def test_serialization_matches_legacy_dataclass(args, kwargs):
    """to_dict(), its JSON bytes, repr and attributes match the old dataclass exactly."""
    new = EnrichedAttendee(*args, **kwargs)
    old = LegacyAttendee(*args, **kwargs)
    assert new.to_dict() == dataclasses.asdict(old)
    assert json.dumps(new.to_dict()).encode() == json.dumps(dataclasses.asdict(old)).encode()
    assert list(new.to_dict()) == [f.name for f in dataclasses.fields(old)]
    assert repr(new) == repr(old)
    for name in EnrichedAttendee.FIELDS:
        assert getattr(new, name) == getattr(old, name)


def test_wire_round_trip_is_byte_identical():
    """A serialized attendee rebuilt with EnrichedAttendee(**data) re-serializes identically."""
    wire = json.dumps(EnrichedAttendee(**FULL).to_dict())
    assert wire == json.dumps(FULL)
    assert json.dumps(EnrichedAttendee(**json.loads(wire)).to_dict()) == wire


def test_attribute_setters_and_equality():
    """Fields are writable as before, and equality/hashing follow dataclass rules."""
    new, old = EnrichedAttendee(name="Ada Lovelace"), LegacyAttendee(name="Ada Lovelace")
    for name, value in FULL.items():
        setattr(new, name, value)
        setattr(old, name, value)
    assert new.to_dict() == dataclasses.asdict(old) == FULL
    assert new == EnrichedAttendee(**FULL)
    assert new != EnrichedAttendee(name="Other")
    assert new != FULL
    with pytest.raises(TypeError):
        hash(new)
    with pytest.raises(TypeError):
        hash(old)


@pytest.mark.parametrize(
    ("args", "kwargs"),
    [
        ((), {}),
        ((), {"name": "x", "unknown": 1}),
        (("x",), {"name": "y"}),
        (tuple(range(11)), {}),
    ],
)
def test_constructor_errors_match_legacy(args, kwargs):
    """Bad constructor calls raise TypeError, as the dataclass did."""
    with pytest.raises(TypeError):
        LegacyAttendee(*args, **kwargs)
    with pytest.raises(TypeError):
        EnrichedAttendee(*args, **kwargs)


def test_meeting_state_to_dict():
    """MeetingState serializes attendees through the compatible to_dict."""
    state = MeetingState(status="active", attendees=[EnrichedAttendee(**FULL)], meeting_title="T")
    assert state.to_dict()["attendees"] == [FULL]
    assert state.to_dict()["meeting_title"] == "T"


def _writer():
    """A stream writer stub that records what is written."""
    sent: list[bytes] = []

    async def drain():
        return None

    return SimpleNamespace(write=sent.append, drain=drain, sent=sent)


async def test_update_participants_carries_enrichment_and_broadcasts():
    """Known names keep enrichment; clients receive the attendee list."""
    service = AttendeeDataService()
    writer = _writer()
    vars(service)["_io"].clients.append(writer)
    service.get_state().attendees = [EnrichedAttendee(**FULL)]

    await service.update_participants([{"name": "Ada Lovelace"}, {"name": "New Person"}], enrich=False)

    attendees = service.get_state().attendees
    assert attendees[0].team == "Engines"
    assert attendees[0].slack_id == "U123"
    assert attendees[1].team is None
    assert service.get_state().status == "active"
    message = json.loads(writer.sent[-1])
    assert message["type"] == "attendees_update"
    assert [a["name"] for a in message["attendees"]] == ["Ada Lovelace", "New Person"]


async def test_background_enrichment_task_is_kept_and_applied():
    """Enrichment runs in a referenced background task and broadcasts each result."""
    service = AttendeeDataService()
    writer = _writer()
    vars(service)["_io"].clients.append(writer)

    async def enrich(attendee):
        attendee.team = "Enriched"
        return attendee

    vars(service)["_enricher"] = SimpleNamespace(enrich=enrich)
    await service.update_participants([{"name": "Ada Lovelace"}])
    tasks = set(vars(service)["_tasks"])
    assert tasks
    await asyncio.wait(tasks)
    assert service.get_state().attendees[0].team == "Enriched"
    assert json.loads(writer.sent[-1])["type"] == "attendee_enriched"
    assert not vars(service)["_tasks"]


async def test_polling_stops_cleanly():
    """stop_periodic_polling cancels the loop and clears the task."""
    service = AttendeeDataService()
    vars(service)["_io"].running = True

    async def poll():
        return []

    await service.start_periodic_polling(poll, interval=60, duration=600)
    assert service.is_polling()
    assert service.get_polling_status()["active"]
    await service.stop_periodic_polling()
    assert not service.is_polling()
    assert service.get_polling_status() == {"active": False, "elapsed": 0, "remaining": 0}


async def test_client_handles_server_messages():
    """The client applies each server message type and fires callbacks."""
    client = AttendeeDataClient()
    seen = {}
    client.on_attendees_update(lambda a: seen.setdefault("attendees", a))
    client.on_status_change(lambda s: seen.setdefault("status", s))
    client.on_attendee_enriched(lambda i, a: seen.setdefault("enriched", (i, a)))
    handle = vars(AttendeeDataClient)["_handle_message"]

    await handle(client, json.dumps({"type": "attendees_update", "attendees": [FULL], "current_index": 0}))
    await handle(client, json.dumps({"type": "meeting_status", "status": "active", "video_device": "/dev/v"}))
    await handle(client, json.dumps({"type": "attendee_enriched", "index": 0, "data": dict(FULL, team="X")}))
    await handle(client, json.dumps({"type": "keepalive"}))
    await handle(client, "not json")
    await handle(client, json.dumps({"type": "attendees_update", "attendees": [{"bogus": 1}]}))

    assert [a.name for a in seen["attendees"]] == ["Ada Lovelace"]
    assert seen["status"] == "active"
    assert seen["enriched"][1].team == "X"
    assert client.get_current_attendee().team == "X"
    assert client.get_video_device() == "/dev/v"

    state = MeetingState(status="ended", attendees=[EnrichedAttendee(**FULL)], audio_source="mon")
    await handle(client, json.dumps({"type": "full_state", "state": state.to_dict()}))
    assert client.get_state().status == "ended"
    assert client.get_audio_source() == "mon"
    assert client.get_attendees() == [EnrichedAttendee(**FULL)]


async def test_client_receive_loop_cancels_cleanly():
    """disconnect() cancels the receive loop and marks the client disconnected."""
    client = AttendeeDataClient()
    reader = asyncio.StreamReader()
    vars(client)["_reader"] = reader
    vars(client)["_connected"] = True
    vars(client)["_receive_task"] = asyncio.create_task(vars(AttendeeDataClient)["_receive_loop"](client))
    await asyncio.sleep(0)
    await client.disconnect()
    assert not client.is_connected()


async def test_get_service_is_a_singleton():
    """get_service returns one shared instance."""
    first = await attendee_service.get_service()
    assert await attendee_service.get_service() is first
