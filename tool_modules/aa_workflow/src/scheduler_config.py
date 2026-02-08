"""Scheduler configuration and execution log.

Extracted from scheduler.py to reduce class size.

Provides:
- RetryConfig: Configuration for job retry behavior with exponential backoff
- SchedulerConfig: Configuration loaded from config.json and state.json
- JobExecutionLog: Track job execution history with file persistence
- DEFAULT_RETRY_CONFIG: Default retry configuration dict
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# Cron history file path - centralized in server.paths
try:
    from server.paths import CRON_HISTORY_FILE

    _CRON_HISTORY_FILE = CRON_HISTORY_FILE
except ImportError:
    _CRON_HISTORY_FILE = Path.home() / ".config" / "aa-workflow" / "cron_history.json"


# Default retry configuration
DEFAULT_RETRY_CONFIG = {
    "max_attempts": 2,
    "backoff": "exponential",
    "initial_delay_seconds": 30,
    "max_delay_seconds": 300,
    "retry_on": ["auth", "network"],
}


@dataclass
class RetryConfig:
    """Configuration for job retry behavior with exponential backoff.

    Attributes:
        enabled: Whether retry is enabled for this job
        max_attempts: Maximum number of retry attempts (not including initial attempt)
        backoff: Backoff strategy - "exponential" or "linear"
        initial_delay_seconds: Initial delay before first retry
        max_delay_seconds: Maximum delay between retries
        retry_on: List of failure types to retry on (auth, network, timeout)
    """

    enabled: bool = True
    max_attempts: int = 2
    backoff: Literal["exponential", "linear"] = "exponential"
    initial_delay_seconds: int = 30
    max_delay_seconds: int = 300
    retry_on: list[str] = field(default_factory=lambda: ["auth", "network"])

    @classmethod
    def from_config(
        cls, job_config: dict, default_config: dict | None = None
    ) -> "RetryConfig":
        """Create RetryConfig from job configuration.

        Args:
            job_config: The job's configuration dict
            default_config: Default retry config from schedules section

        Returns:
            RetryConfig instance
        """
        # Check if retry is explicitly disabled
        retry_setting = job_config.get("retry")
        if retry_setting is False:
            return cls(enabled=False)

        # Start with global defaults
        defaults = default_config or DEFAULT_RETRY_CONFIG

        # If retry is a dict, merge with defaults
        if isinstance(retry_setting, dict):
            config = {**defaults, **retry_setting}
        else:
            config = defaults

        return cls(
            enabled=True,
            max_attempts=config.get("max_attempts", 2),
            backoff=config.get("backoff", "exponential"),
            initial_delay_seconds=config.get("initial_delay_seconds", 30),
            max_delay_seconds=config.get("max_delay_seconds", 300),
            retry_on=config.get("retry_on", ["auth", "network"]),
        )

    def calculate_delay(self, attempt: int) -> int:
        """Calculate delay before retry based on backoff strategy.

        Args:
            attempt: Current attempt number (0-indexed)

        Returns:
            Delay in seconds
        """
        if self.backoff == "exponential":
            # Exponential: initial * 2^attempt
            delay = self.initial_delay_seconds * (2**attempt)
        else:
            # Linear: initial * (attempt + 1)
            delay = self.initial_delay_seconds * (attempt + 1)

        return min(delay, self.max_delay_seconds)

    def should_retry(self, failure_type: str, attempt: int) -> bool:
        """Determine if we should retry based on failure type and attempt count.

        Args:
            failure_type: Type of failure (auth, network, timeout, unknown)
            attempt: Current attempt number (0-indexed)

        Returns:
            True if should retry
        """
        if not self.enabled:
            return False
        if attempt >= self.max_attempts:
            return False
        if failure_type not in self.retry_on:
            return False
        return True


# Project paths - use common module for consistency
from tool_modules.common import PROJECT_ROOT  # noqa: E402

SKILLS_DIR = PROJECT_ROOT / "skills"

# Import ConfigManager for thread-safe config access
from server.config_manager import config as config_manager  # noqa: E402
from server.state_manager import state as state_manager  # noqa: E402


class SchedulerConfig:
    """Configuration for the scheduler loaded from config.json and state.json."""

    def __init__(self, config_data: dict | None = None):
        """Initialize scheduler config from config data or load from file."""
        if config_data is None:
            config_data = self._load_config()

        schedules = config_data.get("schedules", {})
        # Enabled state comes from state.json
        self.enabled = state_manager.is_service_enabled("scheduler")
        self.timezone = schedules.get("timezone", "UTC")
        self.jobs = schedules.get("jobs", [])
        self.poll_sources = schedules.get("poll_sources", {})
        # Execution mode: "claude_cli" (default) or "direct"
        self.execution_mode = schedules.get("execution_mode", "claude_cli")
        # Default retry configuration for all jobs
        self.default_retry = schedules.get("default_retry", DEFAULT_RETRY_CONFIG)

    def _load_config(self) -> dict:
        """Load config using ConfigManager (auto-reloads if file changed)."""
        return config_manager.get_all()

    def get_cron_jobs(self) -> list[dict]:
        """Get jobs that use cron triggers (not poll triggers) and are enabled."""
        return [
            j
            for j in self.jobs
            if j.get("cron") and state_manager.is_job_enabled(j.get("name", ""))
        ]

    def get_poll_jobs(self) -> list[dict]:
        """Get jobs that use poll triggers and are enabled."""
        return [
            j
            for j in self.jobs
            if j.get("trigger") == "poll"
            and state_manager.is_job_enabled(j.get("name", ""))
        ]

    def get_retry_config(self, job_config: dict) -> RetryConfig:
        """Get the retry configuration for a specific job.

        Args:
            job_config: The job's configuration dict

        Returns:
            RetryConfig instance with job-specific or default settings
        """
        return RetryConfig.from_config(job_config, self.default_retry)


class JobExecutionLog:
    """Track job execution history with file persistence."""

    # File path - centralized in server.paths (set at module level)
    HISTORY_FILE = _CRON_HISTORY_FILE

    def __init__(self, max_entries: int = 100):
        self.max_entries = max_entries
        self.entries: list[dict] = []
        self._load_from_file()

    def _load_from_file(self):
        """Load execution history from file."""
        try:
            if self.HISTORY_FILE.exists():
                with open(self.HISTORY_FILE) as f:
                    data = json.load(f)
                    self.entries = data.get("executions", [])[-self.max_entries :]
        except Exception as e:
            logger.warning(f"Failed to load cron history: {e}")
            self.entries = []

    def _save_to_file(self):
        """Save execution history to file."""
        try:
            # Ensure directory exists
            self.HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(self.HISTORY_FILE, "w") as f:
                json.dump({"executions": self.entries}, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save cron history: {e}")

    def log_execution(
        self,
        job_name: str,
        skill: str,
        success: bool,
        duration_ms: int,
        error: str | None = None,
        output_preview: str | None = None,
        session_name: str | None = None,
        retry_info: dict | None = None,
    ):
        """Log a job execution.

        Args:
            job_name: Name of the cron job
            skill: Skill that was executed
            success: Whether the execution succeeded
            duration_ms: Total execution duration in milliseconds
            error: Error message if failed
            output_preview: Preview of output (truncated to 500 chars)
            session_name: Session name for logging
            retry_info: Optional retry information dict with:
                - attempts: Total attempts made (including initial)
                - retried: Whether any retries occurred
                - failure_type: Type of failure that triggered retry
                - remediation_applied: What fix was applied (kube_login, vpn_connect)
                - remediation_success: Whether the fix worked
        """
        entry = {
            "job_name": job_name,
            "skill": skill,
            "timestamp": datetime.now().isoformat(),
            "success": success,
            "duration_ms": duration_ms,
            "error": error,
            "output_preview": output_preview[:500] if output_preview else None,
            "session_name": session_name,
        }

        # Add retry information if present
        if retry_info:
            entry["retry"] = {
                "attempts": retry_info.get("attempts", 1),
                "retried": retry_info.get("retried", False),
                "failure_type": retry_info.get("failure_type"),
                "remediation_applied": retry_info.get("remediation_applied"),
                "remediation_success": retry_info.get("remediation_success"),
            }

        self.entries.append(entry)

        # Trim to max entries
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries :]

        # Persist to file
        self._save_to_file()

    def get_recent(self, limit: int = 10) -> list[dict]:
        """Get recent execution entries."""
        return self.entries[-limit:]

    def get_for_job(self, job_name: str, limit: int = 5) -> list[dict]:
        """Get recent executions for a specific job."""
        job_entries = [e for e in self.entries if e["job_name"] == job_name]
        return job_entries[-limit:]
