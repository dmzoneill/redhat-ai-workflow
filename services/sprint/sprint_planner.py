"""
Sprint Planner — Issue prioritization, Jira refresh, and review checking.

Extracted from SprintDaemon to keep planning logic separate from
daemon lifecycle and D-Bus orchestration.
"""

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path

from services.sprint.bot.workflow_config import (
    COMPLETED_STATUSES,
    REVIEW_STATUSES,
    WorkflowConfig,
    get_workflow_config,
)

PROJECT_ROOT = Path(__file__).parent.parent.parent

logger = logging.getLogger(__name__)


class SprintPlanner:
    """Handles sprint planning: Jira refresh, review checks, and actionability."""

    def __init__(self):
        self._workflow_config: WorkflowConfig | None = None

    # ==================== Workflow Config ====================

    @property
    def workflow_config(self) -> WorkflowConfig:
        """Get the workflow configuration (lazy loaded)."""
        if self._workflow_config is None:
            self._workflow_config = get_workflow_config()
        return self._workflow_config

    # Legacy properties for backward compatibility - delegate to config
    @property
    def ACTIONABLE_STATUSES(self) -> list[str]:
        """Get actionable statuses from config."""
        return self.workflow_config.get_actionable_statuses()

    @property
    def JIRA_STATUS_IN_PROGRESS(self) -> str:
        """Get In Progress status name from config."""
        return self.workflow_config.get_jira_transition("in_progress")

    @property
    def JIRA_STATUS_IN_REVIEW(self) -> str:
        """Get In Review status name from config."""
        return self.workflow_config.get_jira_transition("in_review")

    @property
    def JIRA_STATUS_DONE(self) -> str:
        """Get Done status name from config."""
        return self.workflow_config.get_jira_transition("done")

    def is_actionable(self, issue: dict) -> bool:
        """Check if an issue is actionable based on its Jira status.

        Uses WorkflowConfig to determine actionability based on status mappings.
        Bot should only work on issues in statuses marked with bot_can_work=true.
        """
        return self.workflow_config.is_actionable(issue)

    def export_workflow_config(self) -> dict:
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

    def build_work_prompt(self, issue: dict) -> str:
        """Build the unified work prompt for both foreground and background modes.

        Now delegates to WorkflowConfig for the actual prompt building.
        """
        return self.workflow_config.build_work_prompt(issue)

    # ==================== Jira Integration ====================

    async def refresh_from_jira(self, jira_project: str = "AAP") -> None:
        """Refresh sprint issues from Jira by calling the Jira API directly.

        Args:
            jira_project: Jira project key to fetch issues from.

        Fetches sprint info and issues, then saves to state file.
        """
        logger.info("Refreshing sprint issues from Jira...")

        try:
            from tool_modules.aa_jira.src.tools_basic import jira_get_active_sprint
            from tool_modules.aa_workflow.src.sprint_bot import (
                SprintBotConfig,
                WorkingHours,
                fetch_sprint_issues,
                to_sprint_issue_format,
            )
            from tool_modules.aa_workflow.src.sprint_history import (
                SprintIssue,
                load_sprint_state,
                save_sprint_state,
            )
            from tool_modules.aa_workflow.src.sprint_prioritizer import (
                prioritize_issues,
            )

            config = SprintBotConfig(
                working_hours=WorkingHours(),
                jira_project=jira_project,
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
                logger.info(f"Active sprint: {current_sprint.get('name')}")
            else:
                logger.warning(f"Could not get active sprint info: {sprint_info}")

            # Fetch issues from Jira (async)
            jira_issues = await fetch_sprint_issues(config)

            if not jira_issues:
                logger.warning("No issues fetched from Jira, keeping existing state")
                return

            # Filter to only show issues assigned to current user
            from server.utils import load_config

            user_config = load_config()
            user_info = user_config.get("user", {})
            jira_username = user_info.get("jira_username", "")
            full_name = user_info.get("full_name", "")
            if jira_username or full_name:
                original_count = len(jira_issues)
                # Match against username OR full name (Jira may use either)
                match_values = [v.lower() for v in [jira_username, full_name] if v]
                jira_issues = [
                    issue
                    for issue in jira_issues
                    if issue.get("assignee", "").lower() in match_values
                ]
                logger.info(
                    f"Filtered to {len(jira_issues)}/{original_count} issues assigned to {jira_username or full_name}"
                )

            if not jira_issues:
                logger.info("No issues assigned to current user, clearing sprint list")
                state = load_sprint_state()
                state.current_sprint = current_sprint  # Still update sprint info
                state.issues = []
                state.last_updated = datetime.now().isoformat()
                save_sprint_state(state)
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

                if key in existing_by_key:
                    # Preserve existing state
                    existing = existing_by_key[key]
                    new_issues.append(
                        SprintIssue(
                            key=key,
                            summary=issue_data["summary"],
                            story_points=issue_data.get("storyPoints", 0),
                            priority=issue_data.get("priority", "Major"),
                            jira_status=issue_data.get("jiraStatus", "New"),
                            assignee=issue_data.get("assignee", ""),
                            approval_status=existing.approval_status,  # Preserve
                            waiting_reason=existing.waiting_reason,  # Preserve
                            priority_reasoning=issue_data.get("priorityReasoning", []),
                            estimated_actions=issue_data.get("estimatedActions", []),
                            chat_id=existing.chat_id,  # Preserve
                            timeline=existing.timeline,  # Preserve
                            issue_type=issue_data.get("issueType", "Story"),
                            created=issue_data.get("created", ""),
                        )
                    )
                else:
                    # New issue
                    new_issues.append(
                        SprintIssue(
                            key=key,
                            summary=issue_data["summary"],
                            story_points=issue_data.get("storyPoints", 0),
                            priority=issue_data.get("priority", "Major"),
                            jira_status=issue_data.get("jiraStatus", "New"),
                            assignee=issue_data.get("assignee", ""),
                            approval_status="pending",
                            waiting_reason=None,
                            priority_reasoning=issue_data.get("priorityReasoning", []),
                            estimated_actions=issue_data.get("estimatedActions", []),
                            chat_id=None,
                            timeline=[],
                            issue_type=issue_data.get("issueType", "Story"),
                            created=issue_data.get("created", ""),
                        )
                    )

            # Calculate points for sprint info
            total_points = sum(i.story_points for i in new_issues)
            completed_points = sum(
                i.story_points
                for i in new_issues
                if i.jira_status and i.jira_status.lower() in COMPLETED_STATUSES
            )

            # Update currentSprint with calculated points
            if current_sprint:
                current_sprint["totalPoints"] = total_points
                current_sprint["completedPoints"] = completed_points

            # Update state
            state.current_sprint = current_sprint
            state.issues = new_issues
            state.last_updated = datetime.now().isoformat()
            save_sprint_state(state)

            logger.info(
                f"Sprint refresh completed: {len(new_issues)} issues, "
                f"sprint: {current_sprint.get('name') if current_sprint else 'None'}"
            )

        except Exception as e:
            logger.error(f"Failed to refresh sprint: {e}")
            import traceback

            logger.debug(traceback.format_exc())
            # Don't block - use existing state

    async def check_review_issues(self, load_state_fn, save_state_fn) -> None:
        """Check issues in Review status and try to move them to Done.

        This runs periodically (3x daily) to:
        1. Find issues in "In Review" status
        2. Check if their MR is approved and CI passed
        3. Check for "don't merge" comments
        4. Merge the MR and transition to Done if ready

        This automates the final step of the workflow.

        Args:
            load_state_fn: Callable to load current daemon state.
            save_state_fn: Callable to save daemon state.
        """
        logger.info("Checking issues in Review for merge readiness...")

        state = load_state_fn()
        issues = state.get("issues", [])

        # Find issues in Review status
        review_issues = [
            i for i in issues if i.get("jiraStatus", "").lower() in REVIEW_STATUSES
        ]

        if not review_issues:
            logger.info("No issues in Review status")
            return

        logger.info(f"Found {len(review_issues)} issues in Review")

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
            except Exception as e:
                logger.error(f"Error checking review issue {issue_key}: {e}")
                continue

        # Save any state changes
        save_state_fn(state)

    async def _check_single_review_issue(
        self, issue: dict, dont_merge_patterns: list, state: dict
    ) -> None:
        """Check a single issue in Review and try to merge/close if ready."""
        issue_key = issue.get("key")
        logger.info(f"Checking review status for {issue_key}")

        try:
            import shutil

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
   - Are there any comments containing: {', '.join(dont_merge_patterns[:5])}

3. Report the status in this exact format:
   [MR_STATUS: READY_TO_MERGE] - MR is approved, CI passed, no hold comments
   [MR_STATUS: APPROVED_WITH_HOLD] reason: <the hold comment>
   [MR_STATUS: NEEDS_APPROVAL] - MR not yet approved
   [MR_STATUS: CI_FAILING] - Pipeline failed
   [MR_STATUS: NO_MR] - No MR found for this issue
   [MR_STATUS: CHANGES_REQUESTED] - Reviewer requested changes

Also output the MR ID if found: [MR_ID: <number>]
"""

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
                    timeout=120,  # 2 minute timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.warning(f"Review check timed out for {issue_key}")
                return

            output = stdout.decode("utf-8", errors="replace") if stdout else ""

            # Parse the status
            status_match = re.search(
                r"\[MR_STATUS:\s*(\w+(?:_\w+)*)\](?:\s*reason:\s*(.+))?",
                output,
                re.IGNORECASE,
            )
            mr_id_match = re.search(r"\[MR_ID:\s*(\d+)\]", output)

            if not status_match:
                logger.warning(f"Could not parse MR status for {issue_key}")
                return

            mr_status = status_match.group(1).upper()
            hold_reason = (
                status_match.group(2).strip() if status_match.group(2) else None
            )
            mr_id = int(mr_id_match.group(1)) if mr_id_match else None

            logger.info(f"{issue_key}: MR status = {mr_status}, MR ID = {mr_id}")

            if mr_status == "READY_TO_MERGE" and mr_id:
                # Merge the MR and transition to Done
                await self._merge_and_close(issue_key, mr_id, issue, state)

            elif mr_status == "APPROVED_WITH_HOLD":
                # Log but don't merge
                logger.info(f"{issue_key}: MR approved but on hold: {hold_reason}")
                from services.sprint.daemon import _add_timeline_event

                _add_timeline_event(
                    issue,
                    {
                        "timestamp": datetime.now().isoformat(),
                        "action": "review_hold",
                        "description": f"MR approved but merge on hold: {hold_reason}",
                    },
                )

            elif mr_status == "CHANGES_REQUESTED":
                logger.info(f"{issue_key}: Changes requested on MR")
                # Could notify or take action here

            elif mr_status == "CI_FAILING":
                logger.info(f"{issue_key}: CI is failing")
                # Could notify or take action here

            elif mr_status == "NO_MR":
                logger.warning(f"{issue_key}: No MR found but issue is in Review")

        except Exception as e:
            logger.error(f"Error checking MR status for {issue_key}: {e}")

    async def _merge_and_close(
        self, issue_key: str, mr_id: int, issue: dict, state: dict
    ) -> None:
        """Merge an MR and transition the Jira issue to Done."""
        logger.info(f"Merging MR !{mr_id} and closing {issue_key}")

        try:
            import shutil

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
                    timeout=180,  # 3 minute timeout for merge
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.warning(f"Merge/close timed out for {issue_key}")
                return

            output = stdout.decode("utf-8", errors="replace") if stdout else ""

            # Parse the result
            result_match = re.search(
                r"\[MERGE_RESULT:\s*(\w+)\](?:\s*error:\s*(.+))?", output, re.IGNORECASE
            )

            if result_match:
                result = result_match.group(1).upper()
                error = result_match.group(2).strip() if result_match.group(2) else None

                from services.sprint.daemon import _add_timeline_event

                if result == "SUCCESS":
                    logger.info(
                        f"Successfully merged MR !{mr_id} and closed {issue_key}"
                    )

                    # Update local state
                    issue["jiraStatus"] = self.JIRA_STATUS_DONE
                    issue["approvalStatus"] = "completed"
                    _add_timeline_event(
                        issue,
                        {
                            "timestamp": datetime.now().isoformat(),
                            "action": "merged_and_closed",
                            "description": f"MR !{mr_id} merged, issue closed",
                            "jiraTransition": self.JIRA_STATUS_DONE,
                        },
                    )
                    return  # Signal success via issue state mutation
                else:
                    logger.warning(f"Merge/close failed for {issue_key}: {error}")
                    _add_timeline_event(
                        issue,
                        {
                            "timestamp": datetime.now().isoformat(),
                            "action": "merge_failed",
                            "description": f"Failed to merge/close: {error}",
                        },
                    )
            else:
                logger.warning(f"Could not parse merge result for {issue_key}")

        except Exception as e:
            logger.error(f"Error merging/closing {issue_key}: {e}")
