"""Memory Schema Validation - Pydantic models for memory files.

Validates memory file structure to catch typos and structural errors early.

Usage:
    from scripts.common.memory_schemas import validate_memory

    data = yaml.safe_load(memory_file.read_text())
    if not validate_memory("state/current_work", data):
        print("Invalid structure!")
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from pydantic import BaseModel, Field, validator

    PYDANTIC_AVAILABLE = True
except ImportError:
    # Pydantic not installed, provide graceful degradation
    PYDANTIC_AVAILABLE = False

    class BaseModel:  # type: ignore[no-redef]
        """Fallback BaseModel when Pydantic not installed."""

        def __init__(self, **kwargs):
            pass

        def dict(self):
            return {}

    def Field(*args, **kwargs):  # type: ignore[misc]
        """Fallback Field when Pydantic not installed."""
        return None

    def validator(*args, **kwargs):  # type: ignore[misc]
        """Fallback validator when Pydantic not installed."""
        return lambda f: f


# State Memory Schemas


class ActiveIssue(BaseModel):
    """An active Jira issue being worked on."""

    if PYDANTIC_AVAILABLE:
        key: str = Field(..., description="Jira issue key (e.g., AAP-12345)")  # type: ignore[misc]
        summary: str = Field(..., description="Issue summary/title")  # type: ignore[misc]
        status: str = Field(..., description="Current status (e.g., In Progress)")  # type: ignore[misc]
        branch: str = Field(..., description="Git branch name")  # type: ignore[misc]
        repo: str = Field(..., description="Repository name")  # type: ignore[misc]
        started: str = Field(..., description="ISO timestamp when started")  # type: ignore[misc]

        @validator("key")  # type: ignore[misc]
        def validate_key(cls, v):
            """Ensure issue key matches pattern."""
            if not v or "-" not in v:
                raise ValueError("Issue key must match pattern PROJECT-NUMBER")
            return v


class OpenMR(BaseModel):
    """An open merge request."""

    if PYDANTIC_AVAILABLE:
        id: int = Field(..., description="MR ID number")  # type: ignore[misc]
    project: str = Field(..., description="GitLab project path")
    title: str = Field(..., description="MR title")
    pipeline_status: Optional[str] = Field(None, description="CI/CD pipeline status")
    needs_review: Optional[bool] = Field(None, description="Whether review is needed")


class FollowUp(BaseModel):
    """A follow-up task or reminder."""

    task: str = Field(..., description="Task description")
    priority: Optional[str] = Field(None, description="Priority level (high/medium/low)")
    issue_key: Optional[str] = Field(None, description="Related Jira issue key")


class CurrentWork(BaseModel):
    """State of current work - active issues, MRs, follow-ups."""

    active_issue: Optional[str] = Field("", description="Primary active issue key")
    active_issues: List[ActiveIssue] = Field(default_factory=list, description="All active issues")
    open_mrs: List[OpenMR] = Field(default_factory=list, description="Open merge requests")
    follow_ups: List[FollowUp] = Field(default_factory=list, description="Follow-up tasks")
    last_updated: str = Field(..., description="ISO timestamp of last update")

    @validator("last_updated")
    def validate_timestamp(cls, v):
        """Ensure timestamp is valid ISO format."""
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("last_updated must be valid ISO timestamp")
        return v


class EnvironmentStatus(BaseModel):
    """Status of a single environment."""

    status: str = Field(..., description="Environment status (healthy/degraded/down)")
    last_checked: str = Field(..., description="ISO timestamp of last check")
    issues: List[str] = Field(default_factory=list, description="Known issues")


class EphemeralNamespace(BaseModel):
    """An ephemeral namespace deployment."""

    name: str = Field(..., description="Namespace name")
    deployed_at: str = Field(..., description="ISO timestamp of deployment")
    expires_at: Optional[str] = Field(None, description="ISO timestamp of expiration")
    mr_id: Optional[int] = Field(None, description="Related MR ID")


class Environments(BaseModel):
    """Environment health tracking."""

    environments: Dict[str, EnvironmentStatus] = Field(default_factory=dict, description="Environment statuses")
    ephemeral_namespaces: List[EphemeralNamespace] = Field(
        default_factory=list, description="Active ephemeral namespaces"
    )
    last_checked: str = Field(..., description="ISO timestamp of last check")


# Learned Memory Schemas


class PatternUsageStats(BaseModel):
    """Usage statistics for a pattern."""

    times_matched: int = Field(0, description="How many times pattern matched")
    times_fixed: int = Field(0, description="How many times fix succeeded")
    success_rate: float = Field(0.0, description="Success rate (times_fixed / times_matched)")
    last_matched: Optional[str] = Field(None, description="ISO timestamp of last match")


class ErrorPattern(BaseModel):
    """An error pattern with auto-fix commands."""

    pattern: str = Field(..., description="Error pattern to match")
    meaning: Optional[str] = Field(None, description="What this error means")
    fix: str = Field(..., description="How to fix this error")
    commands: List[str] = Field(default_factory=list, description="MCP tool commands to run")
    usage_stats: Optional[PatternUsageStats] = Field(None, description="Usage statistics")


class AuthPattern(BaseModel):
    """Authentication error pattern."""

    pattern: str = Field(..., description="Auth error pattern to match")
    meaning: Optional[str] = Field(None, description="What this error means")
    fix: str = Field(..., description="How to fix this auth error")
    commands: List[str] = Field(default_factory=list, description="MCP tool commands to run")
    usage_stats: Optional[PatternUsageStats] = Field(None, description="Usage statistics")


class BonfirePattern(BaseModel):
    """Bonfire-specific error pattern."""

    pattern: str = Field(..., description="Bonfire error pattern to match")
    meaning: Optional[str] = Field(None, description="What this error means")
    fix: str = Field(..., description="How to fix this error")
    commands: List[str] = Field(default_factory=list, description="MCP tool commands to run")
    usage_stats: Optional[PatternUsageStats] = Field(None, description="Usage statistics")


class PipelinePattern(BaseModel):
    """CI/CD pipeline error pattern."""

    pattern: str = Field(..., description="Pipeline error pattern to match")
    meaning: Optional[str] = Field(None, description="What this error means")
    fix: str = Field(..., description="How to fix this error")
    commands: List[str] = Field(default_factory=list, description="MCP tool commands to run")
    usage_stats: Optional[PatternUsageStats] = Field(None, description="Usage statistics")


class JiraCLIPattern(BaseModel):
    """Jira CLI error pattern."""

    pattern: str = Field(..., description="Jira error pattern to match")
    description: Optional[str] = Field(None, description="Error description")
    solution: str = Field(..., description="How to solve this error")


class Patterns(BaseModel):
    """Learned error patterns for auto-remediation."""

    auth_patterns: List[AuthPattern] = Field(default_factory=list, description="Authentication patterns")
    error_patterns: List[ErrorPattern] = Field(default_factory=list, description="Generic error patterns")
    bonfire_patterns: List[BonfirePattern] = Field(default_factory=list, description="Bonfire-specific patterns")
    pipeline_patterns: List[PipelinePattern] = Field(default_factory=list, description="CI/CD pipeline patterns")
    jira_cli_patterns: List[JiraCLIPattern] = Field(default_factory=list, description="Jira CLI patterns")
    last_updated: Optional[str] = Field(None, description="ISO timestamp of last update")


class ToolFix(BaseModel):
    """A manually saved tool fix."""

    tool_name: str = Field(..., description="Name of the tool that failed")
    error_pattern: str = Field(..., description="Error pattern to match")
    root_cause: str = Field(..., description="Why the error occurred")
    fix_applied: str = Field(..., description="How to fix it")
    date_learned: str = Field(..., description="Date learned (YYYY-MM-DD)")
    times_prevented: int = Field(0, description="How many times this fix prevented errors")


class ToolFixes(BaseModel):
    """Manual tool fixes saved by users."""

    tool_fixes: List[ToolFix] = Field(default_factory=list, description="Saved tool fixes")
    common_mistakes: Dict[str, str] = Field(default_factory=dict, description="Common mistakes to avoid")


# Schema Registry

SCHEMAS: Dict[str, type] = {
    "state/current_work": CurrentWork,
    "state/environments": Environments,
    "learned/patterns": Patterns,
    "learned/tool_fixes": ToolFixes,
}


def validate_memory(key: str, data: Dict[str, Any]) -> bool:
    """Validate memory data against schema.

    Args:
        key: Memory key (e.g., "state/current_work")
        data: Data to validate

    Returns:
        True if valid, False if validation failed
    """
    if not PYDANTIC_AVAILABLE:
        # Pydantic not installed, skip validation
        return True

    schema = SCHEMAS.get(key)
    if schema is None:
        # No schema defined, allow it
        return True

    try:
        schema(**data)
        return True
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Memory validation failed for {key}: {e}")
        return False


def get_schema_template(key: str) -> Optional[str]:
    """Get YAML template for a memory schema.

    Args:
        key: Memory key (e.g., "state/current_work")

    Returns:
        YAML template string or None if no schema exists
    """
    import yaml

    if BaseModel is object:
        return None

    schema = SCHEMAS.get(key)
    if schema is None:
        return None

    # Create example instance
    try:
        if key == "state/current_work":
            example = CurrentWork(
                active_issue="AAP-12345",
                active_issues=[
                    ActiveIssue(
                        key="AAP-12345",
                        summary="Example issue",
                        status="In Progress",
                        branch="aap-12345-feature",
                        repo="backend",
                        started="2026-01-09T10:00:00",
                    )
                ],
                open_mrs=[OpenMR(id=1459, project="automation-analytics-backend", title="AAP-12345 - feat: example")],
                follow_ups=[FollowUp(task="Update documentation", priority="high")],
                last_updated="2026-01-09T14:00:00",
            )
        elif key == "state/environments":
            example = Environments(
                environments={
                    "stage": EnvironmentStatus(status="healthy", last_checked="2026-01-09T14:00:00", issues=[])
                },
                ephemeral_namespaces=[],
                last_checked="2026-01-09T14:00:00",
            )
        elif key == "learned/patterns":
            example = Patterns(
                auth_patterns=[
                    AuthPattern(
                        pattern="token expired",
                        meaning="Kubernetes credentials expired",
                        fix="Refresh credentials",
                        commands=["kube_login(cluster='e')"],
                    )
                ],
                error_patterns=[],
                bonfire_patterns=[],
                pipeline_patterns=[],
                jira_cli_patterns=[],
            )
        elif key == "learned/tool_fixes":
            example = ToolFixes(
                tool_fixes=[
                    ToolFix(
                        tool_name="bonfire_deploy",
                        error_pattern="manifest unknown",
                        root_cause="Short SHA doesn't exist in Quay",
                        fix_applied="Use full 40-char SHA",
                        date_learned="2026-01-09",
                    )
                ]
            )
        else:
            return None

        return yaml.dump(example.dict(), default_flow_style=False, sort_keys=False)

    except Exception:
        return None
