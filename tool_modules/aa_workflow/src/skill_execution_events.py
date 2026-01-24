"""
Skill Execution Events

Emits execution events to a JSON file that the VS Code extension watches.
This enables real-time flowchart updates when skills run in chat.

Events are written to: ~/.config/aa-workflow/skill_execution.json

This module supports multiple concurrent skill executions:
- Each execution is keyed by execution_id (workspace_uri + skill_name + timestamp)
- Includes session_id and source (chat/cron) for identification
- Completed executions are cleaned up after CLEANUP_TIMEOUT_SECONDS
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Event file path
EXECUTION_FILE = Path.home() / ".config" / "aa-workflow" / "skill_execution.json"

# Cleanup completed executions after this many seconds
CLEANUP_TIMEOUT_SECONDS = 300  # 5 minutes


def _generate_execution_id(workspace_uri: str, skill_name: str) -> str:
    """Generate a unique execution ID."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    # Sanitize workspace_uri for use in key
    safe_workspace = workspace_uri.replace("/", "_").replace(":", "_")[-50:]
    return f"{safe_workspace}_{skill_name}_{timestamp}"


def _load_all_executions() -> dict:
    """Load all executions from file, handling both old and new formats."""
    try:
        if EXECUTION_FILE.exists():
            with open(EXECUTION_FILE) as f:
                data = json.load(f)

            # Handle old single-execution format (backward compatibility)
            if "executions" not in data and "skillName" in data:
                # Convert old format to new format
                old_exec = data
                exec_id = _generate_execution_id(
                    old_exec.get("workspaceUri", "default"), old_exec.get("skillName", "unknown")
                )
                return {
                    "executions": {exec_id: old_exec},
                    "lastUpdated": datetime.now().isoformat(),
                    "version": 2,
                }

            return data
    except (json.JSONDecodeError, OSError) as e:
        logger.debug(f"Could not load executions file: {e}")

    return {"executions": {}, "lastUpdated": datetime.now().isoformat(), "version": 2}


def _save_all_executions(data: dict) -> None:
    """Save all executions to file atomically."""
    try:
        data["lastUpdated"] = datetime.now().isoformat()
        tmp_file = EXECUTION_FILE.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(data, f, indent=2)
        tmp_file.rename(EXECUTION_FILE)
    except Exception as e:
        logger.warning(f"Failed to save executions: {e}")


def _cleanup_old_executions(data: dict) -> dict:
    """Remove completed executions older than CLEANUP_TIMEOUT_SECONDS."""
    now = datetime.now()
    to_remove = []

    for exec_id, execution in data.get("executions", {}).items():
        # Keep running executions
        if execution.get("status") == "running":
            continue

        # Check if completed execution is old enough to remove
        end_time_str = execution.get("endTime")
        if end_time_str:
            try:
                end_time = datetime.fromisoformat(end_time_str)
                age_seconds = (now - end_time).total_seconds()
                if age_seconds > CLEANUP_TIMEOUT_SECONDS:
                    to_remove.append(exec_id)
            except (ValueError, TypeError):
                pass

    for exec_id in to_remove:
        del data["executions"][exec_id]
        logger.debug(f"Cleaned up old execution: {exec_id}")

    return data


class SkillExecutionEmitter:
    """Emits skill execution events for VS Code extension.

    Supports multiple concurrent executions with session context.
    """

    def __init__(
        self,
        skill_name: str,
        steps: list[dict],
        workspace_uri: str = "default",
        session_id: str | None = None,
        session_name: str | None = None,
        source: str = "chat",  # "chat", "cron", "slack", "api"
        source_details: str | None = None,  # e.g., cron job name
    ):
        self.skill_name = skill_name
        self.steps = steps
        self.workspace_uri = workspace_uri
        self.session_id = session_id
        self.session_name = session_name
        self.source = source
        self.source_details = source_details
        self.events: list[dict] = []
        self.current_step_index = -1
        self.status = "running"
        self.start_time = datetime.now().isoformat()
        self.end_time: str | None = None

        # Generate unique execution ID
        self.execution_id = _generate_execution_id(workspace_uri, skill_name)

        # Ensure directory exists
        EXECUTION_FILE.parent.mkdir(parents=True, exist_ok=True)

    def _emit(self, event_type: str, data: dict | None = None) -> None:
        """Emit an event and write to file."""
        event = {
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            "skillName": self.skill_name,
            "workspaceUri": self.workspace_uri,
            "executionId": self.execution_id,
            "stepIndex": (self.current_step_index if self.current_step_index >= 0 else None),
            "stepName": (
                self.steps[self.current_step_index].get("name")
                if 0 <= self.current_step_index < len(self.steps)
                else None
            ),
            "data": data,
        }
        self.events.append(event)
        self._write_state()

    def _write_state(self) -> None:
        """Write current state to multi-execution file."""
        try:
            # Load existing executions
            all_data = _load_all_executions()

            # Clean up old completed executions
            all_data = _cleanup_old_executions(all_data)

            # Build this execution's state
            state = {
                "executionId": self.execution_id,
                "skillName": self.skill_name,
                "workspaceUri": self.workspace_uri,
                "sessionId": self.session_id,
                "sessionName": self.session_name,
                "source": self.source,
                "sourceDetails": self.source_details,
                "status": self.status,
                "currentStepIndex": self.current_step_index,
                "totalSteps": len(self.steps),
                "startTime": self.start_time,
                "endTime": self.end_time,
                "events": self.events,
            }

            # Update this execution in the multi-execution store
            all_data["executions"][self.execution_id] = state

            # Save all executions
            _save_all_executions(all_data)

            logger.debug(
                f"Wrote skill state: {self.skill_name} step={self.current_step_index}, "
                f"events={len(self.events)}, source={self.source}, "
                f"total_executions={len(all_data['executions'])}"
            )
        except Exception as e:
            logger.warning(f"Failed to write skill execution state: {e}")

    def skill_start(self) -> None:
        """Emit skill start event."""
        # Include step info for the extension to display
        steps_info = [
            {
                "name": s.get("name", f"step_{i}"),
                "description": s.get("description"),
                "tool": s.get("tool"),
                "compute": "compute" in s,
                "condition": s.get("condition"),
                "on_error": s.get("on_error"),
            }
            for i, s in enumerate(self.steps)
        ]
        self._emit("skill_start", {"totalSteps": len(self.steps), "steps": steps_info})

    def step_start(self, step_index: int) -> None:
        """Emit step start event."""
        self.current_step_index = step_index
        self._emit("step_start")

    def step_complete(self, step_index: int, duration_ms: int, result: str | None = None) -> None:
        """Emit step complete event."""
        self.current_step_index = step_index
        self._emit(
            "step_complete",
            {
                "duration": duration_ms,
                "result": result[:500] if result else None,
            },
        )

    def step_failed(self, step_index: int, duration_ms: int, error: str) -> None:
        """Emit step failed event."""
        self.current_step_index = step_index
        self._emit(
            "step_failed",
            {
                "duration": duration_ms,
                "error": error[:500],
            },
        )

    def step_skipped(self, step_index: int, reason: str = "condition false") -> None:
        """Emit step skipped event."""
        self.current_step_index = step_index
        self._emit("step_skipped", {"reason": reason})

    def memory_read(self, step_index: int, key: str) -> None:
        """Emit memory read event."""
        self.current_step_index = step_index
        self._emit("memory_read", {"memoryKey": key})

    def memory_write(self, step_index: int, key: str) -> None:
        """Emit memory write event."""
        self.current_step_index = step_index
        self._emit("memory_write", {"memoryKey": key})

    def auto_heal(self, step_index: int, details: str) -> None:
        """Emit auto-heal event."""
        self.current_step_index = step_index
        self._emit("auto_heal", {"healingDetails": details})

    def retry(self, step_index: int, retry_count: int) -> None:
        """Emit retry event."""
        self.current_step_index = step_index
        self._emit("retry", {"retryCount": retry_count})

    def semantic_search(self, step_index: int, query: str) -> None:
        """Emit semantic search event."""
        self.current_step_index = step_index
        self._emit("semantic_search", {"searchQuery": query})

    def remediation_step(self, step_index: int, tool: str, reason: str) -> None:
        """Emit remediation step event (dynamically inserted auto-heal step)."""
        self.current_step_index = step_index
        self._emit("remediation_step", {"tool": tool, "reason": reason})

    def skill_complete(self, success: bool, total_duration_ms: int) -> None:
        """Emit skill complete event."""
        self.status = "success" if success else "failed"
        self.end_time = datetime.now().isoformat()
        self._emit(
            "skill_complete",
            {
                "success": success,
                "duration": total_duration_ms,
            },
        )


# Workspace-aware emitter registry (set by skill executor)
# Key is execution_id for multi-execution support
_workspace_emitters: dict[str, SkillExecutionEmitter] = {}
_current_workspace: str = "default"
_current_execution_id: str | None = None


def get_emitter(workspace_uri: str | None = None, execution_id: str | None = None) -> SkillExecutionEmitter | None:
    """Get the skill execution emitter.

    Args:
        workspace_uri: Workspace URI. If None, uses current workspace.
        execution_id: Specific execution ID. If provided, returns that execution's emitter.

    Returns:
        The emitter, or None if not set.
    """
    if execution_id:
        return _workspace_emitters.get(execution_id)

    # Legacy: find by workspace_uri
    uri = workspace_uri or _current_workspace
    for emitter in _workspace_emitters.values():
        if emitter.workspace_uri == uri:
            return emitter
    return None


def set_emitter(emitter: SkillExecutionEmitter | None, workspace_uri: str = "default") -> None:
    """Set the skill execution emitter.

    Args:
        emitter: The emitter to set, or None to clear.
        workspace_uri: Workspace URI (used for legacy compatibility).
    """
    global _current_workspace, _current_execution_id
    _current_workspace = workspace_uri

    if emitter is None:
        # Clear by workspace_uri (legacy) - remove all emitters for this workspace
        to_remove = [exec_id for exec_id, e in _workspace_emitters.items() if e.workspace_uri == workspace_uri]
        for exec_id in to_remove:
            _workspace_emitters.pop(exec_id, None)
        _current_execution_id = None
    else:
        # Register by execution_id
        _workspace_emitters[emitter.execution_id] = emitter
        _current_execution_id = emitter.execution_id


def emit_event(event_type: str, data: dict[str, Any] | None = None, workspace_uri: str | None = None) -> None:
    """
    Emit an event if there's an active emitter.

    This is a convenience function for use in skill compute blocks.

    Args:
        event_type: Type of event to emit.
        data: Event data.
        workspace_uri: Workspace URI. If None, uses current workspace.
    """
    emitter = get_emitter(workspace_uri)
    if emitter:
        emitter._emit(event_type, data)


def clear_workspace_emitter(workspace_uri: str) -> None:
    """Clear emitters for a specific workspace.

    Args:
        workspace_uri: Workspace URI to clear.
    """
    to_remove = [exec_id for exec_id, e in _workspace_emitters.items() if e.workspace_uri == workspace_uri]
    for exec_id in to_remove:
        _workspace_emitters.pop(exec_id, None)


def get_all_running_executions() -> list[dict]:
    """Get all currently running executions.

    Returns:
        List of execution summaries for running skills.
    """
    running = []
    for emitter in _workspace_emitters.values():
        if emitter.status == "running":
            running.append(
                {
                    "executionId": emitter.execution_id,
                    "skillName": emitter.skill_name,
                    "workspaceUri": emitter.workspace_uri,
                    "sessionId": emitter.session_id,
                    "sessionName": emitter.session_name,
                    "source": emitter.source,
                    "sourceDetails": emitter.source_details,
                    "currentStepIndex": emitter.current_step_index,
                    "totalSteps": len(emitter.steps),
                    "startTime": emitter.start_time,
                }
            )
    return running
