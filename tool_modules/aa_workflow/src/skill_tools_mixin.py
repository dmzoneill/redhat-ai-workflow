# pylint: disable=duplicate-code,cyclic-import
"""Split from skill_engine.py so the public module stays importable."""  # pylint: disable=cyclic-import

import json
import logging
import sys
from typing import Any

from fastmcp import FastMCP

from .skill_paths import tool_modules_dir
from .skill_support import (
    _get_agent_stats_module,
)

logger = logging.getLogger(__name__)


class SkillToolMixin:  # pylint: disable=too-few-public-methods
    """SkillExecutor behavior split out of skill_engine."""

    # Declared for mixins that read sibling state.
    _debug: Any
    _determine_fix_type: Any
    _try_auto_fix: Any
    event_emitter: Any
    server: Any

    def _get_module_for_tool(self, tool_name: str) -> str | None:
        """Map tool name to module name using the discovery system."""
        from server.tool_discovery import (  # pylint: disable=import-outside-toplevel
            get_module_for_tool,
        )

        return get_module_for_tool(tool_name)

    def _format_tool_result(self, result, duration: float) -> dict:
        """Format tool execution result into standard dict.

        Detects error indicators in the result text to properly set success=False
        for tools that return error messages instead of raising exceptions.
        """
        if isinstance(result, tuple):
            result = result[0]

        # Handle FastMCP ToolResult objects
        if hasattr(result, "content") and isinstance(result.content, list):
            # ToolResult from FastMCP - extract text from content
            if result.content and hasattr(result.content[0], "text"):
                text = result.content[0].text
            else:
                text = str(result)
        elif isinstance(result, list) and result:
            text = result[0].text if hasattr(result[0], "text") else str(result[0])
        else:
            text = str(result)

        # Check for error indicators in the result text
        # Tools often return error messages with these prefixes instead of raising
        text_lower = text.lower()
        is_error = (
            text.startswith("❌")
            or text_lower.startswith("error:")
            or "❌ error" in text_lower
            or "❌ failed" in text_lower
            or "connection may have failed" in text_lower
            or "script not found" in text_lower
        )

        return {"success": not is_error, "result": text, "duration": duration}

    async def _execute_workflow_tool(
        self, tool_name: str, args: dict, start_time: float
    ) -> dict:
        """Execute a tool from the workflow module."""
        import time  # pylint: disable=import-outside-toplevel

        try:
            if self.server is None:
                raise RuntimeError("No server available for tool execution")
            result = await self.server.call_tool(tool_name, args)
            duration = time.time() - start_time
            duration_ms = int(duration * 1000)
            self._debug(f"  → Completed in {duration:.2f}s")

            # Record tool call stats
            try:
                agent_stats = _get_agent_stats_module()
                agent_stats.record_tool_call(tool_name, True, duration_ms)
            except Exception as stats_err:  # pylint: disable=broad-exception-caught
                logger.debug("Failed to record tool stats: %s", stats_err)

            return self._format_tool_result(result, duration)
        except Exception as e:  # pylint: disable=broad-exception-caught
            # Record failed tool call
            try:
                agent_stats = _get_agent_stats_module()
                agent_stats.record_tool_call(tool_name, False, 0)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.debug("Suppressed error: %s", exc)
            return {"success": False, "error": str(e)}

    async def _load_and_execute_module_tool(  # pylint: disable=too-many-locals
        self, module: str, tool_name: str, args: dict, start_time: float
    ) -> dict:
        """Load a tool module and execute the specified tool."""
        import importlib.util  # pylint: disable=import-outside-toplevel
        import time  # pylint: disable=import-outside-toplevel
        import types  # pylint: disable=import-outside-toplevel

        self._debug(f"  → Loading module: {module}")
        self._debug(f"  → tool_modules_dir(): {tool_modules_dir()}")

        # Try tools_basic.py first (new structure), then tools.py (legacy)
        tools_file = tool_modules_dir() / f"aa_{module}" / "src" / "tools_basic.py"
        self._debug(f"  → Trying: {tools_file} (exists: {tools_file.exists()})")
        if not tools_file.exists():
            tools_file = tool_modules_dir() / f"aa_{module}" / "src" / "tools.py"
            self._debug(f"  → Fallback: {tools_file} (exists: {tools_file.exists()})")

        if not tools_file.exists():
            return {
                "success": False,
                # pylint: disable-next=line-too-long
                "error": f"Module not found: {module} (checked {tool_modules_dir() / f'aa_{module}' / 'src'})",
            }

        try:
            temp_server = FastMCP(f"skill-{module}")

            # Set up parent package chain so relative imports work
            # (e.g., "from .common import run_glab" in aa_gitlab/src/tools_basic.py)
            # Without this, modules loaded via spec_from_file_location have no
            # __package__ context and relative imports fail with:
            # "attempted relative import with no known parent package"
            pkg_name = f"tool_modules.aa_{module}.src"
            parts = pkg_name.split(".")
            for i in range(1, len(parts) + 1):
                partial = ".".join(parts[:i])
                if partial not in sys.modules:
                    stub = types.ModuleType(partial)
                    stub.__package__ = partial
                    stub.__path__ = [
                        str(tool_modules_dir().parent / partial.replace(".", "/"))
                    ]
                    sys.modules[partial] = stub

            full_module_name = f"{pkg_name}.{tools_file.stem}"

            # Reuse already-loaded modules to preserve in-memory state
            # (e.g. HTTP sessions stored in module-level dicts).
            # Without this, each skill step re-executes the module which
            # resets module globals like _http_sessions = {}.
            if full_module_name in sys.modules:
                loaded_module = sys.modules[full_module_name]
                self._debug(f"  → Reusing already-loaded module: {full_module_name}")
            else:
                spec = importlib.util.spec_from_file_location(
                    full_module_name, tools_file
                )
                if spec is None or spec.loader is None:
                    return {"success": False, "error": f"Could not load: {module}"}

                loaded_module = importlib.util.module_from_spec(spec)
                loaded_module.__package__ = pkg_name
                sys.modules[full_module_name] = loaded_module
                spec.loader.exec_module(loaded_module)

            if hasattr(loaded_module, "register_tools"):
                loaded_module.register_tools(temp_server)

            result = await temp_server.call_tool(tool_name, args)
            duration = time.time() - start_time
            duration_ms = int(duration * 1000)
            self._debug(f"  → Completed in {duration:.2f}s")

            # Record tool call stats
            try:
                agent_stats = _get_agent_stats_module()
                agent_stats.record_tool_call(tool_name, True, duration_ms)
            except Exception as stats_err:  # pylint: disable=broad-exception-caught
                logger.debug("Failed to record tool stats: %s", stats_err)

            return self._format_tool_result(result, duration)

        except Exception as e:  # pylint: disable=broad-exception-caught
            # Record failed tool call
            try:
                agent_stats = _get_agent_stats_module()
                agent_stats.record_tool_call(tool_name, False, 0)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.debug("Suppressed error: %s", exc)
            return {
                "success": False,
                "error": str(e),
                "_temp_server": temp_server if "temp_server" in locals() else None,
            }

    async def _exec_tool(  # pylint: disable=too-many-locals
        self, tool_name: str, args: dict
    ) -> dict:  # pylint: disable=too-many-locals
        """Execute a tool and return its result."""
        import time  # pylint: disable=import-outside-toplevel

        start = time.time()

        self._debug(f"Calling tool: {tool_name}")
        self._debug(f"  → Args: {json.dumps(args)[:200]}")

        module = self._get_module_for_tool(tool_name)
        if not module:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

        # Execute workflow tools directly through server
        if module == "workflow" and self.server:
            return await self._execute_workflow_tool(tool_name, args, start)

        # Execute other module tools with error recovery
        result = await self._load_and_execute_module_tool(
            module, tool_name, args, start
        )

        # If there was an error, try auto-fix and retry
        if not result.get("success"):  # pylint: disable=too-many-nested-blocks
            # Error message can be in 'error' key or 'result' key (for tools that return error text)
            error_msg = result.get("error") or result.get("result", "Unknown error")
            temp_server = result.get("_temp_server")

            if temp_server:
                self._debug(f"  → Error: {error_msg}")

                # Look up through skill_engine so tests can patch those names.
                # isort: off
                from tool_modules.aa_workflow.src import (  # pylint: disable=import-outside-toplevel
                    skill_engine as engine,
                )

                # isort: on
                # pylint: disable-next=protected-access
                matches = engine._check_known_issues_sync(
                    tool_name=tool_name, error_text=error_msg
                )
                # pylint: disable-next=protected-access
                known_text = engine._format_known_issues(matches)

                if matches:
                    self._debug(
                        f"  → Found {len(matches)} known issue(s), attempting auto-fix"
                    )
                    fix_applied = await self._try_auto_fix(error_msg, matches)

                    if fix_applied:
                        self._debug("  → Auto-fix applied, retrying tool")
                        # Emit auto-heal event
                        if self.event_emitter:
                            fix_type = self._determine_fix_type(
                                error_msg.lower(), None, matches
                            )
                            self.event_emitter.auto_heal(
                                self.event_emitter.current_step_index,
                                f"Applied {fix_type or 'auto'} fix for: {error_msg[:50]}",
                            )
                        try:
                            # Emit retry event
                            if self.event_emitter:
                                self.event_emitter.retry(
                                    self.event_emitter.current_step_index,
                                    1,  # First retry
                                )
                            retry_result = await temp_server.call_tool(tool_name, args)
                            duration = time.time() - start
                            duration_ms = int(duration * 1000)
                            self._debug(f"  → Retry completed in {duration:.2f}s")

                            # Record successful retry
                            try:
                                agent_stats = _get_agent_stats_module()
                                agent_stats.record_tool_call(
                                    tool_name, True, duration_ms
                                )
                            except (
                                Exception  # pylint: disable=broad-exception-caught
                            ) as exc:  # pylint: disable=broad-exception-caught
                                logger.debug("Suppressed error: %s", exc)

                            return self._format_tool_result(retry_result, duration)
                        except (
                            Exception  # pylint: disable=broad-exception-caught
                        ) as retry_e:  # pylint: disable=broad-exception-caught
                            # pylint: disable-next=line-too-long
                            error_msg = f"{error_msg}\n\n(Retry after auto-fix also failed: {retry_e})"

                if known_text:
                    error_msg = f"{error_msg}\n{known_text}"

                result["error"] = error_msg

        # Remove internal _temp_server key if present
        result.pop("_temp_server", None)
        return result
