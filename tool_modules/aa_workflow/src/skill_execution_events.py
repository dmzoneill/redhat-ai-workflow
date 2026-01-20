"""
Skill Execution Events

Emits execution events to a JSON file that the VS Code extension watches.
This enables real-time flowchart updates when skills run in chat.

Events are written to: ~/.config/aa-workflow/skill_execution.json

This module is workspace-aware: events include workspace_uri for proper
isolation of skill execution state per workspace.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Event file path
EXECUTION_FILE = Path.home() / ".config" / "aa-workflow" / "skill_execution.json"


class SkillExecutionEmitter:
    """Emits skill execution events for VS Code extension.

    Workspace-aware: events include workspace_uri for proper isolation.
    """

    def __init__(self, skill_name: str, steps: list[dict], workspace_uri: str = "default"):
        self.skill_name = skill_name
        self.steps = steps
        self.workspace_uri = workspace_uri
        self.events: list[dict] = []
        self.current_step_index = -1
        self.status = "running"
        self.start_time = datetime.now().isoformat()
        self.end_time: str | None = None

        # Ensure directory exists
        EXECUTION_FILE.parent.mkdir(parents=True, exist_ok=True)

    def _emit(self, event_type: str, data: dict | None = None) -> None:
        """Emit an event and write to file."""
        event = {
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            "skillName": self.skill_name,
            "workspaceUri": self.workspace_uri,
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
        """Write current state to file."""
        try:
            state = {
                "skillName": self.skill_name,
                "workspaceUri": self.workspace_uri,
                "status": self.status,
                "currentStepIndex": self.current_step_index,
                "totalSteps": len(self.steps),
                "startTime": self.start_time,
                "endTime": self.end_time,
                "events": self.events,
            }
            # Write atomically
            tmp_file = EXECUTION_FILE.with_suffix(".tmp")
            with open(tmp_file, "w") as f:
                json.dump(state, f, indent=2)
            tmp_file.rename(EXECUTION_FILE)
            logger.debug(f"Wrote skill state: step={self.current_step_index}, events={len(self.events)}, workspace={self.workspace_uri}")
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
_workspace_emitters: dict[str, SkillExecutionEmitter] = {}
_current_workspace: str = "default"


def get_emitter(workspace_uri: str | None = None) -> SkillExecutionEmitter | None:
    """Get the skill execution emitter for a workspace.

    Args:
        workspace_uri: Workspace URI. If None, uses current workspace.

    Returns:
        The emitter for the workspace, or None if not set.
    """
    uri = workspace_uri or _current_workspace
    return _workspace_emitters.get(uri)


def set_emitter(emitter: SkillExecutionEmitter | None, workspace_uri: str = "default") -> None:
    """Set the skill execution emitter for a workspace.

    Args:
        emitter: The emitter to set, or None to clear.
        workspace_uri: Workspace URI.
    """
    global _current_workspace
    _current_workspace = workspace_uri

    if emitter is None:
        _workspace_emitters.pop(workspace_uri, None)
    else:
        _workspace_emitters[workspace_uri] = emitter


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
    """Clear the emitter for a specific workspace.

    Args:
        workspace_uri: Workspace URI to clear.
    """
    _workspace_emitters.pop(workspace_uri, None)
