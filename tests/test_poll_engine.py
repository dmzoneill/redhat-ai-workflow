"""Tests for tool_modules/aa_workflow/src/poll_engine.py - Event-based polling triggers."""

import hashlib
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from tool_modules.aa_workflow.src.poll_engine import (
    PollCondition,
    PollEngine,
    PollSource,
    get_poll_engine,
    init_poll_engine,
    parse_duration,
)

# ==================== parse_duration ====================


class TestParseDuration:
    """Tests for parse_duration."""

    def test_seconds(self):
        assert parse_duration("30s") == timedelta(seconds=30)
        assert parse_duration("10sec") == timedelta(seconds=10)
        assert parse_duration("5second") == timedelta(seconds=5)
        assert parse_duration("1seconds") == timedelta(seconds=1)

    def test_minutes(self):
        assert parse_duration("5m") == timedelta(minutes=5)
        assert parse_duration("10min") == timedelta(minutes=10)
        assert parse_duration("1minute") == timedelta(minutes=1)
        assert parse_duration("30minutes") == timedelta(minutes=30)

    def test_hours(self):
        assert parse_duration("1h") == timedelta(hours=1)
        assert parse_duration("2hr") == timedelta(hours=2)
        assert parse_duration("3hour") == timedelta(hours=3)
        assert parse_duration("4hours") == timedelta(hours=4)

    def test_days(self):
        assert parse_duration("1d") == timedelta(days=1)
        assert parse_duration("3day") == timedelta(days=3)
        assert parse_duration("7days") == timedelta(days=7)

    def test_weeks(self):
        assert parse_duration("1w") == timedelta(weeks=1)
        assert parse_duration("2week") == timedelta(weeks=2)
        assert parse_duration("3weeks") == timedelta(weeks=3)

    def test_whitespace(self):
        assert parse_duration("  5m  ") == timedelta(minutes=5)
        assert parse_duration("10 h") == timedelta(hours=10)

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("abc")

    def test_unknown_unit(self):
        with pytest.raises(ValueError, match="Unknown duration unit"):
            parse_duration("5y")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            parse_duration("")


# ==================== PollCondition ====================


class TestPollCondition:
    """Tests for PollCondition."""

    def test_any_condition_default(self):
        cond = PollCondition("")
        assert cond.condition_type == "any"

    def test_any_condition_explicit(self):
        cond = PollCondition("any")
        assert cond.condition_type == "any"

    def test_any_condition_case_insensitive(self):
        cond = PollCondition("ANY")
        assert cond.condition_type == "any"

    def test_count_condition(self):
        cond = PollCondition("count > 5")
        assert cond.condition_type == "count"
        assert cond.operator == ">"
        assert cond.threshold == 5

    def test_count_condition_gte(self):
        cond = PollCondition("count >= 10")
        assert cond.condition_type == "count"
        assert cond.operator == ">="
        assert cond.threshold == 10

    def test_age_condition(self):
        cond = PollCondition("age > 3d")
        assert cond.condition_type == "age"
        assert cond.operator == ">"
        assert cond.threshold_duration == timedelta(days=3)

    def test_age_condition_hours(self):
        cond = PollCondition("age > 2h")
        assert cond.condition_type == "age"
        assert cond.threshold_duration == timedelta(hours=2)

    # ---- evaluate ----

    def test_evaluate_any_with_items(self):
        cond = PollCondition("any")
        met, items = cond.evaluate([{"id": 1}])
        assert met is True
        assert len(items) == 1

    def test_evaluate_any_no_items(self):
        cond = PollCondition("any")
        met, items = cond.evaluate([])
        assert met is False

    def test_evaluate_count_gt_met(self):
        cond = PollCondition("count > 0")
        met, items = cond.evaluate([{"id": 1}, {"id": 2}])
        assert met is True
        assert len(items) == 2

    def test_evaluate_count_gt_not_met(self):
        cond = PollCondition("count > 5")
        met, items = cond.evaluate([{"id": 1}])
        assert met is False
        assert items == []

    def test_evaluate_count_eq(self):
        cond = PollCondition("count == 2")
        met, items = cond.evaluate([{"id": 1}, {"id": 2}])
        assert met is True

    def test_evaluate_count_eq_single_equals(self):
        cond = PollCondition("count = 1")
        met, items = cond.evaluate([{"id": 1}])
        assert met is True

    def test_evaluate_count_ne(self):
        cond = PollCondition("count != 0")
        met, _ = cond.evaluate([{"id": 1}])
        assert met is True

    def test_evaluate_count_ne_diamond(self):
        cond = PollCondition("count <> 0")
        met, _ = cond.evaluate([{"id": 1}])
        assert met is True

    def test_evaluate_count_lt(self):
        cond = PollCondition("count < 3")
        met, items = cond.evaluate([{"id": 1}])
        assert met is True

    def test_evaluate_count_lte(self):
        cond = PollCondition("count <= 2")
        met, items = cond.evaluate([{"id": 1}, {"id": 2}])
        assert met is True

    def test_evaluate_count_gte(self):
        cond = PollCondition("count >= 2")
        met, _ = cond.evaluate([{"id": 1}, {"id": 2}])
        assert met is True

    def test_evaluate_age_gt_met(self):
        cond = PollCondition("age > 1h")
        old_date = (datetime.now() - timedelta(hours=2)).isoformat()
        met, items = cond.evaluate([{"id": 1, "created_at": old_date}])
        assert met is True
        assert len(items) == 1

    def test_evaluate_age_gt_not_met(self):
        cond = PollCondition("age > 1d")
        recent_date = datetime.now().isoformat()
        met, items = cond.evaluate([{"id": 1, "created_at": recent_date}])
        assert met is False
        assert len(items) == 0

    def test_evaluate_age_lt(self):
        cond = PollCondition("age < 1d")
        recent_date = datetime.now().isoformat()
        met, items = cond.evaluate([{"id": 1, "created_at": recent_date}])
        assert met is True

    def test_evaluate_age_gte(self):
        cond = PollCondition("age >= 1s")
        old_date = (datetime.now() - timedelta(seconds=5)).isoformat()
        met, items = cond.evaluate([{"id": 1, "created_at": old_date}])
        assert met is True

    def test_evaluate_age_lte(self):
        cond = PollCondition("age <= 1d")
        recent_date = datetime.now().isoformat()
        met, items = cond.evaluate([{"id": 1, "created_at": recent_date}])
        assert met is True

    def test_evaluate_age_uses_updated_at(self):
        cond = PollCondition("age > 1h")
        old_date = (datetime.now() - timedelta(hours=2)).isoformat()
        met, items = cond.evaluate([{"id": 1, "updated_at": old_date}])
        assert met is True

    def test_evaluate_age_uses_date_field(self):
        cond = PollCondition("age > 1h")
        old_date = (datetime.now() - timedelta(hours=2)).isoformat()
        met, items = cond.evaluate([{"id": 1, "date": old_date}])
        assert met is True

    def test_evaluate_age_no_date_field(self):
        cond = PollCondition("age > 1h")
        met, items = cond.evaluate([{"id": 1}])
        assert met is False

    def test_evaluate_age_with_z_suffix(self):
        cond = PollCondition("age > 1h")
        old_date = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        met, items = cond.evaluate([{"created_at": old_date}])
        assert met is True

    def test_evaluate_age_with_timezone_offset(self):
        cond = PollCondition("age > 1h")
        old_date = (datetime.now() - timedelta(hours=2)).strftime(
            "%Y-%m-%dT%H:%M:%S+00:00"
        )
        met, items = cond.evaluate([{"created_at": old_date}])
        assert met is True

    def test_evaluate_age_invalid_date(self):
        cond = PollCondition("age > 1h")
        met, items = cond.evaluate([{"created_at": "not-a-date"}])
        assert met is False

    def test_evaluate_unknown_type(self):
        cond = PollCondition("")
        cond.condition_type = "unknown"
        met, items = cond.evaluate([{"id": 1}])
        assert met is False
        assert items == []

    # ---- _compare ----

    def test_compare_operators(self):
        cond = PollCondition("count > 0")
        assert cond._compare(5, 3) is True
        cond.operator = ">="
        assert cond._compare(3, 3) is True
        cond.operator = "<"
        assert cond._compare(2, 3) is True
        cond.operator = "<="
        assert cond._compare(3, 3) is True
        cond.operator = "=="
        assert cond._compare(3, 3) is True
        cond.operator = "!="
        assert cond._compare(4, 3) is True
        cond.operator = "??"
        assert cond._compare(3, 3) is False

    # ---- _compare_duration ----

    def test_compare_duration_operators(self):
        cond = PollCondition("age > 1h")
        t1 = timedelta(hours=2)
        t2 = timedelta(hours=1)

        cond.operator = ">"
        assert cond._compare_duration(t1, t2) is True
        cond.operator = ">="
        assert cond._compare_duration(t2, t2) is True
        cond.operator = "<"
        assert cond._compare_duration(t2, t1) is True
        cond.operator = "<="
        assert cond._compare_duration(t2, t2) is True
        cond.operator = "??"
        assert cond._compare_duration(t1, t2) is False


# ==================== PollSource ====================


class TestPollSource:
    """Tests for PollSource."""

    def test_init(self):
        source = PollSource(
            name="test",
            source_type="gitlab_mr_list",
            args={"state": "opened"},
            condition="count > 0",
        )
        assert source.name == "test"
        assert source.source_type == "gitlab_mr_list"
        assert source.last_poll is None
        assert source.last_result == []

    @pytest.mark.asyncio
    async def test_poll_updates_last_poll(self):
        source = PollSource(
            name="test",
            source_type="gitlab_mr_list",
            args={},
            condition="any",
            server=None,
        )
        await source.poll()
        assert source.last_poll is not None

    @pytest.mark.asyncio
    async def test_poll_gitlab_no_server(self):
        source = PollSource(
            name="test",
            source_type="gitlab_mr_list",
            args={},
            condition="any",
            server=None,
        )
        met, items = await source.poll()
        assert met is False
        assert items == []

    @pytest.mark.asyncio
    async def test_poll_jira_no_server(self):
        source = PollSource(
            name="test",
            source_type="jira_search",
            args={},
            condition="any",
            server=None,
        )
        met, items = await source.poll()
        assert met is False

    @pytest.mark.asyncio
    async def test_poll_unknown_type(self):
        source = PollSource(
            name="test",
            source_type="unknown_type",
            args={},
            condition="any",
        )
        met, items = await source.poll()
        assert met is False

    @pytest.mark.asyncio
    async def test_poll_gitlab_success(self):
        server = AsyncMock()
        result_text = MagicMock()
        result_text.text = "!42 - Fix bug (author) - 2024-01-01\n!43 - New feature"
        server.call_tool.return_value = [result_text]

        source = PollSource(
            name="mrs",
            source_type="gitlab_mr_list",
            args={"state": "opened"},
            condition="count > 0",
            server=server,
        )
        met, items = await source.poll()
        assert met is True
        assert len(items) == 2
        assert items[0]["id"] == "42"
        assert items[0]["created_at"] == "2024-01-01"

    @pytest.mark.asyncio
    async def test_poll_gitlab_error(self):
        server = AsyncMock()
        server.call_tool.side_effect = RuntimeError("API error")

        source = PollSource(
            name="mrs",
            source_type="gitlab_mr_list",
            args={},
            condition="any",
            server=server,
        )
        met, items = await source.poll()
        assert met is False

    @pytest.mark.asyncio
    async def test_poll_jira_success(self):
        server = AsyncMock()
        result_text = MagicMock()
        result_text.text = "AAP-100 - Bug in billing\nAAP-200 - Feature request"
        server.call_tool.return_value = [result_text]

        source = PollSource(
            name="issues",
            source_type="jira_search",
            args={"jql": "project=AAP"},
            condition="count > 0",
            server=server,
        )
        met, items = await source.poll()
        assert met is True
        assert len(items) == 2
        assert items[0]["key"] == "AAP-100"

    @pytest.mark.asyncio
    async def test_poll_jira_error(self):
        server = AsyncMock()
        server.call_tool.side_effect = RuntimeError("Jira down")

        source = PollSource(
            name="issues",
            source_type="jira_search",
            args={},
            condition="any",
            server=server,
        )
        met, items = await source.poll()
        assert met is False

    @pytest.mark.asyncio
    async def test_poll_exception_in_fetch(self):
        source = PollSource(
            name="test",
            source_type="gitlab_mr_list",
            args={},
            condition="any",
            server=AsyncMock(),
        )
        source.server.call_tool.side_effect = Exception("Unexpected")
        met, items = await source.poll()
        assert met is False
        assert items == []

    # ---- _parse_mr_list ----

    def test_parse_mr_list(self):
        source = PollSource("t", "gitlab_mr_list", {}, "any")
        items = source._parse_mr_list(
            "# Open MRs\n!10 - Title A - 2024-06-15\n!20 - Title B\n\n"
        )
        assert len(items) == 2
        assert items[0]["id"] == "10"
        assert items[0]["created_at"] == "2024-06-15"
        assert items[1]["id"] == "20"
        assert items[1]["created_at"] is None

    def test_parse_mr_list_empty(self):
        source = PollSource("t", "gitlab_mr_list", {}, "any")
        items = source._parse_mr_list("")
        assert items == []

    def test_parse_mr_list_no_matches(self):
        source = PollSource("t", "gitlab_mr_list", {}, "any")
        items = source._parse_mr_list("No MRs found")
        assert items == []

    # ---- _parse_jira_list ----

    def test_parse_jira_list(self):
        source = PollSource("t", "jira_search", {}, "any")
        items = source._parse_jira_list("AAP-123 - Bug\nAAP-456 - Feature\n")
        assert len(items) == 2
        assert items[0]["key"] == "AAP-123"

    def test_parse_jira_list_empty(self):
        source = PollSource("t", "jira_search", {}, "any")
        items = source._parse_jira_list("")
        assert items == []


# ==================== PollEngine ====================


class TestPollEngine:
    """Tests for PollEngine."""

    def test_init(self):
        engine = PollEngine()
        assert engine._running is False
        assert engine.sources == {}
        assert engine.jobs == []

    def test_configure(self):
        engine = PollEngine()
        engine.configure(
            poll_sources={
                "gitlab_mrs": {
                    "type": "gitlab_mr_list",
                    "args": {"state": "opened"},
                    "condition": "count > 0",
                },
            },
            poll_jobs=[
                {"name": "check_mrs", "condition": "gitlab_mrs", "skill": "review_pr"},
            ],
        )
        assert "gitlab_mrs" in engine.sources
        assert len(engine.jobs) == 1

    def test_get_status(self):
        engine = PollEngine()
        engine.configure(
            poll_sources={"src1": {"type": "t", "args": {}, "condition": "any"}},
            poll_jobs=[{"name": "j1"}],
        )
        status = engine.get_status()
        assert status["running"] is False
        assert "src1" in status["sources"]
        assert status["jobs"] == 1
        assert status["triggered_items_cached"] == 0

    # ---- _hash_item ----

    def test_hash_item_with_id(self):
        engine = PollEngine()
        h = engine._hash_item("job1", {"id": "42"})
        expected = hashlib.md5("job1:42".encode(), usedforsecurity=False).hexdigest()
        assert h == expected

    def test_hash_item_with_key(self):
        engine = PollEngine()
        h = engine._hash_item("job1", {"key": "AAP-100"})
        expected = hashlib.md5(
            "job1:AAP-100".encode(), usedforsecurity=False
        ).hexdigest()
        assert h == expected

    def test_hash_item_fallback_to_str(self):
        engine = PollEngine()
        item = {"title": "something"}
        h = engine._hash_item("job1", item)
        expected = hashlib.md5(
            f"job1:{item}".encode(), usedforsecurity=False
        ).hexdigest()
        assert h == expected

    # ---- _filter_triggered ----

    def test_filter_triggered_new_items(self):
        engine = PollEngine()
        items = [{"id": "1"}, {"id": "2"}]
        new = engine._filter_triggered("job1", items)
        assert len(new) == 2

    def test_filter_triggered_dedup(self):
        engine = PollEngine()
        items = [{"id": "1"}, {"id": "2"}]
        engine._filter_triggered("job1", items)
        # Second call should filter out already-triggered items
        new = engine._filter_triggered("job1", items)
        assert len(new) == 0

    def test_filter_triggered_ttl_expiry(self):
        engine = PollEngine()
        items = [{"id": "1"}]
        engine._filter_triggered("job1", items)
        # Manually expire the hash
        for k in engine._triggered_hashes:
            engine._triggered_hashes[k] = datetime.now() - timedelta(hours=25)
        new = engine._filter_triggered("job1", items)
        assert len(new) == 1

    def test_filter_triggered_max_size(self):
        engine = PollEngine()
        engine._max_triggered_hashes = 5
        # Add 10 items
        for i in range(10):
            engine._filter_triggered("job1", [{"id": str(i)}])
        # Should be capped after cleanup
        engine._filter_triggered("job1", [{"id": "new"}])
        assert len(engine._triggered_hashes) <= 6  # 5 + 1 new

    # ---- _trigger_job ----

    @pytest.mark.asyncio
    async def test_trigger_job_no_callback(self):
        engine = PollEngine(job_callback=None)
        # Should not raise
        await engine._trigger_job(
            {"name": "test", "skill": "deploy", "inputs": {}},
            [{"id": "1"}],
        )

    @pytest.mark.asyncio
    async def test_trigger_job_with_callback(self):
        callback = AsyncMock()
        engine = PollEngine(job_callback=callback)
        job = {
            "name": "test_job",
            "skill": "deploy",
            "inputs": {"env": "stage"},
            "notify": ["slack"],
        }
        items = [{"id": "1"}, {"id": "2"}]
        await engine._trigger_job(job, items)
        callback.assert_awaited_once()
        call_kwargs = callback.call_args[1]
        assert call_kwargs["job_name"] == "test_job"
        assert call_kwargs["skill"] == "deploy"
        assert call_kwargs["inputs"]["_triggered_count"] == 2
        assert call_kwargs["inputs"]["_triggered_items"] == items
        assert call_kwargs["inputs"]["env"] == "stage"
        assert call_kwargs["notify"] == ["slack"]

    @pytest.mark.asyncio
    async def test_trigger_job_callback_error(self):
        callback = AsyncMock(side_effect=RuntimeError("Callback failed"))
        engine = PollEngine(job_callback=callback)
        # Should not raise
        await engine._trigger_job(
            {"name": "test", "skill": "s", "inputs": {}}, [{"id": "1"}]
        )

    # ---- poll_now ----

    @pytest.mark.asyncio
    async def test_poll_now_source_not_found(self):
        engine = PollEngine()
        result = await engine.poll_now("nonexistent")
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_poll_now_success(self):
        engine = PollEngine()
        source = PollSource(
            name="test",
            source_type="jira_search",
            args={},
            condition="any",
            server=AsyncMock(),
        )
        result_text = MagicMock()
        result_text.text = "AAP-100 - Bug"
        source.server.call_tool.return_value = [result_text]
        engine.sources["test"] = source

        result = await engine.poll_now("test")
        assert result["success"] is True
        assert result["condition_met"] is True
        assert result["items_count"] == 1

    @pytest.mark.asyncio
    async def test_poll_now_limits_items(self):
        engine = PollEngine()
        source = PollSource(
            name="test",
            source_type="jira_search",
            args={},
            condition="any",
            server=AsyncMock(),
        )
        lines = "\n".join(f"AAP-{i} - Issue {i}" for i in range(20))
        result_text = MagicMock()
        result_text.text = lines
        source.server.call_tool.return_value = [result_text]
        engine.sources["test"] = source

        result = await engine.poll_now("test")
        assert len(result["items"]) <= 10

    # ---- start / stop ----

    @pytest.mark.asyncio
    async def test_start_stop(self):
        engine = PollEngine()
        engine.configure(poll_sources={}, poll_jobs=[])
        await engine.start()
        assert engine._running is True
        assert engine._task is not None
        await engine.stop()
        assert engine._running is False

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        engine = PollEngine()
        engine.configure(poll_sources={}, poll_jobs=[])
        await engine.start()
        task1 = engine._task
        await engine.start()  # Should not create another task
        assert engine._task is task1
        await engine.stop()


# ==================== Global functions ====================


class TestGlobalFunctions:
    """Tests for module-level convenience functions."""

    def test_init_poll_engine(self):
        callback = AsyncMock()
        engine = init_poll_engine(job_callback=callback)
        assert isinstance(engine, PollEngine)
        assert engine.job_callback is callback

    def test_get_poll_engine(self):
        init_poll_engine()
        engine = get_poll_engine()
        assert isinstance(engine, PollEngine)

    def test_get_poll_engine_none(self):
        import tool_modules.aa_workflow.src.poll_engine as mod

        original = mod._poll_engine
        mod._poll_engine = None
        assert get_poll_engine() is None
        mod._poll_engine = original
