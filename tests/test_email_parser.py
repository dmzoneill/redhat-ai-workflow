"""Tests for services.stats.email_parser."""

import base64
import json
import time
from datetime import date
from types import SimpleNamespace

import pytest

from services.stats import email_parser

SAMPLE = (
    "Jane Exec <jane@redhat.com>\n"
    "Executive Summary\n"
    "We shipped AAP-123 and [Build in 24] work on konflux pipeline.\n\n"
    "AI\n"
    "[Python 3.12] upgrade django CAP-77 lightspeed\n"
)


def _b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode()


def test_parse_email_text_structure():
    """Keys, priorities, sections, themes and sender are extracted."""
    parsed = email_parser.parse_email_text(SAMPLE)
    assert parsed["sender"] == "Jane Exec"
    assert set(parsed["issue_keys"]) == {"AAP-123", "CAP-77"}
    assert [p["name"] for p in parsed["priorities"]] == ["Build in 24", "Python 3.12"]
    assert [s["header"] for s in parsed["sections"]] == ["Executive Summary", "AI"]
    assert parsed["sections"][1]["issue_keys"] == ["CAP-77"]
    assert parsed["themes"][0]["strength"] >= parsed["themes"][-1]["strength"]
    assert parsed["total_sections"] == 2


@pytest.mark.parametrize(
    ("text", "sender"),
    [
        ("Bob <b@c>", "Bob"),
        ("Bob\n<b@c>", "Bob"),
        ("A < x <b@c>", "A"),
        ("<a@b> rest", ""),
        ("Bob <> <b@c>", "Bob <>"),
        ("no address", ""),
        ("Name <unclosed", ""),
        ("", ""),
    ],
)
def test_leading_sender_matches_previous_regex(text, sender):
    """The single-pass sender scan gives the old regex's results."""
    assert email_parser.parse_email_text(text)["sender"] == sender


def test_leading_sender_is_fast_on_hostile_input():
    """A long first line with no address doesn't backtrack."""
    start = time.perf_counter()
    assert email_parser.parse_email_text("a" + " " * 50000 + "<")["sender"] == ""
    assert time.perf_counter() - start < 1.0


@pytest.mark.parametrize(
    ("payload", "body"),
    [
        (
            {
                "parts": [
                    {"mimeType": "text/html", "body": {"data": _b64("<p>H</p>")}},
                    {"mimeType": "text/plain", "body": {"data": _b64("plain")}},
                ]
            },
            "plain",
        ),
        ({"parts": [{"mimeType": "text/html", "body": {"data": _b64("<p>Hi  <b>there</b></p>")}}]}, "Hi there"),
        ({"parts": [{"mimeType": "image/png"}], "body": {"data": _b64("fallback")}}, "fallback"),
        ({}, ""),
    ],
)
def test_message_body(payload, body):
    """Plain text wins, then stripped HTML, then the payload body."""
    assert vars(email_parser)["_message_body"](payload) == body


def _call(value):
    return SimpleNamespace(execute=lambda: value)


class _FakeGmail:
    """Just enough of the Gmail API client for collect_executive_emails_for_date."""

    def __init__(self, messages):
        self.messages_by_id = messages

    def users(self):
        """Return self for chaining."""
        return self

    def messages(self):
        """Return self for chaining."""
        return self

    def list(self, **kwargs):
        """Return every message id."""
        assert kwargs["q"] == "from:boss@x after:2026-10-30 before:2026-10-31"
        return _call({"messages": [{"id": mid} for mid in self.messages_by_id]})

    def get(self, **kwargs):
        """Return one message."""
        return _call(self.messages_by_id[kwargs["id"]])


def test_collect_executive_emails(tmp_path, monkeypatch):
    """New messages are parsed and cached; cached ones are skipped."""
    message = {"payload": {"headers": [{"name": "Subject", "value": "Weekly"}], "body": {"data": _b64(SAMPLE)}}}
    service = _FakeGmail({"m1": message, "m2": {"payload": {}}})
    monkeypatch.setattr(email_parser, "get_executive_senders", lambda: ["boss@x"])
    monkeypatch.setattr(
        email_parser.importlib, "import_module", lambda name: SimpleNamespace(get_gmail_service=lambda: (service, None))
    )

    new_ids = email_parser.collect_executive_emails_for_date(date(2026, 10, 30), tmp_path)
    assert len(new_ids) == 1
    cached = json.loads((tmp_path / "executive_emails" / f"{new_ids[0]}.json").read_text())
    assert cached["subject"] == "Weekly"
    assert cached["gmail_message_id"] == "m1"
    assert cached["collected_date"] == "2026-10-30"

    assert not email_parser.collect_executive_emails_for_date(date(2026, 10, 30), tmp_path)


def test_collect_skips_without_senders(tmp_path, monkeypatch):
    """No configured senders means nothing is fetched."""
    monkeypatch.setattr(email_parser, "get_executive_senders", list)
    assert not email_parser.collect_executive_emails_for_date(date(2026, 10, 30), tmp_path)
