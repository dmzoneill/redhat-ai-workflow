"""Sprint daemon issue execution in Cursor chats or the background Claude CLI."""

import asyncio
import json
import logging
import re
import shutil
from asyncio.subprocess import Process
from collections.abc import Callable
from typing import Any, ClassVar, NamedTuple

# Sprint daemon owns its own state file - no shared file with other services
from services.sprint.bot.execution_tracer import (
    ExecutionTracer,
    StepStatus,
    WorkflowState,
)
from services.sprint.daemon_common import (
    RECOVERABLE_ERRORS,
    _add_timeline_event,
    _local_now,
    _log_safe,
    connect_chat_interface,
    spawn_claude_cli,
)
from services.sprint.daemon_state import SprintStateMixin
from tool_modules.aa_workflow.src.notification_emitter import (
    notify_sprint_issue_blocked,
    notify_sprint_issue_completed,
    notify_sprint_issue_started,
)

logger = logging.getLogger(__name__)


def notify_safely(notify: Callable[..., Any], *args: Any) -> None:
    """Send a desktop notification; a failing notifier never interrupts the work."""
    try:
        notify(*args)
    except RECOVERABLE_ERRORS as exc:
        logger.debug("Suppressed error: %s", exc, exc_info=True)


class BackgroundOutcome(NamedTuple):
    """How a finished Claude CLI run is recorded and reported."""

    status: str  # work-log status: completed, blocked or failed
    action: str  # work-log action type
    detail: str  # work-log action details
    result: dict  # returned to the caller
    prompt: str | None  # suggested Cursor prompt; None = continuation prompt from the work log
    fields: dict  # extra work-log fields
    trace: dict | None  # parse_result trace step details, if any
    notify: str | None  # completed or blocked notification, if any


def resolve_background_outcome(
    issue_key: str, bot_status: dict, returncode: int | None, error_output: str
) -> BackgroundOutcome:
    """Decide the outcome of a Claude CLI run from its status marker, exit code and stderr."""
    status = bot_status["status"]
    if status == "COMPLETED":
        return BackgroundOutcome(
            "completed",
            "completed",
            "Background processing completed successfully",
            {"success": True, "message": f"Completed {issue_key} in background"},
            None,
            {},
            {"decision": "completed", "reason": "Bot reported COMPLETED status"},
            "completed",
        )
    if status == "BLOCKED":
        reason = bot_status.get("reason", "Unknown reason")
        return BackgroundOutcome(
            "blocked",
            "blocked",
            f"Bot blocked: {reason}",
            {"success": False, "error": f"Blocked: {reason}", "blocked": True},
            f"The bot was blocked on {issue_key}: {reason}. "
            "Please provide the needed information or continue the work.",
            {"blocked_reason": reason},
            {"decision": "blocked", "reason": reason, "status": StepStatus.FAILED},
            "blocked",
        )
    if status == "FAILED" or returncode != 0:
        reason = bot_status.get("error") or error_output[:500]
        return BackgroundOutcome(
            "failed",
            "failed",
            f"Background processing failed: {reason[:200]}",
            {"success": False, "error": f"Failed: {reason[:200]}"},
            f"The background process for {issue_key} failed: {reason[:200]}. Please investigate and continue the work.",
            {"error": reason},
            {"decision": "failed", "error": reason[:200], "status": StepStatus.FAILED},
            None,
        )
    return BackgroundOutcome(
        "completed",
        "completed",
        "Background processing completed (no explicit status)",
        {"success": True, "message": f"Completed {issue_key} in background"},
        None,
        {},
        None,
        None,
    )


class SprintWorkMixin(SprintStateMixin):
    """Sprint daemon issue execution in Cursor chats or the background Claude CLI."""

    async def _process_in_cursor(self, issue: dict, state: dict) -> dict:
        """Process an issue by opening a Cursor chat (foreground mode).

        In foreground mode, the bot creates a Cursor chat and the user/bot
        works interactively. The Jira transitions happen:
        - Start: Transition to "In Progress"
        - The chat itself handles completion/review transitions via skills
        """
        # Create tracer and delegate to traced version
        tracer = self._get_tracer(issue["key"], issue)
        return await self._process_in_cursor_traced(issue, state, tracer)

    async def _process_in_cursor_traced(self, issue: dict, state: dict, tracer: ExecutionTracer) -> dict:
        """Process an issue in Cursor with full execution tracing."""
        issue_key = issue["key"]

        # Transition Jira issue to "In Progress"
        await self._start_jira_work(tracer, issue_key, "is_actionable")

        self._trace_transition(tracer, WorkflowState.STARTING_WORK, trigger="transitioned_code_change")

        # Update local status
        issue["approvalStatus"] = "in_progress"
        issue["jiraStatus"] = self.jira_status_in_progress
        state["processingIssue"] = issue_key
        _add_timeline_event(
            issue,
            {
                "timestamp": _local_now().isoformat(),
                "action": "started",
                "description": "Sprint bot started processing in Cursor",
                "jiraTransition": self.jira_status_in_progress,
            },
        )
        issue["hasTrace"] = True
        issue["tracePath"] = str(tracer.trace_path)
        self._save_state(state)

        # Build prompt
        self._trace_transition(tracer, WorkflowState.BUILDING_PROMPT, trigger="branch_created")
        prompt = self._build_work_prompt(issue)
        self._trace_step(
            tracer,
            "build_work_prompt",
            inputs={"workflow_type": tracer.workflow_type},
            outputs={"prompt_length": len(prompt)},
        )

        # Launch Cursor chat
        self._trace_transition(tracer, WorkflowState.LAUNCHING_CHAT, trigger="prompt_ready_foreground")
        self._trace_step(tracer, "launch_cursor_chat", inputs={"issue_key": issue_key})

        chat_id = await self._launch_cursor_chat(issue)

        if chat_id:
            self._trace_step(
                tracer,
                "chat_created",
                outputs={"chat_id": chat_id},
                chat_id=chat_id,
            )
            self._trace_transition(tracer, WorkflowState.IMPLEMENTING, trigger="chat_launched")

            issue["chatId"] = chat_id
            _add_timeline_event(
                issue,
                {
                    "timestamp": _local_now().isoformat(),
                    "action": "chat_created",
                    "description": "Cursor chat created - work in progress",
                    "chatLink": chat_id,
                },
            )
            self._save_state(state)
            self._issues_processed += 1
            logger.info("Chat created for %s: %s", _log_safe(issue_key), _log_safe(chat_id))

            # Note: In foreground mode, the tracer stays in IMPLEMENTING state
            # The chat itself will complete the work and transition Jira
            tracer.save()

            return {
                "success": True,
                "message": f"Processing {issue_key}",
                "chat_id": chat_id,
            }
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
        self._save_state(state)
        logger.warning("Could not create chat for %s", _log_safe(issue_key))
        return {"success": False, "error": f"Failed to create chat for {issue_key}"}

    async def _launch_cursor_chat(self, issue: dict) -> str | None:
        """Launch a Cursor chat for an issue via D-Bus.

        Calls the VS Code extension's D-Bus service to create a new chat
        for the given issue with the unified work prompt. The extension will:
        1. Create a new Cursor chat
        2. Name it with the issue key (using Cursor's auto-naming)
        3. Paste the unified work prompt
        4. Optionally return to the previous chat (background mode)

        Returns the chat ID if successful, None otherwise.
        """
        state = self._load_state()
        return_to_previous = state.get("backgroundTasks", True)

        # Build the unified work prompt
        prompt = self._build_work_prompt(issue)

        try:
            bus, chat_interface = await connect_chat_interface()

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
                logger.warning("LaunchIssueChatWithPrompt returned error: %s", result_dict.get("error"))

            return None

        except RECOVERABLE_ERRORS:
            logger.exception("Failed to launch chat via D-Bus")
            logger.debug("Is VS Code running with the AA Workflow extension active?")
            return None

    async def _run_issue_in_background(self, issue: dict) -> dict:
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

    async def _run_issue_in_background_traced(self, issue: dict, tracer: ExecutionTracer) -> dict:
        """Run issue processing via Claude CLI with full execution tracing.

        Returns dict with success status and details.
        """
        issue_key = issue["key"]
        logger.info("Running %s in background mode (Claude CLI)", _log_safe(issue_key))

        work_log = self._history.init_work_log(issue)
        self._history.save_work_log(issue_key, work_log)
        self._history.log_action(issue_key, "started", "Background processing started")
        self._trace_step(
            tracer,
            "init_work_log",
            outputs={"work_log_path": str(self._history.get_work_log_path(issue_key))},
        )
        notify_safely(notify_sprint_issue_started, issue_key, issue.get("summary", "")[:50])

        try:
            return await self._execute_in_background(issue, tracer, work_log)
        except RECOVERABLE_ERRORS as e:
            self._history.log_action(issue_key, "error", f"Exception: {e!s}")
            work_log = self._history.load_work_log(issue_key)
            work_log["completed"] = _local_now().isoformat()
            prompt = (
                f"The background process for {issue_key} encountered an error: {e!s}. "
                "Please investigate and continue the work."
            )
            self._close_work_log(issue_key, work_log, "failed", prompt, error=str(e))
            logger.exception("Background processing error for %s", _log_safe(issue_key))
            return {"success": False, "error": str(e)}

    async def _execute_in_background(self, issue: dict, tracer: ExecutionTracer, work_log: dict) -> dict:
        """Run Claude CLI on the work prompt and record the outcome in the work log and trace."""
        issue_key = issue["key"]
        claude_path = shutil.which("claude")
        if not claude_path:
            self._history.log_action(issue_key, "error", "Claude CLI not found")
            self._trace_step(tracer, "check_claude_cli", error="Claude CLI not found", status=StepStatus.FAILED)
            tracer.mark_failed("Claude CLI not found")
            work_log["status"] = "failed"
            work_log["error"] = "Claude CLI not found"
            self._history.save_work_log(issue_key, work_log)
            return {"success": False, "error": "Claude CLI not found"}
        self._trace_step(tracer, "check_claude_cli", outputs={"claude_path": claude_path})

        prompt = self._build_work_prompt(issue)
        self._history.log_action(
            issue_key, "claude_started", "Started Claude CLI execution", {"prompt_length": len(prompt)}
        )
        step_id = tracer.start_step("execute_claude_cli", inputs={"prompt_length": len(prompt)})
        process = await spawn_claude_cli(claude_path, prompt)
        streams = await self._communicate_or_time_out(process, issue_key, tracer, step_id)
        if streams is None:
            return {"success": False, "error": "Claude CLI timed out"}
        output, error_output = streams

        work_log = self._history.load_work_log(issue_key)
        work_log["completed"] = _local_now().isoformat()
        self._parse_background_output(issue_key, output, work_log)
        bot_status = self._parse_bot_status(output)
        outcome = resolve_background_outcome(issue_key, bot_status, process.returncode, error_output)
        succeeded = outcome.status == "completed" and process.returncode == 0
        tracer.end_step(
            step_id,
            status=StepStatus.SUCCESS if succeeded else StepStatus.FAILED,
            outputs={
                "return_code": process.returncode,
                "bot_status": bot_status["status"],
                "output_length": len(output),
                "commits_found": len(work_log.get("outcome", {}).get("commits", [])),
                "mrs_found": len(work_log.get("outcome", {}).get("merge_requests", [])),
            },
        )
        return self._apply_background_outcome(issue_key, tracer, work_log, outcome)

    async def _communicate_or_time_out(
        self, process: Process, issue_key: str, tracer: ExecutionTracer, step_id: str
    ) -> tuple[str, str] | None:
        """Wait for Claude CLI; return decoded (stdout, stderr), or record the timeout and return ``None``."""
        cli_timeout = self._config.get("claude_cli_timeout_seconds", 1800)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=cli_timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            timeout_mins = cli_timeout // 60
            self._history.log_action(issue_key, "timeout", f"Claude CLI timed out after {timeout_mins} minutes")
            tracer.end_step(step_id, status=StepStatus.FAILED, error=f"Timeout after {timeout_mins} minutes")
            tracer.mark_failed(f"Claude CLI timed out after {timeout_mins} minutes")
            work_log = self._history.load_work_log(issue_key)
            work_log["completed"] = _local_now().isoformat()
            prompt = (
                f"Continue working on {issue_key}. The background process timed out. "
                "Review the work log and continue from where it left off."
            )
            self._close_work_log(issue_key, work_log, "timeout", prompt)
            return None
        return (
            stdout.decode("utf-8", errors="replace") if stdout else "",
            stderr.decode("utf-8", errors="replace") if stderr else "",
        )

    def _apply_background_outcome(
        self, issue_key: str, tracer: ExecutionTracer, work_log: dict, outcome: BackgroundOutcome
    ) -> dict:
        """Log, notify, trace and persist a resolved background outcome; return the caller's result."""
        self._history.log_action(issue_key, outcome.action, outcome.detail)
        if outcome.notify == "completed":
            notify_safely(notify_sprint_issue_completed, issue_key)
        elif outcome.notify == "blocked":
            notify_safely(notify_sprint_issue_blocked, issue_key, outcome.fields["blocked_reason"])
        if outcome.trace is not None:
            trace = dict(outcome.trace)
            if outcome.notify == "completed":
                trace["outputs"] = {"commits": work_log.get("outcome", {}).get("commits", [])}
            self._trace_step(tracer, "parse_result", **trace)
        work_log.update(outcome.fields)
        prompt = outcome.prompt
        if prompt is None:
            prompt = self._history.generate_continuation_prompt(issue_key, {**work_log, "status": outcome.status})
        self._close_work_log(issue_key, work_log, outcome.status, prompt)
        log = logger.info if outcome.result["success"] else logger.warning
        log("Background processing %s for %s: %s", outcome.status, _log_safe(issue_key), _log_safe(outcome.detail))
        return outcome.result

    def _close_work_log(self, issue_key: str, work_log: dict, status: str, prompt: str, **fields: str) -> None:
        """Set the final status, mark the work continuable in Cursor with ``prompt``, and save."""
        work_log["status"] = status
        work_log.update(fields)
        work_log["cursor_context"]["can_continue"] = True
        work_log["cursor_context"]["suggested_prompt"] = prompt
        self._history.save_work_log(issue_key, work_log)

    _STATUS_DETAIL_KEYS: ClassVar[dict[str, str]] = {"BLOCKED": "reason", "FAILED": "error"}

    def _parse_bot_status(self, output: str) -> dict:
        """Parse the ``[SPRINT_BOT_STATUS: COMPLETED|BLOCKED|FAILED] reason|error: ...`` marker.

        Returns a dict with ``status`` plus ``reason`` (BLOCKED) or ``error`` (FAILED) when given,
        or ``{"status": "UNKNOWN"}`` when no marker is present.
        """
        match = re.search(
            r"\[SPRINT_BOT_STATUS:\s*(COMPLETED|BLOCKED|FAILED)\](?:\s*(?:reason|error):\s*(.+))?",
            output,
            re.IGNORECASE,
        )
        if not match:
            return {"status": "UNKNOWN"}
        status = match.group(1).upper()
        parsed = {"status": status}
        detail_key = self._STATUS_DETAIL_KEYS.get(status)
        if detail_key and match.group(2):
            parsed[detail_key] = match.group(2).strip()
        return parsed

    def _parse_background_output(self, issue_key: str, output: str, work_log: dict) -> None:
        """Parse Claude CLI output to extract commits, MRs, files changed, etc."""

        # Store full output (truncated for large outputs)
        work_log["output_summary"] = output[:5000] if len(output) > 5000 else output

        # Extract commit hashes (git commit output patterns)
        commit_pattern = r"\[[\w-]+\s+([a-f0-9]{7,40})\]"
        commits = re.findall(commit_pattern, output)
        if commits:
            work_log["outcome"]["commits"].extend(commits)
            self._history.log_action(
                issue_key,
                "commits_created",
                f"Created {len(commits)} commit(s)",
                {"commits": commits},
            )

        # Extract MR/PR URLs or IDs
        mr_pattern = r"(?:Merge|merge) (?:Request|request)[:\s]+[#!]?(\d+)|MR[:\s]+[#!]?(\d+)|!(\d+)"
        mr_matches = re.findall(mr_pattern, output)
        mrs = [m for match in mr_matches for m in match if m]
        if mrs:
            work_log["outcome"]["merge_requests"].extend(mrs)
            self._history.log_action(
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
            work_log["cursor_context"]["files_to_review"] = list(set(files))[:10]  # Top 10 files

        # Extract branch names
        branch_pattern = r"(?:branch|checkout -b|created branch)[\s:]+([a-zA-Z0-9_/-]+)"
        branches = re.findall(branch_pattern, output, re.IGNORECASE)
        if branches:
            work_log["outcome"]["branches_created"].extend(list(set(branches)))

    async def _is_cursor_available(self) -> bool:
        """Check if Cursor/VS Code is available via D-Bus."""
        try:
            bus, chat_interface = await connect_chat_interface()
            result = await chat_interface.call_ping()
            bus.disconnect()

            return result and "pong" in result

        except RECOVERABLE_ERRORS:
            logger.debug("Ping failed", exc_info=True)
            return False
