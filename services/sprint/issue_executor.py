"""
Issue Executor — Claude CLI invocation, Cursor chat launching, and Jira transitions.

Extracted from SprintDaemon to keep issue execution logic separate from
daemon lifecycle and D-Bus orchestration.
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from services.sprint.bot.execution_tracer import (
    ExecutionTracer,
    StepStatus,
    WorkflowState,
)

PROJECT_ROOT = Path(__file__).parent.parent.parent

logger = logging.getLogger(__name__)


class IssueExecutor:
    """Handles executing work on individual issues via Claude CLI or Cursor."""

    def __init__(self, planner, history_tracker):
        """Initialize with references to planner and history tracker.

        Args:
            planner: SprintPlanner instance for workflow config, actionability checks.
            history_tracker: SprintHistoryTracker instance for work log management.
        """
        self.planner = planner
        self.history = history_tracker

    # ==================== Execution Tracing ====================

    def _get_tracer(
        self, issue_key: str, issue: dict = None, load_state_fn=None
    ) -> ExecutionTracer:
        """Get or create an execution tracer for an issue.

        Loads existing trace if available, otherwise creates a new one.
        """
        # Try to load existing trace
        tracer = ExecutionTracer.load(issue_key)

        if tracer is None:
            # Create new tracer
            workflow_type = None
            execution_mode = "foreground"

            if issue:
                workflow_type = self.planner.workflow_config.classify_issue(issue)
                if load_state_fn:
                    state = load_state_fn()
                    execution_mode = (
                        "background"
                        if state.get("backgroundTasks", True)
                        else "foreground"
                    )

            tracer = ExecutionTracer(
                issue_key=issue_key,
                workflow_type=workflow_type,
                execution_mode=execution_mode,
            )

        return tracer

    def _trace_step(
        self,
        tracer: ExecutionTracer,
        name: str,
        inputs: dict = None,
        outputs: dict = None,
        decision: str = None,
        reason: str = None,
        skill_name: str = None,
        tool_name: str = None,
        status: StepStatus = StepStatus.SUCCESS,
        error: str = None,
        chat_id: str = None,
    ) -> None:
        """Log a step to the tracer and save."""
        tracer.log_step(
            name=name,
            inputs=inputs,
            outputs=outputs,
            decision=decision,
            reason=reason,
            skill_name=skill_name,
            tool_name=tool_name,
            status=status,
            error=error,
            chat_id=chat_id,
        )
        tracer.save()

    def _trace_transition(
        self,
        tracer: ExecutionTracer,
        to_state: WorkflowState,
        trigger: str = None,
        data: dict = None,
    ) -> None:
        """Log a state transition and save."""
        tracer.transition(to_state, trigger, data)
        tracer.save()

    # ==================== Jira Transitions ====================

    async def transition_jira_issue(self, issue_key: str, target_status: str) -> bool:
        """Transition a Jira issue to a new status using Claude CLI.

        Returns True if successful, False otherwise.
        """
        try:
            import shutil

            claude_path = shutil.which("claude")
            if not claude_path:
                logger.warning(f"Claude CLI not found, cannot transition {issue_key}")
                return False

            prompt = f'Call jira_transition("{issue_key}", "{target_status}") to move the issue to {target_status}.'

            process = await asyncio.create_subprocess_exec(
                claude_path,
                "--print",
                "--dangerously-skip-permissions",
                prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(PROJECT_ROOT),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=60,  # 1 minute timeout for transition
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.warning(f"Jira transition timed out for {issue_key}")
                return False

            if process.returncode == 0:
                logger.info(f"Transitioned {issue_key} to {target_status}")
                return True
            else:
                error = stderr.decode("utf-8", errors="replace") if stderr else ""
                logger.warning(f"Failed to transition {issue_key}: {error[:200]}")
                return False

        except Exception as e:
            logger.error(f"Error transitioning {issue_key}: {e}")
            return False

    # ==================== Cursor Integration ====================

    async def is_cursor_available(self) -> bool:
        """Check if Cursor/VS Code is available via D-Bus."""
        try:
            from dbus_next.aio import MessageBus

            bus = await MessageBus().connect()
            introspection = await bus.introspect(
                "com.aiworkflow.Chat", "/com/aiworkflow/Chat"
            )

            proxy = bus.get_proxy_object(
                "com.aiworkflow.Chat", "/com/aiworkflow/Chat", introspection
            )

            chat_interface = proxy.get_interface("com.aiworkflow.Chat")
            result = await chat_interface.call_ping()
            bus.disconnect()

            return result and "pong" in result

        except Exception:
            return False

    async def launch_cursor_chat(self, issue: dict, load_state_fn) -> str | None:
        """Launch a Cursor chat for an issue via D-Bus.

        Calls the VS Code extension's D-Bus service to create a new chat
        for the given issue with the unified work prompt. The extension will:
        1. Create a new Cursor chat
        2. Name it with the issue key (using Cursor's auto-naming)
        3. Paste the unified work prompt
        4. Optionally return to the previous chat (background mode)

        Returns the chat ID if successful, None otherwise.
        """
        state = load_state_fn()
        return_to_previous = state.get("backgroundTasks", True)

        # Build the unified work prompt
        prompt = self.planner.build_work_prompt(issue)

        try:
            from dbus_next.aio import MessageBus

            bus = await MessageBus().connect()

            # Get the VS Code extension's chat service
            introspection = await bus.introspect(
                "com.aiworkflow.Chat", "/com/aiworkflow/Chat"
            )

            proxy = bus.get_proxy_object(
                "com.aiworkflow.Chat", "/com/aiworkflow/Chat", introspection
            )

            chat_interface = proxy.get_interface("com.aiworkflow.Chat")

            # Launch the chat with the unified prompt
            # Method signature: LaunchIssueChatWithPrompt(issueKey, summary, prompt, returnToPrevious) -> string
            result = await chat_interface.call_launch_issue_chat_with_prompt(
                issue["key"],
                issue.get("summary", "sprint work"),
                prompt,
                return_to_previous,
            )

            bus.disconnect()

            if result:
                result_dict = json.loads(str(result))
                if result_dict.get("success"):
                    return result_dict.get("chatId")
                else:
                    logger.warning(
                        f"LaunchIssueChatWithPrompt returned error: {result_dict.get('error')}"
                    )

            return None

        except Exception as e:
            logger.error(f"Failed to launch chat via D-Bus: {e}")
            logger.debug("Is VS Code running with the AA Workflow extension active?")
            return None

    # ==================== Issue Processing ====================

    async def process_next_issue(
        self, load_state_fn, save_state_fn, on_issue_processed
    ) -> dict:
        """Process the next approved issue that is actionable.

        Execution mode depends on backgroundTasks setting:
        - backgroundTasks=false (Foreground): Opens Cursor chat, WAITS if Cursor not available
        - backgroundTasks=true (Background): Runs via Claude CLI, no Cursor dependency

        Now includes execution tracing for full observability.

        Args:
            load_state_fn: Callable to load current daemon state.
            save_state_fn: Callable to save daemon state.
            on_issue_processed: Callable to increment processed counter.
        """
        from services.sprint.daemon import _add_timeline_event

        state = load_state_fn()

        # Find next approved issue that is also actionable
        next_issue = None
        for issue in state.get("issues", []):
            if issue.get("approvalStatus") == "approved" and self.planner.is_actionable(
                issue
            ):
                next_issue = issue
                break

        if not next_issue:
            return {
                "success": True,
                "message": "No approved actionable issues to process",
            }

        issue_key = next_issue["key"]
        background_mode = state.get("backgroundTasks", True)

        logger.info(f"Processing issue: {issue_key} (background={background_mode})")

        # Initialize execution tracer
        tracer = self._get_tracer(issue_key, next_issue, load_state_fn)
        self._trace_transition(
            tracer, WorkflowState.LOADING, trigger="start_processing"
        )

        # Log issue loading step
        self._trace_step(
            tracer,
            "load_issue",
            inputs={
                "issue_key": issue_key,
                "approval_status": next_issue.get("approvalStatus"),
            },
            outputs={
                "summary": next_issue.get("summary", "")[:100],
                "jira_status": next_issue.get("jiraStatus"),
            },
        )
        self._trace_transition(tracer, WorkflowState.ANALYZING, trigger="issue_loaded")

        # Classify the issue
        workflow_type = self.planner.workflow_config.classify_issue(next_issue)
        tracer.set_workflow_type(
            workflow_type,
            reason=f"Issue type: {next_issue.get('issueType', 'Story')}, keywords matched: {workflow_type}",
        )
        self._trace_transition(
            tracer, WorkflowState.CLASSIFYING, trigger="analysis_complete"
        )

        # Check actionability
        is_actionable = self.planner.is_actionable(next_issue)
        self._trace_step(
            tracer,
            "check_actionable",
            inputs={"jira_status": next_issue.get("jiraStatus")},
            outputs={"is_actionable": is_actionable},
            decision="actionable" if is_actionable else "not_actionable",
            reason=(
                f"Status '{next_issue.get('jiraStatus')}' is "
                f"{'actionable' if is_actionable else 'not actionable'} per workflow config"
            ),
        )
        self._trace_transition(
            tracer, WorkflowState.CHECKING_ACTIONABLE, trigger="classified"
        )

        # Check Cursor availability
        cursor_available = await self.is_cursor_available()

        # FOREGROUND MODE: Requires Cursor - wait if not available
        if not background_mode:
            if not cursor_available:
                logger.info("Foreground mode: Cursor not available, waiting...")
                self._trace_step(
                    tracer,
                    "check_cursor",
                    inputs={"mode": "foreground"},
                    outputs={"cursor_available": False},
                    status=StepStatus.SKIPPED,
                    reason="Cursor not available, waiting...",
                )
                return {
                    "success": False,
                    "waiting": True,
                    "message": "Waiting for Cursor to be available",
                }

            # Cursor is available - launch chat
            self._trace_step(
                tracer,
                "check_cursor",
                inputs={"mode": "foreground"},
                outputs={"cursor_available": True},
            )
            return await self._process_in_cursor_traced(
                next_issue,
                state,
                tracer,
                load_state_fn,
                save_state_fn,
                on_issue_processed,
            )

        # BACKGROUND MODE: Run via Claude CLI (no Cursor dependency)
        logger.info(f"Background mode: Running {issue_key} via Claude CLI")
        self._trace_step(
            tracer,
            "select_execution_mode",
            inputs={"background_tasks": True, "cursor_available": cursor_available},
            decision="background",
            reason="Background mode enabled, running via Claude CLI",
        )

        # Transition to starting work
        self._trace_transition(
            tracer, WorkflowState.TRANSITIONING_JIRA, trigger="is_actionable"
        )

        # Transition Jira issue to "In Progress"
        jira_success = await self.transition_jira_issue(
            issue_key, self.planner.JIRA_STATUS_IN_PROGRESS
        )
        self._trace_step(
            tracer,
            "transition_jira_in_progress",
            inputs={
                "issue_key": issue_key,
                "target_status": self.planner.JIRA_STATUS_IN_PROGRESS,
            },
            outputs={"success": jira_success},
            tool_name="jira_transition",
            status=StepStatus.SUCCESS if jira_success else StepStatus.FAILED,
        )

        if workflow_type == "spike":
            self._trace_transition(
                tracer, WorkflowState.RESEARCHING, trigger="transitioned_spike"
            )
        else:
            self._trace_transition(
                tracer, WorkflowState.STARTING_WORK, trigger="transitioned_code_change"
            )

        # Update local status
        next_issue["approvalStatus"] = "in_progress"
        next_issue["jiraStatus"] = self.planner.JIRA_STATUS_IN_PROGRESS
        state["processingIssue"] = issue_key
        _add_timeline_event(
            next_issue,
            {
                "timestamp": datetime.now().isoformat(),
                "action": "started",
                "description": "Sprint bot started background processing",
                "jiraTransition": self.planner.JIRA_STATUS_IN_PROGRESS,
            },
        )
        # Add trace reference to issue
        next_issue["hasTrace"] = True
        next_issue["tracePath"] = str(tracer.trace_path)
        save_state_fn(state)

        # Build prompt
        self._trace_transition(
            tracer, WorkflowState.BUILDING_PROMPT, trigger="branch_created"
        )
        self._trace_step(
            tracer,
            "build_work_prompt",
            inputs={"workflow_type": workflow_type},
            outputs={"prompt_length": len(self.planner.build_work_prompt(next_issue))},
        )

        # Run in background
        self._trace_transition(
            tracer, WorkflowState.IMPLEMENTING, trigger="prompt_ready_background"
        )
        result = await self._run_issue_in_background_traced(next_issue, tracer)

        # Reload state in case it changed
        state = load_state_fn()
        next_issue = next(
            (i for i in state.get("issues", []) if i["key"] == issue_key), next_issue
        )

        if result.get("success"):
            # Transition Jira issue to "In Review" (work completed, MR created)
            self._trace_transition(
                tracer, WorkflowState.CREATING_MR, trigger="implementation_complete"
            )

            await self.transition_jira_issue(
                issue_key, self.planner.JIRA_STATUS_IN_REVIEW
            )
            self._trace_step(
                tracer,
                "transition_jira_review",
                inputs={
                    "issue_key": issue_key,
                    "target_status": self.planner.JIRA_STATUS_IN_REVIEW,
                },
                outputs={"success": True},
                tool_name="jira_transition",
            )

            self._trace_transition(
                tracer, WorkflowState.AWAITING_REVIEW, trigger="mr_created"
            )
            tracer.mark_completed(summary=f"MR created for {issue_key}")

            _add_timeline_event(
                next_issue,
                {
                    "timestamp": datetime.now().isoformat(),
                    "action": "background_completed",
                    "description": "Background processing completed - moved to review",
                    "workLogPath": str(self.history.get_work_log_path(issue_key)),
                    "jiraTransition": self.planner.JIRA_STATUS_IN_REVIEW,
                },
            )
            next_issue["approvalStatus"] = "completed"
            next_issue["jiraStatus"] = self.planner.JIRA_STATUS_IN_REVIEW
            next_issue["hasWorkLog"] = True
            next_issue["workLogPath"] = str(self.history.get_work_log_path(issue_key))
            next_issue["hasTrace"] = True
            next_issue["tracePath"] = str(tracer.trace_path)
            state["processingIssue"] = None
            save_state_fn(state)
            on_issue_processed()
            return result
        else:
            # Bot is blocked - keep in "In Progress" but mark as blocked with reason
            # Do NOT transition Jira status - it stays "In Progress"
            error_reason = result.get("error", "Background processing failed")

            tracer.mark_blocked(error_reason)

            _add_timeline_event(
                next_issue,
                {
                    "timestamp": datetime.now().isoformat(),
                    "action": "background_blocked",
                    "description": f"Bot blocked: {error_reason}",
                },
            )
            next_issue["approvalStatus"] = "blocked"
            next_issue["waitingReason"] = error_reason
            # jiraStatus stays as "In Progress" - issue is not done, just blocked
            next_issue["hasWorkLog"] = True
            next_issue["hasTrace"] = True
            next_issue["tracePath"] = str(tracer.trace_path)
            next_issue["workLogPath"] = str(self.history.get_work_log_path(issue_key))
            state["processingIssue"] = None
            save_state_fn(state)
            return result

    async def process_in_cursor(
        self, issue: dict, state: dict, load_state_fn, save_state_fn, on_issue_processed
    ) -> dict:
        """Process an issue by opening a Cursor chat (foreground mode).

        In foreground mode, the bot creates a Cursor chat and the user/bot
        works interactively. The Jira transitions happen:
        - Start: Transition to "In Progress"
        - The chat itself handles completion/review transitions via skills
        """
        # Create tracer and delegate to traced version
        tracer = self._get_tracer(issue["key"], issue, load_state_fn)
        return await self._process_in_cursor_traced(
            issue, state, tracer, load_state_fn, save_state_fn, on_issue_processed
        )

    async def _process_in_cursor_traced(
        self,
        issue: dict,
        state: dict,
        tracer: ExecutionTracer,
        load_state_fn,
        save_state_fn,
        on_issue_processed,
    ) -> dict:
        """Process an issue in Cursor with full execution tracing."""
        from services.sprint.daemon import _add_timeline_event

        issue_key = issue["key"]

        # Transition to starting work
        self._trace_transition(
            tracer, WorkflowState.TRANSITIONING_JIRA, trigger="is_actionable"
        )

        # Transition Jira issue to "In Progress"
        jira_success = await self.transition_jira_issue(
            issue_key, self.planner.JIRA_STATUS_IN_PROGRESS
        )
        self._trace_step(
            tracer,
            "transition_jira_in_progress",
            inputs={
                "issue_key": issue_key,
                "target_status": self.planner.JIRA_STATUS_IN_PROGRESS,
            },
            outputs={"success": jira_success},
            tool_name="jira_transition",
            status=StepStatus.SUCCESS if jira_success else StepStatus.FAILED,
        )

        self._trace_transition(
            tracer, WorkflowState.STARTING_WORK, trigger="transitioned_code_change"
        )

        # Update local status
        issue["approvalStatus"] = "in_progress"
        issue["jiraStatus"] = self.planner.JIRA_STATUS_IN_PROGRESS
        state["processingIssue"] = issue_key
        _add_timeline_event(
            issue,
            {
                "timestamp": datetime.now().isoformat(),
                "action": "started",
                "description": "Sprint bot started processing in Cursor",
                "jiraTransition": self.planner.JIRA_STATUS_IN_PROGRESS,
            },
        )
        issue["hasTrace"] = True
        issue["tracePath"] = str(tracer.trace_path)
        save_state_fn(state)

        # Build prompt
        self._trace_transition(
            tracer, WorkflowState.BUILDING_PROMPT, trigger="branch_created"
        )
        prompt = self.planner.build_work_prompt(issue)
        self._trace_step(
            tracer,
            "build_work_prompt",
            inputs={"workflow_type": tracer.workflow_type},
            outputs={"prompt_length": len(prompt)},
        )

        # Launch Cursor chat
        self._trace_transition(
            tracer, WorkflowState.LAUNCHING_CHAT, trigger="prompt_ready_foreground"
        )
        self._trace_step(tracer, "launch_cursor_chat", inputs={"issue_key": issue_key})

        chat_id = await self.launch_cursor_chat(issue, load_state_fn)

        if chat_id:
            self._trace_step(
                tracer,
                "chat_created",
                outputs={"chat_id": chat_id},
                chat_id=chat_id,
            )
            self._trace_transition(
                tracer, WorkflowState.IMPLEMENTING, trigger="chat_launched"
            )

            issue["chatId"] = chat_id
            _add_timeline_event(
                issue,
                {
                    "timestamp": datetime.now().isoformat(),
                    "action": "chat_created",
                    "description": "Cursor chat created - work in progress",
                    "chatLink": chat_id,
                },
            )
            save_state_fn(state)
            on_issue_processed()
            logger.info(f"Chat created for {issue_key}: {chat_id}")

            # Note: In foreground mode, the tracer stays in IMPLEMENTING state
            # The chat itself will complete the work and transition Jira
            tracer.save()

            return {
                "success": True,
                "message": f"Processing {issue_key}",
                "chat_id": chat_id,
            }
        else:
            # Chat creation failed - mark as blocked but keep In Progress in Jira
            self._trace_step(
                tracer,
                "chat_creation_failed",
                error="Failed to create Cursor chat",
                status=StepStatus.FAILED,
            )
            tracer.mark_blocked("Failed to create Cursor chat")

            issue["approvalStatus"] = "blocked"
            issue["waitingReason"] = "Failed to create Cursor chat"
            state["processingIssue"] = None
            save_state_fn(state)
            logger.warning(f"Could not create chat for {issue_key}")
            return {"success": False, "error": f"Failed to create chat for {issue_key}"}

    # ==================== Background Execution ====================

    async def run_issue_in_background(self, issue: dict) -> dict:
        """Run issue processing via Claude CLI (no Cursor chat).

        This is used when backgroundTasks=true and allows the bot to work
        without requiring Cursor to be open.

        The work log captures all actions so the issue can be continued
        interactively in Cursor later if needed.

        Returns dict with success status and details.
        """
        # Create tracer and delegate to traced version
        tracer = self._get_tracer(issue["key"], issue)
        return await self._run_issue_in_background_traced(issue, tracer)

    async def _run_issue_in_background_traced(
        self, issue: dict, tracer: ExecutionTracer
    ) -> dict:
        """Run issue processing via Claude CLI with full execution tracing.

        Returns dict with success status and details.
        """
        issue_key = issue["key"]

        logger.info(f"Running {issue_key} in background mode (Claude CLI)")

        # Initialize work log
        work_log = self.history.init_work_log(issue)
        self.history.save_work_log(issue_key, work_log)

        self.history.log_action(issue_key, "started", "Background processing started")
        self._trace_step(
            tracer,
            "init_work_log",
            outputs={"work_log_path": str(self.history.get_work_log_path(issue_key))},
        )

        # Emit toast notification for issue started
        try:
            from tool_modules.aa_workflow.src.notification_emitter import (
                notify_sprint_issue_started,
            )

            notify_sprint_issue_started(issue_key, issue.get("summary", "")[:50])
        except Exception:
            pass

        try:
            import shutil

            claude_path = shutil.which("claude")
            if not claude_path:
                self.history.log_action(issue_key, "error", "Claude CLI not found")
                self._trace_step(
                    tracer,
                    "check_claude_cli",
                    error="Claude CLI not found",
                    status=StepStatus.FAILED,
                )
                tracer.mark_failed("Claude CLI not found")
                work_log["status"] = "failed"
                work_log["error"] = "Claude CLI not found"
                self.history.save_work_log(issue_key, work_log)
                return {"success": False, "error": "Claude CLI not found"}

            self._trace_step(
                tracer, "check_claude_cli", outputs={"claude_path": claude_path}
            )

            # Build the unified work prompt
            prompt = self.planner.build_work_prompt(issue)

            self.history.log_action(
                issue_key,
                "claude_started",
                "Started Claude CLI execution",
                {
                    "prompt_length": len(prompt),
                },
            )

            # Start step for Claude execution
            step_id = tracer.start_step(
                "execute_claude_cli", inputs={"prompt_length": len(prompt)}
            )

            # Run Claude CLI with extended timeout for actual work
            process = await asyncio.create_subprocess_exec(
                claude_path,
                "--print",
                "--dangerously-skip-permissions",
                prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(PROJECT_ROOT),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=1800,  # 30 minute timeout for actual work
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                self.history.log_action(
                    issue_key, "timeout", "Claude CLI timed out after 30 minutes"
                )
                tracer.end_step(
                    step_id, status=StepStatus.FAILED, error="Timeout after 30 minutes"
                )
                tracer.mark_failed("Claude CLI timed out after 30 minutes")
                work_log = self.history.load_work_log(issue_key)
                work_log["status"] = "timeout"
                work_log["completed"] = datetime.now().isoformat()
                work_log["cursor_context"]["can_continue"] = True
                work_log["cursor_context"]["suggested_prompt"] = (
                    f"Continue working on {issue_key}. The background process timed out. "
                    "Review the work log and continue from where it left off."
                )
                self.history.save_work_log(issue_key, work_log)
                return {"success": False, "error": "Claude CLI timed out"}

            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            error_output = stderr.decode("utf-8", errors="replace") if stderr else ""

            # Update work log with results
            work_log = self.history.load_work_log(issue_key)
            work_log["completed"] = datetime.now().isoformat()

            # Parse output to extract useful information
            self._parse_background_output(issue_key, output, work_log)

            # Check for explicit status markers in output
            bot_status = self._parse_bot_status(output)

            # End the Claude execution step
            tracer.end_step(
                step_id,
                status=(
                    StepStatus.SUCCESS
                    if bot_status["status"] in ("COMPLETED", "UNKNOWN")
                    and process.returncode == 0
                    else StepStatus.FAILED
                ),
                outputs={
                    "return_code": process.returncode,
                    "bot_status": bot_status["status"],
                    "output_length": len(output),
                    "commits_found": len(
                        work_log.get("outcome", {}).get("commits", [])
                    ),
                    "mrs_found": len(
                        work_log.get("outcome", {}).get("merge_requests", [])
                    ),
                },
            )

            if bot_status["status"] == "COMPLETED":
                work_log["status"] = "completed"
                self.history.log_action(
                    issue_key,
                    "completed",
                    "Background processing completed successfully",
                )

                # Emit toast notification for issue completed
                try:
                    from tool_modules.aa_workflow.src.notification_emitter import (
                        notify_sprint_issue_completed,
                    )

                    notify_sprint_issue_completed(issue_key)
                except Exception:
                    pass
                self._trace_step(
                    tracer,
                    "parse_result",
                    decision="completed",
                    reason="Bot reported COMPLETED status",
                    outputs={"commits": work_log.get("outcome", {}).get("commits", [])},
                )

                # Create context for continuing in Cursor
                work_log["cursor_context"]["can_continue"] = True
                work_log["cursor_context"]["suggested_prompt"] = (
                    self.history.generate_continuation_prompt(issue_key, work_log)
                )

                self.history.save_work_log(issue_key, work_log)
                logger.info(f"Background processing completed for {issue_key}")
                return {
                    "success": True,
                    "message": f"Completed {issue_key} in background",
                }

            elif bot_status["status"] == "BLOCKED":
                # Bot is blocked - needs human intervention
                blocked_reason = bot_status.get("reason", "Unknown reason")
                work_log["status"] = "blocked"
                work_log["blocked_reason"] = blocked_reason
                self.history.log_action(
                    issue_key, "blocked", f"Bot blocked: {blocked_reason}"
                )

                # Emit toast notification for issue blocked
                try:
                    from tool_modules.aa_workflow.src.notification_emitter import (
                        notify_sprint_issue_blocked,
                    )

                    notify_sprint_issue_blocked(issue_key, blocked_reason)
                except Exception:
                    pass
                self._trace_step(
                    tracer,
                    "parse_result",
                    decision="blocked",
                    reason=blocked_reason,
                    status=StepStatus.FAILED,
                )

                work_log["cursor_context"]["can_continue"] = True
                work_log["cursor_context"]["suggested_prompt"] = (
                    f"The bot was blocked on {issue_key}: {blocked_reason}. "
                    "Please provide the needed information or continue the work."
                )

                self.history.save_work_log(issue_key, work_log)
                logger.warning(
                    f"Background processing blocked for {issue_key}: {blocked_reason}"
                )
                return {
                    "success": False,
                    "error": f"Blocked: {blocked_reason}",
                    "blocked": True,
                }

            elif bot_status["status"] == "FAILED" or process.returncode != 0:
                # Bot failed
                error_reason = bot_status.get("error") or error_output[:500]
                work_log["status"] = "failed"
                work_log["error"] = error_reason
                self.history.log_action(
                    issue_key,
                    "failed",
                    f"Background processing failed: {error_reason[:200]}",
                )
                self._trace_step(
                    tracer,
                    "parse_result",
                    decision="failed",
                    error=error_reason[:200],
                    status=StepStatus.FAILED,
                )

                work_log["cursor_context"]["can_continue"] = True
                work_log["cursor_context"]["suggested_prompt"] = (
                    f"The background process for {issue_key} failed: {error_reason[:200]}. "
                    "Please investigate and continue the work."
                )

                self.history.save_work_log(issue_key, work_log)
                logger.warning(
                    f"Background processing failed for {issue_key}: {error_reason[:200]}"
                )
                return {"success": False, "error": f"Failed: {error_reason[:200]}"}

            else:
                # No explicit status - assume completed if return code is 0
                if process.returncode == 0:
                    work_log["status"] = "completed"
                    self.history.log_action(
                        issue_key,
                        "completed",
                        "Background processing completed (no explicit status)",
                    )
                    work_log["cursor_context"]["can_continue"] = True
                    work_log["cursor_context"]["suggested_prompt"] = (
                        self.history.generate_continuation_prompt(issue_key, work_log)
                    )
                    self.history.save_work_log(issue_key, work_log)
                    logger.info(f"Background processing completed for {issue_key}")
                    return {
                        "success": True,
                        "message": f"Completed {issue_key} in background",
                    }
                else:
                    work_log["status"] = "failed"
                    work_log["error"] = error_output[:500]
                    self.history.log_action(
                        issue_key, "failed", f"Claude CLI failed: {error_output[:200]}"
                    )
                    work_log["cursor_context"]["can_continue"] = True
                    work_log["cursor_context"][
                        "suggested_prompt"
                    ] = f"The background process for {issue_key} failed. Please investigate and continue the work."
                    self.history.save_work_log(issue_key, work_log)
                    logger.warning(
                        f"Background processing failed for {issue_key}: {error_output[:200]}"
                    )
                    return {
                        "success": False,
                        "error": f"Claude CLI failed: {error_output[:200]}",
                    }

        except Exception as e:
            self.history.log_action(issue_key, "error", f"Exception: {str(e)}")
            work_log = self.history.load_work_log(issue_key)
            work_log["status"] = "failed"
            work_log["error"] = str(e)
            work_log["completed"] = datetime.now().isoformat()
            work_log["cursor_context"]["can_continue"] = True
            work_log["cursor_context"]["suggested_prompt"] = (
                f"The background process for {issue_key} encountered an error: {str(e)}. "
                "Please investigate and continue the work."
            )
            self.history.save_work_log(issue_key, work_log)
            logger.error(f"Background processing error for {issue_key}: {e}")
            return {"success": False, "error": str(e)}

    # ==================== Output Parsing ====================

    def _parse_bot_status(self, output: str) -> dict:
        """Parse the bot status marker from Claude CLI output.

        Looks for lines like:
        - [SPRINT_BOT_STATUS: COMPLETED]
        - [SPRINT_BOT_STATUS: BLOCKED] reason: Need clarification
        - [SPRINT_BOT_STATUS: FAILED] error: Could not find file

        Returns dict with 'status' and optional 'reason' or 'error'.
        """
        # Look for status marker
        status_pattern = r"\[SPRINT_BOT_STATUS:\s*(COMPLETED|BLOCKED|FAILED)\](?:\s*(?:reason|error):\s*(.+))?"
        match = re.search(status_pattern, output, re.IGNORECASE)

        if match:
            status = match.group(1).upper()
            detail = match.group(2).strip() if match.group(2) else None

            result = {"status": status}
            if status == "BLOCKED" and detail:
                result["reason"] = detail
            elif status == "FAILED" and detail:
                result["error"] = detail

            return result

        return {"status": "UNKNOWN"}

    def _parse_background_output(
        self, issue_key: str, output: str, work_log: dict
    ) -> None:
        """Parse Claude CLI output to extract commits, MRs, files changed, etc."""
        # Store full output (truncated for large outputs)
        work_log["output_summary"] = output[:5000] if len(output) > 5000 else output

        # Extract commit hashes (git commit output patterns)
        commit_pattern = r"\[[\w-]+\s+([a-f0-9]{7,40})\]"
        commits = re.findall(commit_pattern, output)
        if commits:
            work_log["outcome"]["commits"].extend(commits)
            self.history.log_action(
                issue_key,
                "commits_created",
                f"Created {len(commits)} commit(s)",
                {"commits": commits},
            )

        # Extract MR/PR URLs or IDs
        mr_pattern = r"[Mm]erge [Rr]equest[:\s]+[#!]?(\d+)|MR[:\s]+[#!]?(\d+)|!(\d+)"
        mr_matches = re.findall(mr_pattern, output)
        mrs = [m for match in mr_matches for m in match if m]
        if mrs:
            work_log["outcome"]["merge_requests"].extend(mrs)
            self.history.log_action(
                issue_key,
                "mr_created",
                "Created/referenced MR(s)",
                {"merge_requests": mrs},
            )

        # Extract file paths that were modified
        file_pattern = r"(?:modified|created|edited|changed):\s*([^\s\n]+\.[a-zA-Z]+)"
        files = re.findall(file_pattern, output, re.IGNORECASE)
        if files:
            work_log["outcome"]["files_changed"].extend(list(set(files)))
            work_log["cursor_context"]["files_to_review"] = list(set(files))[
                :10
            ]  # Top 10 files

        # Extract branch names
        branch_pattern = r"(?:branch|checkout -b|created branch)[\s:]+([a-zA-Z0-9_/-]+)"
        branches = re.findall(branch_pattern, output, re.IGNORECASE)
        if branches:
            work_log["outcome"]["branches_created"].extend(list(set(branches)))
