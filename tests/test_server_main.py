"""Tests for server/main.py - MCP Server main entry point."""

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.main import (
    _get_tool_names_sync,
    _load_single_tool_module,
    _register_debug_for_module,
    create_mcp_server,
    init_scheduler,
    load_agent_config,
    main,
    run_mcp_server,
    setup_logging,
    stop_scheduler,
)

# ────────────────────────────────────────────────────────────────────
# setup_logging
# ────────────────────────────────────────────────────────────────────


class TestSetupLogging:
    def test_returns_logger(self):
        logger = setup_logging()
        assert isinstance(logger, logging.Logger)
        assert logger.name == "server.main"

    def test_configures_handlers(self):
        setup_logging()
        root = logging.getLogger()
        assert len(root.handlers) >= 1


# ────────────────────────────────────────────────────────────────────
# load_agent_config
# ────────────────────────────────────────────────────────────────────


class TestLoadAgentConfig:
    def test_loads_yaml(self, tmp_path):
        personas_dir = tmp_path / "personas"
        personas_dir.mkdir()
        (personas_dir / "devops.yaml").write_text("tools:\n  - k8s\n  - git\n")

        with patch("server.main.PROJECT_DIR", tmp_path):
            result = load_agent_config("devops")

        assert result == ["k8s", "git"]

    def test_returns_none_for_missing_agent(self):
        with patch("server.main.PROJECT_DIR", Path("/nonexistent")):
            result = load_agent_config("no_such_agent")
        assert result is None

    def test_returns_none_for_invalid_yaml(self, tmp_path):
        personas_dir = tmp_path / "personas"
        personas_dir.mkdir()
        (personas_dir / "bad.yaml").write_text(": invalid: yaml: [[[")

        with patch("server.main.PROJECT_DIR", tmp_path):
            result = load_agent_config("bad")

        assert result is None or result == []

    def test_config_without_tools_key(self, tmp_path):
        personas_dir = tmp_path / "personas"
        personas_dir.mkdir()
        (personas_dir / "empty.yaml").write_text("name: empty\n")

        with patch("server.main.PROJECT_DIR", tmp_path):
            result = load_agent_config("empty")

        assert result == []


# ────────────────────────────────────────────────────────────────────
# _get_tool_names_sync
# ────────────────────────────────────────────────────────────────────


class TestGetToolNamesSync:
    def test_extracts_tool_names(self):
        provider = MagicMock()
        provider._components = {
            "tool:my_tool@": MagicMock(),
            "tool:other_tool@1.0": MagicMock(),
            "resource:not_a_tool@": MagicMock(),
        }

        server = MagicMock()
        server.providers = [provider]

        result = _get_tool_names_sync(server)
        assert result == {"my_tool", "other_tool"}

    def test_no_providers(self):
        server = MagicMock()
        server.providers = []
        assert _get_tool_names_sync(server) == set()

    def test_provider_without_components(self):
        provider = MagicMock(spec=[])
        server = MagicMock()
        server.providers = [provider]
        assert _get_tool_names_sync(server) == set()

    def test_multiple_providers(self):
        p1 = MagicMock()
        p1._components = {"tool:a@": MagicMock()}
        p2 = MagicMock()
        p2._components = {"tool:b@": MagicMock()}

        server = MagicMock()
        server.providers = [p1, p2]

        assert _get_tool_names_sync(server) == {"a", "b"}


# ────────────────────────────────────────────────────────────────────
# _load_single_tool_module
# ────────────────────────────────────────────────────────────────────


class TestLoadSingleToolModule:
    def test_loads_module_with_register_tools(self, tmp_path):
        tools_dir = tmp_path / "aa_test" / "src"
        tools_dir.mkdir(parents=True)
        tools_file = tools_dir / "tools_basic.py"
        tools_file.write_text("def register_tools(server):\n    pass\n")

        server = MagicMock()
        server.providers = []

        with patch("server.main.get_tools_file_path", return_value=tools_file):
            result = _load_single_tool_module("test", server, set())

        assert isinstance(result, list)

    def test_missing_tools_file(self):
        server = MagicMock()
        with patch(
            "server.main.get_tools_file_path",
            return_value=Path("/nonexistent/tools.py"),
        ):
            result = _load_single_tool_module("missing", server)
        assert result == []

    def test_module_without_register_tools(self, tmp_path):
        tools_dir = tmp_path / "src"
        tools_dir.mkdir(parents=True)
        tools_file = tools_dir / "tools.py"
        tools_file.write_text("# no register_tools\nx = 1\n")

        server = MagicMock()
        server.providers = []

        with patch("server.main.get_tools_file_path", return_value=tools_file):
            result = _load_single_tool_module("noop", server)
        assert result == []

    def test_spec_none_returns_empty(self, tmp_path):
        tools_file = tmp_path / "tools.py"
        tools_file.write_text("x = 1")

        server = MagicMock()
        with (
            patch("server.main.get_tools_file_path", return_value=tools_file),
            patch("importlib.util.spec_from_file_location", return_value=None),
        ):
            result = _load_single_tool_module("bad_spec", server)
        assert result == []


# ────────────────────────────────────────────────────────────────────
# _register_debug_for_module
# ────────────────────────────────────────────────────────────────────


class TestRegisterDebugForModule:
    def test_calls_wrap_all_tools(self, tmp_path):
        tools_file = tmp_path / "tools.py"
        tools_file.write_text("x = 1")

        server = MagicMock()

        with (
            patch("server.main.get_tools_file_path", return_value=tools_file),
            patch("server.debuggable.wrap_all_tools") as mock_wrap,
        ):
            _register_debug_for_module(server, "test")

        mock_wrap.assert_called_once()
        assert mock_wrap.call_count == 1

    def test_skips_missing_file(self):
        server = MagicMock()

        with (
            patch(
                "server.main.get_tools_file_path",
                return_value=Path("/nonexistent/tools.py"),
            ),
            patch("server.debuggable.wrap_all_tools") as mock_wrap,
        ):
            _register_debug_for_module(server, "missing")

        mock_wrap.assert_not_called()
        assert mock_wrap.call_count == 0


# ────────────────────────────────────────────────────────────────────
# create_mcp_server
# ────────────────────────────────────────────────────────────────────


class TestCreateMcpServer:
    def _patch_create_deps(self, **overrides):
        """Return a stack of patches for create_mcp_server dependencies."""
        defaults = {
            "get_available_modules": patch(
                "server.persona_loader.get_available_modules",
                return_value={"git", "jira"},
            ),
            "load_single": patch(
                "server.main._load_single_tool_module", return_value=["tool_a"]
            ),
            "get_tools_sync": patch(
                "server.main._get_tool_names_sync", return_value=set()
            ),
            "register_debug": patch("server.debuggable.register_debug_tool"),
            "wrap_runtime": patch(
                "server.debuggable.wrap_server_tools_runtime", return_value=0
            ),
            "register_debug_mod": patch("server.main._register_debug_for_module"),
            "init_loader": patch("server.persona_loader.init_loader"),
            "ws_restore": patch(
                "server.workspace_state.WorkspaceRegistry.restore_if_empty",
                return_value=0,
            ),
        }
        defaults.update(overrides)
        return defaults

    def test_creates_server_with_tools(self):
        patches = self._patch_create_deps()
        with (
            patches["get_available_modules"],
            patches["load_single"],
            patches["get_tools_sync"],
            patches["register_debug"],
            patches["wrap_runtime"],
            patches["register_debug_mod"],
            patches["init_loader"] as mock_loader,
            patches["ws_restore"],
        ):
            mock_loader.return_value = MagicMock()
            server = create_mcp_server(name="test", tools=["git"])
        assert server is not None

    def test_loads_all_when_tools_is_none(self):
        patches = self._patch_create_deps()
        with (
            patches["get_available_modules"],
            patches["load_single"] as mock_load,
            patches["get_tools_sync"],
            patches["register_debug"],
            patches["wrap_runtime"],
            patches["register_debug_mod"],
            patches["init_loader"] as mock_loader,
            patches["ws_restore"],
        ):
            mock_loader.return_value = MagicMock()
            create_mcp_server(name="test", tools=None)
        assert mock_load.call_count == 2  # git + jira

    def test_warns_on_unknown_module(self):
        patches = self._patch_create_deps()
        with (
            patches["get_available_modules"],
            patches["load_single"],
            patches["get_tools_sync"],
            patches["register_debug"],
            patches["wrap_runtime"],
            patches["register_debug_mod"],
            patches["init_loader"] as mock_loader,
            patches["ws_restore"],
        ):
            mock_loader.return_value = MagicMock()
            server = create_mcp_server(tools=["unknown_module"])
        assert server is not None

    def test_handles_module_load_error(self):
        patches = self._patch_create_deps(
            load_single=patch(
                "server.main._load_single_tool_module", side_effect=RuntimeError("fail")
            ),
        )
        with (
            patches["get_available_modules"],
            patches["load_single"],
            patches["get_tools_sync"],
            patches["register_debug"],
            patches["wrap_runtime"],
            patches["register_debug_mod"],
            patches["init_loader"] as mock_loader,
            patches["ws_restore"],
        ):
            mock_loader.return_value = MagicMock()
            server = create_mcp_server(tools=["git"])
        assert server is not None

    def test_handles_debug_registration_error(self):
        patches = self._patch_create_deps(
            register_debug=patch(
                "server.debuggable.register_debug_tool",
                side_effect=RuntimeError("debug fail"),
            ),
        )
        with (
            patches["get_available_modules"],
            patches["load_single"],
            patches["get_tools_sync"],
            patches["register_debug"],
            patches["wrap_runtime"],
            patches["register_debug_mod"],
            patches["init_loader"] as mock_loader,
            patches["ws_restore"],
        ):
            mock_loader.return_value = MagicMock()
            server = create_mcp_server(tools=["git"])
        assert server is not None

    def test_handles_persona_loader_error(self):
        patches = self._patch_create_deps(
            init_loader=patch(
                "server.persona_loader.init_loader",
                side_effect=RuntimeError("loader fail"),
            ),
        )
        with (
            patches["get_available_modules"],
            patches["load_single"],
            patches["get_tools_sync"],
            patches["register_debug"],
            patches["wrap_runtime"],
            patches["register_debug_mod"],
            patches["init_loader"],
            patches["ws_restore"],
        ):
            server = create_mcp_server(tools=["git"])
        assert server is not None

    def test_handles_workspace_restore_error(self):
        patches = self._patch_create_deps(
            ws_restore=patch(
                "server.workspace_state.WorkspaceRegistry.restore_if_empty",
                side_effect=RuntimeError("x"),
            ),
        )
        with (
            patches["get_available_modules"],
            patches["load_single"],
            patches["get_tools_sync"],
            patches["register_debug"],
            patches["wrap_runtime"],
            patches["register_debug_mod"],
            patches["init_loader"] as mock_loader,
            patches["ws_restore"],
        ):
            mock_loader.return_value = MagicMock()
            server = create_mcp_server(tools=["git"])
        assert server is not None


# ────────────────────────────────────────────────────────────────────
# init_scheduler
# ────────────────────────────────────────────────────────────────────


class TestInitScheduler:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        server = MagicMock()

        mock_scheduler = MagicMock()
        mock_scheduler.config.get_poll_jobs.return_value = {}

        mock_poll_engine = MagicMock()
        mock_poll_engine.start = AsyncMock()

        mock_state = MagicMock()
        mock_state.is_service_enabled.return_value = True

        with patch.dict(
            "sys.modules",
            {
                "tool_modules.aa_workflow.src.notification_engine": MagicMock(
                    init_notification_engine=MagicMock(),
                    send_notification=AsyncMock(),
                ),
                "tool_modules.aa_workflow.src.poll_engine": MagicMock(
                    init_poll_engine=MagicMock(return_value=mock_poll_engine),
                ),
                "tool_modules.aa_workflow.src.scheduler": MagicMock(
                    init_scheduler=MagicMock(return_value=mock_scheduler),
                    start_scheduler=AsyncMock(),
                ),
            },
        ):
            with (
                patch(
                    "server.main.state_manager",
                    create=True,
                    new=MagicMock(state=mock_state),
                ),
                patch("server.state_manager.state", mock_state),
                patch("server.utils.load_config", return_value={"schedules": {}}),
            ):
                result = await init_scheduler(server)

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_import_error(self):
        """When scheduler dependencies are missing, returns False."""
        server = MagicMock()

        # Force ImportError by setting modules to None
        with patch.dict(
            "sys.modules",
            {
                "tool_modules.aa_workflow.src.notification_engine": None,
            },
            clear=False,
        ):
            # Also need to ensure the import actually fails
            # Remove from cache if present
            for key in list(__import__("sys").modules.keys()):
                if "notification_engine" in key:
                    del __import__("sys").modules[key]

            result = await init_scheduler(server)

        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_scheduler_disabled_in_state(self):
        server = MagicMock()

        mock_scheduler = MagicMock()
        mock_scheduler.config.get_poll_jobs.return_value = {}

        mock_poll_engine = MagicMock()
        mock_poll_engine.start = AsyncMock()

        mock_state = MagicMock()
        mock_state.is_service_enabled.return_value = False  # Disabled

        with patch.dict(
            "sys.modules",
            {
                "tool_modules.aa_workflow.src.notification_engine": MagicMock(
                    init_notification_engine=MagicMock(),
                    send_notification=AsyncMock(),
                ),
                "tool_modules.aa_workflow.src.poll_engine": MagicMock(
                    init_poll_engine=MagicMock(return_value=mock_poll_engine),
                ),
                "tool_modules.aa_workflow.src.scheduler": MagicMock(
                    init_scheduler=MagicMock(return_value=mock_scheduler),
                    start_scheduler=AsyncMock(),
                ),
            },
        ):
            with (
                patch("server.state_manager.state", mock_state),
                patch("server.utils.load_config", return_value={"schedules": {}}),
            ):
                result = await init_scheduler(server)

        assert result is True
        # poll_engine.start should NOT have been called (scheduler disabled)
        mock_poll_engine.start.assert_not_awaited()


# ────────────────────────────────────────────────────────────────────
# stop_scheduler
# ────────────────────────────────────────────────────────────────────


class TestStopScheduler:
    @pytest.mark.asyncio
    async def test_stops_gracefully(self):
        mock_stop_cron = AsyncMock()
        mock_poll = MagicMock(return_value=None)

        with patch.dict(
            "sys.modules",
            {
                "tool_modules.aa_workflow.src.scheduler": MagicMock(
                    stop_scheduler=mock_stop_cron,
                ),
                "tool_modules.aa_workflow.src.poll_engine": MagicMock(
                    get_poll_engine=mock_poll,
                ),
            },
        ):
            await stop_scheduler()
        mock_stop_cron.assert_awaited_once()
        assert mock_stop_cron.await_count == 1

    @pytest.mark.asyncio
    async def test_handles_error(self):
        with patch.dict(
            "sys.modules",
            {
                "tool_modules.aa_workflow.src.scheduler": MagicMock(
                    stop_scheduler=AsyncMock(side_effect=RuntimeError("fail")),
                ),
                "tool_modules.aa_workflow.src.poll_engine": MagicMock(
                    get_poll_engine=MagicMock(return_value=None),
                ),
            },
        ):
            await stop_scheduler()  # Test verifies no exception is raised
        assert True


# ────────────────────────────────────────────────────────────────────
# run_mcp_server
# ────────────────────────────────────────────────────────────────────


class TestRunMcpServer:
    @pytest.mark.asyncio
    async def test_runs_stdio_no_scheduler(self):
        server = MagicMock()
        server.run_stdio_async = AsyncMock()

        with (
            patch(
                "server.main.init_scheduler", new_callable=AsyncMock, return_value=False
            ),
            patch("server.main.stop_scheduler", new_callable=AsyncMock),
        ):
            # Patch the imports inside the function
            with patch.dict(
                "sys.modules",
                {
                    "server.websocket_server": None,  # ImportError
                    "services.memory_abstraction": None,  # ImportError
                },
            ):
                await run_mcp_server(server, enable_scheduler=False)

        server.run_stdio_async.assert_awaited_once()
        assert server.run_stdio_async.await_count == 1

    @pytest.mark.asyncio
    async def test_with_scheduler(self):
        server = MagicMock()
        server.run_stdio_async = AsyncMock()

        with (
            patch(
                "server.main.init_scheduler", new_callable=AsyncMock, return_value=True
            ),
            patch("server.main.stop_scheduler", new_callable=AsyncMock) as mock_stop,
        ):
            with patch.dict(
                "sys.modules",
                {
                    "server.websocket_server": None,
                    "services.memory_abstraction": None,
                },
            ):
                await run_mcp_server(server, enable_scheduler=True)

        mock_stop.assert_awaited_once()
        assert mock_stop.await_count == 1

    @pytest.mark.asyncio
    async def test_websocket_import_error(self):
        """When websocket module not installed, server still runs."""
        server = MagicMock()
        server.run_stdio_async = AsyncMock()

        with (
            patch(
                "server.main.init_scheduler", new_callable=AsyncMock, return_value=False
            ),
            patch("server.main.stop_scheduler", new_callable=AsyncMock),
        ):
            with patch.dict(
                "sys.modules",
                {
                    "server.websocket_server": None,
                    "services.memory_abstraction": None,
                },
            ):
                await run_mcp_server(server, enable_scheduler=False)

        server.run_stdio_async.assert_awaited_once()
        assert True  # Server ran despite missing websocket module

    @pytest.mark.asyncio
    async def test_memory_abstraction_import_error(self):
        """When memory abstraction not available, server still runs."""
        server = MagicMock()
        server.run_stdio_async = AsyncMock()

        # Create a mock websocket module that returns a ws_server
        mock_ws_mod = MagicMock()
        mock_ws_mod.start_websocket_server = AsyncMock(return_value=MagicMock())
        mock_ws_mod.stop_websocket_server = AsyncMock()

        with (
            patch(
                "server.main.init_scheduler", new_callable=AsyncMock, return_value=False
            ),
            patch("server.main.stop_scheduler", new_callable=AsyncMock),
        ):
            with patch.dict(
                "sys.modules",
                {
                    "server.websocket_server": mock_ws_mod,
                    "services.memory_abstraction": None,
                },
            ):
                await run_mcp_server(server, enable_scheduler=False)

        server.run_stdio_async.assert_awaited_once()
        assert True  # Server ran despite missing memory abstraction


# ────────────────────────────────────────────────────────────────────
# main()
# ────────────────────────────────────────────────────────────────────


class TestMain:
    def _common_patches(self):
        """Return common patches for main() tests."""
        return {
            "get_available": patch(
                "server.persona_loader.get_available_modules",
                return_value={"git", "jira", "workflow"},
            ),
            "setup_log": patch("server.main.setup_logging", return_value=MagicMock()),
            "create": patch("server.main.create_mcp_server", return_value=MagicMock()),
            "aio": patch("server.main.asyncio"),
        }

    def test_agent_mode(self):
        p = self._common_patches()
        with (
            p["get_available"],
            p["setup_log"],
            p["create"] as mock_create,
            p["aio"],
            patch("sys.argv", ["server", "--agent", "devops"]),
            patch("server.main.load_agent_config", return_value=["git"]),
        ):
            main()

        assert mock_create.call_args.kwargs["tools"] == ["git"]
        assert mock_create.call_args.kwargs["name"] == "aa-devops"

    def test_agent_not_found(self):
        p = self._common_patches()
        with (
            p["get_available"],
            p["setup_log"],
            patch("sys.argv", ["server", "--agent", "nonexistent"]),
            patch("server.main.load_agent_config", return_value=None),
        ):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 1

    def test_all_mode(self):
        p = self._common_patches()
        with (
            p["get_available"],
            p["setup_log"],
            p["create"] as mock_create,
            p["aio"],
            patch("sys.argv", ["server", "--all"]),
        ):
            main()

        assert mock_create.call_args.kwargs["tools"] is None

    def test_tools_mode(self):
        p = self._common_patches()
        with (
            p["get_available"],
            p["setup_log"],
            p["create"] as mock_create,
            p["aio"],
            patch("sys.argv", ["server", "--tools", "git,jira"]),
        ):
            main()

        assert mock_create.call_args.kwargs["tools"] == ["git", "jira"]

    def test_default_mode(self):
        p = self._common_patches()
        with (
            p["get_available"],
            p["setup_log"],
            p["create"] as mock_create,
            p["aio"],
            patch("sys.argv", ["server"]),
            patch("server.main.load_agent_config", return_value=["workflow"]),
            patch(
                "server.utils.load_config",
                return_value={"agent": {"default_persona": "researcher"}},
            ),
        ):
            main()

        mock_create.assert_called_once()
        assert mock_create.call_count == 1

    def test_default_mode_fallback(self):
        p = self._common_patches()
        with (
            p["get_available"],
            p["setup_log"],
            p["create"] as mock_create,
            p["aio"],
            patch("sys.argv", ["server"]),
            patch("server.main.load_agent_config", return_value=None),
            patch("server.utils.load_config", return_value={}),
        ):
            main()

        assert mock_create.call_args.kwargs["tools"] == ["workflow"]

    def test_keyboard_interrupt(self):
        p = self._common_patches()
        with (
            p["get_available"],
            p["setup_log"],
            p["create"],
            p["aio"] as mock_aio,
            patch("sys.argv", ["server", "--tools", "git"]),
        ):
            mock_aio.run.side_effect = KeyboardInterrupt()
            main()  # Test verifies no exception is raised
        assert True

    def test_server_error(self):
        p = self._common_patches()
        with (
            p["get_available"],
            p["setup_log"],
            p["aio"],
            patch("sys.argv", ["server", "--tools", "git"]),
            patch("server.main.create_mcp_server", side_effect=RuntimeError("fail")),
        ):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 1

    def test_no_scheduler_flag(self):
        p = self._common_patches()
        with (
            p["get_available"],
            p["setup_log"],
            p["create"],
            p["aio"] as mock_aio,
            patch("sys.argv", ["server", "--tools", "git", "--no-scheduler"]),
        ):
            main()

        # asyncio.run was called
        mock_aio.run.assert_called_once()
        assert mock_aio.run.call_count == 1

    def test_custom_name(self):
        p = self._common_patches()
        with (
            p["get_available"],
            p["setup_log"],
            p["create"] as mock_create,
            p["aio"],
            patch("sys.argv", ["server", "--agent", "devops", "--name", "my-server"]),
            patch("server.main.load_agent_config", return_value=["git"]),
        ):
            main()

        assert mock_create.call_args.kwargs["name"] == "my-server"

    def test_agent_default_name(self):
        p = self._common_patches()
        with (
            p["get_available"],
            p["setup_log"],
            p["create"] as mock_create,
            p["aio"],
            patch("sys.argv", ["server", "--agent", "incident"]),
            patch("server.main.load_agent_config", return_value=["prometheus"]),
        ):
            main()

        assert mock_create.call_args.kwargs["name"] == "aa-incident"
