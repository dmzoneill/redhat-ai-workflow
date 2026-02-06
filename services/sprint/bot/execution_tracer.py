"""
Execution Tracer for Sprint Bot

Provides full observability into the sprint bot's decision-making and execution.
Tracks:
- State machine transitions
- Step-by-step execution with inputs/outputs
- Decision points with reasoning
- Timing information

Usage:
    tracer = ExecutionTracer(issue_key="AAP-12345")

    # Log a step
    tracer.log_step("classify_issue",
        inputs={"issue_type": "Story"},
        outputs={"classification": "code_change"},
        decision="code_change",
        reason="No spike keywords found"
    )

    # Transition state
    tracer.transition("analyzing", "classifying", trigger="issue_loaded")

    # Save trace
    tracer.save()

    # Generate Mermaid diagram
    mermaid = tracer.to_mermaid()
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# Trace storage location - consistent with other memory/state files
PROJECT_ROOT = Path(__file__).parent.parent.parent
TRACES_DIR = PROJECT_ROOT / "memory" / "state" / "sprint_traces"


class StepStatus(str, Enum):
    """Status of an execution step."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowState(str, Enum):
    """States in the sprint bot state machine."""

    IDLE = "idle"
    LOADING = "loading"
    ANALYZING = "analyzing"
    CLASSIFYING = "classifying"
    CHECKING_ACTIONABLE = "checking_actionable"
    TRANSITIONING_JIRA = "transitioning_jira"
    STARTING_WORK = "starting_work"
    RESEARCHING = "researching"
    BUILDING_PROMPT = "building_prompt"
    LAUNCHING_CHAT = "launching_chat"
    IMPLEMENTING = "implementing"
    CREATING_MR = "creating_mr"
    DOCUMENTING = "documenting"  # For spikes
    AWAITING_REVIEW = "awaiting_review"
    MERGING = "merging"
    CLOSING = "closing"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class StepTrace:
    """A single step in the execution trace."""

    step_id: str
    name: str
    timestamp: str
    duration_ms: Optional[int] = None
    status: StepStatus = StepStatus.PENDING
    inputs: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    decision: Optional[str] = None
    reason: Optional[str] = None
    error: Optional[str] = None
    skill_name: Optional[str] = None
    tool_name: Optional[str] = None
    chat_id: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        d = {
            "step_id": self.step_id,
            "name": self.name,
            "timestamp": self.timestamp,
            "status": self.status.value,
        }
        if self.duration_ms is not None:
            d["duration_ms"] = self.duration_ms
        if self.inputs:
            d["inputs"] = self.inputs
        if self.outputs:
            d["outputs"] = self.outputs
        if self.decision:
            d["decision"] = self.decision
        if self.reason:
            d["reason"] = self.reason
        if self.error:
            d["error"] = self.error
        if self.skill_name:
            d["skill_name"] = self.skill_name
        if self.tool_name:
            d["tool_name"] = self.tool_name
        if self.chat_id:
            d["chat_id"] = self.chat_id
        return d


@dataclass
class StateTransition:
    """A state machine transition."""

    from_state: str
    to_state: str
    timestamp: str
    trigger: Optional[str] = None
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        d = {
            "from_state": self.from_state,
            "to_state": self.to_state,
            "timestamp": self.timestamp,
        }
        if self.trigger:
            d["trigger"] = self.trigger
        if self.data:
            d["data"] = self.data
        return d


class ExecutionTracer:
    """
    Traces execution of sprint bot workflows.

    Provides:
    - Step-by-step logging with inputs/outputs
    - State machine transition tracking
    - Decision point recording with reasoning
    - Mermaid diagram generation
    - Persistence to YAML files
    """

    # State machine definition - valid transitions
    STATE_MACHINE = {
        WorkflowState.IDLE: [WorkflowState.LOADING],
        WorkflowState.LOADING: [WorkflowState.ANALYZING, WorkflowState.FAILED],
        WorkflowState.ANALYZING: [WorkflowState.CLASSIFYING, WorkflowState.BLOCKED, WorkflowState.FAILED],
        WorkflowState.CLASSIFYING: [WorkflowState.CHECKING_ACTIONABLE, WorkflowState.FAILED],
        WorkflowState.CHECKING_ACTIONABLE: [
            WorkflowState.TRANSITIONING_JIRA,
            WorkflowState.BLOCKED,  # Not actionable
            WorkflowState.FAILED,
        ],
        WorkflowState.TRANSITIONING_JIRA: [
            WorkflowState.STARTING_WORK,
            WorkflowState.RESEARCHING,  # For spikes
            WorkflowState.FAILED,
        ],
        WorkflowState.STARTING_WORK: [WorkflowState.BUILDING_PROMPT, WorkflowState.BLOCKED, WorkflowState.FAILED],
        WorkflowState.RESEARCHING: [
            WorkflowState.DOCUMENTING,  # Spike path
            WorkflowState.BUILDING_PROMPT,
            WorkflowState.BLOCKED,
            WorkflowState.FAILED,
        ],
        WorkflowState.BUILDING_PROMPT: [
            WorkflowState.LAUNCHING_CHAT,
            WorkflowState.IMPLEMENTING,  # Background mode
            WorkflowState.FAILED,
        ],
        WorkflowState.LAUNCHING_CHAT: [WorkflowState.IMPLEMENTING, WorkflowState.FAILED],
        WorkflowState.IMPLEMENTING: [
            WorkflowState.CREATING_MR,
            WorkflowState.BLOCKED,
            WorkflowState.COMPLETED,  # For spikes that go straight to done
            WorkflowState.FAILED,
        ],
        WorkflowState.DOCUMENTING: [WorkflowState.CLOSING, WorkflowState.BLOCKED, WorkflowState.FAILED],
        WorkflowState.CREATING_MR: [WorkflowState.AWAITING_REVIEW, WorkflowState.BLOCKED, WorkflowState.FAILED],
        WorkflowState.AWAITING_REVIEW: [
            WorkflowState.MERGING,
            WorkflowState.BLOCKED,
            WorkflowState.IMPLEMENTING,  # Feedback requires changes
        ],
        WorkflowState.MERGING: [WorkflowState.CLOSING, WorkflowState.FAILED],
        WorkflowState.CLOSING: [WorkflowState.COMPLETED, WorkflowState.FAILED],
        WorkflowState.BLOCKED: [
            WorkflowState.ANALYZING,  # Retry after unblock
            WorkflowState.IMPLEMENTING,
            WorkflowState.COMPLETED,  # Manual completion
        ],
        WorkflowState.COMPLETED: [],  # Terminal state
        WorkflowState.FAILED: [
            WorkflowState.IDLE,  # Retry
        ],
    }

    # Human-readable state descriptions
    STATE_DESCRIPTIONS = {
        WorkflowState.IDLE: "Not started",
        WorkflowState.LOADING: "Loading issue from Jira",
        WorkflowState.ANALYZING: "Analyzing issue details",
        WorkflowState.CLASSIFYING: "Determining work type",
        WorkflowState.CHECKING_ACTIONABLE: "Checking if actionable",
        WorkflowState.TRANSITIONING_JIRA: "Updating Jira status",
        WorkflowState.STARTING_WORK: "Creating branch",
        WorkflowState.RESEARCHING: "Searching codebase",
        WorkflowState.BUILDING_PROMPT: "Preparing work prompt",
        WorkflowState.LAUNCHING_CHAT: "Opening Cursor chat",
        WorkflowState.IMPLEMENTING: "Making changes",
        WorkflowState.DOCUMENTING: "Documenting findings",
        WorkflowState.CREATING_MR: "Creating merge request",
        WorkflowState.AWAITING_REVIEW: "Waiting for review",
        WorkflowState.MERGING: "Merging MR",
        WorkflowState.CLOSING: "Closing issue",
        WorkflowState.BLOCKED: "Blocked - waiting for input",
        WorkflowState.COMPLETED: "Completed",
        WorkflowState.FAILED: "Failed",
    }

    def __init__(
        self,
        issue_key: str,
        workflow_type: Optional[str] = None,
        execution_mode: str = "foreground",
    ):
        """
        Initialize a new execution tracer.

        Args:
            issue_key: Jira issue key (e.g., AAP-12345)
            workflow_type: "code_change" or "spike" (auto-detected if not provided)
            execution_mode: "foreground" (Cursor chat) or "background" (Claude CLI)
        """
        self.issue_key = issue_key
        self.workflow_type = workflow_type
        self.execution_mode = execution_mode

        self.started_at = datetime.utcnow().isoformat() + "Z"
        self.completed_at: Optional[str] = None

        self.current_state = WorkflowState.IDLE
        self.steps: list[StepTrace] = []
        self.transitions: list[StateTransition] = []

        self._step_counter = 0
        self._step_start_time: Optional[float] = None
        self._current_step: Optional[StepTrace] = None

        # Ensure traces directory exists
        TRACES_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def trace_path(self) -> Path:
        """Path to the trace file for this issue."""
        return TRACES_DIR / f"{self.issue_key}.yaml"

    def start_step(
        self,
        name: str,
        inputs: Optional[dict] = None,
        skill_name: Optional[str] = None,
        tool_name: Optional[str] = None,
    ) -> str:
        """
        Start a new execution step.

        Args:
            name: Human-readable step name
            inputs: Input parameters for this step
            skill_name: If this step runs a skill
            tool_name: If this step calls a tool

        Returns:
            Step ID for later reference
        """
        self._step_counter += 1
        step_id = f"step_{self._step_counter}"

        self._current_step = StepTrace(
            step_id=step_id,
            name=name,
            timestamp=datetime.utcnow().isoformat() + "Z",
            status=StepStatus.RUNNING,
            inputs=inputs or {},
            skill_name=skill_name,
            tool_name=tool_name,
        )
        self._step_start_time = time.time()

        self.steps.append(self._current_step)
        logger.debug(f"[Tracer] Started step: {name} ({step_id})")

        return step_id

    def end_step(
        self,
        step_id: Optional[str] = None,
        status: StepStatus = StepStatus.SUCCESS,
        outputs: Optional[dict] = None,
        decision: Optional[str] = None,
        reason: Optional[str] = None,
        error: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> None:
        """
        End the current or specified step.

        Args:
            step_id: Step to end (defaults to current)
            status: Final status of the step
            outputs: Output values from the step
            decision: If this was a decision point, what was decided
            reason: Reasoning for the decision
            error: Error message if failed
            chat_id: Cursor chat ID if applicable
        """
        step = self._current_step
        if step_id:
            step = next((s for s in self.steps if s.step_id == step_id), None)

        if not step:
            logger.warning(f"[Tracer] No step to end: {step_id}")
            return

        # Calculate duration
        if self._step_start_time:
            step.duration_ms = int((time.time() - self._step_start_time) * 1000)

        step.status = status
        if outputs:
            step.outputs = outputs
        if decision:
            step.decision = decision
        if reason:
            step.reason = reason
        if error:
            step.error = error
            step.status = StepStatus.FAILED
        if chat_id:
            step.chat_id = chat_id

        logger.debug(f"[Tracer] Ended step: {step.name} -> {status.value}")

        self._current_step = None
        self._step_start_time = None

    def log_step(
        self,
        name: str,
        inputs: Optional[dict] = None,
        outputs: Optional[dict] = None,
        decision: Optional[str] = None,
        reason: Optional[str] = None,
        status: StepStatus = StepStatus.SUCCESS,
        skill_name: Optional[str] = None,
        tool_name: Optional[str] = None,
        duration_ms: Optional[int] = None,
        error: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> str:
        """
        Log a complete step in one call.

        Convenience method for steps that complete immediately.
        """
        step_id = self.start_step(name, inputs, skill_name, tool_name)

        if duration_ms and self._current_step:
            self._current_step.duration_ms = duration_ms
            self._step_start_time = None  # Don't calculate

        self.end_step(
            step_id=step_id,
            status=status,
            outputs=outputs,
            decision=decision,
            reason=reason,
            error=error,
            chat_id=chat_id,
        )

        return step_id

    def transition(
        self,
        to_state: WorkflowState | str,
        trigger: Optional[str] = None,
        data: Optional[dict] = None,
    ) -> bool:
        """
        Transition to a new state.

        Args:
            to_state: Target state
            trigger: What triggered this transition
            data: Additional context data

        Returns:
            True if transition was valid and executed
        """
        if isinstance(to_state, str):
            try:
                to_state = WorkflowState(to_state)
            except ValueError:
                logger.error(f"[Tracer] Invalid state: {to_state}")
                return False

        # Validate transition
        valid_targets = self.STATE_MACHINE.get(self.current_state, [])
        if to_state not in valid_targets:
            logger.warning(
                f"[Tracer] Invalid transition: {self.current_state.value} -> {to_state.value}. "
                f"Valid targets: {[s.value for s in valid_targets]}"
            )
            # Allow anyway but log warning

        transition = StateTransition(
            from_state=self.current_state.value,
            to_state=to_state.value,
            timestamp=datetime.utcnow().isoformat() + "Z",
            trigger=trigger,
            data=data or {},
        )

        self.transitions.append(transition)

        logger.info(
            f"[Tracer] State transition: {self.current_state.value} -> {to_state.value}"
            f"{f' (trigger: {trigger})' if trigger else ''}"
        )

        self.current_state = to_state

        # Mark completion
        if to_state in (WorkflowState.COMPLETED, WorkflowState.FAILED):
            self.completed_at = datetime.utcnow().isoformat() + "Z"

        return True

    def set_workflow_type(self, workflow_type: str, reason: str) -> None:
        """Set the workflow type with reasoning."""
        self.workflow_type = workflow_type
        self.log_step(
            "classify_workflow",
            outputs={"workflow_type": workflow_type},
            decision=workflow_type,
            reason=reason,
        )

    def mark_blocked(self, reason: str, waiting_for: Optional[str] = None) -> None:
        """Mark the workflow as blocked."""
        self.transition(
            WorkflowState.BLOCKED,
            trigger="blocked",
            data={"reason": reason, "waiting_for": waiting_for},
        )
        self.log_step(
            "mark_blocked",
            outputs={"blocked": True, "reason": reason},
            status=StepStatus.SUCCESS,
        )

    def mark_completed(self, summary: Optional[str] = None) -> None:
        """Mark the workflow as completed."""
        self.transition(WorkflowState.COMPLETED, trigger="completed")
        self.log_step(
            "mark_completed",
            outputs={"completed": True, "summary": summary},
            status=StepStatus.SUCCESS,
        )

    def mark_failed(self, error: str) -> None:
        """Mark the workflow as failed."""
        self.transition(WorkflowState.FAILED, trigger="error", data={"error": error})
        self.log_step(
            "mark_failed",
            error=error,
            status=StepStatus.FAILED,
        )

    def to_dict(self) -> dict:
        """Convert trace to dictionary for serialization."""
        return {
            "issue_key": self.issue_key,
            "workflow_type": self.workflow_type,
            "execution_mode": self.execution_mode,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "current_state": self.current_state.value,
            "state_description": self.STATE_DESCRIPTIONS.get(self.current_state, ""),
            "steps": [s.to_dict() for s in self.steps],
            "transitions": [t.to_dict() for t in self.transitions],
            "summary": self._generate_summary(),
        }

    def _generate_summary(self) -> dict:
        """Generate a summary of the execution."""
        total_duration = sum(s.duration_ms or 0 for s in self.steps)
        successful = sum(1 for s in self.steps if s.status == StepStatus.SUCCESS)
        failed = sum(1 for s in self.steps if s.status == StepStatus.FAILED)

        return {
            "total_steps": len(self.steps),
            "successful_steps": successful,
            "failed_steps": failed,
            "total_duration_ms": total_duration,
            "total_transitions": len(self.transitions),
            "final_state": self.current_state.value,
        }

    def save(self) -> Path:
        """Save trace to YAML file."""
        try:
            data = self.to_dict()
            self.trace_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
            logger.info(f"[Tracer] Saved trace to {self.trace_path}")
            return self.trace_path
        except Exception as e:
            logger.error(f"[Tracer] Failed to save trace: {e}")
            raise

    @classmethod
    def load(cls, issue_key: str) -> Optional["ExecutionTracer"]:
        """Load an existing trace from file."""
        trace_path = TRACES_DIR / f"{issue_key}.yaml"
        if not trace_path.exists():
            return None

        try:
            data = yaml.safe_load(trace_path.read_text())

            tracer = cls(
                issue_key=data["issue_key"],
                workflow_type=data.get("workflow_type"),
                execution_mode=data.get("execution_mode", "foreground"),
            )

            tracer.started_at = data.get("started_at", tracer.started_at)
            tracer.completed_at = data.get("completed_at")

            # Restore state
            try:
                tracer.current_state = WorkflowState(data.get("current_state", "idle"))
            except ValueError:
                tracer.current_state = WorkflowState.IDLE

            # Restore steps
            for step_data in data.get("steps", []):
                step = StepTrace(
                    step_id=step_data["step_id"],
                    name=step_data["name"],
                    timestamp=step_data["timestamp"],
                    duration_ms=step_data.get("duration_ms"),
                    status=StepStatus(step_data.get("status", "success")),
                    inputs=step_data.get("inputs", {}),
                    outputs=step_data.get("outputs", {}),
                    decision=step_data.get("decision"),
                    reason=step_data.get("reason"),
                    error=step_data.get("error"),
                    skill_name=step_data.get("skill_name"),
                    tool_name=step_data.get("tool_name"),
                    chat_id=step_data.get("chat_id"),
                )
                tracer.steps.append(step)

            # Restore transitions
            for trans_data in data.get("transitions", []):
                trans = StateTransition(
                    from_state=trans_data["from_state"],
                    to_state=trans_data["to_state"],
                    timestamp=trans_data["timestamp"],
                    trigger=trans_data.get("trigger"),
                    data=trans_data.get("data", {}),
                )
                tracer.transitions.append(trans)

            tracer._step_counter = len(tracer.steps)

            return tracer

        except Exception as e:
            logger.error(f"[Tracer] Failed to load trace: {e}")
            return None

    def to_mermaid(self, highlight_path: bool = True) -> str:
        """
        Generate a Mermaid state diagram.

        Args:
            highlight_path: Whether to highlight the path taken

        Returns:
            Mermaid diagram string
        """
        lines = ["stateDiagram-v2"]

        # Add state descriptions as notes
        lines.append("    %% State definitions")
        for state in WorkflowState:
            desc = self.STATE_DESCRIPTIONS.get(state, state.value)
            lines.append(f"    {state.value}: {desc}")

        lines.append("")
        lines.append("    %% Transitions")

        # Add all valid transitions
        for from_state, to_states in self.STATE_MACHINE.items():
            for to_state in to_states:
                lines.append(f"    {from_state.value} --> {to_state.value}")

        # Add start/end markers
        lines.append("")
        lines.append("    [*] --> idle")
        lines.append("    completed --> [*]")
        lines.append("    failed --> [*]")

        if highlight_path and self.transitions:
            lines.append("")
            lines.append("    %% Highlight path taken")

            # Collect visited states
            visited_states = {WorkflowState.IDLE}
            for trans in self.transitions:
                try:
                    visited_states.add(WorkflowState(trans.to_state))
                except ValueError:
                    pass

            # Style visited states
            for state in visited_states:
                if state == self.current_state:
                    # Current state - yellow/orange
                    lines.append(f"    style {state.value} fill:#FFD700,stroke:#FF8C00,stroke-width:3px")
                elif state in (WorkflowState.COMPLETED,):
                    # Completed - green
                    lines.append(f"    style {state.value} fill:#90EE90,stroke:#228B22")
                elif state in (WorkflowState.FAILED, WorkflowState.BLOCKED):
                    # Failed/blocked - red
                    lines.append(f"    style {state.value} fill:#FFB6C1,stroke:#DC143C")
                else:
                    # Visited - light green
                    lines.append(f"    style {state.value} fill:#98FB98,stroke:#32CD32")

        return "\n".join(lines)

    def to_mermaid_flowchart(self) -> str:
        """
        Generate a Mermaid flowchart showing the actual execution path.

        This is more linear and shows the actual steps taken.
        """
        lines = ["flowchart TD"]

        # Add steps as nodes
        for i, step in enumerate(self.steps):
            # Determine node shape based on status
            if step.status == StepStatus.SUCCESS:
                shape_start, shape_end = "[", "]"
                style = "fill:#90EE90"
            elif step.status == StepStatus.FAILED:
                shape_start, shape_end = "[[", "]]"
                style = "fill:#FFB6C1"
            elif step.status == StepStatus.RUNNING:
                shape_start, shape_end = "((", "))"
                style = "fill:#FFD700"
            elif step.status == StepStatus.SKIPPED:
                shape_start, shape_end = "[/", "/]"
                style = "fill:#D3D3D3"
            else:
                shape_start, shape_end = "[", "]"
                style = "fill:#FFFFFF"

            # Build label
            label_parts = [step.name]
            if step.decision:
                label_parts.append(f"Decision: {step.decision}")
            if step.duration_ms:
                label_parts.append(f"{step.duration_ms}ms")

            label = "<br>".join(label_parts)
            node_id = f"step{i}"

            lines.append(f'    {node_id}{shape_start}"{label}"{shape_end}')
            lines.append(f"    style {node_id} {style}")

            # Connect to previous step
            if i > 0:
                prev_id = f"step{i-1}"
                lines.append(f"    {prev_id} --> {node_id}")

        return "\n".join(lines)

    def to_timeline_html(self) -> str:
        """
        Generate HTML for a timeline view.

        Returns HTML that can be embedded in the VS Code webview.
        """
        html_parts = ['<div class="execution-timeline">']

        for step in self.steps:
            # Status icon
            if step.status == StepStatus.SUCCESS:
                icon = "✅"
                status_class = "success"
            elif step.status == StepStatus.FAILED:
                icon = "❌"
                status_class = "failed"
            elif step.status == StepStatus.RUNNING:
                icon = "🔄"
                status_class = "running"
            elif step.status == StepStatus.SKIPPED:
                icon = "⏭️"
                status_class = "skipped"
            else:
                icon = "⏳"
                status_class = "pending"

            # Format timestamp
            try:
                ts = datetime.fromisoformat(step.timestamp.replace("Z", "+00:00"))
                time_str = ts.strftime("%H:%M:%S")
            except (ValueError, AttributeError):
                time_str = step.timestamp[:19]

            html_parts.append(
                f"""
            <div class="timeline-step {status_class}">
                <div class="timeline-marker">{icon}</div>
                <div class="timeline-content">
                    <div class="timeline-header">
                        <span class="timeline-time">{time_str}</span>
                        <span class="timeline-name">{step.name}</span>
                        {f'<span class="timeline-duration">{step.duration_ms}ms</span>' if step.duration_ms else ''}
                    </div>
            """
            )

            # Add details
            if step.decision:
                html_parts.append(
                    f"""
                    <div class="timeline-decision">
                        <strong>Decision:</strong> {step.decision}
                        {f'<br><em>{step.reason}</em>' if step.reason else ''}
                    </div>
                """
                )

            if step.inputs:
                inputs_str = ", ".join(f"{k}={v}" for k, v in list(step.inputs.items())[:3])
                html_parts.append(f'<div class="timeline-inputs">Inputs: {inputs_str}</div>')

            if step.outputs:
                outputs_str = ", ".join(f"{k}={v}" for k, v in list(step.outputs.items())[:3])
                html_parts.append(f'<div class="timeline-outputs">Outputs: {outputs_str}</div>')

            if step.error:
                html_parts.append(f'<div class="timeline-error">Error: {step.error}</div>')

            if step.chat_id:
                html_parts.append(
                    f"""
                    <div class="timeline-chat">
                        <a href="#" onclick="openChat('{step.chat_id}')">Open Chat</a>
                    </div>
                """
                )

            html_parts.append("</div></div>")

        html_parts.append("</div>")

        return "\n".join(html_parts)


def list_traces() -> list[dict]:
    """List all available traces with summary info."""
    traces = []

    if not TRACES_DIR.exists():
        return traces

    for trace_file in TRACES_DIR.glob("*.yaml"):
        try:
            data = yaml.safe_load(trace_file.read_text())
            traces.append(
                {
                    "issue_key": data.get("issue_key"),
                    "workflow_type": data.get("workflow_type"),
                    "current_state": data.get("current_state"),
                    "started_at": data.get("started_at"),
                    "completed_at": data.get("completed_at"),
                    "summary": data.get("summary", {}),
                }
            )
        except Exception as e:
            logger.warning(f"Failed to read trace {trace_file}: {e}")

    # Sort by started_at descending
    traces.sort(key=lambda t: t.get("started_at", ""), reverse=True)

    return traces


def get_trace(issue_key: str) -> Optional[dict]:
    """Get a trace by issue key."""
    trace_path = TRACES_DIR / f"{issue_key}.yaml"
    if not trace_path.exists():
        return None

    try:
        return yaml.safe_load(trace_path.read_text())
    except Exception as e:
        logger.error(f"Failed to load trace for {issue_key}: {e}")
        return None


def delete_trace(issue_key: str) -> bool:
    """Delete a trace file."""
    trace_path = TRACES_DIR / f"{issue_key}.yaml"
    if trace_path.exists():
        trace_path.unlink()
        return True
    return False
