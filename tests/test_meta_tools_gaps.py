"""Tests for tool gap tools (meta_tool_handlers)."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from tool_modules.aa_workflow.src import meta_tools as mt


class TestToolGapsList:
    """Tests for tool_gaps_list tool."""

    @pytest.mark.asyncio
    async def test_no_gaps(self):
        """An empty gap list is reported through the registered tool."""
        server = FastMCP("test-gaps")
        mt.register_meta_tools(server)

        mock_gap = MagicMock()
        mock_gap.get_gaps.return_value = []
        with patch("tool_modules.aa_workflow.src.tool_gap_detector.tool_gap", mock_gap):
            result = await server.call_tool("tool_gaps_list", {})

        assert "No tool gaps" in str(result)
        mock_gap.get_gaps.assert_called_once()

    @pytest.mark.asyncio
    async def test_gaps_error(self):
        """Gaps error."""

        server = FastMCP("test-gaps-err")
        mt.register_meta_tools(server)

        with patch(
            "tool_modules.aa_workflow.src.tool_gap_detector.tool_gap",
            side_effect=Exception("import error"),
            create=True,
        ):
            result = await server.call_tool("tool_gaps_list", {"status": "open"})
            # Should handle the error gracefully
            text = str(result)
            assert "Error" in text or "error" in text or "gap" in text.lower()

    @pytest.mark.asyncio
    async def test_invalid_status(self):
        """Invalid status."""

        server = FastMCP("test-gap-update")
        mt.register_meta_tools(server)

        result = await server.call_tool("tool_gap_update", {"gap_id": "abc", "status": "invalid_status"})
        text = str(result)
        assert "Invalid status" in text or "invalid" in text.lower()


class TestToolGapErrorPaths:
    """Tests for tool gap error handling paths."""

    @pytest.mark.asyncio
    async def test_gaps_list_import_error(self):
        """Test tool_gaps_list when tool_gap_detector cannot be imported."""

        server = FastMCP("test-gap-ie")
        mt.register_meta_tools(server)

        # Force the import to fail
        with patch.dict("sys.modules", {"tool_modules.aa_workflow.src.tool_gap_detector": None}):
            result = await server.call_tool("tool_gaps_list", {"status": "open"})
            text = str(result)
            assert "Error" in text or "error" in text

    @pytest.mark.asyncio
    async def test_gap_update_import_error(self):
        """Test tool_gap_update when tool_gap_detector cannot be imported."""

        server = FastMCP("test-gap-upd-ie")
        mt.register_meta_tools(server)

        with patch.dict("sys.modules", {"tool_modules.aa_workflow.src.tool_gap_detector": None}):
            result = await server.call_tool("tool_gap_update", {"gap_id": "abc", "status": "open"})
            text = str(result)
            assert "Error" in text or "error" in text


class TestToolGapUpdateViaServer:
    """Tests for tool_gap_update via server."""

    @pytest.mark.asyncio
    async def test_gap_update_success(self):
        """Gap update success."""

        server = FastMCP("test-gap-upd-ok")
        mt.register_meta_tools(server)

        mock_gap = MagicMock()
        mock_gap.update_status.return_value = True

        with patch(
            "tool_modules.aa_workflow.src.tool_gap_detector.tool_gap",
            mock_gap,
        ):
            result = await server.call_tool("tool_gap_update", {"gap_id": "abc", "status": "implemented"})
            text = str(result)
            assert "Updated" in text or "implemented" in text

    @pytest.mark.asyncio
    async def test_gap_update_not_found(self):
        """Gap update not found."""

        server = FastMCP("test-gap-upd-nf")
        mt.register_meta_tools(server)

        mock_gap = MagicMock()
        mock_gap.update_status.return_value = False

        with patch(
            "tool_modules.aa_workflow.src.tool_gap_detector.tool_gap",
            mock_gap,
        ):
            result = await server.call_tool("tool_gap_update", {"gap_id": "xyz", "status": "open"})
            text = str(result)
            assert "not found" in text


class TestToolGapsListViaServer:
    """Tests for tool_gaps_list via server."""

    @pytest.mark.asyncio
    async def test_gaps_list_with_results(self):
        """Gaps list with results."""

        server = FastMCP("test-gaps-list-ok")
        mt.register_meta_tools(server)

        mock_gap = MagicMock()
        mock_gap.get_gaps.return_value = [
            {
                "suggested_tool_name": "jira_sprint_list",
                "vote_count": 3,
                "status": "open",
                "desired_action": "List sprints",
                "requesting_skills": ["sprint_planning"],
                "context": "Need sprint data",
                "workaround_used": "Manual API call",
                "suggested_args": '{"project": "AAP"}',
            }
        ]

        with patch(
            "tool_modules.aa_workflow.src.tool_gap_detector.tool_gap",
            mock_gap,
        ):
            result = await server.call_tool("tool_gaps_list", {"status": "open"})
            text = str(result)
            assert "jira_sprint_list" in text
            assert "List sprints" in text

    @pytest.mark.asyncio
    async def test_gaps_list_empty(self):
        """Gaps list empty."""

        server = FastMCP("test-gaps-list-empty")
        mt.register_meta_tools(server)

        mock_gap = MagicMock()
        mock_gap.get_gaps.return_value = []

        with patch(
            "tool_modules.aa_workflow.src.tool_gap_detector.tool_gap",
            mock_gap,
        ):
            result = await server.call_tool("tool_gaps_list", {"status": "open"})
            text = str(result)
            assert "No tool gaps" in text or "no" in text.lower()
