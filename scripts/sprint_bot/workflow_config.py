"""
Workflow Configuration Loader

Loads and provides access to the sprint workflow configuration from config.json.
This centralizes all workflow logic using the ConfigManager singleton.

Usage:
    from scripts.sprint_bot.workflow_config import WorkflowConfig, get_workflow_config

    config = get_workflow_config()

    # Check if an issue is actionable
    if config.is_actionable(issue):
        ...

    # Get the workflow stage for a Jira status
    stage = config.get_status_stage("In Progress")  # Returns "in_progress"

    # Classify an issue type
    issue_type = config.classify_issue(issue)  # Returns "spike" or "code_change"

    # Build the work prompt
    prompt = config.build_work_prompt(issue)
"""

import logging
from typing import Any, Optional

# Import the centralized ConfigManager and StateManager
from server.config_manager import config as config_manager
from server.state_manager import state as state_manager

logger = logging.getLogger(__name__)


class WorkflowConfig:
    """Loads and provides access to sprint workflow configuration from config.json."""

    def __init__(self):
        """Initialize the workflow config from ConfigManager."""
        self._config: dict = {}
        self._status_to_stage: dict[str, str] = {}
        self._load_config()

    def _load_config(self) -> None:
        """Load the configuration from ConfigManager."""
        try:
            sprint_config = config_manager.get("sprint")
            if sprint_config and isinstance(sprint_config, dict):
                self._config = sprint_config
                self._build_status_mapping()
                logger.debug(f"Loaded sprint workflow config from config.json")
            else:
                logger.warning("Sprint config not found in config.json, using defaults")
                self._config = self._default_config()
                self._build_status_mapping()
        except Exception as e:
            logger.error(f"Failed to load workflow config: {e}")
            self._config = self._default_config()
            self._build_status_mapping()

    def reload(self) -> None:
        """Reload the configuration from ConfigManager."""
        config_manager.reload()
        self._load_config()

    def _build_status_mapping(self) -> None:
        """Build a reverse mapping from Jira status to workflow stage."""
        self._status_to_stage = {}
        for stage, config in self._config.get("status_mappings", {}).items():
            for jira_status in config.get("jira_statuses", []):
                self._status_to_stage[jira_status.lower()] = stage

    def _default_config(self) -> dict:
        """Return default configuration if not found in config.json."""
        return {
            "status_mappings": {
                "not_ready": {
                    "display_name": "Not Ready",
                    "icon": "⚠️",
                    "jira_statuses": ["new", "refinement"],
                    "bot_can_work": False,
                    "ui_order": 1,
                },
                "ready": {
                    "display_name": "Ready",
                    "icon": "📋",
                    "jira_statuses": ["to do", "open", "backlog", "ready"],
                    "bot_can_work": True,
                    "ui_order": 2,
                },
                "in_progress": {
                    "display_name": "In Progress",
                    "icon": "🔄",
                    "jira_statuses": ["in progress", "in development"],
                    "bot_can_work": False,
                    "ui_order": 3,
                },
                "review": {
                    "display_name": "Review",
                    "icon": "👀",
                    "jira_statuses": ["review", "in review", "code review"],
                    "bot_can_work": False,
                    "ui_order": 4,
                },
                "done": {
                    "display_name": "Done",
                    "icon": "✅",
                    "jira_statuses": ["done", "closed", "resolved"],
                    "bot_can_work": False,
                    "ui_order": 5,
                },
            },
            "jira_transitions": {
                "in_progress": "In Progress",
                "in_review": "In Review",
                "done": "Done",
            },
            "issue_classification": {
                "spike": {
                    "issue_types": ["spike", "research"],
                    "keywords": ["research", "investigate", "spike", "poc"],
                    "workflow": {"creates_mr": False, "final_status": "done"},
                },
                "code_change": {
                    "default": True,
                    "issue_types": ["story", "task", "bug"],
                    "workflow": {"creates_mr": True, "final_status": "review"},
                },
            },
            "merge_hold_patterns": ["don't merge", "do not merge", "hold off", "wip"],
            "project_detection": {
                "automation-analytics-backend": {
                    "keywords": ["backend", "api"],
                    "default": True,
                }
            },
            "commit_format": {
                "pattern": "{issue_key} - {type}({scope}): {description}",
                "types": ["feat", "fix", "refactor", "docs", "test", "chore"],
            },
        }

    # ==================== STATUS METHODS ====================

    def get_status_stage(self, jira_status: str) -> Optional[str]:
        """Get the workflow stage for a Jira status.

        Args:
            jira_status: The Jira status (e.g., "In Progress")

        Returns:
            The workflow stage (e.g., "in_progress") or None if not found
        """
        if not jira_status:
            return None

        status_lower = jira_status.lower().strip()

        # Direct match
        if status_lower in self._status_to_stage:
            return self._status_to_stage[status_lower]

        # Partial match (e.g., "In Progress" matches "in progress")
        for mapped_status, stage in self._status_to_stage.items():
            if mapped_status in status_lower or status_lower in mapped_status:
                return stage

        return None

    def get_status_config(self, stage: str) -> dict:
        """Get the configuration for a workflow stage.

        Args:
            stage: The workflow stage (e.g., "ready", "in_progress")

        Returns:
            The stage configuration dict
        """
        return self._config.get("status_mappings", {}).get(stage, {})

    def get_all_status_mappings(self) -> dict:
        """Get all status mappings for UI rendering."""
        return self._config.get("status_mappings", {})

    def get_actionable_statuses(self) -> list[str]:
        """Get list of Jira statuses where bot can work."""
        statuses = []
        for stage, config in self._config.get("status_mappings", {}).items():
            if config.get("bot_can_work", False):
                statuses.extend(config.get("jira_statuses", []))
        return statuses

    def is_actionable(self, issue: dict) -> bool:
        """Check if the bot can work on this issue.

        Args:
            issue: Issue dict with jiraStatus field

        Returns:
            True if bot can work on this issue
        """
        jira_status = (issue.get("jiraStatus") or "").lower().strip()
        if not jira_status:
            return False

        stage = self.get_status_stage(jira_status)
        if not stage:
            return False

        stage_config = self.get_status_config(stage)
        return stage_config.get("bot_can_work", False)

    # ==================== JIRA TRANSITION METHODS ====================

    def get_jira_transition(self, target: str) -> str:
        """Get the exact Jira status name for a transition.

        Args:
            target: The target stage (e.g., "in_progress", "review", "done")

        Returns:
            The exact Jira status name to use
        """
        transitions = self._config.get("jira_transitions", {})

        # Map common aliases
        if target in ["in_review", "review"]:
            return transitions.get("in_review", "In Review")
        elif target in ["in_progress", "progress"]:
            return transitions.get("in_progress", "In Progress")
        elif target in ["done", "closed", "complete"]:
            return transitions.get("done", "Done")

        return transitions.get(target, target.title())

    # ==================== ISSUE CLASSIFICATION ====================

    def classify_issue(self, issue: dict) -> str:
        """Classify an issue as spike or code_change.

        Args:
            issue: Issue dict with issueType, summary, description fields

        Returns:
            "spike" or "code_change"
        """
        classification = self._config.get("issue_classification", {})

        issue_type = (issue.get("issueType") or "").lower().strip()
        summary = (issue.get("summary") or "").lower()
        description = (issue.get("description") or "").lower()
        text = f"{summary} {description}"

        # Check spike classification
        spike_config = classification.get("spike", {})

        # Check issue type
        spike_types = [t.lower() for t in spike_config.get("issue_types", [])]
        if issue_type in spike_types:
            return "spike"

        # Check keywords
        spike_keywords = spike_config.get("keywords", [])
        for keyword in spike_keywords:
            if keyword.lower() in text:
                return "spike"

        # Default to code_change
        return "code_change"

    def get_issue_workflow(self, issue: dict) -> dict:
        """Get the workflow configuration for an issue.

        Args:
            issue: Issue dict

        Returns:
            Workflow config dict with steps, persona, creates_mr, etc.
        """
        issue_class = self.classify_issue(issue)
        classification = self._config.get("issue_classification", {})
        return classification.get(issue_class, {}).get("workflow", {})

    # ==================== PROJECT DETECTION ====================

    def detect_project(self, issue: dict) -> Optional[str]:
        """Detect which project/repo an issue belongs to.

        Args:
            issue: Issue dict with summary, description, comments

        Returns:
            Project key (e.g., "automation-analytics-backend") or None
        """
        projects = self._config.get("project_detection", {})

        # Build searchable text
        summary = (issue.get("summary") or "").lower()
        description = (issue.get("description") or "").lower()
        comments = " ".join((c.get("body") or "").lower() for c in issue.get("comments", []) if isinstance(c, dict))
        text = f"{summary} {description} {comments}"

        # Check each project's keywords
        default_project = None
        for project_key, config in projects.items():
            if config.get("default"):
                default_project = project_key

            keywords = config.get("keywords", [])
            for keyword in keywords:
                if keyword.lower() in text:
                    return project_key

        return default_project

    def get_project_config(self, project_key: str) -> dict:
        """Get configuration for a project.

        Args:
            project_key: The project key (e.g., "automation-analytics-backend")

        Returns:
            Project config dict
        """
        return self._config.get("project_detection", {}).get(project_key, {})

    # ==================== MERGE HOLD DETECTION ====================

    def has_merge_hold(self, comments: list[str]) -> tuple[bool, Optional[str]]:
        """Check if any comments indicate the MR should not be merged.

        Args:
            comments: List of comment strings

        Returns:
            Tuple of (has_hold, matching_pattern)
        """
        patterns = self._config.get("merge_hold_patterns", [])

        for comment in comments:
            comment_lower = comment.lower()
            for pattern in patterns:
                if pattern.lower() in comment_lower:
                    return True, pattern

        return False, None

    def get_merge_hold_patterns(self) -> list[str]:
        """Get list of merge hold patterns."""
        return self._config.get("merge_hold_patterns", [])

    # ==================== SCHEDULING ====================

    def get_scheduling_config(self) -> dict:
        """Get scheduling configuration."""
        return self._config.get("scheduling", {})

    def get_working_hours(self) -> dict:
        """Get working hours configuration."""
        return self._config.get(
            "working_hours",
            {
                "timezone": "Europe/Dublin",
                "start_hour": 9,
                "end_hour": 17,
                "weekdays_only": True,
            },
        )

    # ==================== NOTIFICATIONS ====================

    def get_notification_config(self, event: str) -> dict:
        """Get notification configuration for an event.

        Args:
            event: Event name (e.g., "on_mr_created", "on_blocked")

        Returns:
            Notification config dict
        """
        return self._config.get("notifications", {}).get(event, {})

    def is_notification_enabled(self, event: str) -> bool:
        """Check if notifications are enabled for an event."""
        config = self.get_notification_config(event)
        return config.get("enabled", False)

    # ==================== BOT BEHAVIOR ====================

    def is_sprint_bot_enabled(self) -> bool:
        """Check if sprint bot service is enabled (from state.json)."""
        return state_manager.is_service_enabled("sprint_bot")

    def set_sprint_bot_enabled(self, enabled: bool) -> None:
        """Enable or disable sprint bot service (in state.json)."""
        state_manager.set_service_enabled("sprint_bot", enabled, flush=True)

    def get_bot_behavior(self) -> dict:
        """Get bot behavior configuration."""
        return self._config.get("bot_behavior", {})

    def get_forbidden_phrases(self) -> list[str]:
        """Get phrases that should never appear in bot comments."""
        return self._config.get("bot_behavior", {}).get("forbidden_phrases", [])

    def get_skip_labels(self) -> list[str]:
        """Get labels that indicate an issue should be skipped."""
        return self._config.get("bot_behavior", {}).get("skip_labels", [])

    def get_auto_approve_labels(self) -> list[str]:
        """Get labels that indicate an issue should be auto-approved."""
        return self._config.get("bot_behavior", {}).get("auto_approve_labels", [])

    # ==================== BLOCKER DETECTION ====================

    def get_blocker_config(self) -> dict:
        """Get blocker detection configuration."""
        return self._config.get("blocker_detection", {})

    # ==================== COMMIT FORMAT ====================

    def get_commit_format(self) -> dict:
        """Get commit message format configuration."""
        return self._config.get(
            "commit_format",
            {
                "pattern": "{issue_key} - {type}({scope}): {description}",
                "types": ["feat", "fix", "refactor", "docs", "test", "chore"],
            },
        )

    # ==================== STATE MACHINE ====================

    def get_state_machine(self) -> dict:
        """Get state machine configuration for execution tracing."""
        return self._config.get("state_machine", {})

    def get_state_config(self, state: str) -> dict:
        """Get configuration for a specific state.

        Args:
            state: State name (e.g., "idle", "loading", "implementing")

        Returns:
            State config dict with description, icon, type
        """
        states = self._config.get("state_machine", {}).get("states", {})
        return states.get(state, {})

    def get_valid_transitions(self, from_state: str) -> list[dict]:
        """Get valid transitions from a state.

        Args:
            from_state: Current state name

        Returns:
            List of transition dicts with 'to' and 'trigger' keys
        """
        transitions = self._config.get("state_machine", {}).get("transitions", {})
        return transitions.get(from_state, [])

    # ==================== PROMPT BUILDING ====================

    def build_work_prompt(self, issue: dict) -> str:
        """Build the unified work prompt for an issue.

        Args:
            issue: Issue dict with key, summary, description, etc.

        Returns:
            The complete prompt string
        """
        issue_key = issue.get("key", "UNKNOWN")
        summary = issue.get("summary", "No summary")
        description = issue.get("description", "No description provided")
        issue_type = issue.get("issueType", "Story")
        acceptance_criteria = issue.get("acceptanceCriteria", "See description")

        # Truncate long fields
        if len(description) > 1500:
            description = description[:1500] + "... [truncated]"
        if len(acceptance_criteria) > 800:
            acceptance_criteria = acceptance_criteria[:800] + "... [truncated]"

        # Classify the issue
        issue_class = self.classify_issue(issue)
        is_spike = issue_class == "spike"

        # Get workflow config
        workflow = self.get_issue_workflow(issue)
        commit_format = self.get_commit_format()

        # Escape summary for JSON
        summary_escaped = summary[:100].replace('"', '\\"').replace("\n", " ")

        prompt = f"""You are working on Jira issue {issue_key}.

## Issue Details
- **Key**: {issue_key}
- **Summary**: {summary}
- **Type**: {issue_type}
- **Description**:
{description}

- **Acceptance Criteria**:
{acceptance_criteria}

## WORKFLOW INSTRUCTIONS

Follow these steps in order:

### STEP 1: Start a Session
```
session_start(name="{issue_key} - {summary[:50]}")
```

### STEP 2: Determine Work Type

Based on the issue details above:
- **SPIKE/RESEARCH**: Issue type is Spike, or summary contains: research, investigate, spike, POC
- **CODE CHANGE**: Story, Task, Bug, or any issue requiring implementation

{"This appears to be a **SPIKE/RESEARCH** issue." if is_spike else "This appears to be a **CODE CHANGE** issue."}

### STEP 3: Execute the Workflow

"""

        if is_spike:
            prompt += f"""**FOR SPIKE/RESEARCH:**

1. **Research the topic**:
```
skill_run("research_topic", '{{"topic": "{summary_escaped}", "depth": "deep"}}')
```

2. **Document your findings on Jira**:
```
jira_add_comment("{issue_key}", "## Research Findings\\n\\n### Summary\\n[Your key findings here]\\n\\n### Technical Details\\n[Detailed analysis]\\n\\n### Recommendations\\n[Suggested approach or code changes]")
```

3. **Transition to Done** (no PR needed for spikes):
```
jira_transition("{issue_key}", "{self.get_jira_transition('done')}")
```

→ Output: `[SPRINT_BOT_STATUS: COMPLETED]`
"""
        else:
            prompt += f"""**FOR CODE CHANGE:**

1. **Start work** (creates branch, loads developer persona, transitions to In Progress):
```
skill_run("start_work", '{{"issue_key": "{issue_key}"}}')
```

2. **Understand the codebase**:
   - Read the issue description and acceptance criteria carefully
   - Use `code_search` to find relevant code
   - Read the files you need to modify

3. **Implement the changes**:
   - Make the necessary code modifications
   - Create commits with proper format: `{issue_key} - type(scope): description`
   - Types: {', '.join(commit_format.get('types', ['feat', 'fix', 'refactor']))}

4. **Create MR** (notifies team, transitions to In Review):
```
skill_run("create_mr", '{{"issue_key": "{issue_key}", "draft": false}}')
```

→ Output: `[SPRINT_BOT_STATUS: COMPLETED]`
"""

        prompt += f"""

### STEP 4: Handle Blockers

If you CANNOT complete the work due to:
- Missing information or unclear requirements
- Need clarification from humans
- External dependency or waiting on another team
- Technical blocker you cannot resolve

Then:
```
jira_add_comment("{issue_key}", "## Clarification Needed\\n\\n[Your specific questions here]\\n\\nPlease provide details so work can continue.")
jira_block("{issue_key}", "[Specific reason - e.g., Waiting for API spec from team X]")
```

→ Output: `[SPRINT_BOT_STATUS: BLOCKED] reason: [specific reason]`

## STATUS REPORTING (REQUIRED)

At the END of your work, you MUST output ONE of these status lines:

- `[SPRINT_BOT_STATUS: COMPLETED]` - Work done (MR created or research documented)
- `[SPRINT_BOT_STATUS: BLOCKED] reason: <why>` - Need human input, marked blocked in Jira
- `[SPRINT_BOT_STATUS: FAILED] error: <what>` - Something went wrong

## IMPORTANT RULES

1. **Never mention "bot" or "automated"** in Jira comments - appear human
2. **Commit messages MUST follow**: `{issue_key} - type(scope): description`
3. **If project/repo unclear**, check the issue description/comments for keywords (backend, frontend, billing, etc.)
4. **For spikes**: Document findings on Jira, transition straight to Done (no PR)
5. **For code changes**: Always create MR, transition to In Review
6. **If blocked**: Add comment explaining what you need, then call jira_block with reason

Begin working now.
"""

        return prompt

    # ==================== RAW CONFIG ACCESS ====================

    @property
    def raw_config(self) -> dict:
        """Get the raw configuration dict."""
        return self._config

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value by key."""
        return self._config.get(key, default)


# Singleton instance for easy access
_workflow_config: Optional[WorkflowConfig] = None


def get_workflow_config() -> WorkflowConfig:
    """Get the singleton WorkflowConfig instance."""
    global _workflow_config
    if _workflow_config is None:
        _workflow_config = WorkflowConfig()
    return _workflow_config


def reload_workflow_config() -> WorkflowConfig:
    """Reload the workflow configuration from config.json."""
    global _workflow_config
    _workflow_config = WorkflowConfig()
    return _workflow_config
