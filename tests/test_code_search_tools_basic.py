"""Tests for aa_code_search tools_basic hashing, timestamps and tool registration."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from tool_modules.aa_code_search.src import tools_basic


def _private(name):
    """Return a private helper from tools_basic."""
    return vars(tools_basic)[name]


def test_compute_file_hash_is_sha256(tmp_path):
    """File hashes are SHA-256 hex digests of the content."""
    path = tmp_path / "a.py"
    path.write_bytes(b"print('hi')\n")
    assert _private("_compute_file_hash")(path) == hashlib.sha256(b"print('hi')\n").hexdigest()


def test_now_is_aware():
    """The current time carries a timezone."""
    assert _private("_now")().tzinfo is not None


def test_parse_timestamp_naive_and_aware():
    """Naive (legacy) timestamps are read as local time; aware ones are kept."""
    parse = _private("_parse_timestamp")
    parsed = parse("2026-01-02T03:04:05")
    assert parsed.tzinfo is not None
    assert parsed.replace(tzinfo=None).isoformat() == "2026-01-02T03:04:05"
    aware = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert parse(aware.isoformat()) == aware


@pytest.fixture(name="vector_db")
def fixture_vector_db(tmp_path, monkeypatch):
    """Point VECTOR_DB_PATH at a temporary directory."""
    monkeypatch.setattr(tools_basic, "VECTOR_DB_PATH", tmp_path)
    return tmp_path


def _write_metadata(root, indexed_at):
    """Write a metadata.json for project 'p' with the given indexed_at."""
    (root / "p").mkdir()
    (root / "p" / "metadata.json").write_text(json.dumps({"indexed_at": indexed_at}), encoding="utf-8")


def test_is_index_stale_fresh_aware(vector_db):
    """A just-written (aware) timestamp is fresh."""
    _write_metadata(vector_db, _private("_now")().isoformat())
    assert not _private("_is_index_stale")("p", max_age_minutes=60)


def test_is_index_stale_legacy_naive(vector_db):
    """Legacy naive timestamps still compare correctly."""
    _write_metadata(vector_db, (_private("_now")() - timedelta(hours=3)).replace(tzinfo=None).isoformat())
    assert _private("_is_index_stale")("p", max_age_minutes=60)
    assert not _private("_is_index_stale")("p", max_age_minutes=600)


@pytest.mark.usefixtures("vector_db")
def test_is_index_stale_missing_metadata():
    """A project without metadata is stale."""
    assert _private("_is_index_stale")("missing")


def _registered_tools():
    """Register the tools against a capturing registry and return them by name."""
    tools = {}

    def tool():
        def decorator(func):
            tools[func.__name__] = func
            return func

        return decorator

    registry = type("Registry", (), {"tool": staticmethod(tool)})
    tools_basic.register_tools(registry)
    return tools


def test_register_tools_names_and_docstrings():
    """All tools are registered and keep their MCP descriptions."""
    tools = _registered_tools()
    assert set(tools) == {
        "code_index",
        "code_search",
        "code_stats",
        "code_compact",
        "knowledge_deep_scan",
        "code_watch",
        "code_watch_all",
        "code_health",
        "code_cache",
    }
    assert all(func.__doc__ and func.__doc__.strip() for func in tools.values())


@pytest.mark.parametrize(
    ("tool", "impl", "kwargs", "expected"),
    [
        ("code_index", "_code_index_impl", {"project": "p"}, {"project": "p", "force": False}),
        (
            "code_search",
            "_code_search_impl",
            {"query": "q"},
            {"query": "q", "project": "", "limit": 10, "file_filter": "", "type_filter": ""},
        ),
        ("code_compact", "_code_compact_impl", {"project": "p"}, {"project": "p"}),
        ("knowledge_deep_scan", "_knowledge_deep_scan_impl", {"project": "p"}, {"project": "p"}),
        (
            "code_watch_all",
            "_code_watch_all_impl",
            {"action": "stop"},
            {"action": "stop", "debounce_seconds": 5.0},
        ),
    ],
)
async def test_tools_delegate_to_impl(monkeypatch, tool, impl, kwargs, expected):
    """Each tool forwards its arguments, with defaults, to its implementation."""
    seen = {}

    async def fake_impl(**call_kwargs):
        seen.update(call_kwargs)
        return ["ok"]

    monkeypatch.setattr(tools_basic, impl, fake_impl)
    assert await _registered_tools()[tool](**kwargs) == ["ok"]
    assert seen == expected
