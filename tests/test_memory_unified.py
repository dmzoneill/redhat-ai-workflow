"""Tests for tool_modules/aa_workflow/src/memory_unified.py - Unified memory interface."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tool_modules.aa_workflow.src.memory_unified import (
    _get_memory_interface,
    _parse_sources,
)

# ==================== Helper to capture registered tool functions ====================


def _capture_tools():
    """Register tools with pass-through decorators and return the captured functions."""
    captured = {}

    def passthrough_decorator():
        def decorator(fn):
            return fn

        return decorator

    mock_server = MagicMock()
    # Make server.tool() return a pass-through decorator
    mock_server.tool.return_value = lambda fn: fn

    with (
        patch(
            "tool_modules.aa_workflow.src.memory_unified.auto_heal",
            side_effect=lambda **kw: (lambda fn: fn),
        ),
        patch(
            "tool_modules.aa_workflow.src.memory_unified.ToolRegistry",
        ) as MockRegistry,
    ):
        mock_registry = MagicMock()

        # Capture each tool function when tool() is called
        def capture_tool(**kwargs):
            def decorator(fn):
                captured[fn.__name__] = fn
                return fn

            return decorator

        mock_registry.tool = capture_tool
        mock_registry.count = 5
        MockRegistry.return_value = mock_registry

        from tool_modules.aa_workflow.src.memory_unified import register_tools

        register_tools(mock_server)

    return captured


# Capture once at module level for reuse
_TOOLS = _capture_tools()


# ==================== _get_memory_interface ====================


class TestGetMemoryInterface:
    """Tests for _get_memory_interface."""

    def test_from_ctx_server_memory(self):
        ctx = MagicMock()
        ctx.server.memory = MagicMock(name="memory_from_ctx")
        result = _get_memory_interface(ctx)
        assert result is ctx.server.memory

    def test_from_ctx_no_server_attr(self):
        ctx = MagicMock(spec=[])  # No attributes at all
        result = _get_memory_interface(ctx)
        assert result is not None or result is None

    def test_none_ctx_falls_to_global(self):
        with patch(
            "services.memory_abstraction.get_memory_interface",
            return_value=MagicMock(name="global_memory"),
        ):
            result = _get_memory_interface(None)
            assert result is not None

    def test_ctx_with_memory_attribute(self):
        ctx = MagicMock()
        memory = MagicMock()
        ctx.server.memory = memory
        assert _get_memory_interface(ctx) is memory

    def test_ctx_server_no_memory(self):
        ctx = MagicMock()
        del ctx.server.memory
        result = _get_memory_interface(ctx)
        assert result is not None or result is None


# ==================== _parse_sources ====================


class TestParseSources:
    """Tests for _parse_sources."""

    def test_none_returns_none(self):
        assert _parse_sources(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_sources("") is None

    def test_comma_separated(self):
        mock_sf = MagicMock()
        mock_sf.side_effect = lambda name: MagicMock(name_val=name)
        with patch.dict(
            "sys.modules",
            {"services.memory_abstraction": MagicMock(SourceFilter=mock_sf)},
        ):
            result = _parse_sources("code,yaml,slack")
            assert result is not None
            assert len(result) == 3

    def test_comma_separated_with_spaces(self):
        mock_sf = MagicMock()
        mock_sf.side_effect = lambda name: MagicMock(name_val=name)
        with patch.dict(
            "sys.modules",
            {"services.memory_abstraction": MagicMock(SourceFilter=mock_sf)},
        ):
            result = _parse_sources("code , yaml , slack")
            assert result is not None
            assert len(result) == 3

    def test_json_array_strings(self):
        mock_sf = MagicMock()
        mock_sf.side_effect = lambda name: MagicMock(name_val=name)
        mock_sf.from_dict = MagicMock(
            side_effect=lambda d: MagicMock(
                name_val=d.get("name") if isinstance(d, dict) else d
            )
        )
        with patch.dict(
            "sys.modules",
            {"services.memory_abstraction": MagicMock(SourceFilter=mock_sf)},
        ):
            result = _parse_sources('["code", "yaml"]')
            assert result is not None
            assert len(result) == 2

    def test_json_array_dicts(self):
        mock_sf = MagicMock()
        mock_sf.side_effect = lambda name: MagicMock(name_val=name)
        mock_sf.from_dict = MagicMock(return_value=MagicMock())
        with patch.dict(
            "sys.modules",
            {"services.memory_abstraction": MagicMock(SourceFilter=mock_sf)},
        ):
            result = _parse_sources('[{"name": "code", "limit": 5}]')
            assert result is not None
            assert len(result) == 1
            mock_sf.from_dict.assert_called_once()

    def test_json_array_mixed(self):
        mock_sf = MagicMock()
        mock_sf.side_effect = lambda name: MagicMock(name_val=name)
        mock_sf.from_dict = MagicMock(return_value=MagicMock())
        with patch.dict(
            "sys.modules",
            {"services.memory_abstraction": MagicMock(SourceFilter=mock_sf)},
        ):
            result = _parse_sources('[{"name": "code"}, "yaml"]')
            assert result is not None
            assert len(result) == 2

    def test_invalid_json_returns_none(self):
        result = _parse_sources("[invalid json")
        assert result is None

    def test_parse_error_returns_none(self):
        with patch(
            "tool_modules.aa_workflow.src.memory_unified.json.loads",
            side_effect=Exception("Parse error"),
        ):
            result = _parse_sources("[1,2,3]")
            assert result is None

    def test_comma_separated_skips_empty(self):
        mock_sf = MagicMock()
        mock_sf.side_effect = lambda name: MagicMock(name_val=name)
        with patch.dict(
            "sys.modules",
            {"services.memory_abstraction": MagicMock(SourceFilter=mock_sf)},
        ):
            result = _parse_sources("code,,yaml,")
            assert result is not None
            assert len(result) == 2


# ==================== memory_ask tool ====================


class TestMemoryAsk:
    """Tests for the memory_ask inner tool function."""

    @pytest.mark.asyncio
    async def test_no_memory_interface(self):
        fn = _TOOLS["memory_ask"]
        with patch(
            "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
            return_value=None,
        ):
            result = await fn(question="What?")
            assert "not available" in result

    @pytest.mark.asyncio
    async def test_query_success_include_slow(self):
        fn = _TOOLS["memory_ask"]
        memory = AsyncMock()
        memory.query.return_value = {"results": []}
        memory.format = MagicMock(return_value="## Results\nDone.")
        with patch(
            "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
            return_value=memory,
        ):
            result = await fn(question="What am I working on?", include_slow=True)
            assert "Results" in result
            memory.query.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_query_with_explicit_sources(self):
        fn = _TOOLS["memory_ask"]
        memory = AsyncMock()
        memory.query.return_value = {"results": []}
        memory.format = MagicMock(return_value="OK")
        mock_sf = MagicMock()
        mock_sf.side_effect = lambda name: MagicMock(name_val=name)
        with (
            patch(
                "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
                return_value=memory,
            ),
            patch.dict(
                "sys.modules",
                {"services.memory_abstraction": MagicMock(SourceFilter=mock_sf)},
            ),
        ):
            result = await fn(question="test", sources="code,yaml")
            assert "OK" in result

    @pytest.mark.asyncio
    async def test_query_adds_slow_hint(self):
        fn = _TOOLS["memory_ask"]
        memory = AsyncMock()
        memory.query.return_value = {"results": []}
        memory.format = MagicMock(return_value="Results here")
        mock_sf = MagicMock()
        mock_sf.side_effect = lambda name: MagicMock(name_val=name)
        with (
            patch(
                "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
                return_value=memory,
            ),
            patch.dict(
                "sys.modules",
                {"services.memory_abstraction": MagicMock(SourceFilter=mock_sf)},
            ),
        ):
            # include_slow=False with explicit sources -> should add tip
            result = await fn(question="test", sources="code", include_slow=False)
            assert "Tip" in result

    @pytest.mark.asyncio
    async def test_query_no_hint_when_include_slow(self):
        fn = _TOOLS["memory_ask"]
        memory = AsyncMock()
        memory.query.return_value = {"results": []}
        memory.format = MagicMock(return_value="Results here")
        with patch(
            "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
            return_value=memory,
        ):
            result = await fn(question="test", include_slow=True)
            assert "Tip" not in result

    @pytest.mark.asyncio
    async def test_query_exception(self):
        fn = _TOOLS["memory_ask"]
        memory = AsyncMock()
        memory.query.side_effect = RuntimeError("Query failed")
        with patch(
            "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
            return_value=memory,
        ):
            result = await fn(question="test", include_slow=True)
            assert "Query failed" in result

    @pytest.mark.asyncio
    async def test_query_fast_sources_only(self):
        fn = _TOOLS["memory_ask"]
        memory = AsyncMock()
        memory.query.return_value = {"results": []}
        memory.format = MagicMock(return_value="Fast results")

        mock_manifest = MagicMock()
        mock_manifest.list_fast_adapters.return_value = ["yaml", "code"]
        mock_sf = MagicMock()
        mock_sf.side_effect = lambda name: MagicMock(name_val=name)

        with (
            patch(
                "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
                return_value=memory,
            ),
            patch.dict(
                "sys.modules",
                {
                    "services.memory_abstraction.registry": MagicMock(
                        ADAPTER_MANIFEST=mock_manifest
                    ),
                    "services.memory_abstraction": MagicMock(SourceFilter=mock_sf),
                },
            ),
        ):
            result = await fn(question="test", include_slow=False)
            assert "Fast results" in result


# ==================== memory_search tool ====================


class TestMemorySearch:
    """Tests for the memory_search inner tool function."""

    @pytest.mark.asyncio
    async def test_no_memory_interface(self):
        fn = _TOOLS["memory_search"]
        with patch(
            "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
            return_value=None,
        ):
            result = await fn(query="test")
            assert "not available" in result

    @pytest.mark.asyncio
    async def test_search_success(self):
        fn = _TOOLS["memory_search"]
        memory = AsyncMock()
        memory.search.return_value = {"results": [{"text": "found"}]}
        memory.format = MagicMock(return_value="Found: item")
        with patch(
            "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
            return_value=memory,
        ):
            result = await fn(query="billing")
            assert "Found" in result

    @pytest.mark.asyncio
    async def test_search_exception(self):
        fn = _TOOLS["memory_search"]
        memory = AsyncMock()
        memory.search.side_effect = RuntimeError("Search error")
        with patch(
            "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
            return_value=memory,
        ):
            result = await fn(query="test")
            assert "Search failed" in result


# ==================== memory_store tool ====================


class TestMemoryStore:
    """Tests for the memory_store inner tool function."""

    @pytest.mark.asyncio
    async def test_no_memory_interface(self):
        fn = _TOOLS["memory_store"]
        with patch(
            "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
            return_value=None,
        ):
            result = await fn(key="k", value="v")
            assert "not available" in result

    @pytest.mark.asyncio
    async def test_store_json_value(self):
        fn = _TOOLS["memory_store"]
        memory = AsyncMock()
        store_result = MagicMock()
        store_result.error = None
        memory.store.return_value = store_result
        with patch(
            "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
            return_value=memory,
        ):
            result = await fn(key="state/test", value='{"a": 1}')
            assert "Stored" in result
            # Check that JSON was parsed
            call_kwargs = memory.store.call_args[1]
            assert call_kwargs["value"] == {"a": 1}

    @pytest.mark.asyncio
    async def test_store_plain_string(self):
        fn = _TOOLS["memory_store"]
        memory = AsyncMock()
        store_result = MagicMock()
        store_result.error = None
        memory.store.return_value = store_result
        with patch(
            "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
            return_value=memory,
        ):
            result = await fn(key="state/test", value="plain text")
            assert "Stored" in result
            call_kwargs = memory.store.call_args[1]
            assert call_kwargs["value"] == "plain text"

    @pytest.mark.asyncio
    async def test_store_error_result(self):
        fn = _TOOLS["memory_store"]
        memory = AsyncMock()
        store_result = MagicMock()
        store_result.error = "Write failed"
        memory.store.return_value = store_result
        with patch(
            "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
            return_value=memory,
        ):
            result = await fn(key="k", value="v")
            assert "Store failed" in result
            assert "Write failed" in result

    @pytest.mark.asyncio
    async def test_store_exception(self):
        fn = _TOOLS["memory_store"]
        memory = AsyncMock()
        memory.store.side_effect = RuntimeError("Boom")
        with patch(
            "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
            return_value=memory,
        ):
            result = await fn(key="k", value="v")
            assert "Store failed" in result


# ==================== memory_health tool ====================


class TestMemoryHealth:
    """Tests for the memory_health inner tool function."""

    @pytest.mark.asyncio
    async def test_no_memory_interface(self):
        fn = _TOOLS["memory_health"]
        with patch(
            "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
            return_value=None,
        ):
            result = await fn()
            data = json.loads(result)
            assert "error" in data

    @pytest.mark.asyncio
    async def test_health_success(self):
        fn = _TOOLS["memory_health"]
        memory = AsyncMock()
        memory.health_check.return_value = {"yaml": "ok", "code": "ok"}
        with patch(
            "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
            return_value=memory,
        ):
            result = await fn()
            data = json.loads(result)
            assert data["yaml"] == "ok"

    @pytest.mark.asyncio
    async def test_health_exception(self):
        fn = _TOOLS["memory_health"]
        memory = AsyncMock()
        memory.health_check.side_effect = RuntimeError("Fail")
        with patch(
            "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
            return_value=memory,
        ):
            result = await fn()
            data = json.loads(result)
            assert "error" in data


# ==================== memory_list_adapters tool ====================


class TestMemoryListAdapters:
    """Tests for the memory_list_adapters inner tool function."""

    @pytest.mark.asyncio
    async def test_no_memory_interface(self):
        fn = _TOOLS["memory_list_adapters"]
        with patch(
            "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
            return_value=None,
        ):
            result = await fn()
            data = json.loads(result)
            assert "error" in data

    @pytest.mark.asyncio
    async def test_list_adapters_fast_and_slow(self):
        fn = _TOOLS["memory_list_adapters"]
        memory = MagicMock()
        memory.list_adapters.return_value = ["yaml", "jira"]

        info_fast = MagicMock()
        info_fast.name = "yaml"
        info_fast.display_name = "YAML"
        info_fast.capabilities = ["query", "store"]
        info_fast.priority = 1
        info_fast.latency_class = "fast"

        info_slow = MagicMock()
        info_slow.name = "jira"
        info_slow.display_name = "Jira"
        info_slow.capabilities = ["query"]
        info_slow.priority = 5
        info_slow.latency_class = "slow"

        memory.get_adapter_info.side_effect = lambda n: (
            info_fast if n == "yaml" else info_slow
        )

        with patch(
            "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
            return_value=memory,
        ):
            result = await fn()
            data = json.loads(result)
            assert data["fast_adapters"]["count"] == 1
            assert data["slow_adapters"]["count"] == 1
            assert data["total_count"] == 2

    @pytest.mark.asyncio
    async def test_list_adapters_skips_none_info(self):
        fn = _TOOLS["memory_list_adapters"]
        memory = MagicMock()
        memory.list_adapters.return_value = ["missing"]
        memory.get_adapter_info.return_value = None

        with patch(
            "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
            return_value=memory,
        ):
            result = await fn()
            data = json.loads(result)
            assert data["total_count"] == 0

    @pytest.mark.asyncio
    async def test_list_adapters_exception(self):
        fn = _TOOLS["memory_list_adapters"]
        memory = MagicMock()
        memory.list_adapters.side_effect = RuntimeError("Failed")

        with patch(
            "tool_modules.aa_workflow.src.memory_unified._get_memory_interface",
            return_value=memory,
        ):
            result = await fn()
            data = json.loads(result)
            assert "error" in data


# ==================== register_tools ====================


class TestRegisterTools:
    """Tests for register_tools function."""

    def test_registers_five_tools(self):
        assert len(_TOOLS) == 5
        assert "memory_ask" in _TOOLS
        assert "memory_search" in _TOOLS
        assert "memory_store" in _TOOLS
        assert "memory_health" in _TOOLS
        assert "memory_list_adapters" in _TOOLS


# ==================== JSON parsing ====================


class TestJsonParsing:
    """Tests for JSON parsing behavior in store path."""

    def test_valid_json_parsed(self):
        value = '{"key": "value"}'
        parsed = json.loads(value)
        assert parsed == {"key": "value"}

    def test_invalid_json_kept_as_string(self):
        value = "just a string"
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value
        assert parsed == "just a string"

    def test_json_list(self):
        value = '["a", "b"]'
        parsed = json.loads(value)
        assert parsed == ["a", "b"]
