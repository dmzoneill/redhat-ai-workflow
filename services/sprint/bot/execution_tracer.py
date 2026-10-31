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
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import ClassVar, Optional, TypedDict, Unpack

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


class StepDetails(TypedDict, total=False):
    """Optional result details accepted by :meth:`ExecutionTracer.end_step`."""

    outputs: dict | None
    decision: str | None
    reason: str | None
    error: str | None
    chat_id: str | None


class LogStepDetails(StepDetails, total=False):
    """Optional details accepted by :meth:`ExecutionTracer.log_step`."""

    inputs: dict | None
    skill_name: str | None
    tool_name: str | None
    duration_ms: int | None


@dataclass
class StepOutcome:
    """Result of a step: timing, outputs, decision and error details."""

    duration_ms: int | None = None
    outputs: dict = field(default_factory=dict)
    decision: str | None = None
    reason: str | None = None
    error: str | None = None
    chat_id: str | None = None


@dataclass
class StepOrigin:
    """Which skill or tool a step ran, if any."""

    skill_name: str | None = None
    tool_name: str | None = None


@dataclass
class StepTrace:
    """A single step in the execution trace."""

    step_id: str
    name: str
    timestamp: str
    status: StepStatus = StepStatus.PENDING
    inputs: dict = field(default_factory=dict)
    origin: StepOrigin = field(default_factory=StepOrigin)
    outcome: StepOutcome = field(default_factory=StepOutcome)

    @property
    def duration_ms(self) -> int | None:
        """Step duration in milliseconds."""
        return self.outcome.duration_ms

    @property
    def outputs(self) -> dict:
        """Output values from the step."""
        return self.outcome.outputs

    @property
    def decision(self) -> str | None:
        """What was decided, if this was a decision point."""
        return self.outcome.decision

    @property
    def reason(self) -> str | None:
        """Reasoning for the decision."""
        return self.outcome.reason

    @property
    def error(self) -> str | None:
        """Error message if the step failed."""
        return self.outcome.error

    @property
    def chat_id(self) -> str | None:
        """Cursor chat ID, if applicable."""
        return self.outcome.chat_id

    @classmethod
    def from_dict(cls, step_data: dict) -> "StepTrace":
        """Rebuild a step from its serialized form."""
        return cls(
            step_id=step_data["step_id"],
            name=step_data["name"],
            timestamp=step_data["timestamp"],
            status=StepStatus(step_data.get("status", "success")),
            inputs=step_data.get("inputs", {}),
            origin=StepOrigin(skill_name=step_data.get("skill_name"), tool_name=step_data.get("tool_name")),
            outcome=StepOutcome(
                duration_ms=step_data.get("duration_ms"),
                outputs=step_data.get("outputs", {}),
                decision=step_data.get("decision"),
                reason=step_data.get("reason"),
                error=step_data.get("error"),
                chat_id=step_data.get("chat_id"),
            ),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        d: dict = {
            "step_id": self.step_id,
            "name": self.name,
            "timestamp": self.timestamp,
            "status": self.status.value,
        }
        if self.duration_ms is not None:
            d["duration_ms"] = self.duration_ms
        optional = {
            "inputs": self.inputs,
            "outputs": self.outputs,
            "decision": self.decision,
            "reason": self.reason,
            "error": self.error,
            "skill_name": self.origin.skill_name,
            "tool_name": self.origin.tool_name,
            "chat_id": self.chat_id,
        }
        d.update({key: value for key, value in optional.items() if value})
        return d


@dataclass
class _StepCursor:
    """The step currently being timed."""

    counter: int = 0
    start_time: float | None = None
    current: StepTrace | None = None


@dataclass
class _TraceRecord:
    """Timestamps, steps and transitions recorded for a trace."""

    started_at: str
    completed_at: str | None = None
    steps: list[StepTrace] = field(default_factory=list)
    transitions: list["StateTransition"] = field(default_factory=list)


@dataclass
class StateTransition:
    """A state machine transition."""

    from_state: str
    to_state: str
    timestamp: str
    trigger: str | None = None
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        d: dict = {
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
    STATE_MACHINE: ClassVar[dict] = {
        WorkflowState.IDLE: [WorkflowState.LOADING],
        WorkflowState.LOADING: [WorkflowState.ANALYZING, WorkflowState.FAILED],
        WorkflowState.ANALYZING: [
            WorkflowState.CLASSIFYING,
            WorkflowState.BLOCKED,
            WorkflowState.FAILED,
        ],
        WorkflowState.CLASSIFYING: [
            WorkflowState.CHECKING_ACTIONABLE,
            WorkflowState.FAILED,
        ],
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
        WorkflowState.STARTING_WORK: [
            WorkflowState.BUILDING_PROMPT,
            WorkflowState.BLOCKED,
            WorkflowState.FAILED,
        ],
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
        WorkflowState.LAUNCHING_CHAT: [
            WorkflowState.IMPLEMENTING,
            WorkflowState.FAILED,
        ],
        WorkflowState.IMPLEMENTING: [
            WorkflowState.CREATING_MR,
            WorkflowState.BLOCKED,
            WorkflowState.COMPLETED,  # For spikes that go straight to done
            WorkflowState.FAILED,
        ],
        WorkflowState.DOCUMENTING: [
            WorkflowState.CLOSING,
            WorkflowState.BLOCKED,
            WorkflowState.FAILED,
        ],
        WorkflowState.CREATING_MR: [
            WorkflowState.AWAITING_REVIEW,
            WorkflowState.BLOCKED,
            WorkflowState.FAILED,
        ],
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
    STATE_DESCRIPTIONS: ClassVar[dict] = {
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
        workflow_type: str | None = None,
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

        self.current_state = WorkflowState.IDLE
        self._record = _TraceRecord(started_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
        self._cursor = _StepCursor()

        # Ensure traces directory exists
        TRACES_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def started_at(self) -> str:
        """ISO timestamp when the trace started."""
        return self._record.started_at

    @property
    def completed_at(self) -> str | None:
        """ISO timestamp when the trace finished, if it has."""
        return self._record.completed_at

    @property
    def steps(self) -> list[StepTrace]:
        """Recorded steps, in order."""
        return self._record.steps

    @property
    def transitions(self) -> list[StateTransition]:
        """Recorded state transitions, in order."""
        return self._record.transitions

    @property
    def trace_path(self) -> Path:
        """Path to the trace file for this issue."""
        return TRACES_DIR / f"{self.issue_key}.yaml"

    def start_step(
        self,
        name: str,
        inputs: dict | None = None,
        skill_name: str | None = None,
        tool_name: str | None = None,
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
        self._cursor.counter += 1
        step_id = f"step_{self._cursor.counter}"

        self._cursor.current = StepTrace(
            step_id=step_id,
            name=name,
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            status=StepStatus.RUNNING,
            inputs=inputs or {},
            origin=StepOrigin(skill_name=skill_name, tool_name=tool_name),
        )
        self._cursor.start_time = time.time()

        self.steps.append(self._cursor.current)
        logger.debug("[Tracer] Started step: %s (%s)", name, step_id)

        return step_id

    def end_step(
        self,
        step_id: str | None = None,
        status: StepStatus = StepStatus.SUCCESS,
        **details: Unpack[StepDetails],
    ) -> None:
        """
        End the current or specified step.

        Args:
            step_id: Step to end (defaults to current)
            status: Final status of the step
            **details: Optional ``outputs`` (output values), ``decision`` (what was decided at a
                decision point), ``reason`` (reasoning for it), ``error`` (error message if failed)
                and ``chat_id`` (Cursor chat ID).
        """
        step = self._cursor.current
        if step_id:
            step = next((s for s in self.steps if s.step_id == step_id), None)

        if not step:
            logger.warning("[Tracer] No step to end: %s", step_id)
            return

        # Calculate duration
        if self._cursor.start_time:
            step.outcome.duration_ms = int((time.time() - self._cursor.start_time) * 1000)

        step.status = status
        outcome = step.outcome
        outcome.outputs = details.get("outputs") or outcome.outputs
        outcome.decision = details.get("decision") or outcome.decision
        outcome.reason = details.get("reason") or outcome.reason
        outcome.chat_id = details.get("chat_id") or outcome.chat_id
        error = details.get("error")
        if error:
            outcome.error = error
            step.status = StepStatus.FAILED

        logger.debug("[Tracer] Ended step: %s -> %s", step.name, status.value)

        self._cursor.current = None
        self._cursor.start_time = None

    def log_step(
        self,
        name: str,
        status: StepStatus = StepStatus.SUCCESS,
        **details: Unpack[LogStepDetails],
    ) -> str:
        """
        Log a complete step in one call.

        Convenience method for steps that complete immediately. Accepts the
        :meth:`end_step` details plus ``inputs``, ``skill_name``, ``tool_name``
        and ``duration_ms``.
        """
        step_id = self.start_step(name, details.get("inputs"), details.get("skill_name"), details.get("tool_name"))

        duration_ms = details.get("duration_ms")
        if duration_ms and self._cursor.current:
            self._cursor.current.outcome.duration_ms = duration_ms
            self._cursor.start_time = None  # Don't calculate

        self.end_step(
            step_id=step_id,
            status=status,
            outputs=details.get("outputs"),
            decision=details.get("decision"),
            reason=details.get("reason"),
            error=details.get("error"),
            chat_id=details.get("chat_id"),
        )

        return step_id

    def transition(
        self,
        to_state: WorkflowState | str,
        trigger: str | None = None,
        data: dict | None = None,
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
                logger.error("[Tracer] Invalid state: %s", to_state)
                return False

        # Validate transition
        valid_targets = self.STATE_MACHINE.get(self.current_state, [])
        if to_state not in valid_targets:
            logger.warning(
                "[Tracer] Invalid transition: %s -> %s. Valid targets: %s",
                self.current_state.value,
                to_state.value,
                [s.value for s in valid_targets],
            )
            # Allow anyway but log warning

        transition = StateTransition(
            from_state=self.current_state.value,
            to_state=to_state.value,
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            trigger=trigger,
            data=data or {},
        )

        self.transitions.append(transition)

        logger.info(
            "[Tracer] State transition: %s -> %s%s",
            self.current_state.value,
            to_state.value,
            f" (trigger: {trigger})" if trigger else "",
        )

        self.current_state = to_state

        # Mark completion
        if to_state in (WorkflowState.COMPLETED, WorkflowState.FAILED):
            self._record.completed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

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

    def mark_blocked(self, reason: str, waiting_for: str | None = None) -> None:
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

    def mark_completed(self, summary: str | None = None) -> None:
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
            logger.info("[Tracer] Saved trace to %s", self.trace_path)
            return self.trace_path
        except Exception as e:
            logger.error("[Tracer] Failed to save trace: %s", e)
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

            tracer._record.started_at = data.get("started_at", tracer.started_at)
            tracer._record.completed_at = data.get("completed_at")

            # Restore state
            try:
                tracer.current_state = WorkflowState(data.get("current_state", "idle"))
            except ValueError:
                tracer.current_state = WorkflowState.IDLE

            # Restore steps
            tracer.steps.extend(StepTrace.from_dict(step_data) for step_data in data.get("steps", []))

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

            tracer._cursor.counter = len(tracer.steps)

            return tracer

        except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError, AttributeError):
            logger.exception("[Tracer] Failed to load trace")
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
                except ValueError as exc:
                    logger.debug("Invalid value encountered: %s", exc)

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
                prev_id = f"step{i - 1}"
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

            html_parts.append(f"""
            <div class="timeline-step {status_class}">
                <div class="timeline-marker">{icon}</div>
                <div class="timeline-content">
                    <div class="timeline-header">
                        <span class="timeline-time">{time_str}</span>
                        <span class="timeline-name">{step.name}</span>
                        {f'<span class="timeline-duration">{step.duration_ms}ms</span>' if step.duration_ms else ""}
                    </div>
            """)

            # Add details
            if step.decision:
                html_parts.append(f"""
                    <div class="timeline-decision">
                        <strong>Decision:</strong> {step.decision}
                        {f"<br><em>{step.reason}</em>" if step.reason else ""}
                    </div>
                """)

            if step.inputs:
                inputs_str = ", ".join(f"{k}={v}" for k, v in list(step.inputs.items())[:3])
                html_parts.append(f'<div class="timeline-inputs">Inputs: {inputs_str}</div>')

            if step.outputs:
                outputs_str = ", ".join(f"{k}={v}" for k, v in list(step.outputs.items())[:3])
                html_parts.append(f'<div class="timeline-outputs">Outputs: {outputs_str}</div>')

            if step.error:
                html_parts.append(f'<div class="timeline-error">Error: {step.error}</div>')

            if step.chat_id:
                html_parts.append(f"""
                    <div class="timeline-chat">
                        <a href="#" onclick="openChat('{step.chat_id}')">Open Chat</a>
                    </div>
                """)

            html_parts.append("</div></div>")

        html_parts.append("</div>")

        return "\n".join(html_parts)


def list_traces() -> list[dict]:
    """List all available traces with summary info."""
    traces: list[dict] = []

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
        except (OSError, yaml.YAMLError, AttributeError) as e:
            logger.warning("Failed to read trace %s: %s", trace_file, e, exc_info=True)

    # Sort by started_at descending
    traces.sort(key=lambda t: t.get("started_at", ""), reverse=True)

    return traces


def get_trace(issue_key: str) -> dict | None:
    """Get a trace by issue key."""
    trace_path = TRACES_DIR / f"{issue_key}.yaml"
    if not trace_path.exists():
        return None

    try:
        return yaml.safe_load(trace_path.read_text())
    except (OSError, yaml.YAMLError):
        logger.exception("Failed to load trace for %s", issue_key)
        return None


def delete_trace(issue_key: str) -> bool:
    """Delete a trace file."""
    trace_path = TRACES_DIR / f"{issue_key}.yaml"
    if trace_path.exists():
        trace_path.unlink()
        return True
    return False
