"""Cursor interaction and code processing for Sprint Daemon."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

import yaml

from services.sprint.bot.execution_tracer import (
    ExecutionTracer,
    StepStatus,
    WorkflowState,
)
from services.sprint.timeline import _add_timeline_event

PROJECT_ROOT = Path(__file__).parent.parent.parent

logger = logging.getLogger(__name__)


class SprintCursorMixin:
    """Mixin providing Cursor interaction, code processing, and prompt building."""

    def _build_cursor_context_prompt(self, issue_key: str, work_log: dict) -> str:
        """Build a comprehensive context prompt for continuing work in Cursor."""
        parts = []

        # Header
        parts.append(f"# Continuing Work on {issue_key}")
        parts.append("")

        # Issue details
        parts.append("## Issue Details")
        parts.append(f"- **Summary**: {work_log.get('summary', 'N/A')}")
        parts.append(f"- **Type**: {work_log.get('issue_type', 'N/A')}")
        if work_log.get("story_points"):
            parts.append(f"- **Story Points**: {work_log.get('story_points')}")
        parts.append("")

        # Background work summary
        parts.append("## Background Work Summary")
        parts.append(f"- **Status**: {work_log.get('status', 'unknown')}")
        parts.append(f"- **Started**: {work_log.get('started', 'N/A')}")
        parts.append(f"- **Completed**: {work_log.get('completed', 'N/A')}")
        parts.append("")

        # Outcome
        outcome = work_log.get("outcome", {})
        if any(outcome.values()):
            parts.append("## Work Completed")
            if outcome.get("commits"):
                parts.append(f"- **Commits**: {', '.join(outcome['commits'][:5])}")
            if outcome.get("merge_requests"):
                parts.append(
                    f"- **Merge Requests**: {', '.join(outcome['merge_requests'])}"
                )
            if outcome.get("files_changed"):
                parts.append(
                    f"- **Files Changed**: {', '.join(outcome['files_changed'][:10])}"
                )
            if outcome.get("branches_created"):
                parts.append(
                    f"- **Branches**: {', '.join(outcome['branches_created'])}"
                )
            parts.append("")

        # Actions log (last 10)
        actions = work_log.get("actions", [])
        if actions:
            parts.append("## Recent Actions")
            for action in actions[-10:]:
                timestamp = action.get("timestamp", "")[:19]  # Trim to datetime
                action_type = action.get("type", "")
                details = action.get("details", "")
                parts.append(f"- [{timestamp}] **{action_type}**: {details}")
            parts.append("")

        # Suggested next steps
        cursor_context = work_log.get("cursor_context", {})
        if cursor_context.get("suggested_prompt"):
            parts.append("## Suggested Next Steps")
            parts.append(cursor_context["suggested_prompt"])
            parts.append("")

        # Files to review
        if cursor_context.get("files_to_review"):
            parts.append("## Files to Review")
            for f in cursor_context["files_to_review"]:
                parts.append(f"- `{f}`")
            parts.append("")

        # Error info if failed
        if work_log.get("error"):
            parts.append("## Error Information")
            parts.append(f"```\n{work_log['error']}\n```")
            parts.append("")

        # Instructions
        parts.append("---")
        parts.append(
            "Please review the above context and continue working on this issue."
        )
        parts.append(
            'Load the developer persona if needed: `persona_load("developer")`'
        )

        return "\n".join(parts)

    async def _handle_open_in_cursor(self, params: dict) -> dict:
        """Open an issue's work log in Cursor for interactive continuation.

        This creates a new Cursor chat with the context from the background work,
        allowing the user to continue working on the issue interactively.
        """
        issue_key = params.get("issue_key")
        if not issue_key:
            return {"success": False, "error": "issue_key required"}

        # Load work log
        work_log = self._load_work_log(issue_key)
        if not work_log:
            return {"success": False, "error": f"No work log found for {issue_key}"}

        # Check if Cursor is available
        cursor_available = await self._is_cursor_available()
        if not cursor_available:
            return {
                "success": False,
                "error": "Cursor is not available. Please open VS Code/Cursor first.",
            }

        # Build the context prompt from the work log
        prompt = self._build_cursor_context_prompt(issue_key, work_log)

        # Create a Cursor chat with this context
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

            # Launch the chat with context
            result = await chat_interface.call_launch_issue_chat(
                issue_key,
                f"Continue: {work_log.get('summary', '')}",
                False,  # Don't return to previous - user wants to work on this
            )

            bus.disconnect()

            if result:
                result_dict = json.loads(str(result))
                if result_dict.get("success"):
                    chat_id = result_dict.get("chatId")

                    # Update the issue with the new chat ID
                    state = self._load_state()
                    for issue in state.get("issues", []):
                        if issue.get("key") == issue_key:
                            issue["chatId"] = chat_id
                            _add_timeline_event(
                                issue,
                                {
                                    "timestamp": datetime.now().isoformat(),
                                    "action": "opened_in_cursor",
                                    "description": "Opened background work in Cursor for interactive continuation",
                                    "chatLink": chat_id,
                                },
                            )
                            break
                    self._save_state(state)

                    logger.info(f"Opened {issue_key} in Cursor: {chat_id}")
                    return {
                        "success": True,
                        "message": f"Opened {issue_key} in Cursor",
                        "chat_id": chat_id,
                        "context_prompt": prompt,
                    }

            return {"success": False, "error": "Failed to create Cursor chat"}

        except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            logger.error(f"Failed to open {issue_key} in Cursor: {e}")
            return {"success": False, "error": str(e)}

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

    async def _process_in_cursor_traced(
        self, issue: dict, state: dict, tracer: ExecutionTracer
    ) -> dict:
        """Process an issue in Cursor with full execution tracing."""
        issue_key = issue["key"]

        # Transition to starting work
        self._trace_transition(
            tracer, WorkflowState.TRANSITIONING_JIRA, trigger="is_actionable"
        )

        # Transition Jira issue to "In Progress"
        jira_success = await self._transition_jira_issue(
            issue_key, self.JIRA_STATUS_IN_PROGRESS
        )
        self._trace_step(
            tracer,
            "transition_jira_in_progress",
            inputs={
                "issue_key": issue_key,
                "target_status": self.JIRA_STATUS_IN_PROGRESS,
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
        issue["jiraStatus"] = self.JIRA_STATUS_IN_PROGRESS
        state["processingIssue"] = issue_key
        _add_timeline_event(
            issue,
            {
                "timestamp": datetime.now().isoformat(),
                "action": "started",
                "description": "Sprint bot started processing in Cursor",
                "jiraTransition": self.JIRA_STATUS_IN_PROGRESS,
            },
        )
        issue["hasTrace"] = True
        issue["tracePath"] = str(tracer.trace_path)
        self._save_state(state)

        # Build prompt
        self._trace_transition(
            tracer, WorkflowState.BUILDING_PROMPT, trigger="branch_created"
        )
        prompt = self._build_work_prompt(issue)
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

        chat_id = await self._launch_cursor_chat(issue)

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
            self._save_state(state)
            self._issues_processed += 1
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
            self._save_state(state)
            logger.warning(f"Could not create chat for {issue_key}")
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

        except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            logger.error(f"Failed to launch chat via D-Bus: {e}")
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

    async def _run_issue_in_background_traced(
        self, issue: dict, tracer: ExecutionTracer
    ) -> dict:
        """Run issue processing via Claude CLI with full execution tracing.

        Returns dict with success status and details.
        """
        issue_key = issue["key"]

        logger.info(f"Running {issue_key} in background mode (Claude CLI)")

        # Initialize work log
        work_log = self._init_work_log(issue)
        self._save_work_log(issue_key, work_log)

        self._log_action(issue_key, "started", "Background processing started")
        self._trace_step(
            tracer,
            "init_work_log",
            outputs={"work_log_path": str(self._get_work_log_path(issue_key))},
        )

        # Emit toast notification for issue started
        try:
            from tool_modules.aa_workflow.src.notification_emitter import (
                notify_sprint_issue_started,
            )

            notify_sprint_issue_started(issue_key, issue.get("summary", "")[:50])
        except OSError as exc:
            logger.debug("Suppressed error: %s", exc)

        # Log to daily session file
        try:
            from tool_modules.aa_workflow.src.memory_tools import append_session_entry

            append_session_entry(
                {
                    "type": "sprint",
                    "action": f"Sprint: {issue_key} started",
                    "details": issue.get("summary", "")[:100],
                    "issues": [issue_key],
                    "source": "sprint",
                }
            )
        except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            logger.debug("Suppressed append_session_entry: %s", e, exc_info=True)

        try:
            import shutil

            claude_path = shutil.which("claude")
            if not claude_path:
                self._log_action(issue_key, "error", "Claude CLI not found")
                self._trace_step(
                    tracer,
                    "check_claude_cli",
                    error="Claude CLI not found",
                    status=StepStatus.FAILED,
                )
                tracer.mark_failed("Claude CLI not found")
                work_log["status"] = "failed"
                work_log["error"] = "Claude CLI not found"
                self._save_work_log(issue_key, work_log)
                return {"success": False, "error": "Claude CLI not found"}

            self._trace_step(
                tracer, "check_claude_cli", outputs={"claude_path": claude_path}
            )

            # Build the unified work prompt
            prompt = self._build_work_prompt(issue)

            self._log_action(
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
                self._log_action(
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
                work_log = self._load_work_log(issue_key)
                work_log["status"] = "timeout"
                work_log["completed"] = datetime.now().isoformat()
                work_log["cursor_context"]["can_continue"] = True
                work_log["cursor_context"]["suggested_prompt"] = (
                    f"Continue working on {issue_key}. The background process timed out. "
                    "Review the work log and continue from where it left off."
                )
                self._save_work_log(issue_key, work_log)
                return {"success": False, "error": "Claude CLI timed out"}

            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            error_output = stderr.decode("utf-8", errors="replace") if stderr else ""

            # Update work log with results
            work_log = self._load_work_log(issue_key)
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
                self._log_action(
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
                except OSError as exc:
                    logger.debug("Suppressed error: %s", exc)

                # Log to daily session file
                try:
                    from tool_modules.aa_workflow.src.memory_tools import (
                        append_session_entry,
                    )

                    commits = work_log.get("outcome", {}).get("commits", [])
                    append_session_entry(
                        {
                            "type": "sprint",
                            "action": f"Sprint: {issue_key} completed",
                            "details": f"{len(commits)} commits, background processing done",
                            "issues": [issue_key],
                            "source": "sprint",
                        }
                    )
                except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError):
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
                    self._generate_continuation_prompt(issue_key, work_log)
                )

                self._save_work_log(issue_key, work_log)
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
                self._log_action(issue_key, "blocked", f"Bot blocked: {blocked_reason}")

                # Emit toast notification for issue blocked
                try:
                    from tool_modules.aa_workflow.src.notification_emitter import (
                        notify_sprint_issue_blocked,
                    )

                    notify_sprint_issue_blocked(issue_key, blocked_reason)
                except OSError as exc:
                    logger.debug("Suppressed error: %s", exc)

                # Log to daily session file
                try:
                    from tool_modules.aa_workflow.src.memory_tools import (
                        append_session_entry,
                    )

                    append_session_entry(
                        {
                            "type": "sprint",
                            "action": f"Sprint: {issue_key} blocked",
                            "details": blocked_reason[:200],
                            "issues": [issue_key],
                            "source": "sprint",
                        }
                    )
                except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError):
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

                self._save_work_log(issue_key, work_log)
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
                self._log_action(
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

                self._save_work_log(issue_key, work_log)
                logger.warning(
                    f"Background processing failed for {issue_key}: {error_reason[:200]}"
                )
                return {"success": False, "error": f"Failed: {error_reason[:200]}"}

            else:
                # No explicit status - assume completed if return code is 0
                if process.returncode == 0:
                    work_log["status"] = "completed"
                    self._log_action(
                        issue_key,
                        "completed",
                        "Background processing completed (no explicit status)",
                    )
                    work_log["cursor_context"]["can_continue"] = True
                    work_log["cursor_context"]["suggested_prompt"] = (
                        self._generate_continuation_prompt(issue_key, work_log)
                    )
                    self._save_work_log(issue_key, work_log)
                    logger.info(f"Background processing completed for {issue_key}")
                    return {
                        "success": True,
                        "message": f"Completed {issue_key} in background",
                    }
                else:
                    work_log["status"] = "failed"
                    work_log["error"] = error_output[:500]
                    self._log_action(
                        issue_key, "failed", f"Claude CLI failed: {error_output[:200]}"
                    )
                    work_log["cursor_context"]["can_continue"] = True
                    work_log["cursor_context"][
                        "suggested_prompt"
                    ] = f"The background process for {issue_key} failed. Please investigate and continue the work."
                    self._save_work_log(issue_key, work_log)
                    logger.warning(
                        f"Background processing failed for {issue_key}: {error_output[:200]}"
                    )
                    return {
                        "success": False,
                        "error": f"Claude CLI failed: {error_output[:200]}",
                    }

        except (
            OSError,
            json.JSONDecodeError,
            yaml.YAMLError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ) as e:
            self._log_action(issue_key, "error", f"Exception: {str(e)}")
            work_log = self._load_work_log(issue_key)
            work_log["status"] = "failed"
            work_log["error"] = str(e)
            work_log["completed"] = datetime.now().isoformat()
            work_log["cursor_context"]["can_continue"] = True
            work_log["cursor_context"]["suggested_prompt"] = (
                f"The background process for {issue_key} encountered an error: {str(e)}. "
                "Please investigate and continue the work."
            )
            self._save_work_log(issue_key, work_log)
            logger.error(f"Background processing error for {issue_key}: {e}")
            return {"success": False, "error": str(e)}

    def _parse_bot_status(self, output: str) -> dict:
        """Parse the bot status marker from Claude CLI output.

        Looks for lines like:
        - [SPRINT_BOT_STATUS: COMPLETED]
        - [SPRINT_BOT_STATUS: BLOCKED] reason: Need clarification
        - [SPRINT_BOT_STATUS: FAILED] error: Could not find file

        Returns dict with 'status' and optional 'reason' or 'error'.
        """
        import re

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
        import re

        # Store full output (truncated for large outputs)
        work_log["output_summary"] = output[:5000] if len(output) > 5000 else output

        # Extract commit hashes (git commit output patterns)
        commit_pattern = r"\[[\w-]+\s+([a-f0-9]{7,40})\]"
        commits = re.findall(commit_pattern, output)
        if commits:
            work_log["outcome"]["commits"].extend(commits)
            self._log_action(
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
            self._log_action(
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

    def _generate_continuation_prompt(self, issue_key: str, work_log: dict) -> str:
        """Generate a prompt for continuing work in Cursor."""
        status = work_log.get("status", "unknown")
        summary = work_log.get("summary", "")
        commits = work_log.get("outcome", {}).get("commits", [])
        mrs = work_log.get("outcome", {}).get("merge_requests", [])
        files = work_log.get("outcome", {}).get("files_changed", [])

        prompt_parts = [f"Continue working on {issue_key}: {summary}"]
        prompt_parts.append("")
        prompt_parts.append("## Background Work Summary")
        prompt_parts.append(f"- Status: {status}")

        if commits:
            prompt_parts.append(f"- Commits created: {', '.join(commits[:5])}")
        if mrs:
            prompt_parts.append(f"- Merge requests: {', '.join(mrs)}")
        if files:
            prompt_parts.append(f"- Files modified: {', '.join(files[:5])}")

        prompt_parts.append("")
        prompt_parts.append("## Next Steps")

        if status == "completed":
            prompt_parts.append("The background work completed successfully. Please:")
            prompt_parts.append("1. Review the changes made")
            prompt_parts.append("2. Run tests to verify the implementation")
            prompt_parts.append("3. Check if the MR needs any updates")
        elif status == "failed":
            prompt_parts.append("The background work failed. Please:")
            prompt_parts.append("1. Review the error in the work log")
            prompt_parts.append("2. Investigate the issue")
            prompt_parts.append("3. Complete the implementation")
        else:
            prompt_parts.append("Please review the work done and continue as needed.")

        return "\n".join(prompt_parts)
