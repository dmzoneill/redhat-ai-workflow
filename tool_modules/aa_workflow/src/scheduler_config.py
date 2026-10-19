# pylint: disable=duplicate-code,cyclic-import
"""Scheduler configuration and execution log.

Single implementation of retry settings, schedule config, and job history.
``scheduler`` re-exports these classes. Methods resolve ``state_manager`` and
``config_manager`` through the scheduler module when it is loaded so tests that
patch those names keep working.
"""

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

try:
    from scripts.common.config_loader import load_config
except ImportError:  # optional; retry defaults fall back to hardcoded values
    load_config = None  # type: ignore[assignment]

from server.config_manager import config as config_manager

try:
    from server.paths import CRON_HISTORY_FILE
except ImportError:
    CRON_HISTORY_FILE = None

from server.state_manager import state as state_manager
from tool_modules.common import PROJECT_ROOT

logger = logging.getLogger(__name__)

if CRON_HISTORY_FILE is None:
    _CRON_HISTORY_FILE = Path.home() / ".config" / "aa-workflow" / "cron_history.json"
else:
    _CRON_HISTORY_FILE = CRON_HISTORY_FILE

SKILLS_DIR = PROJECT_ROOT / "skills"

# Hardcoded fallback retry configuration (used only if config.json lacks schedules.default_retry)
_FALLBACK_RETRY_CONFIG = {
    "max_attempts": 2,
    "backoff": "exponential",
    "initial_delay_seconds": 30,
    "max_delay_seconds": 300,
    "retry_on": ["auth", "network"],
}


_FALLBACKS = {
    "config_manager": config_manager,
    "state_manager": state_manager,
}


def _runtime(name: str):
    """Return a scheduler-module binding when that module is already loaded."""
    scheduler_mod = sys.modules.get("tool_modules.aa_workflow.src.scheduler")
    if scheduler_mod is not None and hasattr(scheduler_mod, name):
        return getattr(scheduler_mod, name)
    return _FALLBACKS[name]


def expand_vpn_script(configured: str | None) -> str:
    """Expand a configured VPN script path, or the default script location."""
    script = configured or "~/src/redhatter/src/redhatter_vpn/vpn-connect"
    return os.path.expanduser(script)


def _load_default_retry_config() -> dict:
    """Load default retry config from config.json, falling back to hardcoded defaults."""
    if load_config is None:
        return dict(_FALLBACK_RETRY_CONFIG)
    config = load_config()
    cfg_retry = config.get("schedules", {}).get("default_retry")
    if isinstance(cfg_retry, dict) and cfg_retry:
        return cfg_retry
    return dict(_FALLBACK_RETRY_CONFIG)


DEFAULT_RETRY_CONFIG = _load_default_retry_config()


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
        retry_setting = job_config.get("retry")
        if retry_setting is False:
            return cls(enabled=False)

        defaults = default_config or DEFAULT_RETRY_CONFIG
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
            delay = self.initial_delay_seconds * (2**attempt)
        else:
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
        return failure_type in self.retry_on


class SchedulerConfig:
    """Configuration for the scheduler loaded from config.json and state.json."""

    enabled: bool
    timezone: str
    jobs: list
    poll_sources: dict
    execution_mode: str
    default_retry: dict

    def __init__(self, config_data: dict | None = None):
        """Initialize scheduler config from config data or load from file."""
        if config_data is None:
            config_data = self._load_config()

        schedules = config_data.get("schedules", {})
        config_enabled = schedules.get("enabled", False)
        state_override = _runtime("state_manager").get("services", "scheduler", {})
        if isinstance(state_override, dict) and "enabled" in state_override:
            self.enabled = state_override["enabled"]
        else:
            self.enabled = config_enabled
        self.timezone = schedules.get("timezone", "UTC")
        self.jobs = schedules.get("jobs", [])
        self.poll_sources = schedules.get("poll_sources", {})
        self.execution_mode = schedules.get("execution_mode", "claude_cli")
        self.default_retry = schedules.get("default_retry", DEFAULT_RETRY_CONFIG)

    def _load_config(self) -> dict:
        """Load config using ConfigManager (auto-reloads if file changed)."""
        return _runtime("config_manager").get_all()

    def _is_job_enabled(self, job_config: dict) -> bool:
        """Resolve job enabled state: config.json first, state.json override.

        Args:
            job_config: The job configuration dict from config.json

        Returns:
            True if the job is enabled
        """
        job_name = job_config.get("name", "")
        config_enabled = job_config.get("enabled", True)
        state_override = _runtime("state_manager").get("jobs", job_name, {})
        if isinstance(state_override, dict) and "enabled" in state_override:
            return state_override["enabled"]
        return config_enabled

    def job_is_enabled(self, job_config: dict) -> bool:
        """Public wrapper so other classes can check a job without protected access."""
        return self._is_job_enabled(job_config)

    def get_cron_jobs(self) -> list[dict]:
        """Get jobs that use cron triggers (not poll triggers) and are enabled.

        Enabled resolution: config.json per-job 'enabled' field first,
        then state.json runtime override if present.
        """
        return [j for j in self.jobs if j.get("cron") and self._is_job_enabled(j)]

    def get_poll_jobs(self) -> list[dict]:
        """Get jobs that use poll triggers and are enabled.

        Enabled resolution: config.json per-job 'enabled' field first,
        then state.json runtime override if present.
        """
        return [
            j
            for j in self.jobs
            if j.get("trigger") == "poll" and self._is_job_enabled(j)
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

    HISTORY_FILE = _CRON_HISTORY_FILE

    def __init__(self, max_entries: int = 100):
        self.max_entries = max_entries
        self.entries: list[dict] = []
        self._load_from_file()

    def _load_from_file(self):
        """Load execution history from file."""
        try:
            if self.HISTORY_FILE.exists():
                with open(self.HISTORY_FILE, encoding="utf-8") as handle:
                    data = json.load(handle)
                    self.entries = data.get("executions", [])[-self.max_entries :]
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load cron history: %s", exc)
            self.entries = []

    def _save_to_file(self):
        """Save execution history to file."""
        try:
            self.HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(self.HISTORY_FILE, "w", encoding="utf-8") as handle:
                json.dump({"executions": self.entries}, handle, indent=2)
        except OSError as exc:
            logger.warning("Failed to save cron history: %s", exc)

    def log_execution(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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

        The parameter list is the public job-history API used by cron jobs and tests.

        Args:
            job_name: Name of the cron job
            skill: Skill that was executed
            success: Whether the execution succeeded
            duration_ms: Total execution duration in milliseconds
            error: Error message if failed
            output_preview: Preview of output (truncated to 500 chars)
            session_name: Session name for logging
            retry_info: Optional retry information dict
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
        if retry_info:
            entry["retry"] = {
                "attempts": retry_info.get("attempts", 1),
                "retried": retry_info.get("retried", False),
                "failure_type": retry_info.get("failure_type"),
                "remediation_applied": retry_info.get("remediation_applied"),
                "remediation_success": retry_info.get("remediation_success"),
            }
        self.entries.append(entry)
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries :]
        self._save_to_file()

    def get_recent(self, limit: int = 10) -> list[dict]:
        """Get recent execution entries."""
        return self.entries[-limit:]

    def get_for_job(self, job_name: str, limit: int = 5) -> list[dict]:
        """Get recent executions for a specific job."""
        job_entries = [entry for entry in self.entries if entry["job_name"] == job_name]
        return job_entries[-limit:]
