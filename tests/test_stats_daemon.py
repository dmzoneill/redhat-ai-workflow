"""Tests for the stats daemon and its handler mixins (services/stats)."""

import base64
import json
import os
import stat
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.stats import daemon as daemon_module
from services.stats import executive_emails, issue_hierarchy, report_export
from services.stats.daemon import StatsDaemon, apply_scoring_updates
from services.stats.day_detail import classify_match_reason, issue_lineage
from services.stats.executive_emails import (
    GmailBackfill,
    backfill_window,
    flat_message_body,
    map_issues_to_email,
    nested_message_body,
)
from services.stats.handler_utils import (
    category_points,
    load_daily_files,
    quarter_end,
    quarter_of,
    quarter_start,
    today_local,
    weekdays_between,
)
from services.stats.issue_hierarchy import build_tree, parse_epic, parse_fields, parse_issue
from services.stats.quarter_data import captured_day, sum_daily_points

EXPECTED_DBUS_METHODS = {
    "get_state",
    "get_agent_stats",
    "get_inference_stats",
    "get_skill_execution",
    "collect_daily",
    "backfill",
    "evaluate_all",
    "get_scoring_config",
    "set_scoring_config",
    "reset_scoring_config",
    "get_captured_days",
    "get_issue_hierarchy",
    "export_report",
    "get_day_detail",
    "get_competency_evidence",
    "parse_executive_email",
    "map_deliverables",
    "list_executive_emails",
    "delete_executive_email",
    "search_executive_gmail",
    "read_gmail_message",
    "backfill_executive_emails",
}


class FakeCollector:
    """DataCollector stand-in rooted in a temp dir."""

    def __init__(self, root: Path):
        self.root = root
        self.collected: list[date] = []

    def get_perf_dir(self, year=None, quarter=None) -> Path:
        """Perf dir for any quarter."""
        del year, quarter
        return self.root / "perf"

    def get_daily_dir(self, year=None, quarter=None) -> Path:
        """Daily dir for any quarter."""
        del year, quarter
        return self.root / "perf" / "daily"

    def collect_for_date(self, day: date) -> dict:
        """Pretend to collect one day; fail on the 3rd."""
        self.collected.append(day)
        if day.day == 3:
            raise OSError("collector failed")
        return {"events": [{}, {}], "daily_total": 4}


def _event(title: str, points: dict | None = None, source: str = "github", ev_type: str = "pr") -> dict:
    return {"title": title, "source": source, "type": ev_type, "points": points or {"collaboration": 3}, "url": "u"}


@pytest.fixture(name="daemon")
def daemon_fixture(tmp_path: Path) -> StatsDaemon:
    """StatsDaemon with D-Bus off and its data under tmp_path."""
    d = StatsDaemon(enable_dbus=False)
    d.__dict__["_collector"] = FakeCollector(tmp_path)
    daily = tmp_path / "perf" / "daily"
    daily.mkdir(parents=True)
    first = today_local().replace(day=1)
    (daily / f"{first.isoformat()}.json").write_text(
        json.dumps(
            {
                "date": first.isoformat(),
                "events": [
                    _event("AAP-1 fix billing api"),
                    _event("AAP-2 review docs", {"collaboration": 2, "technical_contribution": 1}, "slack", "msg"),
                    _event("ANSTRAT-9 strategy"),
                ],
                "daily_points": {"collaboration": 8, "technical_contribution": 1},
                "daily_total": 9,
            }
        ),
        encoding="utf-8",
    )
    (daily / "2099-01-01.json").write_text("{not json", encoding="utf-8")
    return d


def _handler(d: StatsDaemon, name: str):
    return d.__dict__["_custom_handlers"][name]


# ==================== StatsDaemon ====================


def test_dbus_method_names_unchanged(daemon):
    """Every D-Bus method from before the split is still registered."""
    assert set(daemon.__dict__["_custom_handlers"]) == EXPECTED_DBUS_METHODS


def test_apply_scoring_updates_merges_known_competencies():
    """Integer keys are coerced and unknown competencies ignored."""
    current: dict = {}
    apply_scoring_updates(
        current, {"daily_cap": "4", "competencies": {"collaboration": {"base_points": "2", "x": 1}, "nope": {}}}
    )
    assert current == {"daily_cap": 4, "competencies": {"collaboration": {"base_points": 2}}}


async def test_backfill_reports_failed_days(daemon):
    """A collector error marks that day failed without stopping the backfill."""
    result = await _handler(daemon, "backfill")()
    today = today_local()
    assert result["processed"] == len(weekdays_between(quarter_start(today.year, quarter_of(today)), today))
    failed = [r for r in result["results"] if not r["success"]]
    assert all(r["error"] == "collector failed" for r in failed)


async def test_collect_daily_error_is_returned(daemon):
    """collect_daily returns the collector error instead of raising."""
    result = await _handler(daemon, "collect_daily")(date=today_local().replace(day=3).isoformat())
    assert result == {"success": False, "error": "collector failed"}


async def test_evaluate_all_rescores_readable_files(daemon, monkeypatch):
    """Only parseable daily files are rewritten."""
    monkeypatch.setattr(daemon_module, "map_competencies", lambda *_: {"collaboration": 1})
    result = await _handler(daemon, "evaluate_all")()
    assert result["files_updated"] == 1


# ==================== QuarterDataMixin ====================


def test_sum_daily_points_skips_unreadable_files(daemon):
    """Bad JSON files are skipped when summing points."""
    points, total_events, highlights = sum_daily_points(daemon.daily_dir())
    assert points == {"collaboration": 8, "technical_contribution": 1}
    assert total_events == 3
    assert highlights[0] == "AAP-1 fix billing api"


def test_captured_day_for_unreadable_file():
    """An unreadable file still shows up as an empty day."""
    assert captured_day(Path("2026-01-05.json"), None)["event_count"] == 0


async def test_captured_days_coverage(daemon):
    """Both files are listed and coverage is computed from weekdays."""
    result = await _handler(daemon, "get_captured_days")()
    assert [d["date"] for d in result["days"]][1] == "2099-01-01"
    assert result["coverage"]["captured"] == 2


def test_load_file_caches_and_falls_back(daemon, tmp_path):
    """load_file caches by mtime and returns the cached copy if the file breaks."""
    path = tmp_path / "x.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    assert daemon.load_file(path) == {"a": 1}
    path.write_text("{broken", encoding="utf-8")
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 10))
    assert daemon.load_file(path) == {"a": 1}
    assert daemon.load_file(tmp_path / "missing.json") is None


def test_update_summary_writes_summary(daemon):
    """update_summary writes summary.json with cumulative points."""
    summary = daemon.update_summary()
    assert summary["cumulative_points"]["collaboration"] == 8
    assert (daemon.perf_dir() / "summary.json").exists()


# ==================== handler_utils ====================


def test_quarter_bounds():
    """Quarter start and end dates."""
    assert quarter_start(2026, 4) == date(2026, 10, 1)
    assert quarter_end(2026, 1) == date(2026, 3, 31)
    assert quarter_end(2026, 4) == date(2026, 12, 31)


def test_weekdays_between_skips_weekend():
    """Saturday and Sunday are excluded."""
    assert weekdays_between(date(2026, 10, 30), date(2026, 11, 2)) == [date(2026, 10, 30), date(2026, 11, 2)]


def test_load_daily_files_marks_bad_files(tmp_path):
    """Unparsable or non-object files load as None."""
    (tmp_path / "a.json").write_text("[1]", encoding="utf-8")
    (tmp_path / "b.json").write_text("{", encoding="utf-8")
    assert [data for _, data in load_daily_files(tmp_path)] == [None, None]
    assert not load_daily_files(tmp_path / "missing")


def test_category_points_groups_by_category():
    """Unknown competencies fall into Other."""
    assert category_points({"unknown_comp": 2})["Other"] == 2


# ==================== IssueHierarchyMixin ====================


def test_parse_fields_matches_first_colon():
    """Field names stop at the first colon; values keep later colons."""
    assert parse_fields("Summary : a: b\nnot a field\nComponent/s: X") == [("summary", "a: b"), ("component/s", "X")]


def test_parse_issue_and_epic():
    """Issue fields, epic link and the fallback summary."""
    info = parse_issue("AAP-1", "Summary: S\nIssue Type: Bug\nEpic Link: AAP-100\nComponent/s: C")
    assert info == {
        "key": "AAP-1",
        "type": "story",
        "summary": "S",
        "issue_type": "Bug",
        "epic": "AAP-100",
        "component": "C",
    }
    assert parse_issue("AAP-2", "AAP-2: Hello")["summary"] == "Hello"
    assert parse_epic("AAP-100", "Summary: E\nStatus: x") == {"key": "AAP-100", "issue_type": "Epic", "summary": "E"}


def test_build_tree_groups_by_strategy_and_epic():
    """Issues go under epics, epics under ANSTRATs; the rest are uncategorized."""
    keys = {
        "AAP-1": {"points": 3, "titles": ["fix api"], "event_count": 1},
        "AAP-2": {"points": 1, "titles": ["docs"], "event_count": 1},
    }
    info = {"AAP-1": {"epic": "AAP-100"}, "AAP-100": {"summary": "E", "parent_initiative": "ANSTRAT-9"}}
    tree = build_tree(keys, info)
    assert tree["strategies"][0]["key"] == "ANSTRAT-9"
    assert tree["strategies"][0]["children"][0]["children"][0]["keywords"] == ["api", "fix"]
    assert [n["key"] for n in tree["uncategorized"]] == ["AAP-2"]


async def test_run_rh_issue_errors(tmp_path, monkeypatch):
    """Non-zero exit and timeouts raise RhIssueError."""
    script = tmp_path / "rh-issue"
    script.write_text('#!/bin/sh\n[ "$1" = slow ] && sleep 5\n[ "$1" = fail ] && exit 2\necho ok\n', encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    monkeypatch.setenv("PATH", env["PATH"])
    assert (await issue_hierarchy.run_rh_issue(["ok"], 5, env)).strip() == "ok"
    with pytest.raises(issue_hierarchy.RhIssueError):
        await issue_hierarchy.run_rh_issue(["fail"], 5, env)
    with pytest.raises(issue_hierarchy.RhIssueError):
        await issue_hierarchy.run_rh_issue(["slow"], 0.2, env)


async def test_issue_hierarchy_from_daily_data(daemon):
    """Without Jira, issues are uncategorized and ANSTRATs are strategies."""
    result = await _handler(daemon, "get_issue_hierarchy")()
    assert result["total_issues"] == 3
    assert result["cached"] is False
    assert [s["key"] for s in result["strategies"]] == ["ANSTRAT-9"]


# ==================== DayDetailMixin ====================


def test_classify_match_reason_default():
    """No signal falls back to 'pattern match'."""
    assert classify_match_reason("zzz", "x", "y", "no_such_competency") == "pattern match"


def test_issue_lineage_walks_epic_and_anstrat():
    """Lineage includes the epic and its ANSTRAT."""
    info = {"AAP-1": {"epic": "AAP-100"}, "AAP-100": {"summary": "E", "parent_initiative": "ANSTRAT-9"}}
    assert issue_lineage("AAP-1", info)["anstrat"] == {"key": "ANSTRAT-9", "summary": ""}


async def test_day_detail(daemon):
    """Events get issue keys and lineage; bad input is reported."""
    first = today_local().replace(day=1).isoformat()
    result = await _handler(daemon, "get_day_detail")(date=first)
    assert result["events"][0]["issue_keys"] == ["AAP-1"]
    assert (await _handler(daemon, "get_day_detail")(date="bad"))["success"] is False
    assert (await _handler(daemon, "get_day_detail")(date="2001-01-01"))["has_data"] is False


async def test_competency_evidence(daemon):
    """Evidence and totals are per competency."""
    result = await _handler(daemon, "get_competency_evidence")()
    assert result["competency_totals"]["collaboration"] == 8
    assert len(result["competency_evidence"]["collaboration"]) == 3


# ==================== ExecutiveEmailMixin ====================


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def test_message_bodies():
    """Plain text wins over HTML; nested parts are searched depth-first."""
    payload = {
        "parts": [
            {"mimeType": "text/html", "body": {"data": _b64("<p>Hi <b>there</b></p>")}},
            {"mimeType": "text/plain", "body": {"data": _b64("plain")}},
        ]
    }
    assert flat_message_body(payload) == "plain"
    nested = {"mimeType": "multipart", "parts": [{"mimeType": "multipart", "parts": payload["parts"][:1]}]}
    assert nested_message_body(nested) == "Hi there"


def test_backfill_window_q4():
    """Q4 runs to Jan 1 of the next year or tomorrow, whichever is first."""
    assert backfill_window(date(2026, 12, 31), 2026, 4) == (date(2026, 10, 1), date(2027, 1, 1))
    assert backfill_window(date(2026, 10, 5), 2026, 4)[1] == date(2026, 10, 6)


def test_map_issues_to_email_match_order():
    """Direct keys, then ANSTRAT links, then themes; each issue maps once."""
    parsed = {
        "issue_keys": {"AAP-1": ["ctx"], "ANSTRAT-9": []},
        "themes": [{"name": "T", "matched_keywords": ["docs"]}],
    }
    user_issues = {
        "AAP-1": {"parent_anstrat": "ANSTRAT-9"},
        "AAP-2": {"parent_anstrat": "ANSTRAT-9"},
        "AAP-3": {"keywords": ["docs"]},
    }
    kinds = [(m["user_issue"], m["match_type"]) for m in map_issues_to_email(parsed, user_issues)]
    assert kinds == [("AAP-1", "direct_key"), ("AAP-2", "anstrat_link"), ("AAP-3", "theme")]


async def test_parse_list_map_delete_email(daemon):
    """Round trip through the email cache handlers."""
    parsed = await _handler(daemon, "parse_executive_email")(text="Ship AAP-1 now", email_id="e1")
    assert parsed["email_id"] == "e1"
    emails = (await _handler(daemon, "list_executive_emails")())["emails"]
    assert [e["email_id"] for e in emails] == ["e1"]
    mapped = await _handler(daemon, "map_deliverables")()
    assert mapped["email_id"] == "e1"
    assert (await _handler(daemon, "delete_executive_email")(email_id="e1"))["deleted"] == "e1"
    assert (await _handler(daemon, "map_deliverables")(email_id="e1"))["success"] is False


async def test_gmail_unavailable(daemon, monkeypatch):
    """Without the Gmail module, the Gmail handlers say so."""
    monkeypatch.setattr(executive_emails, "gmail_service", lambda: (None, "Gmail module not available"))
    result = await _handler(daemon, "read_gmail_message")(message_id="m")
    assert result == {"success": False, "error": "Gmail module not available"}


def _request(value):
    """Canned Gmail API request whose execute() returns or raises *value*."""

    def execute():
        if isinstance(value, Exception):
            raise value
        return value

    return SimpleNamespace(execute=execute)


class _Messages:
    def list(self, **kwargs):
        """One page per sender; 'bad' senders fail."""
        if "bad" in kwargs["q"]:
            return _request(ValueError("api down"))
        return _request({"messages": [{"id": "old"}, {"id": "new"}]})

    def get(self, **kwargs):
        """A message with a plain-text body."""
        del kwargs
        return _request(
            {
                "payload": {
                    "headers": [{"name": "Subject", "value": "S"}],
                    "mimeType": "text/plain",
                    "body": {"data": _b64("Body")},
                }
            }
        )


def test_gmail_backfill_counts_and_errors(tmp_path):
    """Known messages are skipped, new ones cached, and API errors recorded per sender."""
    (tmp_path / "x.json").write_text(json.dumps({"gmail_message_id": "old"}), encoding="utf-8")
    service = SimpleNamespace(users=lambda: SimpleNamespace(messages=_Messages))
    backfill = GmailBackfill(service, tmp_path, (date(2026, 10, 1), date(2026, 11, 1)))
    backfill.run(["boss@x", "bad@x"])
    assert backfill.totals == {"new": 1, "skipped": 1}
    assert backfill.sender_results[1] == {"sender": "bad@x", "error": "api down"}


# ==================== ReportExporter ====================


async def test_export_markdown_and_json(daemon):
    """Markdown is the default format; JSON includes every event."""
    md = await _handler(daemon, "export_report")()
    assert md["format"] == "markdown"
    assert Path(md["path"]).read_text(encoding="utf-8").startswith("# Q")
    js = await _handler(daemon, "export_report")(format="json")
    assert json.loads(Path(js["path"]).read_text(encoding="utf-8"))["total_events"] == 3


async def test_export_pdf_gathers_template_data(daemon, monkeypatch):
    """PDF export collects hierarchy, evidence and days for the template."""
    seen: dict = {}

    def fake_render(data, template, output):
        seen.update(data, template=template.name)
        return str(output)

    monkeypatch.setattr(report_export, "render_pdf", fake_render)
    result = await _handler(daemon, "export_report")(format="pdf")
    assert result["format"] == "pdf"
    assert seen["template"] == "report_template.html"
    assert seen["days_captured"] == 2
    assert seen["total_issues"] == 3
