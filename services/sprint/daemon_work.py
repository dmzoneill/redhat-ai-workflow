"""Sprint daemon issue execution in Cursor chats or the background Claude CLI."""

import asyncio
import json
import logging
import re
import shutil
from typing import ClassVar

# Sprint daemon owns its own state file - no shared file with other services
from services.sprint.bot.execution_tracer import (
    ExecutionTracer,
    StepStatus,
    WorkflowState,
)
from services.sprint.daemon_common import (
    _add_timeline_event,
    _local_now,
    _log_safe,
    connect_chat_interface,
    spawn_claude_cli,
)
from services.sprint.daemon_state import SprintStateMixin

logger = logging.getLogger(__name__)


class SprintWorkMixin(SprintStateMixin):
    """Sprint daemon issue execution in Cursor chats or the background Claude CLI."""

    # pylint: disable-next=too-many-statements
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

        if chat_id:  # pylint: disable=no-else-return
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
                if result_dict.get("success"):  # pylint: disable=no-else-return
                    return result_dict.get("chatId")
                else:
                    logger.warning("LaunchIssueChatWithPrompt returned error: %s", result_dict.get("error"))

            return None

        except Exception:  # pylint: disable=broad-exception-caught
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

    # pylint: disable-next=too-many-locals,too-many-return-statements,too-many-statements
    async def _run_issue_in_background_traced(self, issue: dict, tracer: ExecutionTracer) -> dict:
        """Run issue processing via Claude CLI with full execution tracing.

        Returns dict with success status and details.
        """
        issue_key = issue["key"]

        logger.info("Running %s in background mode (Claude CLI)", _log_safe(issue_key))

        # Initialize work log
        work_log = self._history.init_work_log(issue)
        self._history.save_work_log(issue_key, work_log)

        self._history.log_action(issue_key, "started", "Background processing started")
        self._trace_step(
            tracer,
            "init_work_log",
            outputs={"work_log_path": str(self._history.get_work_log_path(issue_key))},
        )

        # Emit toast notification for issue started
        try:
            from tool_modules.aa_workflow.src.notification_emitter import (  # pylint: disable=import-outside-toplevel
                notify_sprint_issue_started,
            )

            notify_sprint_issue_started(issue_key, issue.get("summary", "")[:50])
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug("Suppressed error: %s", exc, exc_info=True)

        try:
            claude_path = shutil.which("claude")
            if not claude_path:
                self._history.log_action(issue_key, "error", "Claude CLI not found")
                self._trace_step(
                    tracer,
                    "check_claude_cli",
                    error="Claude CLI not found",
                    status=StepStatus.FAILED,
                )
                tracer.mark_failed("Claude CLI not found")
                work_log["status"] = "failed"
                work_log["error"] = "Claude CLI not found"
                self._history.save_work_log(issue_key, work_log)
                return {"success": False, "error": "Claude CLI not found"}

            self._trace_step(tracer, "check_claude_cli", outputs={"claude_path": claude_path})

            # Build the unified work prompt
            prompt = self._build_work_prompt(issue)

            self._history.log_action(
                issue_key,
                "claude_started",
                "Started Claude CLI execution",
                {
                    "prompt_length": len(prompt),
                },
            )

            # Start step for Claude execution
            step_id = tracer.start_step("execute_claude_cli", inputs={"prompt_length": len(prompt)})

            # Run Claude CLI with extended timeout for actual work
            process = await spawn_claude_cli(claude_path, prompt)

            cli_timeout = self._config.get("claude_cli_timeout_seconds", 1800)
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=cli_timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                timeout_mins = cli_timeout // 60
                self._history.log_action(
                    issue_key,
                    "timeout",
                    f"Claude CLI timed out after {timeout_mins} minutes",
                )
                tracer.end_step(
                    step_id,
                    status=StepStatus.FAILED,
                    error=f"Timeout after {timeout_mins} minutes",
                )
                tracer.mark_failed(f"Claude CLI timed out after {timeout_mins} minutes")
                work_log = self._history.load_work_log(issue_key)
                work_log["status"] = "timeout"
                work_log["completed"] = _local_now().isoformat()
                work_log["cursor_context"]["can_continue"] = True
                work_log["cursor_context"]["suggested_prompt"] = (
                    f"Continue working on {issue_key}. The background process timed out. "
                    "Review the work log and continue from where it left off."
                )
                self._history.save_work_log(issue_key, work_log)
                return {"success": False, "error": "Claude CLI timed out"}

            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            error_output = stderr.decode("utf-8", errors="replace") if stderr else ""

            # Update work log with results
            work_log = self._history.load_work_log(issue_key)
            work_log["completed"] = _local_now().isoformat()

            # Parse output to extract useful information
            self._parse_background_output(issue_key, output, work_log)

            # Check for explicit status markers in output
            bot_status = self._parse_bot_status(output)

            # End the Claude execution step
            tracer.end_step(
                step_id,
                status=(
                    StepStatus.SUCCESS
                    if bot_status["status"] in ("COMPLETED", "UNKNOWN") and process.returncode == 0
                    else StepStatus.FAILED
                ),
                outputs={
                    "return_code": process.returncode,
                    "bot_status": bot_status["status"],
                    "output_length": len(output),
                    "commits_found": len(work_log.get("outcome", {}).get("commits", [])),
                    "mrs_found": len(work_log.get("outcome", {}).get("merge_requests", [])),
                },
            )

            if bot_status["status"] == "COMPLETED":  # pylint: disable=no-else-return
                work_log["status"] = "completed"
                self._history.log_action(
                    issue_key,
                    "completed",
                    "Background processing completed successfully",
                )

                # Emit toast notification for issue completed
                try:
                    # pylint: disable-next=import-outside-toplevel
                    from tool_modules.aa_workflow.src.notification_emitter import (
                        notify_sprint_issue_completed,
                    )

                    notify_sprint_issue_completed(issue_key)
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.debug("Suppressed error: %s", exc, exc_info=True)
                self._trace_step(
                    tracer,
                    "parse_result",
                    decision="completed",
                    reason="Bot reported COMPLETED status",
                    outputs={"commits": work_log.get("outcome", {}).get("commits", [])},
                )

                # Create context for continuing in Cursor
                work_log["cursor_context"]["can_continue"] = True
                work_log["cursor_context"]["suggested_prompt"] = self._history.generate_continuation_prompt(
                    issue_key, work_log
                )

                self._history.save_work_log(issue_key, work_log)
                logger.info("Background processing completed for %s", _log_safe(issue_key))
                return {
                    "success": True,
                    "message": f"Completed {issue_key} in background",
                }

            elif bot_status["status"] == "BLOCKED":
                # Bot is blocked - needs human intervention
                blocked_reason = bot_status.get("reason", "Unknown reason")
                work_log["status"] = "blocked"
                work_log["blocked_reason"] = blocked_reason
                self._history.log_action(issue_key, "blocked", f"Bot blocked: {blocked_reason}")

                # Emit toast notification for issue blocked
                try:
                    # pylint: disable-next=import-outside-toplevel
                    from tool_modules.aa_workflow.src.notification_emitter import (
                        notify_sprint_issue_blocked,
                    )

                    notify_sprint_issue_blocked(issue_key, blocked_reason)
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.debug("Suppressed error: %s", exc, exc_info=True)
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

                self._history.save_work_log(issue_key, work_log)
                logger.warning(
                    "Background processing blocked for %s: %s", _log_safe(issue_key), _log_safe(blocked_reason)
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
                self._history.log_action(
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

                self._history.save_work_log(issue_key, work_log)
                logger.warning(
                    "Background processing failed for %s: %s", _log_safe(issue_key), _log_safe(error_reason[:200])
                )
                return {"success": False, "error": f"Failed: {error_reason[:200]}"}

            else:
                # No explicit status - assume completed if return code is 0
                if process.returncode == 0:  # pylint: disable=no-else-return
                    work_log["status"] = "completed"
                    self._history.log_action(
                        issue_key,
                        "completed",
                        "Background processing completed (no explicit status)",
                    )
                    work_log["cursor_context"]["can_continue"] = True
                    work_log["cursor_context"]["suggested_prompt"] = self._history.generate_continuation_prompt(
                        issue_key, work_log
                    )
                    self._history.save_work_log(issue_key, work_log)
                    logger.info("Background processing completed for %s", _log_safe(issue_key))
                    return {
                        "success": True,
                        "message": f"Completed {issue_key} in background",
                    }
                else:
                    work_log["status"] = "failed"
                    work_log["error"] = error_output[:500]
                    self._history.log_action(issue_key, "failed", f"Claude CLI failed: {error_output[:200]}")
                    work_log["cursor_context"]["can_continue"] = True
                    retry_prompt = (
                        f"The background process for {issue_key} failed. Please investigate and continue the work."
                    )
                    work_log["cursor_context"]["suggested_prompt"] = retry_prompt
                    self._history.save_work_log(issue_key, work_log)
                    logger.warning(
                        "Background processing failed for %s: %s", _log_safe(issue_key), _log_safe(error_output[:200])
                    )
                    return {
                        "success": False,
                        "error": f"Claude CLI failed: {error_output[:200]}",
                    }

        except Exception as e:  # pylint: disable=broad-exception-caught
            self._history.log_action(issue_key, "error", f"Exception: {e!s}")
            work_log = self._history.load_work_log(issue_key)
            work_log["status"] = "failed"
            work_log["error"] = str(e)
            work_log["completed"] = _local_now().isoformat()
            work_log["cursor_context"]["can_continue"] = True
            work_log["cursor_context"]["suggested_prompt"] = (
                f"The background process for {issue_key} encountered an error: {e!s}. "
                "Please investigate and continue the work."
            )
            self._history.save_work_log(issue_key, work_log)
            logger.exception("Background processing error for %s", _log_safe(issue_key))
            return {"success": False, "error": str(e)}

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

        except Exception:  # pylint: disable=broad-exception-caught
            logger.debug("Ping failed", exc_info=True)
            return False
