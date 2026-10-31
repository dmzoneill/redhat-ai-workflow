"""Sprint daemon issue selection and D-Bus method handlers."""

import json
import logging

import yaml

# Sprint daemon owns its own state file - no shared file with other services
from services.sprint.bot.execution_tracer import (
    ExecutionTracer,
    StepStatus,
    WorkflowState,
)
from services.sprint.daemon_common import (
    PROJECT_ROOT,
    RECOVERABLE_ERRORS,
    SPRINT_STATE_FILE,
    _add_timeline_event,
    _local_now,
    _log_safe,
    connect_chat_interface,
)
from services.sprint.daemon_work import SprintWorkMixin

logger = logging.getLogger(__name__)


def find_issue(state: dict, issue_key: str) -> dict | None:
    """The issue with ``issue_key`` in the sprint state, if present."""
    return next((issue for issue in state.get("issues", []) if issue.get("key") == issue_key), None)


async def launch_continuation_chat(issue_key: str, work_log: dict) -> str | None:
    """Ask the VS Code extension over D-Bus for a chat continuing ``issue_key``; return its chat ID."""
    bus, chat_interface = await connect_chat_interface()
    # Don't return to the previous chat: the user wants to work on this one
    result = await chat_interface.call_launch_issue_chat(issue_key, f"Continue: {work_log.get('summary', '')}", False)
    bus.disconnect()
    if not result:
        return None
    result_dict = json.loads(str(result))
    return result_dict.get("chatId") if result_dict.get("success") else None


class SprintDBusHandlersMixin(SprintWorkMixin):
    """Sprint daemon issue selection and D-Bus method handlers."""

    async def _handle_list_issues(self, status: str | None = None, actionable: bool | None = None, **_kwargs) -> dict:
        """List all sprint issues."""
        state = self._load_state()
        issues = state.get("issues", [])

        # Add actionable flag to each issue
        for issue in issues:
            issue["isActionable"] = self._is_actionable(issue)

        # Filter by status if requested
        if status:
            issues = [i for i in issues if i.get("approvalStatus") == status]

        # Filter by actionable if requested
        if actionable is not None:
            issues = [i for i in issues if i.get("isActionable") == actionable]

        actionable_count = sum(1 for i in issues if i.get("isActionable"))

        return {
            "success": True,
            "issues": issues,
            "total": len(issues),
            "actionable_count": actionable_count,
            "not_actionable_count": len(issues) - actionable_count,
        }

    async def _handle_approve_issue(self, issue_key: str | None = None, **_kwargs) -> dict:
        """Approve an issue for processing.

        Only allows approval of actionable issues (New/Refinement/Backlog).
        Issues in Review/Done cannot be approved.
        """
        if not issue_key:
            return {"success": False, "error": "issue_key required"}

        state = self._load_state()
        for issue in state.get("issues", []):
            if issue.get("key") == issue_key:
                # Check if issue is actionable
                if not self._is_actionable(issue):
                    jira_status = issue.get("jiraStatus", "unknown")
                    return {
                        "success": False,
                        "error": f"Issue {issue_key} is not actionable (status: {jira_status}). "
                        "Bot only works on issues in New/Refinement/Backlog.",
                    }

                issue["approvalStatus"] = "approved"
                _add_timeline_event(
                    issue,
                    {
                        "timestamp": _local_now().isoformat(),
                        "action": "approved",
                        "description": "Issue approved for sprint bot",
                    },
                )
                self._save_state(state)
                logger.info("Approved issue: %s", issue_key)
                return {"success": True, "message": f"Issue {issue_key} approved"}

        return {"success": False, "error": f"Issue {issue_key} not found"}

    async def _handle_reject_issue(self, issue_key: str | None = None, **_kwargs) -> dict:
        """Reject/unapprove an issue - set back to pending.

        This is the opposite of approve - removes the issue from the bot queue.
        """
        if not issue_key:
            return {"success": False, "error": "issue_key required"}

        state = self._load_state()
        for issue in state.get("issues", []):
            if issue.get("key") == issue_key:
                issue["approvalStatus"] = "pending"
                _add_timeline_event(
                    issue,
                    {
                        "timestamp": _local_now().isoformat(),
                        "action": "unapproved",
                        "description": "Issue unapproved - removed from bot queue",
                    },
                )
                self._save_state(state)
                logger.info("Rejected/unapproved issue: %s", issue_key)
                return {"success": True, "message": f"Issue {issue_key} unapproved"}

        return {"success": False, "error": f"Issue {issue_key} not found"}

    async def _handle_abort_issue(self, issue_key: str | None = None, **_kwargs) -> dict:
        """Abort an in-progress issue - user takes control.

        Sets the issue to blocked and clears processingIssue if it matches.
        """
        if not issue_key:
            return {"success": False, "error": "issue_key required"}

        state = self._load_state()
        for issue in state.get("issues", []):
            if issue.get("key") == issue_key:
                issue["approvalStatus"] = "blocked"
                _add_timeline_event(
                    issue,
                    {
                        "timestamp": _local_now().isoformat(),
                        "action": "aborted",
                        "description": "User took control - automated work stopped",
                    },
                )
                # Clear processingIssue if this was the active one
                if state.get("processingIssue") == issue_key:
                    state["processingIssue"] = None
                self._save_state(state)
                logger.info("Aborted issue: %s", issue_key)
                return {
                    "success": True,
                    "message": f"Issue {issue_key} aborted - you can now work on it manually",
                }

        return {"success": False, "error": f"Issue {issue_key} not found"}

    async def _handle_skip_issue(
        self, issue_key: str | None = None, reason: str = "Manually skipped", **_kwargs
    ) -> dict:
        """Skip/block an issue."""
        if not issue_key:
            return {"success": False, "error": "issue_key required"}

        state = self._load_state()
        for issue in state.get("issues", []):
            if issue.get("key") == issue_key:
                issue["approvalStatus"] = "blocked"
                issue["waitingReason"] = reason
                _add_timeline_event(
                    issue,
                    {
                        "timestamp": _local_now().isoformat(),
                        "action": "skipped",
                        "description": f"Issue skipped: {reason}",
                    },
                )
                self._save_state(state)
                logger.info("Skipped issue: %s - %s", issue_key, reason)
                return {"success": True, "message": f"Issue {issue_key} skipped"}

        return {"success": False, "error": f"Issue {issue_key} not found"}

    async def _handle_refresh(self, **_kwargs) -> dict:
        """Force refresh from Jira."""
        try:
            await self._refresh_from_jira()
            return {"success": True, "message": "Refreshed from Jira"}
        except RECOVERABLE_ERRORS as e:
            logger.exception("Failed to refresh from Jira via D-Bus")
            return {"success": False, "error": str(e)}

    async def _handle_enable(self, **_kwargs) -> dict:
        """Enable automatic mode (scheduled Mon-Fri 9-5)."""
        state = self._load_state()
        state["automaticMode"] = True
        state["lastUpdated"] = _local_now().isoformat()
        self._save_state(state)
        logger.info("Sprint bot automatic mode enabled")
        return {"success": True, "message": "Sprint bot automatic mode enabled"}

    async def _handle_disable(self, **_kwargs) -> dict:
        """Disable automatic mode."""
        state = self._load_state()
        state["automaticMode"] = False
        state["lastUpdated"] = _local_now().isoformat()
        self._save_state(state)
        logger.info("Sprint bot automatic mode disabled")
        return {"success": True, "message": "Sprint bot automatic mode disabled"}

    async def _handle_start(self, **_kwargs) -> dict:
        """Manually start the bot (ignores schedule)."""
        state = self._load_state()
        state["manuallyStarted"] = True
        state["lastUpdated"] = _local_now().isoformat()
        self._save_state(state)
        logger.info("Sprint bot manually started")
        return {"success": True, "message": "Sprint bot started manually"}

    async def _handle_stop(self, **_kwargs) -> dict:
        """Stop the bot (if manually started)."""
        state = self._load_state()
        state["manuallyStarted"] = False
        state["processingIssue"] = None
        state["lastUpdated"] = _local_now().isoformat()
        self._save_state(state)
        logger.info("Sprint bot stopped")
        return {"success": True, "message": "Sprint bot stopped"}

    async def _handle_get_config(self, **_kwargs) -> dict:
        """Get current configuration."""
        return {"success": True, "config": self._config}

    async def _handle_set_config(self, **kwargs) -> dict:
        """Update configuration."""
        for key, value in kwargs.items():
            if key in self._config:
                self._config[key] = value
        return {"success": True, "config": self._config}

    async def _handle_approve_all(self, **_kwargs) -> dict:
        """Approve all pending actionable issues.

        Only approves issues that are in actionable Jira statuses
        (New, Refinement, Backlog, etc.). Issues in Review/Done are skipped.
        """
        state = self._load_state()
        approved_count = 0
        skipped_count = 0

        for issue in state.get("issues", []):
            if issue.get("approvalStatus") == "pending":
                if self._is_actionable(issue):
                    issue["approvalStatus"] = "approved"
                    _add_timeline_event(
                        issue,
                        {
                            "timestamp": _local_now().isoformat(),
                            "action": "approved",
                            "description": "Bulk approved by sprint bot",
                        },
                    )
                    approved_count += 1
                else:
                    # Mark as completed/ignored since it's not actionable
                    issue["approvalStatus"] = "completed"
                    skipped_count += 1
                    logger.debug(
                        "Skipped non-actionable issue: %s (status: %s)", issue.get("key"), issue.get("jiraStatus")
                    )

        self._save_state(state)
        logger.info("Approved %s actionable issues, skipped %s non-actionable", approved_count, skipped_count)
        return {
            "success": True,
            "approved_count": approved_count,
            "skipped_count": skipped_count,
        }

    async def _handle_reject_all(self, **_kwargs) -> dict:
        """Reject/unapprove all approved issues - set back to pending.

        This is the opposite of approve_all.
        """
        state = self._load_state()
        rejected_count = 0

        for issue in state.get("issues", []):
            if issue.get("approvalStatus") == "approved":
                issue["approvalStatus"] = "pending"
                _add_timeline_event(
                    issue,
                    {
                        "timestamp": _local_now().isoformat(),
                        "action": "unapproved",
                        "description": "Bulk unapproved",
                    },
                )
                rejected_count += 1

        self._save_state(state)
        logger.info("Unapproved %s issues", rejected_count)
        return {"success": True, "rejected_count": rejected_count}

    async def _handle_toggle_background(self, enabled: bool | None = None, **_kwargs) -> dict:
        """Toggle background tasks mode.

        When enabled, the bot processes issues in background without opening
        Cursor windows in the foreground.
        """
        state = self._load_state()

        if enabled is not None:
            state["backgroundTasks"] = enabled
        else:
            state["backgroundTasks"] = not state.get("backgroundTasks", False)

        state["lastUpdated"] = _local_now().isoformat()
        self._save_state(state)

        mode = "enabled" if state["backgroundTasks"] else "disabled"
        logger.info("Background tasks %s", mode)
        return {
            "success": True,
            "backgroundTasks": state["backgroundTasks"],
            "message": f"Background tasks {mode}",
        }

    async def _handle_get_state(self, **_kwargs) -> dict:
        """Get full sprint state for UI.

        Returns the complete sprint state including issues, config, and status.
        This is the primary method for UI to read sprint state via D-Bus.
        """
        state = self._load_state()

        # Add runtime status info
        _, _, within_hours, is_active = self._runtime_flags(state)

        state["runtime"] = {
            "is_active": is_active,
            "within_working_hours": within_hours,
            "issues_processed": self._issues_processed,
            "issues_completed": self._issues_completed,
            "last_jira_refresh": (self._last_jira_refresh.isoformat() if self._last_jira_refresh else None),
        }

        return {"success": True, "state": state}

    async def _handle_get_history(self, **_kwargs) -> dict:
        """Get sprint history (completed sprints).

        Returns a list of completed sprints with their issues and stats.
        """
        try:
            state = self._load_state()
            history = state.get("sprint_history", [])
            return {"success": True, "history": history}
        except RECOVERABLE_ERRORS as e:
            logger.exception("Failed to get sprint history")
            return {"success": False, "error": str(e), "history": []}

    async def _handle_get_trace(self, issue_key: str | None = None, **_kwargs) -> dict:
        """Get execution trace for an issue.

        Parameters:
            issue_key: The Jira issue key to get trace for
        """
        if not issue_key:
            return {"success": False, "error": "issue_key required"}

        try:
            traces_dir = PROJECT_ROOT / "memory" / "state" / "sprint_traces"
            trace_file = traces_dir / f"{issue_key}.yaml"

            if not trace_file.exists():
                return {"success": False, "error": f"No trace found for {issue_key}"}

            trace = yaml.safe_load(trace_file.read_text(encoding="utf-8"))

            return {"success": True, "trace": trace}
        except RECOVERABLE_ERRORS as e:
            logger.exception("Failed to get trace for %s", issue_key)
            return {"success": False, "error": str(e)}

    async def _handle_list_traces(self, **_kwargs) -> dict:
        """List all available execution traces.

        Returns a list of trace summaries (issue key, state, started_at).
        """
        try:
            traces_dir = PROJECT_ROOT / "memory" / "state" / "sprint_traces"
            traces = []

            if traces_dir.exists():
                for trace_file in traces_dir.glob("*.yaml"):
                    try:
                        trace = yaml.safe_load(trace_file.read_text(encoding="utf-8"))
                        if trace:
                            traces.append(
                                {
                                    "issue_key": trace.get("issue_key", trace_file.stem),
                                    "state": trace.get("current_state", "unknown"),
                                    "started_at": trace.get("started_at", ""),
                                }
                            )
                    except (OSError, yaml.YAMLError) as e:
                        logger.warning("Failed to parse trace %s: %s", trace_file, e)

            # Sort by started_at descending
            traces.sort(key=lambda t: t.get("started_at", ""), reverse=True)
            return {"success": True, "traces": traces}
        except RECOVERABLE_ERRORS as e:
            logger.exception("Failed to list traces")
            return {"success": False, "error": str(e), "traces": []}

    async def _handle_process_next(self, **_kwargs) -> dict:
        """Manually trigger processing of next issue."""
        result = await self._process_next_issue()
        return result

    async def _handle_get_work_log(self, params: dict) -> dict:
        """Get the work log for an issue."""
        issue_key = params.get("issue_key")
        if not issue_key:
            return {"success": False, "error": "issue_key required"}

        work_log = self._history.load_work_log(issue_key)
        if not work_log:
            return {"success": False, "error": f"No work log found for {issue_key}"}

        return {"success": True, "work_log": work_log}

    async def _handle_write_state(self, *_args, **_kwargs) -> dict:
        """Write state to file immediately (for UI refresh requests)."""
        try:
            state = self._load_state()
            self._save_state(state)
            return {"success": True, "file": str(SPRINT_STATE_FILE)}
        except RECOVERABLE_ERRORS as e:
            logger.exception("Failed to save sprint state via D-Bus")
            return {"success": False, "error": str(e)}

    async def _handle_start_issue(self, params: dict) -> dict:
        """Start processing an issue immediately, bypassing all checks.

        This is triggered from the UI "Start Issue" button and:
        - Skips sprint started/automatic mode checks
        - Skips Jira hygiene checks (missing story points, etc.)
        - Skips actionable status checks
        - Immediately starts processing the issue

        Parameters:
            issue_key: The Jira issue key to start
            background: If False, opens chat in foreground (default: use state.backgroundTasks)
        """
        issue_key = params.get("issue_key")
        if not issue_key:
            return {"success": False, "error": "issue_key required"}

        # Get background preference from params, falling back to state setting
        state = self._load_state()
        background_mode = params.get("background")
        if background_mode is None:
            background_mode = state.get("backgroundTasks", True)

        target_issue = find_issue(state, issue_key)
        if not target_issue:
            return {"success": False, "error": f"Issue {issue_key} not found in sprint"}

        logger.info("Starting issue immediately: %s (background=%s)", _log_safe(issue_key), _log_safe(background_mode))
        target_issue["approvalStatus"] = "in_progress"
        state["processingIssue"] = issue_key
        _add_timeline_event(
            target_issue,
            {
                "timestamp": _local_now().isoformat(),
                "action": "force_started",
                "description": "Issue started immediately via UI (bypassing checks)",
            },
        )
        self._save_state(state)

        tracer = self._get_tracer(issue_key, target_issue)
        self._trace_transition(tracer, WorkflowState.LOADING, trigger="force_start")
        self._trace_step(
            tracer,
            "force_start_issue",
            inputs={"issue_key": issue_key, "background_mode": background_mode},
            decision="force_start",
            reason="User requested immediate start via UI, bypassing all checks",
        )

        if not background_mode:
            return await self._force_start_in_cursor(target_issue, state, tracer)

        # BACKGROUND MODE: Run via Claude CLI
        await self._start_jira_work(tracer, issue_key, "force_start_background")
        self._trace_transition(tracer, WorkflowState.BUILDING_PROMPT, trigger="jira_transitioned")
        result = await self._run_background_and_record(target_issue, state, tracer)
        if result.get("success"):
            return {"success": True, "message": f"Completed {issue_key}", "mode": "background"}
        return {"success": False, "error": result.get("error", "Background processing failed"), "mode": "background"}

    async def _force_start_in_cursor(self, issue: dict, state: dict, tracer: ExecutionTracer) -> dict:
        """Foreground force-start: open a Cursor chat, or block the issue when Cursor is not running."""
        if await self._is_cursor_available():
            return await self._process_in_cursor_traced(issue, state, tracer)
        issue["approvalStatus"] = "blocked"
        issue["waitingReason"] = "Cursor not available for foreground mode"
        state["processingIssue"] = None
        self._save_state(state)
        return {
            "success": False,
            "error": "Cursor is not available. Please open VS Code/Cursor first, or use background mode.",
        }

    async def _run_background_and_record(self, issue: dict, state: dict, tracer: ExecutionTracer) -> dict:
        """Mark the issue started, run it via Claude CLI and record completion (to Review) or the block reason.

        Returns the background run's result.
        """
        issue_key = issue["key"]
        issue["approvalStatus"] = "in_progress"
        issue["jiraStatus"] = self.jira_status_in_progress
        state["processingIssue"] = issue_key
        _add_timeline_event(
            issue,
            {
                "timestamp": _local_now().isoformat(),
                "action": "started",
                "description": "Sprint bot started background processing",
                "jiraTransition": self.jira_status_in_progress,
            },
        )
        issue["hasTrace"] = True
        issue["tracePath"] = str(tracer.trace_path)
        self._save_state(state)

        self._trace_transition(tracer, WorkflowState.IMPLEMENTING, trigger="prompt_ready_background")
        result = await self._run_issue_in_background_traced(issue, tracer)

        # Reload state in case it changed during the run
        state = self._load_state()
        issue = find_issue(state, issue_key) or issue
        work_log_path = str(self._history.get_work_log_path(issue_key))
        if result.get("success"):
            await self._move_to_review(issue, tracer, work_log_path)
            self._issues_processed += 1
        else:
            # Blocked: Jira stays "In Progress"; the issue waits for a human with the reason
            error_reason = result.get("error", "Background processing failed")
            tracer.mark_blocked(error_reason)
            _add_timeline_event(
                issue,
                {
                    "timestamp": _local_now().isoformat(),
                    "action": "background_blocked",
                    "description": f"Bot blocked: {error_reason}",
                },
            )
            issue["approvalStatus"] = "blocked"
            issue["waitingReason"] = error_reason
        issue.update(hasWorkLog=True, workLogPath=work_log_path, hasTrace=True, tracePath=str(tracer.trace_path))
        state["processingIssue"] = None
        self._save_state(state)
        return result

    async def _move_to_review(self, issue: dict, tracer: ExecutionTracer, work_log_path: str) -> None:
        """Transition a completed issue to In Review in Jira, the trace and the issue's timeline."""
        issue_key = issue["key"]
        self._trace_transition(tracer, WorkflowState.CREATING_MR, trigger="implementation_complete")
        await self._transition_jira_issue(issue_key, self.jira_status_in_review)
        self._trace_step(
            tracer,
            "transition_jira_review",
            inputs={"issue_key": issue_key, "target_status": self.jira_status_in_review},
            outputs={"success": True},
            tool_name="jira_transition",
        )
        self._trace_transition(tracer, WorkflowState.AWAITING_REVIEW, trigger="mr_created")
        tracer.mark_completed(summary=f"MR created for {issue_key}")
        _add_timeline_event(
            issue,
            {
                "timestamp": _local_now().isoformat(),
                "action": "background_completed",
                "description": "Background processing completed - moved to review",
                "workLogPath": work_log_path,
                "jiraTransition": self.jira_status_in_review,
            },
        )
        issue["approvalStatus"] = "completed"
        issue["jiraStatus"] = self.jira_status_in_review

    async def _handle_open_in_cursor(self, params: dict) -> dict:
        """Open an issue's work log in Cursor for interactive continuation.

        This creates a new Cursor chat with the context from the background work,
        allowing the user to continue working on the issue interactively.
        """
        issue_key = params.get("issue_key")
        if not issue_key:
            return {"success": False, "error": "issue_key required"}

        work_log = self._history.load_work_log(issue_key)
        if not work_log:
            return {"success": False, "error": f"No work log found for {issue_key}"}

        if not await self._is_cursor_available():
            return {"success": False, "error": "Cursor is not available. Please open VS Code/Cursor first."}

        prompt = self._history.build_cursor_context_prompt(issue_key, work_log)
        try:
            chat_id = await launch_continuation_chat(issue_key, work_log)
        except RECOVERABLE_ERRORS as e:
            logger.exception("Failed to open %s in Cursor", issue_key)
            return {"success": False, "error": str(e)}
        if not chat_id:
            return {"success": False, "error": "Failed to create Cursor chat"}

        state = self._load_state()
        issue = find_issue(state, issue_key)
        if issue:
            issue["chatId"] = chat_id
            _add_timeline_event(
                issue,
                {
                    "timestamp": _local_now().isoformat(),
                    "action": "opened_in_cursor",
                    "description": "Opened background work in Cursor for interactive continuation",
                    "chatLink": chat_id,
                },
            )
        self._save_state(state)
        logger.info("Opened %s in Cursor: %s", issue_key, chat_id)
        return {
            "success": True,
            "message": f"Opened {issue_key} in Cursor",
            "chat_id": chat_id,
            "context_prompt": prompt,
        }

    async def _process_next_issue(self) -> dict:
        """Process the next approved issue that is actionable.

        Execution mode depends on backgroundTasks setting:
        - backgroundTasks=false (Foreground): Opens Cursor chat, WAITS if Cursor not available
        - backgroundTasks=true (Background): Runs via Claude CLI, no Cursor dependency

        Now includes execution tracing for full observability.
        """
        state = self._load_state()
        next_issue = next(
            (i for i in state.get("issues", []) if i.get("approvalStatus") == "approved" and self._is_actionable(i)),
            None,
        )
        if not next_issue:
            return {"success": True, "message": "No approved actionable issues to process"}

        issue_key = next_issue["key"]
        background_mode = state.get("backgroundTasks", True)
        logger.info("Processing issue: %s (background=%s)", _log_safe(issue_key), _log_safe(background_mode))

        tracer = self._get_tracer(issue_key, next_issue)
        workflow_type = self._trace_issue_analysis(tracer, next_issue)
        cursor_available = await self._is_cursor_available()

        if not background_mode:
            return await self._process_in_foreground(next_issue, state, tracer, cursor_available)

        # BACKGROUND MODE: Run via Claude CLI (no Cursor dependency)
        logger.info("Background mode: Running %s via Claude CLI", _log_safe(issue_key))
        self._trace_step(
            tracer,
            "select_execution_mode",
            inputs={"background_tasks": True, "cursor_available": cursor_available},
            decision="background",
            reason="Background mode enabled, running via Claude CLI",
        )
        await self._start_jira_work(tracer, issue_key, "is_actionable")
        if workflow_type == "spike":
            self._trace_transition(tracer, WorkflowState.RESEARCHING, trigger="transitioned_spike")
        else:
            self._trace_transition(tracer, WorkflowState.STARTING_WORK, trigger="transitioned_code_change")
        self._trace_transition(tracer, WorkflowState.BUILDING_PROMPT, trigger="branch_created")
        self._trace_step(
            tracer,
            "build_work_prompt",
            inputs={"workflow_type": workflow_type},
            outputs={"prompt_length": len(self._build_work_prompt(next_issue))},
        )
        return await self._run_background_and_record(next_issue, state, tracer)

    def _trace_issue_analysis(self, tracer: ExecutionTracer, issue: dict) -> str:
        """Trace loading, classifying and the actionability check of an issue; return its workflow type."""
        self._trace_transition(tracer, WorkflowState.LOADING, trigger="start_processing")
        self._trace_step(
            tracer,
            "load_issue",
            inputs={"issue_key": issue["key"], "approval_status": issue.get("approvalStatus")},
            outputs={"summary": issue.get("summary", "")[:100], "jira_status": issue.get("jiraStatus")},
        )
        self._trace_transition(tracer, WorkflowState.ANALYZING, trigger="issue_loaded")

        workflow_type = self.workflow_config.classify_issue(issue)
        tracer.set_workflow_type(
            workflow_type,
            reason=f"Issue type: {issue.get('issueType', 'Story')}, keywords matched: {workflow_type}",
        )
        self._trace_transition(tracer, WorkflowState.CLASSIFYING, trigger="analysis_complete")

        is_actionable = self._is_actionable(issue)
        verdict = "actionable" if is_actionable else "not actionable"
        self._trace_step(
            tracer,
            "check_actionable",
            inputs={"jira_status": issue.get("jiraStatus")},
            outputs={"is_actionable": is_actionable},
            decision=verdict.replace(" ", "_"),
            reason=f"Status '{issue.get('jiraStatus')}' is {verdict} per workflow config",
        )
        self._trace_transition(tracer, WorkflowState.CHECKING_ACTIONABLE, trigger="classified")
        return workflow_type

    async def _process_in_foreground(
        self, issue: dict, state: dict, tracer: ExecutionTracer, cursor_available: bool
    ) -> dict:
        """Foreground mode needs Cursor: launch the chat, or wait until Cursor is running."""
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
            return {"success": False, "waiting": True, "message": "Waiting for Cursor to be available"}
        self._trace_step(tracer, "check_cursor", inputs={"mode": "foreground"}, outputs={"cursor_available": True})
        return await self._process_in_cursor_traced(issue, state, tracer)
