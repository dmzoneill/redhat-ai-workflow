# pylint: disable=duplicate-code,cyclic-import
"""SkillExecutor class composed from step mixins."""

import logging
from typing import Any, Optional

from fastmcp import Context, FastMCP

from server.utils import load_config

from .skill_compute_mixin import SkillComputeMixin
from .skill_heal_mixin import SkillHealMixin
from .skill_recovery_mixin import SkillRecoveryMixin
from .skill_run_mixin import SkillRunMixin
from .skill_step_mixin import SkillStepMixin
from .skill_template_mixin import SkillTemplateMixin
from .skill_tools_mixin import SkillToolMixin

logger = logging.getLogger(__name__)

try:
    from server.usage_pattern_learner import UsagePatternLearner

    LAYER5_AVAILABLE = True
except ImportError:
    LAYER5_AVAILABLE = False
    logger.warning(
        "Layer 5 (Usage Pattern Learning) not available - errors won't be learned from"
    )

try:
    from server.websocket_server import get_websocket_server

    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    logger.debug("WebSocket server not available - real-time updates disabled")


class SkillExecutor(  # pylint: disable=too-many-instance-attributes
    SkillRunMixin,
    SkillStepMixin,
    SkillToolMixin,
    SkillComputeMixin,
    SkillRecoveryMixin,
    SkillHealMixin,
    SkillTemplateMixin,
):
    """Full skill execution engine with debug support.

    Workspace-aware: tracks workspace_uri for proper isolation of skill
    state and events per workspace.
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,too-many-statements
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
    ):
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
        from datetime import date  # pylint: disable=import-outside-toplevel

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
                from tool_modules.aa_workflow.src.skill_execution_events import (  # pylint: disable=import-outside-toplevel
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
                    "Event emitter initialized for skill: %s (workspace: %s, source: %s)",
                    skill_name,
                    workspace_uri,
                    source,
                )
                # Debug: write to a file to confirm emitter is created
                from pathlib import Path  # pylint: disable=import-outside-toplevel

                debug_file = (
                    Path.home() / ".config" / "aa-workflow" / "emitter_debug.log"
                )
                debug_file.parent.mkdir(parents=True, exist_ok=True)
                with open(debug_file, "a", encoding="utf-8") as f:
                    from datetime import (  # pylint: disable=import-outside-toplevel
                        datetime,
                    )  # pylint: disable=import-outside-toplevel

                    skill_name = skill.get("name", "unknown")
                    f.write(
                        f"{datetime.now().isoformat()} - Emitter created for {skill_name} (source: {source})\n"  # pylint: disable=line-too-long
                    )
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Failed to initialize event emitter: %s", e)
                # Also write to debug file on failure
                try:
                    from datetime import (  # pylint: disable=import-outside-toplevel
                        datetime,
                    )  # pylint: disable=import-outside-toplevel
                    from pathlib import Path  # pylint: disable=import-outside-toplevel

                    debug_file = (
                        Path.home() / ".config" / "aa-workflow" / "emitter_debug.log"
                    )
                    debug_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(debug_file, "a", encoding="utf-8") as f:
                        f.write(
                            f"{datetime.now().isoformat()} - FAILED to create emitter: {e}\n"
                        )
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.debug("Suppressed error: %s", exc)

        # Layer 5: Initialize usage pattern learner
        self.usage_learner = None
        if LAYER5_AVAILABLE:
            try:
                self.usage_learner = UsagePatternLearner()
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Failed to initialize Layer 5 learner: %s", e)

        # WebSocket server for real-time updates
        self.ws_server = None
        if WEBSOCKET_AVAILABLE:
            try:
                self.ws_server = get_websocket_server()
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.debug("WebSocket server not available: %s", e)

        # Generate unique skill execution ID
        import uuid  # pylint: disable=import-outside-toplevel

        self.skill_id = str(uuid.uuid4())[:8]

    def _debug(self, msg: str):
        """Add debug message."""
        if self.debug:
            import time  # pylint: disable=import-outside-toplevel

            elapsed = (
                f"[{time.time() - self.start_time:.2f}s]" if self.start_time else ""
            )
            self.log.append(f"🔍 {elapsed} {msg}")

    async def _learn_from_error(self, tool_name: str, params: dict, error_msg: str):
        """Send error to Layer 5 learning system (async).

        This is called when on_error: continue swallows an error.
        Layer 5 will:
        1. Classify the error (usage vs infrastructure)
        2. Extract patterns and prevention steps
        3. Merge with similar patterns
        4. Build confidence over time
        """
        if not self.usage_learner:
            return

        try:
            # Learn from this error asynchronously
            await self.usage_learner.learn_from_observation(  # type: ignore[attr-defined]
                tool_name=tool_name,
                params=params,
                error_message=error_msg,
                context={},
                success=False,
            )
            self._debug(f"Layer 5: Learned from error in {tool_name}")
        except Exception as e:  # pylint: disable=broad-exception-caught
            # Don't let learning failure break the skill
            logger.warning("Layer 5 learning failed: %s", e)
