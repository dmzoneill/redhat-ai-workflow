"""Tests for the meet-bot Jira context preloader."""

import io
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from tool_modules.aa_meet_bot.src import jira_preloader
from tool_modules.aa_meet_bot.src.jira_preloader import JiraIssue, JiraPreloader, get_jira_preloader

_parse_jira_table = vars(jira_preloader)["_parse_jira_table"]
_jira_credentials = vars(jira_preloader)["_jira_credentials"]


def _issue(key="AAP-1", status="Open"):
    return JiraIssue(key, "Summary", status, "Me", "Story", "Major")


def test_parse_pipe_table():
    """Pipe tables: header normalised, separator skipped, rows without key dropped."""
    out = "Key | Status | Story Points\n----|--------|---\nAAP-1 | Open | 3\n | x | y\nFound 1"
    assert _parse_jira_table(out) == [{"key": "AAP-1", "status": "Open", "story_points": "3"}]


def test_parse_space_table():
    """Whitespace-separated tables split on two or more spaces."""
    out = "📊 results\nKey     Summary      Status\nAAP-2   Do thing     Done\n"
    assert _parse_jira_table(out) == [{"key": "AAP-2", "summary": "Do thing", "status": "Done"}]


def test_parse_table_without_header():
    """No recognisable header yields no rows."""
    assert not _parse_jira_table("one\ntwo")
    assert not _parse_jira_table("single")


def test_issue_to_dict_and_defaults():
    """JiraIssue keeps its keyword constructor, defaults and dict format."""
    issue = JiraIssue(key="K", summary="S", status="Open", assignee="A", issue_type="Bug", priority="P", labels=["x"])
    assert issue.to_dict() == {
        "key": "K",
        "summary": "S",
        "status": "Open",
        "assignee": "A",
        "type": "Bug",
        "priority": "P",
        "story_points": None,
        "labels": ["x"],
    }
    assert not _issue().to_dict()["labels"]


def test_parse_issue_handles_dicts_and_strings(monkeypatch):
    """API dict fields and plain strings are both accepted."""
    monkeypatch.setattr(jira_preloader, "get_config", lambda: None)
    preloader = JiraPreloader()
    parse = vars(JiraPreloader)["_parse_issue"]
    issue = parse(
        preloader,
        {
            "key": "AAP-3",
            "fields": {
                "summary": "s",
                "status": {"name": "Open"},
                "assignee": None,
                "issuetype": "Bug",
                "priority": {"name": "High"},
                "customfield_10016": 5,
                "labels": ["a"],
            },
        },
    )
    assert issue == JiraIssue("AAP-3", "s", "Open", "None", "Bug", "High", 5, ["a"])


def test_credentials_from_env_and_config(monkeypatch, tmp_path):
    """JIRA_JPAT wins over JIRA_TOKEN; the config file is the fallback."""
    monkeypatch.setenv("JIRA_URL", "https://j")
    monkeypatch.setenv("JIRA_JPAT", "jpat")
    monkeypatch.setenv("JIRA_TOKEN", "tok")
    assert _jira_credentials() == ("https://j", "jpat")
    monkeypatch.delenv("JIRA_JPAT")
    monkeypatch.delenv("JIRA_TOKEN")
    monkeypatch.setattr(jira_preloader.Path, "home", lambda: tmp_path)
    assert _jira_credentials() == ("https://j", "")
    cfg = tmp_path / ".config" / "jira"
    cfg.mkdir(parents=True)
    (cfg / "config.json").write_text(json.dumps({"token": "t", "url": "https://c"}), encoding="utf-8")
    assert _jira_credentials() == ("https://c", "t")


async def test_jql_search(monkeypatch):
    """The search builds an authorised request and parses the issues."""
    monkeypatch.setattr(jira_preloader, "get_config", lambda: None)
    monkeypatch.setattr(jira_preloader, "_jira_credentials", lambda: ("https://j", "tok"))
    seen = {}

    def fake_open(req, timeout):
        seen.update(url=req.full_url, auth=req.get_header("Authorization"), timeout=timeout)
        body = {"issues": [{"key": "AAP-9", "fields": {"summary": "s", "status": {"name": "Done"}}}]}
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(jira_preloader, "_http_opener", lambda: SimpleNamespace(open=fake_open))
    issues = await vars(JiraPreloader)["_jql_search"](JiraPreloader(), "project = AAP")
    assert [i.key for i in issues] == ["AAP-9"]
    assert seen["url"].startswith("https://j/rest/api/2/search?jql=project+%3D+AAP")
    assert seen["auth"] == "Bearer tok"
    assert seen["timeout"] == 30


async def test_jql_search_errors_return_empty(monkeypatch):
    """Network errors are logged and give no issues; no token gives no request."""
    monkeypatch.setattr(jira_preloader, "get_config", lambda: None)
    monkeypatch.setattr(jira_preloader, "_jira_credentials", lambda: ("https://j", "tok"))

    def fail(*_args, **_kwargs):
        raise jira_preloader.urllib.error.URLError("down")

    monkeypatch.setattr(jira_preloader, "_http_opener", lambda: SimpleNamespace(open=fail))
    assert not await vars(JiraPreloader)["_jql_search"](JiraPreloader(), "x")
    monkeypatch.setattr(jira_preloader, "_jira_credentials", lambda: ("https://j", ""))
    assert not await vars(JiraPreloader)["_jql_search"](JiraPreloader(), "x")


async def test_preload_updates_responder(monkeypatch):
    """preload() stores the issues, pushes context to the responder and stamps the refresh."""
    monkeypatch.setattr(jira_preloader, "get_config", lambda: None)
    updates = {}
    responder = SimpleNamespace(update_jira_context=lambda **kw: updates.update(kw), jira_context=SimpleNamespace())
    monkeypatch.setattr(jira_preloader, "get_llm_responder", lambda: responder)
    preloader = JiraPreloader()

    async def fake_search(jql):
        return [_issue("AAP-1" if "currentUser" in jql else "AAP-2")]

    monkeypatch.setattr(preloader, "_jql_search", fake_search)
    assert await preloader.preload("XYZ")
    assert [i.key for i in preloader.my_issues] == ["AAP-1"]
    assert updates["issues"][0]["key"] == "AAP-2"
    assert preloader.last_refresh is not None
    assert not await preloader.refresh_if_stale() is False
    preloader.last_refresh = datetime.now(UTC) - timedelta(hours=1)
    assert await preloader.refresh_if_stale()


def test_summaries(monkeypatch):
    """Status and issue summaries."""
    monkeypatch.setattr(jira_preloader, "get_config", lambda: None)
    preloader = JiraPreloader()
    assert preloader.get_status_summary() == "No sprint data loaded."
    preloader.issues = [_issue("AAP-1", "Open"), _issue("AAP-2", "Done"), _issue("AAP-3", "Open")]
    preloader.my_issues = [_issue()]
    assert preloader.get_status_summary() == "Sprint has 3 items: 1 Done, 2 Open. I have 1 assigned."
    assert preloader.get_issue_summary("aap-2") == "AAP-2: Summary (Done)"
    assert preloader.get_issue_summary("NOPE") is None


def test_get_jira_preloader_is_singleton(monkeypatch):
    """The accessor returns one shared instance."""
    monkeypatch.setattr(jira_preloader, "get_config", lambda: None)
    get_jira_preloader.cache_clear()
    try:
        assert get_jira_preloader() is get_jira_preloader()
    finally:
        get_jira_preloader.cache_clear()


def test_fetch_json_rejects_non_http_schemes():
    """file: and other schemes are refused before any request is made."""
    fetch = vars(jira_preloader)["_fetch_json"]
    for url in ("file:///etc/passwd", "ftp://x/y"):
        try:
            fetch(jira_preloader.urllib.request.Request(url))
        except ValueError as e:
            assert "non-HTTP" in str(e)
        else:
            raise AssertionError(url)
    handlers = {type(h).__name__ for h in vars(jira_preloader)["_http_opener"]().handlers}
    assert "FileHandler" not in handlers
    assert "HTTPSHandler" in handlers
