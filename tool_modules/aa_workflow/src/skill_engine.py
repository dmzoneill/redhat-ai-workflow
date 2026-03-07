"""Skill Execution Engine - Multi-step workflow execution.

Provides:
- skill_list: List available skills
- skill_run: Execute a skill
- SkillExecutor: Class that handles step-by-step execution

This module is workspace-aware: skill execution context includes workspace_uri
for proper isolation of skill state and events per workspace.
"""

import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml
from fastmcp import Context, FastMCP
from mcp.types import TextContent

from server.tool_registry import ToolRegistry
from server.utils import load_config

try:
    from .constants import SKILLS_DIR, TOOL_MODULES_DIR
    from .known_issues import check_known_issues_sync as _check_known_issues_sync
    from .known_issues import format_known_issues as _format_known_issues
    from .skill_error_recovery import ErrorRecoveryMixin
    from .skill_safety import SprintSafetyGuard  # noqa: F401
    from .skill_template import TemplateEngineMixin
except ImportError:
    from known_issues import check_known_issues_sync as _check_known_issues_sync
    from known_issues import format_known_issues as _format_known_issues
    from skill_error_recovery import ErrorRecoveryMixin
    from skill_safety import SprintSafetyGuard  # noqa: F401
    from skill_template import TemplateEngineMixin

    TOOL_MODULES_DIR = Path(__file__).parent.parent.parent
    PROJECT_DIR = TOOL_MODULES_DIR.parent
    SKILLS_DIR = PROJECT_DIR / "skills"

logger = logging.getLogger(__name__)

# Skills after which we remind the LLM to call session_close (improves session logs)
SKILLS_TRIGGER_SESSION_CLOSE_REMINDER: frozenset[str] = frozenset(
    {
        "create_mr",
        "close_issue",
        "close_mr",
        "beer",
        "coffee",
        "start_work",
        "release_to_prod",
        "release_aa_backend_prod",
        "attach_session_to_jira",
        "create_jira_issue",
    }
)


class AttrDict(dict):
    """Dictionary that allows attribute-style access to keys.

    This allows skill YAML compute blocks to use `inputs.repo` instead of `inputs["repo"]`.
    """

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as e:
            raise AttributeError(f"'AttrDict' object has no attribute '{key}'") from e

    def __setattr__(self, key, value):
        self[key] = value

    def __delattr__(self, key):
        try:
            del self[key]
        except KeyError as e:
            raise AttributeError(f"'AttrDict' object has no attribute '{key}'") from e


# Layer 5: Usage Pattern Learning integration
try:
    from server.usage_pattern_learner import UsagePatternLearner

    LAYER5_AVAILABLE = True
except ImportError:
    LAYER5_AVAILABLE = False
    logger.warning(
        "Layer 5 (Usage Pattern Learning) not available - errors won't be learned from"
    )

# WebSocket server for real-time updates
try:
    from server.websocket_server import get_websocket_server

    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    logger.debug("WebSocket server not available - real-time updates disabled")


# Agent stats helper - handles import in both package and direct load contexts
def _get_agent_stats_module():
    """Get the agent_stats module, handling both package and direct load contexts."""
    try:
        # Try relative import first (works when loaded as package)
        from . import agent_stats

        return agent_stats
    except ImportError:
        # Fall back to direct file loading (works when loaded dynamically)
        # Force fresh load by removing from sys.modules cache
        import importlib.util
        import sys

        agent_stats_path = Path(__file__).parent / "agent_stats.py"

        # Remove cached version to force fresh load
        if "agent_stats" in sys.modules:
            del sys.modules["agent_stats"]

        spec = importlib.util.spec_from_file_location("agent_stats", agent_stats_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["agent_stats"] = (
            module  # Register before exec to handle circular imports
        )
        spec.loader.exec_module(module)
        return module


@dataclass
class SkillExecutorConfig:
    """Configuration for SkillExecutor, used when passing config= instead of kwargs."""

    debug: bool = False
    enable_interactive_recovery: bool = True
    emit_events: bool = True
    workspace_uri: str = "default"
    source: str = "chat"
    source_details: str | None = None


class SkillExecutor(ErrorRecoveryMixin, TemplateEngineMixin):
    """Full skill execution engine with debug support.

    Workspace-aware: tracks workspace_uri for proper isolation of skill
    state and events per workspace.
    """

    def __init__(
        self,
        skill: dict,
        inputs: dict,
        debug: bool = False,
        server: FastMCP | None = None,
        create_issue_fn=None,
        ask_question_fn=None,
        enable_interactive_recovery: bool = True,
        emit_events: bool = True,
        workspace_uri: str = "default",
        ctx: Optional["Context"] = None,
        # Session context for multi-execution tracking
        session_id: str | None = None,
        session_name: str | None = None,
        source: str = "chat",  # "chat", "cron", "slack", "api"
        source_details: str | None = None,  # e.g., cron job name
        config: SkillExecutorConfig | None = None,
    ):
        # Allow config= to override individual kwargs
        if config is not None:
            debug = config.debug
            enable_interactive_recovery = config.enable_interactive_recovery
            emit_events = config.emit_events
            workspace_uri = config.workspace_uri
            source = config.source
            source_details = config.source_details or source_details

        self.skill = skill
        self.inputs = inputs
        self.debug = debug
        self.server = server
        self.create_issue_fn = create_issue_fn
        self.ask_question_fn = ask_question_fn
        self.enable_interactive_recovery = enable_interactive_recovery
        self.emit_events = emit_events
        self.workspace_uri = workspace_uri
        self.ctx = ctx
        self.session_id = session_id
        self.session_name = session_name
        self.source = source
        self.source_details = source_details
        # Load config.json config for compute blocks
        self.config = load_config()
        # Add today's date for templating (YYYY-MM-DD format)
        from datetime import date

        self.context: dict[str, Any] = {
            "inputs": inputs,
            "config": self.config,
            "workspace_uri": workspace_uri,
            "today": date.today().isoformat(),
        }
        self.log: list[str] = []
        self.step_results: list[dict] = []
        self.start_time: float | None = None
        self.error_recovery: Any = None  # Initialized when needed

        # Event emitter for VS Code extension (workspace-aware, multi-execution)
        self.event_emitter = None
        if emit_events:
            try:
                # Use absolute import to avoid relative import issues
                from tool_modules.aa_workflow.src.skill_execution_events import (
                    SkillExecutionEmitter,
                    set_emitter,
                )

                self.event_emitter = SkillExecutionEmitter(
                    skill.get("name", "unknown"),
                    skill.get("steps", []),
                    workspace_uri=workspace_uri,
                    session_id=session_id,
                    session_name=session_name,
                    source=source,
                    source_details=source_details,
                )
                set_emitter(self.event_emitter, workspace_uri)
                skill_name = skill.get("name", "unknown")
                logger.info(
                    f"Event emitter initialized for skill: {skill_name} (workspace: {workspace_uri}, source: {source})"
                )
                # Debug: write to a file to confirm emitter is created
                from pathlib import Path

                debug_file = (
                    Path.home() / ".config" / "aa-workflow" / "emitter_debug.log"
                )
                debug_file.parent.mkdir(parents=True, exist_ok=True)
                with open(debug_file, "a", encoding="utf-8") as f:
                    from datetime import datetime

                    skill_name = skill.get("name", "unknown")
                    f.write(
                        f"{datetime.now().isoformat()} - Emitter created for {skill_name} (source: {source})\n"
                    )
            except Exception as e:
                logger.warning(f"Failed to initialize event emitter: {e}")
                # Also write to debug file on failure
                try:
                    from datetime import datetime
                    from pathlib import Path

                    debug_file = (
                        Path.home() / ".config" / "aa-workflow" / "emitter_debug.log"
                    )
                    debug_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(debug_file, "a", encoding="utf-8") as f:
                        f.write(
                            f"{datetime.now().isoformat()} - FAILED to create emitter: {e}\n"
                        )
                except Exception as exc:
                    logger.debug("Suppressed error: %s", exc)

        # Layer 5: Initialize usage pattern learner
        self.usage_learner = None
        if LAYER5_AVAILABLE:
            try:
                self.usage_learner = UsagePatternLearner()
            except Exception as e:
                logger.warning(f"Failed to initialize Layer 5 learner: {e}")

        # WebSocket server for real-time updates
        self.ws_server = None
        if WEBSOCKET_AVAILABLE:
            try:
                self.ws_server = get_websocket_server()
            except Exception as e:
                logger.debug(f"WebSocket server not available: {e}")

        # Generate unique skill execution ID
        import uuid

        self.skill_id = str(uuid.uuid4())[:8]

    def _debug(self, msg: str):
        """Add debug message."""
        if self.debug:
            import time

            elapsed = (
                f"[{time.time() - self.start_time:.2f}s]" if self.start_time else ""
            )
            self.log.append(f"🔍 {elapsed} {msg}")

    def _get_module_for_tool(self, tool_name: str) -> str | None:
        """Map tool name to module name using the discovery system."""
        from server.tool_discovery import get_module_for_tool

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
        import time

        try:
            assert self.server is not None, "No server available for tool execution"
            result = await self.server.call_tool(tool_name, args)
            duration = time.time() - start_time
            duration_ms = int(duration * 1000)
            self._debug(f"  → Completed in {duration:.2f}s")

            # Record tool call stats
            try:
                agent_stats = _get_agent_stats_module()
                agent_stats.record_tool_call(tool_name, True, duration_ms)
            except Exception as stats_err:
                logger.debug(f"Failed to record tool stats: {stats_err}")

            return self._format_tool_result(result, duration)
        except Exception as e:
            # Record failed tool call
            try:
                agent_stats = _get_agent_stats_module()
                agent_stats.record_tool_call(tool_name, False, 0)
            except Exception as exc:
                logger.debug("Suppressed error: %s", exc)
            return {"success": False, "error": str(e)}

    async def _load_and_execute_module_tool(
        self, module: str, tool_name: str, args: dict, start_time: float
    ) -> dict:
        """Load a tool module and execute the specified tool."""
        import importlib.util
        import time
        import types

        self._debug(f"  → Loading module: {module}")
        self._debug(f"  → TOOL_MODULES_DIR: {TOOL_MODULES_DIR}")

        # Try tools_basic.py first (new structure), then tools.py (legacy)
        tools_file = TOOL_MODULES_DIR / f"aa_{module}" / "src" / "tools_basic.py"
        self._debug(f"  → Trying: {tools_file} (exists: {tools_file.exists()})")
        if not tools_file.exists():
            tools_file = TOOL_MODULES_DIR / f"aa_{module}" / "src" / "tools.py"
            self._debug(f"  → Fallback: {tools_file} (exists: {tools_file.exists()})")

        if not tools_file.exists():
            return {
                "success": False,
                "error": f"Module not found: {module} (checked {TOOL_MODULES_DIR / f'aa_{module}' / 'src'})",
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
                        str(TOOL_MODULES_DIR.parent / partial.replace(".", "/"))
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
            except Exception as stats_err:
                logger.debug(f"Failed to record tool stats: {stats_err}")

            return self._format_tool_result(result, duration)

        except Exception as e:
            # Record failed tool call
            try:
                agent_stats = _get_agent_stats_module()
                agent_stats.record_tool_call(tool_name, False, 0)
            except Exception as exc:
                logger.debug("Suppressed error: %s", exc)
            return {
                "success": False,
                "error": str(e),
                "_temp_server": temp_server if "temp_server" in locals() else None,
            }

    async def _exec_tool(self, tool_name: str, args: dict) -> dict:
        """Execute a tool and return its result."""
        import time

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
        if not result.get("success"):
            # Error message can be in 'error' key or 'result' key (for tools that return error text)
            error_msg = result.get("error") or result.get("result", "Unknown error")
            temp_server = result.get("_temp_server")

            if temp_server:
                self._debug(f"  → Error: {error_msg}")

                # Check for known issues and attempt auto-fix
                matches = _check_known_issues_sync(
                    tool_name=tool_name, error_text=error_msg
                )
                known_text = _format_known_issues(matches)

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
                            except Exception as exc:
                                logger.debug("Suppressed error: %s", exc)

                            return self._format_tool_result(retry_result, duration)
                        except Exception as retry_e:
                            error_msg = f"{error_msg}\n\n(Retry after auto-fix also failed: {retry_e})"

                if known_text:
                    error_msg = f"{error_msg}\n{known_text}"

                result["error"] = error_msg

        # Remove internal _temp_server key if present
        result.pop("_temp_server", None)
        return result

    def _validate_tool_args(
        self, tool: str, raw_args: dict, args: dict, step_name: str
    ) -> str | None:
        """Validate tool arguments after template rendering.

        Returns:
            Error message if validation fails, None if valid.
        """
        # Check for empty required arguments that came from templates
        # Skip validation for args that use 'default' or 'or' in the template (these are optional)
        for key, raw_value in raw_args.items():
            if isinstance(raw_value, str) and "{{" in raw_value:
                # Skip if template has a default/fallback (e.g., "{{ x | default('') }}" or "{{ x or '' }}")
                if "default(" in raw_value or " or " in raw_value:
                    continue
                rendered_value = args.get(key, "")
                if rendered_value == "" or rendered_value is None:
                    # Extract variable name from template for better error message
                    import re

                    var_match = re.search(r"\{\{\s*([^}]+)\s*\}\}", raw_value)
                    var_name = var_match.group(1).strip() if var_match else raw_value
                    return (
                        f"Required argument '{key}' is empty. "
                        f"Template '{raw_value}' rendered to empty string. "
                        f"Check if '{var_name}' is defined in a previous step."
                    )
        return None

    async def _process_tool_step(
        self, step: dict, step_num: int, step_name: str, output_lines: list[str]
    ) -> bool:
        """Process a 'tool' step and append results to output_lines.

        Returns:
            True if processing should continue, False if skill should stop
        """
        tool = step["tool"]
        raw_args = step.get("args", {})
        args = self._template_dict(raw_args)

        # Validate that template rendering produced valid arguments
        validation_error = self._validate_tool_args(tool, raw_args, args, step_name)
        if validation_error:
            self._debug(f"Argument validation failed for {tool}: {validation_error}")
            output_lines.append(f"🔧 **Step {step_num}: {step_name}**")
            output_lines.append(f"   *Tool: `{tool}`*")
            output_lines.append(f"   ❌ {validation_error}")

            # Check on_error handling
            on_error = step.get("on_error", "fail")
            if on_error == "continue":
                output_lines.append("   ⏭️ Continuing (on_error: continue)")
                return True

            # Record step failure
            self.step_results.append(
                {
                    "step": step_name,
                    "tool": tool,
                    "success": False,
                    "error": validation_error,
                }
            )
            return False

        output_lines.append(f"🔧 **Step {step_num}: {step_name}**")
        output_lines.append(f"   *Tool: `{tool}`*")

        result = await self._exec_tool(tool, args)

        if result["success"]:
            output_name = step.get("output", step_name)
            result_text = result["result"]

            # Check for soft failures - tool returned success but result contains error
            is_soft_failure, soft_error = self._detect_soft_failure(result_text)

            if is_soft_failure and step.get("on_error") == "auto_heal":
                # Treat as error and trigger auto-heal
                output_lines.append(
                    f"   ⚠️ Soft failure detected: {(soft_error or '')[:100]}"
                )
                self._debug(f"Soft failure in {tool}: {soft_error}")

                # Store result anyway (some steps may need it even if failed)
                self.context[output_name] = result_text
                self._parse_and_store_tool_result(result_text, output_name)

                # Trigger auto-heal flow
                should_continue = await self._handle_tool_error(
                    tool,
                    step,
                    step_name,
                    soft_error or "Soft failure detected",
                    output_lines,
                )
                if not should_continue:
                    output_lines.append(f"\n⛔ **Skill failed at step {step_num}**")
                return should_continue

            # Normal success path
            self.context[output_name] = result_text
            self._parse_and_store_tool_result(result_text, output_name)

            duration = result.get("duration", 0)
            output_lines.append(f"   ✅ Success ({duration:.2f}s)")

            result_preview = result_text[:300]
            if len(result_text) > 300:
                result_preview += "..."
            output_lines.append(f"   ```\n   {result_preview}\n   ```\n")

            self.step_results.append(
                {"step": step_name, "tool": tool, "success": True, "duration": duration}
            )
            return True

        # Handle error - error message can be in 'error' key or 'result' key
        error_msg = result.get("error") or result.get("result", "Unknown error")
        should_continue = await self._handle_tool_error(
            tool, step, step_name, error_msg, output_lines
        )
        if not should_continue:
            output_lines.append(f"\n⛔ **Skill failed at step {step_num}**")
        return should_continue

    def _format_skill_outputs(self, output_lines: list[str]):
        """Format and append skill outputs section."""
        if not self.skill.get("outputs"):
            return

        output_lines.append("\n### 📤 Outputs\n")
        for out in self.skill["outputs"]:
            out_name = out.get("name", "output")
            if "value" in out:
                val = out["value"]
                output_value: Any
                if isinstance(val, str):
                    output_value = self._template(val)
                elif isinstance(val, (dict, list)):
                    output_value = (
                        self._template_dict(val)
                        if isinstance(val, dict)
                        else [
                            self._template(i) if isinstance(i, str) else i for i in val
                        ]
                    )
                else:
                    output_value = val

                self.context[out_name] = output_value
                output_lines.append(f"**{out_name}:**\n{output_value}\n")
            elif "compute" in out:
                result = self._exec_compute(out["compute"], out_name)
                output_lines.append(f"**{out_name}:** {result}\n")

    def _process_then_block(self, step: dict, output_lines: list[str]) -> str | None:
        """Process a 'then' block with early return.

        Returns:
            Final output string if early return, None to continue execution
        """
        import time

        self._debug("Processing 'then' block")
        for then_item in step["then"]:
            if "return" in then_item:
                ret = then_item["return"]
                templated = (
                    self._template_dict(ret)
                    if isinstance(ret, dict)
                    else self._template(str(ret))
                )
                self._debug(f"Early return: {templated}")

                total_time = time.time() - (self.start_time or 0.0)
                output_lines.append(f"✅ **Early Exit**\n{templated}\n")
                output_lines.append(f"\n---\n⏱️ *Completed in {total_time:.2f}s*")

                if self.debug and self.log:
                    output_lines.append("\n\n### 🔍 Debug Log\n```")
                    output_lines.extend(self.log)
                    output_lines.append("```")

                return "\n".join(output_lines)
        return None

    async def execute(self) -> str:  # noqa: C901
        """Execute all steps and return the result."""
        import time

        self.start_time = time.time()

        skill_name = self.skill.get("name", "unknown")
        total_steps = len(self.skill.get("steps", []))
        self._debug(f"Starting skill: {skill_name}")
        self._debug(f"Inputs: {json.dumps(self.inputs)}")

        # Emit skill start event (file-based)
        if self.event_emitter:
            self.event_emitter.skill_start()

        # Emit skill start event (WebSocket)
        if self.ws_server and self.ws_server.is_running:
            import asyncio

            asyncio.create_task(
                self.ws_server.skill_started(
                    skill_id=self.skill_id,
                    skill_name=skill_name,
                    total_steps=total_steps,
                    inputs=self.inputs,
                    source=self.source,
                )
            )

        # Log skill start to daily session file (so sessions show in-progress work)
        try:
            from tool_modules.aa_workflow.src.memory_tools import append_session_entry

            entry_start: dict[str, Any] = {
                "type": "skill",
                "action": f"skill: {skill_name} started",
                "details": f"Running (0/{total_steps} steps)",
                "skill_name": skill_name,
                "source": self.source,
            }
            if self.session_id:
                entry_start["session_id"] = self.session_id
            append_session_entry(entry_start)
        except Exception as e:
            self._debug(f"Failed to log skill start to session: {e}")

        for inp in self.skill.get("inputs", []):
            name = inp["name"]
            if name not in self.inputs and "default" in inp:
                # Template the default value to resolve variables like {{ today }}
                default_val = inp["default"]
                if isinstance(default_val, str) and "{{" in default_val:
                    default_val = self._template(default_val)
                self.inputs[name] = default_val
                self.context["inputs"] = self.inputs
                self._debug(f"Applied default: {name} = {default_val}")

        defaults = self.skill.get("defaults", {})
        self.context["defaults"] = defaults

        output_lines = [f"## 🚀 Executing Skill: {skill_name}\n"]
        output_lines.append(f"*{self.skill.get('description', '')}*\n")

        if self.debug:
            output_lines.append("### 📋 Inputs")
            for k, v in self.inputs.items():
                output_lines.append(f"- `{k}`: {v}")
            output_lines.append("")

        output_lines.append("### 📝 Execution Log\n")

        step_num = 0
        for step in self.skill.get("steps", []):
            step_index = step_num  # 0-based index for events
            step_num += 1
            step_name = step.get("name", f"step_{step_num}")
            step_start_time = time.time()

            if "condition" in step:
                if not self._eval_condition(step["condition"]):
                    self._debug(f"Skipping step '{step_name}' - condition false")
                    output_lines.append(
                        f"⏭️ **Step {step_num}: {step_name}** - *skipped (condition false)*\n"
                    )
                    # Emit step skipped event
                    if self.event_emitter:
                        self.event_emitter.step_skipped(step_index, "condition false")
                    continue

            # Emit step start event (file-based)
            if self.event_emitter:
                self.event_emitter.step_start(step_index)

            # Emit step start event (WebSocket)
            if self.ws_server and self.ws_server.is_running:
                import asyncio

                description = step.get("description", "")
                asyncio.create_task(
                    self.ws_server.step_started(
                        skill_id=self.skill_id,
                        step_index=step_index,
                        step_name=step_name,
                        description=description[:200] if description else "",
                    )
                )

            if "then" in step:
                early_return = self._process_then_block(step, output_lines)
                if early_return is not None:
                    # Emit skill complete (early return)
                    if self.event_emitter:
                        total_time = time.time() - (self.start_time or 0.0)
                        self.event_emitter.skill_complete(True, int(total_time * 1000))
                    return early_return
                continue

            step_success = True
            step_error = None

            if "tool" in step:
                # Check for memory operations
                tool_name = step.get("tool", "")
                if self.event_emitter:
                    self._emit_memory_events_for_tool(
                        step_index, tool_name, step.get("args", {})
                    )

                should_continue = await self._process_tool_step(
                    step, step_num, step_name, output_lines
                )

                # Check step result
                if self.step_results:
                    last_result = self.step_results[-1]
                    step_success = last_result.get("success", True)
                    if not step_success:
                        step_error = last_result.get("error", "Unknown error")

                if not should_continue:
                    # Emit step failed event
                    if self.event_emitter:
                        duration_ms = int((time.time() - step_start_time) * 1000)
                        self.event_emitter.step_failed(
                            step_index, duration_ms, step_error or "Step failed"
                        )
                    break

            elif "compute" in step:
                output_name = step.get("output", step_name)
                output_lines.append(f"🧮 **Step {step_num}: {step_name}** (compute)")

                try:
                    result = self._exec_compute(step["compute"], output_name)

                    # Check if compute returned an error string
                    if isinstance(result, str) and result.startswith("<compute error:"):
                        step_success = False
                        step_error = result
                        output_lines.append(f"   ❌ {result}\n")
                        self._debug(f"Compute step '{step_name}' failed: {result}")

                        # Store error result in context so dependent steps can check
                        self.context[output_name] = None
                        self.context[f"{output_name}_error"] = result

                        # Record step failure
                        self.step_results.append(
                            {
                                "step": step_name,
                                "compute": True,
                                "success": False,
                                "error": result,
                            }
                        )
                    else:
                        self.context[output_name] = result
                        output_lines.append(
                            f"   → `{output_name}` = {str(result)[:100]}\n"
                        )
                except Exception as e:
                    step_success = False
                    step_error = str(e)
                    output_lines.append(f"   ❌ Error: {e}\n")

            elif "description" in step:
                output_lines.append(f"📝 **Step {step_num}: {step_name}** (manual)")
                output_lines.append(f"   {self._template(step['description'])}\n")

            # Emit step complete/failed event (file-based)
            if self.event_emitter:
                duration_ms = int((time.time() - step_start_time) * 1000)
                if step_success:
                    self.event_emitter.step_complete(step_index, duration_ms)
                else:
                    self.event_emitter.step_failed(
                        step_index, duration_ms, step_error or "Unknown error"
                    )

            # Emit step complete/failed event (WebSocket)
            if self.ws_server and self.ws_server.is_running:
                import asyncio

                duration_ms = int((time.time() - step_start_time) * 1000)
                if step_success:
                    asyncio.create_task(
                        self.ws_server.step_completed(
                            skill_id=self.skill_id,
                            step_index=step_index,
                            step_name=step_name,
                            duration_ms=duration_ms,
                        )
                    )
                else:
                    asyncio.create_task(
                        self.ws_server.step_failed(
                            skill_id=self.skill_id,
                            step_index=step_index,
                            step_name=step_name,
                            error=step_error or "Unknown error",
                        )
                    )

        self._format_skill_outputs(output_lines)

        total_time = time.time() - (self.start_time or 0.0)
        success_count = sum(1 for r in self.step_results if r.get("success"))
        fail_count = sum(1 for r in self.step_results if not r.get("success"))

        output_lines.append(
            f"\n---\n⏱️ *Completed in {total_time:.2f}s* | "
            f"✅ {success_count} succeeded | ❌ {fail_count} failed"
        )

        # Emit skill complete event (file-based)
        if self.event_emitter:
            overall_success = fail_count == 0
            self.event_emitter.skill_complete(overall_success, int(total_time * 1000))
            # Clear the global emitter
            try:
                from .skill_execution_events import set_emitter

                set_emitter(None)
            except Exception as exc:
                logger.debug("Suppressed error: %s", exc)

        # Emit skill complete event (WebSocket)
        if self.ws_server and self.ws_server.is_running:
            import asyncio

            overall_success = fail_count == 0
            if overall_success:
                asyncio.create_task(
                    self.ws_server.skill_completed(
                        skill_id=self.skill_id,
                        total_duration_ms=int(total_time * 1000),
                    )
                )
            else:
                # Get last error from step_results
                last_error = "Skill failed"
                for r in reversed(self.step_results):
                    if not r.get("success") and r.get("error"):
                        last_error = r["error"]
                        break
                asyncio.create_task(
                    self.ws_server.skill_failed(
                        skill_id=self.skill_id,
                        error=last_error,
                        total_duration_ms=int(total_time * 1000),
                    )
                )

        # Track skill execution in agent stats
        try:
            agent_stats = _get_agent_stats_module()
            overall_success = fail_count == 0
            agent_stats.record_skill_execution(
                skill_name=skill_name,
                success=overall_success,
                duration_ms=int(total_time * 1000),
                steps_completed=success_count,
                total_steps=len(self.skill.get("steps", [])),
            )
        except Exception as e:
            self._debug(f"Failed to record skill stats: {e}")

        # Log skill completion to daily session file
        try:
            from tool_modules.aa_workflow.src.memory_tools import append_session_entry

            overall_success = fail_count == 0
            total_steps = len(self.skill.get("steps", []))
            entry: dict[str, Any] = {
                "type": "skill",
                "action": f"skill: {skill_name}",
                "details": (
                    f"{'Success' if overall_success else 'Failed'} "
                    f"({success_count}/{total_steps} steps, "
                    f"{int(total_time * 1000)}ms)"
                ),
                "skill_name": skill_name,
                "result": "success" if overall_success else "failure",
                "duration_ms": int(total_time * 1000),
                "source": self.source,
            }
            if self.session_id:
                entry["session_id"] = self.session_id
            append_session_entry(entry)
        except Exception as e:
            self._debug(f"Failed to log skill to session: {e}")

        # Remind to call session_close after high-signal skills (improves session logs)
        if (
            fail_count == 0
            and skill_name in SKILLS_TRIGGER_SESSION_CLOSE_REMINDER
            and self.source == "chat"
        ):
            output_lines.append("")
            output_lines.append(
                "💡 **Session log:** When you finish, call `session_close(issues, accomplished, next_steps)` "
                "so the day's log has a summary."
            )

        # Extract and save learnings from successful skill execution
        if fail_count == 0:
            await self._extract_and_save_learnings(output_lines)

        if self.debug and self.log:
            output_lines.append("\n\n### 🔍 Debug Log\n```")
            output_lines.extend(self.log)
            output_lines.append("```")

        return "\n".join(output_lines)

    def _emit_memory_events_for_tool(
        self, step_index: int, tool_name: str, args: dict
    ) -> None:
        """Emit memory read/write events based on tool being called."""
        if not self.event_emitter:
            return

        # Memory read tools
        memory_read_tools = [
            "memory_read",
            "memory_query",
            "check_known_issues",
            "memory_stats",
        ]
        if any(t in tool_name for t in memory_read_tools):
            key = args.get("key", tool_name)
            self.event_emitter.memory_read(step_index, key)

        # Memory write tools
        memory_write_tools = [
            "memory_write",
            "memory_update",
            "memory_append",
            "memory_session_log",
            "learn_tool_fix",
        ]
        if any(t in tool_name for t in memory_write_tools):
            key = args.get("key", tool_name)
            self.event_emitter.memory_write(step_index, key)

        # Semantic search tools
        semantic_search_tools = [
            "code_search",
            "knowledge_query",
            "semantic_search",
            "vector_search",
        ]
        if any(t in tool_name for t in semantic_search_tools):
            query = args.get("query", args.get("section", tool_name))
            self.event_emitter.semantic_search(step_index, query)

    async def _extract_and_save_learnings(self, output_lines: list[str]) -> None:
        """Extract learnings from successful skill execution and save to knowledge.

        This is called after a skill completes successfully. It analyzes the
        execution context and results to extract potential learnings.
        """
        skill_name = self.skill.get("name", "unknown")

        # Skip skills that don't produce learnable outcomes
        non_learning_skills = [
            "memory_view",
            "memory_cleanup",
            "coffee",
            "beer",
            "standup_summary",
            "weekly_summary",
        ]
        if skill_name in non_learning_skills:
            return

        # Try to detect project and persona
        try:
            from .knowledge_tools import (
                _detect_project_from_path,
                _get_current_persona,
                _load_knowledge,
                _save_knowledge,
            )

            project = _detect_project_from_path()
            if not project:
                self._debug("No project detected, skipping learning extraction")
                return

            persona = _get_current_persona() or "developer"

            # Load existing knowledge
            knowledge = _load_knowledge(persona, project)
            if not knowledge:
                self._debug(f"No knowledge file for {project}/{persona}, skipping")
                return

            # Extract learning based on skill type
            task = self.inputs.get("issue_key", skill_name)

            # Map skill -> (input_key, template)
            _learning_templates = {
                "start_work": ("issue_key", "Started work on {}"),
                "create_mr": ("issue_key", "Created MR for {}"),
                "review_pr": ("mr_id", "Reviewed MR !{}"),
                "review_all_prs": ("mr_id", "Reviewed MR !{}"),
                "test_mr_ephemeral": (
                    "mr_id",
                    "Tested MR !{} in ephemeral environment",
                ),
                "investigate_alert": ("alert_name", "Investigated alert: {}"),
                "close_issue": ("issue_key", "Closed issue {}"),
            }

            learning = None
            if skill_name in _learning_templates:
                input_key, template = _learning_templates[skill_name]
                value = self.inputs.get(input_key, "")
                if value:
                    learning = template.format(value)

            # Save learning if we extracted one
            if learning:
                # Ensure learned_from_tasks exists
                if "learned_from_tasks" not in knowledge:
                    knowledge["learned_from_tasks"] = []

                # Add the learning
                knowledge["learned_from_tasks"].append(
                    {
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "task": task,
                        "learning": learning,
                        "skill": skill_name,
                    }
                )

                # Limit to last 50 learnings
                knowledge["learned_from_tasks"] = knowledge["learned_from_tasks"][-50:]

                # Slightly increase confidence
                current_confidence = knowledge.get("metadata", {}).get(
                    "confidence", 0.5
                )
                knowledge["metadata"]["confidence"] = min(
                    current_confidence + 0.01, 1.0
                )

                # Save
                _save_knowledge(persona, project, knowledge)
                self._debug(f"Saved learning: {learning}")

                # Add note to output
                output_lines.append(f"\n📚 *Learning recorded: {learning}*")

        except Exception as e:
            self._debug(f"Failed to extract/save learnings: {e}")


def _skill_list_impl() -> list[TextContent]:
    """Implementation of skill_list tool."""
    skills = []
    if SKILLS_DIR.exists():
        for f in SKILLS_DIR.glob("*.yaml"):
            if f.name == "README.md":
                continue
            try:
                with open(f, encoding="utf-8") as fp:
                    data = yaml.safe_load(fp)
                skills.append(
                    {
                        "name": data.get("name", f.stem),
                        "description": data.get("description", "No description"),
                        "inputs": [i["name"] for i in data.get("inputs", [])],
                    }
                )
            except Exception as e:
                skills.append(
                    {"name": f.stem, "description": f"Error loading: {e}", "inputs": []}
                )

    if not skills:
        return [
            TextContent(
                type="text",
                text="No skills found. Create .yaml files in skills/ directory.",
            )
        ]

    lines = ["## Available Skills\n"]
    for s in skills:
        inputs = ", ".join(s["inputs"]) if s["inputs"] else "none"
        lines.append(f"### {s['name']}")
        lines.append(f"{s['description']}")
        lines.append(f"**Inputs:** {inputs}\n")

    return [TextContent(type="text", text="\n".join(lines))]


def _validate_skill_inputs(skill: dict, input_data: dict) -> list[str]:
    """Validate required skill inputs and return list of missing inputs."""
    missing = []
    for inp in skill.get("inputs", []):
        if inp.get("required", False) and inp["name"] not in input_data:
            if "default" not in inp:
                missing.append(inp["name"])
    return missing


def _format_skill_plan(
    skill: dict, skill_name: str, input_data: dict
) -> list[TextContent]:
    """Format skill execution plan (preview mode)."""
    lines = [f"## 📋 Skill Plan: {skill.get('name', skill_name)}\n"]
    lines.append(f"*{skill.get('description', '')}*\n")
    lines.append("### Inputs")
    for k, v in input_data.items():
        lines.append(f"- `{k}`: {v}")
    lines.append("\n### Steps to Execute\n")

    step_num = 0
    for step in skill.get("steps", []):
        step_num += 1
        name = step.get("name", f"step_{step_num}")

        if "tool" in step:
            lines.append(f"{step_num}. **{name}** → `{step['tool']}`")
            if step.get("condition"):
                lines.append(f"   *Condition: {step['condition']}*")
        elif "compute" in step:
            lines.append(f"{step_num}. **{name}** → compute")
        elif "description" in step:
            lines.append(f"{step_num}. **{name}** → manual step")

    lines.append("\n*Run with `execute=True` to execute this plan*")
    return [TextContent(type="text", text="\n".join(lines))]


async def _skill_run_impl(
    skill_name: str,
    inputs: str,
    execute: bool,
    debug: bool,
    server: "FastMCP",
    create_issue_fn=None,
    ask_question_fn=None,
    ctx: Optional["Context"] = None,
    source: str = "chat",
    source_details: str | None = None,
) -> list[TextContent]:
    """Implementation of skill_run tool.

    Args:
        skill_name: Name of the skill to run.
        inputs: JSON string of input parameters.
        execute: Whether to execute (True) or just preview (False).
        debug: Whether to show debug output.
        server: FastMCP server instance.
        create_issue_fn: Function to create Jira issues.
        ask_question_fn: Function to ask user questions.
        ctx: MCP Context for workspace/session info.
        source: Source of execution ("chat", "cron", "slack", "api").
        source_details: Additional source info (e.g., cron job name).
    """
    skill_file = SKILLS_DIR / f"{skill_name}.yaml"
    if not skill_file.exists():
        available = (
            [f.stem for f in SKILLS_DIR.glob("*.yaml")] if SKILLS_DIR.exists() else []
        )
        return [
            TextContent(
                type="text",
                text=f"❌ Skill not found: {skill_name}\n\n"
                f"Available: {', '.join(available) or 'none'}",
            )
        ]

    try:
        with open(skill_file, encoding="utf-8") as f:
            skill = yaml.safe_load(f)

        try:
            input_data = json.loads(inputs) if inputs else {}
        except json.JSONDecodeError:
            return [TextContent(type="text", text=f"❌ Invalid inputs JSON: {inputs}")]

        # Validate inputs
        missing = _validate_skill_inputs(skill, input_data)
        if missing:
            lines = [f"❌ Missing required inputs: {', '.join(missing)}\n"]
            lines.append("### Required Inputs\n")
            for inp in skill.get("inputs", []):
                req = "**required**" if inp.get("required") else "optional"
                default = f" (default: {inp['default']})" if "default" in inp else ""
                lines.append(
                    f"- `{inp['name']}` ({inp.get('type', 'string')}) - {req}{default}"
                )
                if inp.get("description"):
                    lines.append(f"  {inp['description']}")
            return [TextContent(type="text", text="\n".join(lines))]

        # Preview mode: just show the plan
        if not execute:
            return _format_skill_plan(skill, skill_name, input_data)

        # Get session context from workspace if available
        workspace_uri = "default"
        session_id = None
        session_name = None

        if ctx:
            try:
                from server.workspace_state import WorkspaceRegistry

                workspace = await WorkspaceRegistry.get_for_ctx(ctx)
                workspace_uri = workspace.workspace_uri
                session = workspace.get_active_session()
                if session:
                    session_id = session.session_id
                    session_name = session.name
            except Exception as e:
                logger.debug(f"Could not get session context: {e}")

        # Execute mode: run the skill
        executor = SkillExecutor(
            skill,
            input_data,
            debug=debug,
            server=server,
            create_issue_fn=create_issue_fn,
            ask_question_fn=ask_question_fn,
            enable_interactive_recovery=True,
            emit_events=True,  # Enable VS Code extension events
            workspace_uri=workspace_uri,
            ctx=ctx,
            session_id=session_id,
            session_name=session_name,
            source=source,
            source_details=source_details,
        )
        result = await executor.execute()

        return [TextContent(type="text", text=result)]

    except Exception as e:
        import traceback

        if debug:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Error: {e}\n\n```\n{traceback.format_exc()}\n```",
                )
            ]
        return [TextContent(type="text", text=f"❌ Error loading skill: {e}")]


def register_skill_tools(
    server: "FastMCP", create_issue_fn=None, ask_question_fn=None
) -> int:
    """Register skill tools with the MCP server."""
    registry = ToolRegistry(server)

    @registry.tool()
    async def skill_list() -> list[TextContent]:
        """
        List all available skills (reusable workflows).

        Skills are multi-step workflows that combine MCP tools with logic.
        Use skill_run() to execute a skill.

        Returns:
            List of available skills with descriptions.
        """
        return _skill_list_impl()

    @registry.tool()
    async def skill_run(
        ctx: "Context",
        skill_name: str,
        inputs: str = "{}",
        args: str = "",
        execute: bool = True,
        debug: bool = False,
    ) -> list[TextContent]:
        """
        Execute a skill (multi-step workflow).

        Skills chain multiple MCP tools together with logic and conditions.

        Args:
            skill_name: Name of the skill (e.g., "start_work", "investigate_alert")
            inputs: JSON object with input parameters (preferred)
            args: Alias for inputs (for convenience)
            execute: If True (default), run the tools. If False, just show the plan.
            debug: If True, show detailed execution trace with timing.

        Returns:
            Execution results or plan preview.
        """
        # Support both 'inputs' and 'args' parameter names
        actual_inputs = args if args else inputs
        return await _skill_run_impl(
            skill_name,
            actual_inputs,
            execute,
            debug,
            server,
            create_issue_fn,
            ask_question_fn,
            ctx=ctx,
            source="chat",
        )

    return registry.count
