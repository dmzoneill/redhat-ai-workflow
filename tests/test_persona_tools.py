"""Tests for tool_modules/aa_workflow/src/persona_tools.py - Persona management tools."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Context, FastMCP

# ==================== _list_personas_impl ====================


class TestListPersonasImpl:
    """Tests for _list_personas_impl."""

    def test_no_personas_dir(self):
        from tool_modules.aa_workflow.src.persona_tools import _list_personas_impl

        with patch(
            "tool_modules.aa_workflow.src.persona_tools.PERSONAS_DIR"
        ) as mock_dir:
            mock_dir.exists.return_value = False
            result = _list_personas_impl()
            assert len(result) == 1
            assert "No personas found" in result[0].text

    def test_empty_personas_dir(self):
        from tool_modules.aa_workflow.src.persona_tools import _list_personas_impl

        with patch(
            "tool_modules.aa_workflow.src.persona_tools.PERSONAS_DIR"
        ) as mock_dir:
            mock_dir.exists.return_value = True
            mock_dir.glob.return_value = []
            result = _list_personas_impl()
            assert len(result) == 1
            assert "No personas found" in result[0].text

    def test_skips_readme(self):
        from tool_modules.aa_workflow.src.persona_tools import _list_personas_impl

        with patch(
            "tool_modules.aa_workflow.src.persona_tools.PERSONAS_DIR"
        ) as mock_dir:
            mock_dir.exists.return_value = True
            readme = MagicMock(spec=Path)
            readme.name = "README.md"
            readme.stem = "README"
            mock_dir.glob.return_value = [readme]
            result = _list_personas_impl()
            assert len(result) == 1
            assert "No personas found" in result[0].text

    def test_lists_persona_with_heading_and_role(self):
        from tool_modules.aa_workflow.src.persona_tools import _list_personas_impl

        with patch(
            "tool_modules.aa_workflow.src.persona_tools.PERSONAS_DIR"
        ) as mock_dir:
            mock_dir.exists.return_value = True
            persona_file = MagicMock(spec=Path)
            persona_file.name = "devops.md"
            persona_file.stem = "devops"
            persona_file.read_text.return_value = (
                "# DevOps Engineer\n\n## Your Role\n- Deploy and manage infrastructure"
            )
            mock_dir.glob.return_value = [persona_file]

            result = _list_personas_impl()
            assert len(result) == 1
            text = result[0].text
            assert "DevOps Engineer" in text
            assert "`devops`" in text
            assert "Deploy and manage infrastructure" in text

    def test_lists_persona_no_role_section(self):
        from tool_modules.aa_workflow.src.persona_tools import _list_personas_impl

        with patch(
            "tool_modules.aa_workflow.src.persona_tools.PERSONAS_DIR"
        ) as mock_dir:
            mock_dir.exists.return_value = True
            persona_file = MagicMock(spec=Path)
            persona_file.name = "dev.md"
            persona_file.stem = "dev"
            persona_file.read_text.return_value = "# Developer\nSome content"
            mock_dir.glob.return_value = [persona_file]

            result = _list_personas_impl()
            assert len(result) == 1
            assert "Developer" in result[0].text

    def test_handles_read_error(self):
        from tool_modules.aa_workflow.src.persona_tools import _list_personas_impl

        with patch(
            "tool_modules.aa_workflow.src.persona_tools.PERSONAS_DIR"
        ) as mock_dir:
            mock_dir.exists.return_value = True
            bad_file = MagicMock(spec=Path)
            bad_file.name = "broken.md"
            bad_file.stem = "broken"
            bad_file.read_text.side_effect = IOError("Permission denied")
            mock_dir.glob.return_value = [bad_file]

            result = _list_personas_impl()
            assert len(result) == 1
            assert "Error" in result[0].text

    def test_multiple_personas(self):
        from tool_modules.aa_workflow.src.persona_tools import _list_personas_impl

        with patch(
            "tool_modules.aa_workflow.src.persona_tools.PERSONAS_DIR"
        ) as mock_dir:
            mock_dir.exists.return_value = True
            f1 = MagicMock(spec=Path)
            f1.name = "dev.md"
            f1.stem = "dev"
            f1.read_text.return_value = "# Developer\n## Your Role\n- Write code"

            f2 = MagicMock(spec=Path)
            f2.name = "ops.md"
            f2.stem = "ops"
            f2.read_text.return_value = "# Operations\n## Your Role\n- Manage infra"

            mock_dir.glob.return_value = [f1, f2]

            result = _list_personas_impl()
            assert len(result) == 1
            assert "Developer" in result[0].text
            assert "Operations" in result[0].text
            assert "persona_load" in result[0].text


# ==================== _load_persona_impl ====================


class TestLoadPersonaImpl:
    """Tests for _load_persona_impl."""

    @pytest.mark.asyncio
    async def test_dynamic_load_success(self):
        from tool_modules.aa_workflow.src.persona_tools import _load_persona_impl

        ctx = MagicMock(spec=Context)

        with patch("tool_modules.aa_workflow.src.persona_tools.PERSONAS_DIR"):
            with patch("tool_modules.aa_workflow.src.persona_tools.sys") as mock_sys:
                mock_sys.path = []
                with patch("server.persona_loader.get_loader") as mock_get_loader:
                    mock_loader = AsyncMock()
                    mock_loader.switch_persona.return_value = {
                        "success": True,
                        "description": "DevOps persona",
                        "modules_loaded": ["bonfire", "k8s"],
                        "tool_count": 10,
                        "persona": "You are a DevOps engineer.",
                    }
                    mock_get_loader.return_value = mock_loader

                    result = await _load_persona_impl("devops", ctx)
                    assert len(result) == 1
                    assert "Persona Loaded" in result[0].text
                    assert "devops" in result[0].text
                    assert "10" in result[0].text

    @pytest.mark.asyncio
    async def test_dynamic_load_failure(self):
        from tool_modules.aa_workflow.src.persona_tools import _load_persona_impl

        ctx = MagicMock(spec=Context)

        with patch("tool_modules.aa_workflow.src.persona_tools.PERSONAS_DIR"):
            with patch("server.persona_loader.get_loader") as mock_get_loader:
                mock_loader = AsyncMock()
                mock_loader.switch_persona.return_value = {
                    "success": False,
                    "error": "Unknown persona",
                    "available": ["devops", "developer"],
                }
                mock_get_loader.return_value = mock_loader

                result = await _load_persona_impl("nonexistent", ctx)
                assert len(result) == 1
                assert "Unknown persona" in result[0].text
                assert "devops" in result[0].text

    @pytest.mark.asyncio
    async def test_fallback_static_mode(self):
        from tool_modules.aa_workflow.src.persona_tools import _load_persona_impl

        ctx = MagicMock(spec=Context)

        with patch(
            "tool_modules.aa_workflow.src.persona_tools.PERSONAS_DIR"
        ) as mock_dir:
            # Make dynamic loading fail
            with patch(
                "server.persona_loader.get_loader",
                side_effect=ImportError("Not available"),
            ):
                persona_file = MagicMock(spec=Path)
                persona_file.exists.return_value = True
                persona_file.read_text.return_value = (
                    "# DevOps\nYou are a devops engineer."
                )
                mock_dir.__truediv__ = MagicMock(return_value=persona_file)

                result = await _load_persona_impl("devops", ctx)
                assert len(result) == 1
                assert "Static mode" in result[0].text
                assert "DevOps" in result[0].text

    @pytest.mark.asyncio
    async def test_fallback_persona_not_found(self):
        from tool_modules.aa_workflow.src.persona_tools import _load_persona_impl

        ctx = MagicMock(spec=Context)

        with patch(
            "tool_modules.aa_workflow.src.persona_tools.PERSONAS_DIR"
        ) as mock_dir:
            with patch(
                "server.persona_loader.get_loader",
                side_effect=ImportError("Not available"),
            ):
                persona_file = MagicMock(spec=Path)
                persona_file.exists.return_value = False
                mock_dir.__truediv__ = MagicMock(return_value=persona_file)

                result = await _load_persona_impl("nonexistent", ctx)
                assert len(result) == 1
                assert "not found" in result[0].text

    @pytest.mark.asyncio
    async def test_fallback_read_error(self):
        from tool_modules.aa_workflow.src.persona_tools import _load_persona_impl

        ctx = MagicMock(spec=Context)

        with patch(
            "tool_modules.aa_workflow.src.persona_tools.PERSONAS_DIR"
        ) as mock_dir:
            with patch(
                "server.persona_loader.get_loader",
                side_effect=ImportError("Not available"),
            ):
                persona_file = MagicMock(spec=Path)
                persona_file.exists.return_value = True
                persona_file.read_text.side_effect = IOError("Cannot read")
                mock_dir.__truediv__ = MagicMock(return_value=persona_file)

                result = await _load_persona_impl("broken", ctx)
                assert len(result) == 1
                assert "Error" in result[0].text


# ==================== register_persona_tools ====================


class TestRegisterPersonaTools:
    """Tests for register_persona_tools."""

    def test_registers_two_tools(self):
        from tool_modules.aa_workflow.src.persona_tools import register_persona_tools

        server = MagicMock(spec=FastMCP)
        # ToolRegistry wraps server.tool - we need to mock that
        server.tool = MagicMock(return_value=lambda fn: fn)

        with patch(
            "tool_modules.aa_workflow.src.persona_tools.ToolRegistry"
        ) as MockRegistry:
            mock_registry = MagicMock()
            mock_registry.tool.return_value = lambda fn: fn
            mock_registry.count = 2
            MockRegistry.return_value = mock_registry

            count = register_persona_tools(server)
            assert count == 2
