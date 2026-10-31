"""Sprint daemon state file, Jira sync, work log and tracing helpers."""

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import traceback
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

# Sprint daemon owns its own state file - no shared file with other services
from services.sprint.bot.execution_tracer import (
    ExecutionTracer,
    StepStatus,
    WorkflowState,
)
from services.sprint.bot.workflow_config import (
    COMPLETED_STATUSES,
    REVIEW_STATUSES,
    WorkflowConfig,
    get_workflow_config,
)
from services.sprint.daemon_common import (
    SPRINT_STATE_FILE,
    _add_timeline_event,
    _local_now,
    _log_safe,
    spawn_claude_cli,
)
from services.sprint.sprint_history_tracker import SprintHistoryTracker

logger = logging.getLogger(__name__)


class SprintStateMixin:
    """Sprint daemon state file, Jira sync, work log and tracing helpers."""

    # Stateless helper owning work-log files and Cursor context prompts
    _history = SprintHistoryTracker()

    # Set by SprintDaemon.__init__
    _config: dict
    _workflow_config: WorkflowConfig | None
    _shutdown_event: asyncio.Event
    _issues_processed: int = 0
    _issues_completed: int = 0
    _last_jira_refresh: datetime | None
    _last_review_check: datetime | None

    @staticmethod
    def _elapsed_seconds(since: datetime | None) -> float:
        """Seconds since ``since``; infinite if it never happened."""
        if since is None:
            return float("inf")
        return (_local_now() - since).total_seconds()

    # ==================== State Management ====================

    def _load_state(self) -> dict:
        """Load sprint state from sprint_state.json.

        Handles backward compatibility with old 'botEnabled' field.
        """
        try:
            if SPRINT_STATE_FILE.exists():
                state = json.loads(SPRINT_STATE_FILE.read_text())

                # Migrate old 'botEnabled' field to new fields
                if "botEnabled" in state and "automaticMode" not in state:
                    state["automaticMode"] = state.pop("botEnabled", False)
                    state["manuallyStarted"] = False

                # Ensure new fields exist
                if "automaticMode" not in state:
                    state["automaticMode"] = False
                if "manuallyStarted" not in state:
                    state["manuallyStarted"] = False
                if "nextSprint" not in state:
                    state["nextSprint"] = None

                return state
        except (OSError, ValueError, TypeError, AttributeError) as e:
            logger.error("Failed to load state: %s", e)
        return self._default_state()

    def _save_state(self, sprint_state: dict) -> None:
        """Save sprint state to sprint_state.json.

        Each service owns its own state file. The VS Code extension reads
        all state files on refresh. No shared file = no race conditions.
        """
        try:
            SPRINT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

            # Add workflow config to state for UI consumption
            sprint_state["workflowConfig"] = self._export_workflow_config()

            # Write atomically (temp file + rename)
            temp_fd, temp_path = tempfile.mkstemp(suffix=".tmp", prefix="sprint_state_", dir=SPRINT_STATE_FILE.parent)
            try:
                with os.fdopen(temp_fd, "w") as f:
                    json.dump(sprint_state, f, indent=2, default=str)
                Path(temp_path).replace(SPRINT_STATE_FILE)
            except Exception:
                try:
                    Path(temp_path).unlink()
                except OSError as exc:
                    logger.debug("OS operation failed: %s", exc)
                raise

        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Failed to save state")

    def _export_workflow_config(self) -> dict:
        """Export workflow configuration for UI consumption.

        Returns a simplified version of the workflow config that the UI needs
        for rendering status sections and colors.
        """
        config = self.workflow_config

        # Export status mappings
        status_mappings = {}
        for stage, stage_config in config.get_all_status_mappings().items():
            status_mappings[stage] = {
                "displayName": stage_config.get("display_name", stage.title()),
                "icon": stage_config.get("icon", "📋"),
                "color": stage_config.get("color", "gray"),
                "description": stage_config.get("description", ""),
                "jiraStatuses": stage_config.get("jira_statuses", []),
                "botCanWork": stage_config.get("bot_can_work", False),
                "uiOrder": stage_config.get("ui_order", 99),
                "showApproveButtons": stage_config.get("show_approve_buttons", False),
                "botMonitors": stage_config.get("bot_monitors", False),
            }

        # Export merge hold patterns
        merge_hold_patterns = config.get_merge_hold_patterns()

        # Export issue classification keywords
        issue_classification = config.get("issue_classification", {})
        spike_keywords = issue_classification.get("spike", {}).get("keywords", [])

        return {
            "statusMappings": status_mappings,
            "mergeHoldPatterns": merge_hold_patterns,
            "spikeKeywords": spike_keywords,
            "version": config.get("version", "1.0"),
        }

    def _default_state(self) -> dict:
        """Return default sprint state."""
        return {
            "currentSprint": None,
            "nextSprint": None,
            "issues": [],
            "automaticMode": False,  # Bot runs on schedule (Mon-Fri 9-5)
            "manuallyStarted": False,  # Bot is running now (ignores schedule)
            "backgroundTasks": False,
            "lastUpdated": _local_now().isoformat(),
            "processingIssue": None,
        }

    # ==================== Working Hours ====================

    def _is_within_working_hours(self) -> bool:
        """Check if current time is within working hours."""
        wh = self._config["working_hours"]

        try:
            tz = ZoneInfo(wh["timezone"])
            now = datetime.now(tz)
        except ImportError:
            now = _local_now()

        # Check weekday (0=Monday, 6=Sunday)
        if wh["weekdays_only"] and now.weekday() >= 5:
            return False

        # Check time
        start = time(wh["start_hour"], wh["start_minute"])
        end = time(wh["end_hour"], wh["end_minute"])
        current_time = now.time()

        return start <= current_time <= end

    # ==================== Jira Integration ====================

    # pylint: disable-next=too-many-locals,too-many-statements
    async def _refresh_from_jira(self) -> None:
        """Refresh sprint issues from Jira by calling the Jira API directly.

        Fetches sprint info and issues, then saves to state file.
        """
        logger.info("Refreshing sprint issues from Jira...")

        try:
            from tool_modules.aa_jira.src.tools_basic import (  # pylint: disable=import-outside-toplevel
                jira_get_active_sprint,
            )
            from tool_modules.aa_workflow.src.sprint_bot import (  # pylint: disable=import-outside-toplevel
                SprintBotConfig,
                WorkingHours,
                fetch_sprint_issues,
                to_sprint_issue_format,
            )
            from tool_modules.aa_workflow.src.sprint_history import (  # pylint: disable=import-outside-toplevel
                SprintIssue,
                load_sprint_state,
                save_sprint_state,
            )
            from tool_modules.aa_workflow.src.sprint_prioritizer import (  # pylint: disable=import-outside-toplevel
                prioritize_issues,
            )

            config = SprintBotConfig(
                working_hours=WorkingHours(),
                jira_project=self._config.get("jira_project", "AAP"),
            )

            # Fetch active sprint info first (for currentSprint metadata)
            sprint_info = await jira_get_active_sprint(project=config.jira_project)
            current_sprint = None
            if sprint_info and "error" not in sprint_info:
                current_sprint = {
                    "id": str(sprint_info.get("id", "")),
                    "name": sprint_info.get("name", ""),
                    "startDate": sprint_info.get("startDate", ""),
                    "endDate": sprint_info.get("endDate", ""),
                    "totalPoints": 0,  # Will be calculated from issues
                    "completedPoints": 0,  # Will be calculated from issues
                }
                logger.info("Active sprint: %s", current_sprint.get("name"))
            else:
                logger.warning("Could not get active sprint info: %s", sprint_info)

            # Fetch issues from Jira (async)
            jira_issues = await fetch_sprint_issues(config)

            if not jira_issues:
                logger.warning("No issues fetched from Jira, keeping existing state")
                self._last_jira_refresh = _local_now()
                return

            # Filter to only show issues assigned to current user
            from server.utils import load_config  # pylint: disable=import-outside-toplevel

            user_config = load_config()
            user_info = user_config.get("user", {})
            jira_username = user_info.get("jira_username", "")
            full_name = user_info.get("full_name", "")
            if jira_username or full_name:
                original_count = len(jira_issues)
                # Match against username OR full name (Jira may use either)
                match_values = [v.lower() for v in [jira_username, full_name] if v]
                jira_issues = [issue for issue in jira_issues if issue.get("assignee", "").lower() in match_values]
                logger.info(
                    "Filtered to %s/%s issues assigned to %s",
                    len(jira_issues),
                    original_count,
                    jira_username or full_name,
                )

            if not jira_issues:
                logger.info("No issues assigned to current user, clearing sprint list")
                state = load_sprint_state()
                state.current_sprint = current_sprint  # Still update sprint info
                state.issues = []
                state.last_updated = _local_now().isoformat()
                save_sprint_state(state)
                self._last_jira_refresh = _local_now()
                return

            # Prioritize issues
            prioritized = prioritize_issues(jira_issues)
            sprint_issues = to_sprint_issue_format(prioritized)

            # Load existing state to preserve approval status, chat IDs, etc.
            state = load_sprint_state()
            existing_by_key = {issue.key: issue for issue in state.issues}

            # Merge with existing state
            new_issues = []
            for issue_data in sprint_issues:
                key = issue_data["key"]
                # Preserve approval status, waiting reason, chat ID and timeline of known issues
                existing = existing_by_key.get(key)
                new_issues.append(
                    SprintIssue(
                        key=key,
                        summary=issue_data["summary"],
                        story_points=issue_data.get("storyPoints", 0),
                        priority=issue_data.get("priority", "Major"),
                        jira_status=issue_data.get("jiraStatus", "New"),
                        assignee=issue_data.get("assignee", ""),
                        approval_status=existing.approval_status if existing else "pending",
                        waiting_reason=existing.waiting_reason if existing else None,
                        priority_reasoning=issue_data.get("priorityReasoning", []),
                        estimated_actions=issue_data.get("estimatedActions", []),
                        chat_id=existing.chat_id if existing else None,
                        timeline=existing.timeline if existing else [],
                        issue_type=issue_data.get("issueType", "Story"),
                        created=issue_data.get("created", ""),
                    )
                )

            # Calculate points for sprint info
            total_points = sum(i.story_points for i in new_issues)
            completed_points = sum(
                i.story_points for i in new_issues if i.jira_status and i.jira_status.lower() in COMPLETED_STATUSES
            )

            # Update currentSprint with calculated points
            if current_sprint:
                current_sprint["totalPoints"] = total_points
                current_sprint["completedPoints"] = completed_points

            # Update state
            state.current_sprint = current_sprint
            state.issues = new_issues
            state.last_updated = _local_now().isoformat()
            save_sprint_state(state)

            logger.info(
                "Sprint refresh completed: %s issues, sprint: %s",
                len(new_issues),
                current_sprint.get("name") if current_sprint else "None",
            )
            self._last_jira_refresh = _local_now()

        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Failed to refresh sprint")

            logger.debug(traceback.format_exc())
            # Don't block - use existing state
            self._last_jira_refresh = _local_now()

    async def _check_review_issues(self) -> None:
        """Check issues in Review status and try to move them to Done.

        This runs periodically (3x daily) to:
        1. Find issues in "In Review" status
        2. Check if their MR is approved and CI passed
        3. Check for "don't merge" comments
        4. Merge the MR and transition to Done if ready

        This automates the final step of the workflow.
        """
        logger.info("Checking issues in Review for merge readiness...")
        self._last_review_check = _local_now()

        state = self._load_state()
        issues = state.get("issues", [])

        # Find issues in Review status
        review_issues = [i for i in issues if i.get("jiraStatus", "").lower() in REVIEW_STATUSES]

        if not review_issues:
            logger.info("No issues in Review status")
            return

        logger.info("Found %s issues in Review", len(review_issues))

        # Patterns that indicate "don't merge yet"
        dont_merge_patterns = [
            "don't merge",
            "do not merge",
            "dont merge",
            "hold off",
            "hold merge",
            "wait until",
            "don't merge until",
            "do not merge until",
            "needs more work",
            "wip",
            "work in progress",
        ]

        for issue in review_issues:
            issue_key = issue.get("key")
            if not issue_key:
                continue

            try:
                await self._check_single_review_issue(issue, dont_merge_patterns, state)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Error checking review issue %s", issue_key)
                continue

        # Save any state changes
        self._save_state(state)

    # pylint: disable-next=too-many-locals
    async def _check_single_review_issue(self, issue: dict, dont_merge_patterns: list, state: dict) -> None:
        """Check a single issue in Review and try to merge/close if ready."""
        issue_key = issue.get("key")
        logger.info("Checking review status for %s", _log_safe(issue_key))

        try:
            claude_path = shutil.which("claude")
            if not claude_path:
                logger.warning("Claude CLI not found, skipping review check")
                return

            # Build prompt to check MR status
            prompt = f"""Check the merge request status for Jira issue {issue_key}.

1. First, find the MR for this issue:
   ```
   gitlab_mr_list(project="automation-analytics/automation-analytics-backend", search="{issue_key}")
   ```

2. If an MR exists, check its status:
   - Is it approved?
   - Has the pipeline passed?
   - Are there any comments containing: {", ".join(dont_merge_patterns[:5])}

3. Report the status in this exact format:
   [MR_STATUS: READY_TO_MERGE] - MR is approved, CI passed, no hold comments
   [MR_STATUS: APPROVED_WITH_HOLD] reason: <the hold comment>
   [MR_STATUS: NEEDS_APPROVAL] - MR not yet approved
   [MR_STATUS: CI_FAILING] - Pipeline failed
   [MR_STATUS: NO_MR] - No MR found for this issue
   [MR_STATUS: CHANGES_REQUESTED] - Reviewer requested changes

Also output the MR ID if found: [MR_ID: <number>]
"""

            process = await spawn_claude_cli(claude_path, prompt)

            try:
                stdout, _stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=120,  # 2 minute timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.warning("Review check timed out for %s", _log_safe(issue_key))
                return

            output = stdout.decode("utf-8", errors="replace") if stdout else ""

            # Parse the status

            status_match = re.search(
                r"\[MR_STATUS:\s*(\w+)\](?:\s*reason:\s*(.+))?",
                output,
                re.IGNORECASE,
            )
            mr_id_match = re.search(r"\[MR_ID:\s*(\d+)\]", output)

            if not status_match:
                logger.warning("Could not parse MR status for %s", _log_safe(issue_key))
                return

            mr_status = status_match.group(1).upper()
            hold_reason = status_match.group(2).strip() if status_match.group(2) else None
            mr_id = int(mr_id_match.group(1)) if mr_id_match else None

            logger.info("%s: MR status = %s, MR ID = %s", _log_safe(issue_key), _log_safe(mr_status), _log_safe(mr_id))

            if mr_status == "READY_TO_MERGE" and mr_id and issue_key:
                # Merge the MR and transition to Done
                await self._merge_and_close(issue_key, mr_id, issue, state)

            elif mr_status == "APPROVED_WITH_HOLD":
                # Log but don't merge
                logger.info("%s: MR approved but on hold: %s", _log_safe(issue_key), _log_safe(hold_reason))
                _add_timeline_event(
                    issue,
                    {
                        "timestamp": _local_now().isoformat(),
                        "action": "review_hold",
                        "description": f"MR approved but merge on hold: {hold_reason}",
                    },
                )

            elif mr_status == "CHANGES_REQUESTED":
                logger.info("%s: Changes requested on MR", _log_safe(issue_key))
                # Could notify or take action here

            elif mr_status == "CI_FAILING":
                logger.info("%s: CI is failing", _log_safe(issue_key))
                # Could notify or take action here

            elif mr_status == "NO_MR":
                logger.warning("%s: No MR found but issue is in Review", _log_safe(issue_key))

        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Error checking MR status for %s", _log_safe(issue_key))

    # pylint: disable-next=unused-argument
    async def _merge_and_close(self, issue_key: str, mr_id: int, issue: dict, state: dict) -> None:
        """Merge an MR and transition the Jira issue to Done."""
        logger.info("Merging MR !%s and closing %s", _log_safe(mr_id), _log_safe(issue_key))

        try:
            claude_path = shutil.which("claude")
            if not claude_path:
                logger.warning("Claude CLI not found, cannot merge")
                return

            # Build prompt to merge and close
            prompt = f"""Merge the MR and close the Jira issue:

1. Merge the MR:
   ```
   gitlab_mr_merge(project="automation-analytics/automation-analytics-backend",
       mr_id={mr_id}, when_pipeline_succeeds=true)
   ```

2. Close the Jira issue:
   ```
   skill_run("close_issue", '{{"issue_key": "{issue_key}"}}')
   ```

3. Report the result:
   [MERGE_RESULT: SUCCESS] - MR merged and issue closed
   [MERGE_RESULT: MERGE_FAILED] error: <reason>
   [MERGE_RESULT: CLOSE_FAILED] error: <reason>
"""

            process = await spawn_claude_cli(claude_path, prompt)

            try:
                stdout, _stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=180,  # 3 minute timeout for merge
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.warning("Merge/close timed out for %s", _log_safe(issue_key))
                return

            output = stdout.decode("utf-8", errors="replace") if stdout else ""

            # Parse the result

            result_match = re.search(r"\[MERGE_RESULT:\s*(\w+)\](?:\s*error:\s*(.+))?", output, re.IGNORECASE)

            if result_match:
                result = result_match.group(1).upper()
                error = result_match.group(2).strip() if result_match.group(2) else None

                if result == "SUCCESS":
                    logger.info("Successfully merged MR !%s and closed %s", _log_safe(mr_id), _log_safe(issue_key))

                    # Update local state
                    issue["jiraStatus"] = self.jira_status_done
                    issue["approvalStatus"] = "completed"
                    _add_timeline_event(
                        issue,
                        {
                            "timestamp": _local_now().isoformat(),
                            "action": "merged_and_closed",
                            "description": f"MR !{mr_id} merged, issue closed",
                            "jiraTransition": self.jira_status_done,
                        },
                    )
                    self._issues_completed += 1
                else:
                    logger.warning("Merge/close failed for %s: %s", _log_safe(issue_key), _log_safe(error))
                    _add_timeline_event(
                        issue,
                        {
                            "timestamp": _local_now().isoformat(),
                            "action": "merge_failed",
                            "description": f"Failed to merge/close: {error}",
                        },
                    )
            else:
                logger.warning("Could not parse merge result for %s", _log_safe(issue_key))

        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Error merging/closing %s", _log_safe(issue_key))

    # ==================== Issue Processing ====================

    # ==================== WORKFLOW CONFIG ====================
    # Status mappings and workflow logic are loaded from config.json -> sprint section
    # See: server/config_manager.py and scripts/sprint_bot/workflow_config.py

    @property
    def workflow_config(self) -> WorkflowConfig:
        """Get the workflow configuration (lazy loaded)."""
        if self._workflow_config is None:
            self._workflow_config = get_workflow_config()
        return self._workflow_config

    # Legacy properties for backward compatibility - delegate to config
    @property
    def actionable_statuses(self) -> list[str]:
        """Get actionable statuses from config."""
        return self.workflow_config.get_actionable_statuses()

    @property
    def jira_status_in_progress(self) -> str:
        """Get In Progress status name from config."""
        return self.workflow_config.get_jira_transition("in_progress")

    @property
    def jira_status_in_review(self) -> str:
        """Get In Review status name from config."""
        return self.workflow_config.get_jira_transition("in_review")

    @property
    def jira_status_done(self) -> str:
        """Get Done status name from config."""
        return self.workflow_config.get_jira_transition("done")

    def _build_work_prompt(self, issue: dict) -> str:
        """Build the unified work prompt for both foreground and background modes.

        This prompt guides the bot through the complete workflow from understanding
        the issue to completing the work and transitioning Jira status.

        Now delegates to WorkflowConfig for the actual prompt building.
        """
        return self.workflow_config.build_work_prompt(issue)

    # ==================== EXECUTION TRACING ====================
    # Tracks state machine transitions and step execution for observability

    def _get_tracer(self, issue_key: str, issue: dict | None = None) -> ExecutionTracer:
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
                workflow_type = self.workflow_config.classify_issue(issue)
                state = self._load_state()
                execution_mode = "background" if state.get("backgroundTasks", True) else "foreground"

            tracer = ExecutionTracer(
                issue_key=issue_key,
                workflow_type=workflow_type,
                execution_mode=execution_mode,
            )

        return tracer

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def _trace_step(
        self,
        tracer: ExecutionTracer,
        name: str,
        inputs: dict | None = None,
        outputs: dict | None = None,
        decision: str | None = None,
        reason: str | None = None,
        skill_name: str | None = None,
        tool_name: str | None = None,
        status: StepStatus = StepStatus.SUCCESS,
        error: str | None = None,
        chat_id: str | None = None,
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
        trigger: str | None = None,
        data: dict | None = None,
    ) -> None:
        """Log a state transition and save."""
        tracer.transition(to_state, trigger, data)
        tracer.save()

    async def _transition_jira_issue(self, issue_key: str, target_status: str) -> bool:
        """Transition a Jira issue to a new status using Claude CLI.

        Returns True if successful, False otherwise.
        """
        try:
            claude_path = shutil.which("claude")
            if not claude_path:
                logger.warning("Claude CLI not found, cannot transition %s", _log_safe(issue_key))
                return False

            prompt = f'Call jira_transition("{issue_key}", "{target_status}") to move the issue to {target_status}.'

            process = await spawn_claude_cli(claude_path, prompt)

            try:
                _stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=60,  # 1 minute timeout for transition
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.warning("Jira transition timed out for %s", _log_safe(issue_key))
                return False

            if process.returncode == 0:  # pylint: disable=no-else-return
                logger.info("Transitioned %s to %s", _log_safe(issue_key), _log_safe(target_status))
                return True
            else:
                error = stderr.decode("utf-8", errors="replace") if stderr else ""
                logger.warning("Failed to transition %s: %s", _log_safe(issue_key), _log_safe(error[:200]))
                return False

        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Error transitioning %s", _log_safe(issue_key))
            return False

    async def _start_jira_work(self, tracer: ExecutionTracer, issue_key: str, trigger: str) -> bool:
        """Trace the TRANSITIONING_JIRA state and move the Jira issue to In Progress."""
        self._trace_transition(tracer, WorkflowState.TRANSITIONING_JIRA, trigger=trigger)
        jira_success = await self._transition_jira_issue(issue_key, self.jira_status_in_progress)
        self._trace_step(
            tracer,
            "transition_jira_in_progress",
            inputs={
                "issue_key": issue_key,
                "target_status": self.jira_status_in_progress,
            },
            outputs={"success": jira_success},
            tool_name="jira_transition",
            status=StepStatus.SUCCESS if jira_success else StepStatus.FAILED,
        )
        return jira_success

    def _runtime_flags(self, state: dict) -> tuple[bool, bool, bool, bool]:
        """Return ``(automatic_mode, manually_started, within_hours, is_active)`` for a state dict."""
        automatic_mode = state.get("automaticMode", False)
        manually_started = state.get("manuallyStarted", False)
        within_hours = self._is_within_working_hours()
        return automatic_mode, manually_started, within_hours, manually_started or (automatic_mode and within_hours)

    def _is_actionable(self, issue: dict) -> bool:
        """Check if an issue is actionable based on its Jira status.

        Uses WorkflowConfig to determine actionability based on status mappings.
        Bot should only work on issues in statuses marked with bot_can_work=true.
        """
        return self.workflow_config.is_actionable(issue)

    # ==================== Background Execution ====================

    # ==================== Main Loop ====================

    async def _wait_with_shutdown(self, seconds: float) -> bool:
        """Wait for specified seconds, but return early if shutdown requested.

        Returns True if shutdown was requested, False if wait completed normally.
        """
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout=seconds)
            return True  # Shutdown requested
        except asyncio.TimeoutError:
            return False  # Normal timeout
