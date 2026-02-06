"""Scheduler Engine - Cron-based task scheduling for MCP server.

Provides:
- CronScheduler: APScheduler-based scheduler for running skills on schedule
- Hot-reload support for config changes
- Integration with SkillExecutor for task execution
- Auto-retry with exponential backoff and remediation for failed jobs
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from croniter import croniter

if TYPE_CHECKING:
    from fastmcp import FastMCP

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
    def from_config(cls, job_config: dict, default_config: dict | None = None) -> "RetryConfig":
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
from server.config_manager import CONFIG_FILE  # noqa: E402
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
        return [j for j in self.jobs if j.get("cron") and state_manager.is_job_enabled(j.get("name", ""))]

    def get_poll_jobs(self) -> list[dict]:
        """Get jobs that use poll triggers and are enabled."""
        return [j for j in self.jobs if j.get("trigger") == "poll" and state_manager.is_job_enabled(j.get("name", ""))]

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


class CronScheduler:
    """APScheduler-based cron scheduler for MCP server.

    Runs skills on schedule based on config.json configuration.
    """

    def __init__(
        self,
        server: "FastMCP | None" = None,
        notification_callback: Callable | None = None,
    ):
        """Initialize the scheduler.

        Args:
            server: FastMCP server instance for skill execution
            notification_callback: Async callback for sending notifications
        """
        self.server = server
        self.notification_callback = notification_callback
        self.config = SchedulerConfig()
        self.scheduler: AsyncIOScheduler | None = None
        self.execution_log = JobExecutionLog()
        self._running = False
        self._config_mtime: float | None = None

    def _create_scheduler(self) -> AsyncIOScheduler:
        """Create a new APScheduler instance."""
        return AsyncIOScheduler(
            timezone=self.config.timezone,
            job_defaults={
                "coalesce": True,  # Combine missed runs
                "max_instances": 1,  # Only one instance per job
                "misfire_grace_time": 300,  # 5 min grace for missed jobs
            },
        )

    def _log_to_file(self, message: str):
        """Write a log message to file for debugging."""
        try:
            log_file = Path.home() / ".config" / "aa-workflow" / "scheduler.log"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a") as f:
                f.write(f"{datetime.now().isoformat()} - {message}\n")
        except Exception:
            pass

    def _cleanup_skill_execution_state(self, skill_name: str, error: str):
        """Clean up stale skill execution state after timeout or crash.

        When a cron job times out or crashes, the skill_execution.json file
        may be left in "running" state. This method resets it to "failed"
        so the UI doesn't show a perpetually running skill.

        Args:
            skill_name: Name of the skill that failed
            error: Error message to record
        """
        try:
            execution_file = Path.home() / ".config" / "aa-workflow" / "skill_execution.json"
            if not execution_file.exists():
                return

            # Read current state to check if it's the same skill
            with open(execution_file) as f:
                current_state = json.load(f)

            # Only clean up if it's the same skill and still "running"
            if current_state.get("skillName") != skill_name:
                self._log_to_file(
                    f"Skill execution state is for different skill "
                    f"({current_state.get('skillName')}), not cleaning up"
                )
                return

            if current_state.get("status") != "running":
                self._log_to_file(f"Skill execution state is already {current_state.get('status')}, not cleaning up")
                return

            # Update state to failed
            current_state["status"] = "failed"
            current_state["endTime"] = datetime.now().isoformat()

            # Add a timeout event to the events list
            if "events" not in current_state:
                current_state["events"] = []
            current_state["events"].append(
                {
                    "type": "skill_timeout",
                    "timestamp": datetime.now().isoformat(),
                    "skillName": skill_name,
                    "workspaceUri": current_state.get("workspaceUri", "default"),
                    "stepIndex": current_state.get("currentStepIndex"),
                    "stepName": None,
                    "data": {"error": error},
                }
            )

            # Write atomically
            tmp_file = execution_file.with_suffix(".tmp")
            with open(tmp_file, "w") as f:
                json.dump(current_state, f, indent=2)
            tmp_file.rename(execution_file)

            self._log_to_file(f"Cleaned up stale skill execution state for {skill_name}")
            logger.info(f"Cleaned up stale skill execution state for {skill_name}")

        except Exception as e:
            self._log_to_file(f"Failed to cleanup skill execution state: {e}")
            logger.warning(f"Failed to cleanup skill execution state: {e}")

    async def start(self, add_cron_jobs: bool = True):
        """Start the scheduler.

        The scheduler always starts to enable config watching.
        Jobs are only added if the scheduler is enabled in config AND add_cron_jobs=True.

        Args:
            add_cron_jobs: If False, skip adding cron jobs (useful when cron daemon handles them).
                          Default True for backward compatibility with cron_daemon.py.
        """
        self._log_to_file(f"start() called, _running={self._running}, add_cron_jobs={add_cron_jobs}")

        if self._running:
            logger.warning("Scheduler already running")
            self._log_to_file("Scheduler already running, returning")
            return

        self.scheduler = self._create_scheduler()
        self._log_to_file(f"Created scheduler, config.enabled={self.config.enabled}")

        # Add config watcher job (runs every 30 seconds, always active)
        self.scheduler.add_job(
            self._check_config_and_reload,
            "interval",
            seconds=30,
            id="_config_watcher",
            name="Config Watcher",
            replace_existing=True,
        )
        self._log_to_file("Added config watcher job")

        # Only add cron jobs if scheduler is enabled AND add_cron_jobs is True
        # The MCP server should pass add_cron_jobs=False since cron_daemon handles cron jobs
        if self.config.enabled and add_cron_jobs:
            cron_jobs = self.config.get_cron_jobs()
            self._log_to_file(f"Adding {len(cron_jobs)} cron jobs: {[j.get('name') for j in cron_jobs]}")
            for job in cron_jobs:
                self._add_cron_job(job)
            logger.info(f"Scheduler started with {len(cron_jobs)} cron jobs")
        elif self.config.enabled and not add_cron_jobs:
            logger.info("Scheduler started (cron jobs handled by cron_daemon)")
            self._log_to_file("Scheduler started, cron jobs skipped (handled by cron_daemon)")
        else:
            logger.info("Scheduler started (disabled in config, watching for changes)")
            self._log_to_file("Scheduler disabled in config")

        # Start the scheduler
        self.scheduler.start()
        self._running = True
        self._config_mtime = CONFIG_FILE.stat().st_mtime if CONFIG_FILE.exists() else None
        self._log_to_file(f"Scheduler started, _running={self._running}")

    async def stop(self):
        """Stop the scheduler gracefully."""
        if not self._running or not self.scheduler:
            return

        self.scheduler.shutdown(wait=True)
        self._running = False
        logger.info("Scheduler stopped")

    def _add_cron_job(self, job_config: dict):
        """Add a cron job to the scheduler."""
        if not self.scheduler:
            return

        job_name = job_config.get("name", "unnamed")
        skill = job_config.get("skill", "")
        cron_expr = job_config.get("cron", "")
        inputs = job_config.get("inputs", {})
        notify = job_config.get("notify", [])
        persona = job_config.get("persona", "")  # Optional persona to load
        # Timeout in seconds - default 600 (10 min), can be increased for batch jobs
        timeout_seconds = job_config.get("timeout_seconds", 600)

        # Get retry configuration for this job
        retry_config = self.config.get_retry_config(job_config)

        if not skill or not cron_expr:
            logger.warning(f"Job {job_name} missing skill or cron expression")
            return

        try:
            # Parse cron expression into APScheduler trigger
            trigger = self._parse_cron_to_trigger(cron_expr)

            # Add the job
            self.scheduler.add_job(
                self._execute_job,
                trigger=trigger,
                id=job_name,
                name=job_name,
                kwargs={
                    "job_name": job_name,
                    "skill": skill,
                    "inputs": inputs,
                    "notify": notify,
                    "persona": persona,
                    "retry_config": retry_config,
                    "timeout_seconds": timeout_seconds,
                },
                replace_existing=True,
            )

            persona_info = f" (persona: {persona})" if persona else ""
            retry_info = f", retry: {retry_config.max_attempts}" if retry_config.enabled else ", retry: disabled"
            timeout_info = f", timeout: {timeout_seconds}s" if timeout_seconds != 600 else ""
            logger.info(
                f"Added cron job: {job_name} ({cron_expr}) -> skill:{skill}{persona_info}{retry_info}{timeout_info}"
            )

        except Exception as e:
            logger.error(f"Failed to add job {job_name}: {e}")

    def _parse_cron_to_trigger(self, cron_expr: str) -> CronTrigger:
        """Parse a cron expression into an APScheduler CronTrigger.

        Supports standard 5-field cron: minute hour day month day_of_week
        """
        parts = cron_expr.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {cron_expr} (expected 5 fields)")

        minute, hour, day, month, day_of_week = parts

        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone=self.config.timezone,
        )

    async def _execute_job(
        self,
        job_name: str,
        skill: str,
        inputs: dict,
        notify: list[str],
        persona: str = "",
        retry_config: RetryConfig | None = None,
        timeout_seconds: int = 600,
    ):
        """Execute a scheduled job with retry and auto-remediation support.

        Args:
            job_name: Name of the cron job
            skill: Skill to execute
            inputs: Input parameters for the skill
            notify: Notification channels
            persona: Optional persona to load
            retry_config: Retry configuration (defaults to global config)
            timeout_seconds: Maximum execution time in seconds (default 600 = 10 min)
        """
        import asyncio
        import shutil
        import time

        start_time = time.time()
        now = datetime.now()
        # Replace / with - in skill name to avoid invalid file paths
        safe_skill = skill.replace("/", "-")
        session_name = f"cron-{safe_skill}-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}"
        persona_info = f", persona: {persona}" if persona else ""
        logger.info(f"Executing scheduled job: {job_name} (skill: {skill}{persona_info}) in session: {session_name}")
        self._log_to_file(
            f"_execute_job called: job={job_name}, skill={skill}, persona={persona}, session={session_name}"
        )

        # Emit toast notification for job start
        try:
            from tool_modules.aa_workflow.src.notification_emitter import notify_cron_job_started

            notify_cron_job_started(job_name, skill)
        except Exception:
            pass

        # Use default retry config if not provided
        if retry_config is None:
            retry_config = RetryConfig()

        # Track retry information
        retry_info = {
            "attempts": 0,
            "retried": False,
            "failure_type": None,
            "remediation_applied": None,
            "remediation_success": None,
        }

        success = False
        error_msg = None
        output = None

        # Check execution mode from config
        use_claude_cli = self.config.execution_mode == "claude_cli"
        claude_path = shutil.which("claude") if use_claude_cli else None

        # Retry loop
        max_attempts = retry_config.max_attempts + 1 if retry_config.enabled else 1
        for attempt in range(max_attempts):
            retry_info["attempts"] = attempt + 1

            if attempt > 0:
                retry_info["retried"] = True
                # Calculate backoff delay
                delay = retry_config.calculate_delay(attempt - 1)
                logger.info(f"Job {job_name}: Retry attempt {attempt}/{retry_config.max_attempts} after {delay}s delay")
                self._log_to_file(f"Retry {attempt}/{retry_config.max_attempts} for {job_name}, waiting {delay}s")
                await asyncio.sleep(delay)

            # Execute the job
            if use_claude_cli and claude_path:
                self._log_to_file(f"Using Claude CLI at {claude_path} (attempt {attempt + 1})")
                success, output, error_msg = await self._run_with_claude_cli(
                    job_name=job_name,
                    skill=skill,
                    inputs=inputs,
                    session_name=f"{session_name}-attempt{attempt + 1}" if attempt > 0 else session_name,
                    persona=persona,
                    timeout_seconds=timeout_seconds,
                )
            else:
                if use_claude_cli and not claude_path:
                    self._log_to_file("Claude CLI not found, falling back to direct execution")
                else:
                    self._log_to_file(f"Using direct execution mode (attempt {attempt + 1})")
                try:
                    output = await self._run_skill(skill, inputs, job_name=job_name)
                    success = True
                    logger.info(f"Job {job_name} completed successfully (direct execution)")
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Job {job_name} failed: {e}")

            # If successful, break out of retry loop
            if success:
                if attempt > 0:
                    logger.info(f"Job {job_name} succeeded after {attempt + 1} attempts")
                break

            # Detect failure type for potential retry
            failure_type = self._detect_failure_type(error_msg or output or "")
            retry_info["failure_type"] = failure_type

            # Check if we should retry
            if not retry_config.should_retry(failure_type, attempt):
                logger.info(f"Job {job_name}: Not retrying (type={failure_type}, attempt={attempt})")
                break

            # Apply remediation before retry
            remediation_applied, remediation_success = await self._apply_remediation(failure_type, job_name)
            retry_info["remediation_applied"] = remediation_applied
            retry_info["remediation_success"] = remediation_success

            if not remediation_success:
                logger.warning(f"Job {job_name}: Remediation failed, but will still retry")

        duration_ms = int((time.time() - start_time) * 1000)
        duration_seconds = duration_ms / 1000.0

        # Emit toast notification for job completion
        try:
            if success:
                from tool_modules.aa_workflow.src.notification_emitter import notify_cron_job_completed

                notify_cron_job_completed(job_name, skill, duration_seconds)
            else:
                from tool_modules.aa_workflow.src.notification_emitter import notify_cron_job_failed

                notify_cron_job_failed(job_name, skill, error_msg or "Unknown error")
        except Exception:
            pass

        # Log execution with retry info
        self.execution_log.log_execution(
            job_name=job_name,
            skill=skill,
            success=success,
            duration_ms=duration_ms,
            error=error_msg,
            output_preview=output,
            session_name=session_name,
            retry_info=retry_info if retry_info["attempts"] > 1 or retry_info["failure_type"] else None,
        )

        # Send notifications
        if notify and self.notification_callback:
            await self._send_notifications(
                job_name=job_name,
                skill=skill,
                success=success,
                output=output,
                error=error_msg,
                notify_channels=notify,
            )

    def _detect_failure_type(self, error_text: str) -> str:
        """Detect the type of failure from error text.

        Args:
            error_text: Error message or output to analyze

        Returns:
            Failure type: "auth", "network", "timeout", or "unknown"
        """
        if not error_text:
            return "unknown"

        error_lower = error_text.lower()

        # Auth patterns
        auth_patterns = [
            "unauthorized",
            "401",
            "forbidden",
            "403",
            "token expired",
            "authentication required",
            "not authorized",
            "permission denied",
            "credentials",
        ]
        if any(p in error_lower for p in auth_patterns):
            return "auth"

        # Network patterns
        network_patterns = [
            "no route to host",
            "connection refused",
            "network unreachable",
            "timeout",
            "dial tcp",
            "connection reset",
            "eof",
            "cannot connect",
            "httpsconnectionpool",
        ]
        if any(p in error_lower for p in network_patterns):
            return "network"

        # Timeout patterns
        timeout_patterns = [
            "timed out",
            "deadline exceeded",
            "context deadline",
        ]
        if any(p in error_lower for p in timeout_patterns):
            return "timeout"

        return "unknown"

    async def _apply_remediation(self, failure_type: str, job_name: str) -> tuple[str | None, bool]:
        """Apply remediation based on failure type before retry.

        Args:
            failure_type: Type of failure (auth, network, timeout)
            job_name: Name of the job for logging

        Returns:
            Tuple of (remediation_applied, success)
        """

        if failure_type == "auth":
            logger.info(f"Job {job_name}: Applying auth remediation (kube_login)")
            self._log_to_file(f"Applying kube_login remediation for {job_name}")
            success = await self._run_kube_login()
            return "kube_login", success

        elif failure_type == "network":
            logger.info(f"Job {job_name}: Applying network remediation (vpn_connect)")
            self._log_to_file(f"Applying vpn_connect remediation for {job_name}")
            success = await self._run_vpn_connect()
            return "vpn_connect", success

        elif failure_type == "timeout":
            # For timeouts, just wait a bit longer (no specific fix)
            logger.info(f"Job {job_name}: Timeout detected, will retry with delay")
            return None, True

        return None, False

    async def _run_kube_login(self, cluster: str = "stage") -> bool:
        """Run kube_login to refresh credentials.

        Returns:
            True if successful
        """
        import asyncio

        try:
            # Map cluster names to short codes
            cluster_map = {
                "stage": "s",
                "production": "p",
                "prod": "p",
                "ephemeral": "e",
                "konflux": "k",
            }
            short = cluster_map.get(cluster, "s")

            # Run kube command to refresh credentials
            logger.info(f"Running kube {short} to refresh credentials")
            process = await asyncio.create_subprocess_exec(
                "kube",
                short,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
                output = (stdout.decode() if stdout else "") + (stderr.decode() if stderr else "")

                if process.returncode == 0 or "logged in" in output.lower():
                    logger.info(f"kube_login({cluster}) successful")
                    return True

                logger.warning(f"kube_login({cluster}) failed: {output[:200]}")
                return False

            except asyncio.TimeoutError:
                process.kill()
                logger.warning(f"kube_login({cluster}) timed out")
                return False

        except FileNotFoundError:
            logger.warning("kube command not found")
            return False
        except Exception as e:
            logger.warning(f"kube_login error: {e}")
            return False

    async def _run_vpn_connect(self) -> bool:
        """Run vpn_connect to establish VPN connection.

        Returns:
            True if successful
        """
        import asyncio
        import os

        try:
            # Try to find VPN connect script
            vpn_script = os.path.expanduser("~/src/redhatter/src/redhatter_vpn/vpn-connect")

            if not os.path.exists(vpn_script):
                logger.warning(f"VPN script not found: {vpn_script}")
                return False

            logger.info("Running vpn-connect")
            process = await asyncio.create_subprocess_exec(
                vpn_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
                output = (stdout.decode() if stdout else "") + (stderr.decode() if stderr else "")

                if process.returncode == 0 or "successfully activated" in output.lower():
                    logger.info("vpn_connect successful")
                    return True

                logger.warning(f"vpn_connect failed: {output[:200]}")
                return False

            except asyncio.TimeoutError:
                process.kill()
                logger.warning("vpn_connect timed out")
                return False

        except FileNotFoundError:
            logger.warning("VPN script not found")
            return False
        except Exception as e:
            logger.warning(f"vpn_connect error: {e}")
            return False

    async def _run_with_claude_cli(
        self,
        job_name: str,
        skill: str,
        inputs: dict,
        session_name: str,
        persona: str = "",
        timeout_seconds: int = 600,
    ) -> tuple[bool, str | None, str | None]:
        """Run a skill using Claude CLI for AI-powered execution.

        Args:
            job_name: Name of the cron job
            skill: Skill name to execute
            inputs: Input parameters for the skill
            session_name: Session name for logging
            persona: Optional persona to load before executing
            timeout_seconds: Maximum execution time in seconds (default 600 = 10 min)

        Returns:
            Tuple of (success, output, error_message)
        """
        import asyncio

        # Build the prompt for Claude
        inputs_str = json.dumps(inputs) if inputs else "{}"

        # Include persona loading instruction if specified
        persona_instruction = ""
        if persona:
            persona_instruction = f"""
First, load the appropriate persona:
- Call agent_load("{persona}") to load the {persona} persona with its tools and skills

Then proceed with the skill execution.
"""

        prompt = f"""You are running a scheduled cron job. Execute the following skill and report the results.

Job: {job_name}
Skill: {skill}
Inputs: {inputs_str}
Session: {session_name}
Persona: {persona if persona else "default"}

Instructions:
{persona_instruction}1. Call skill_run("{skill}", inputs='{inputs_str}')
2. If the skill fails, try to diagnose and fix the issue
3. Log the result to memory using memory_session_log()
4. Summarize what happened

Begin execution now."""

        # Create output log file
        log_dir = Path.home() / ".config" / "aa-workflow" / "cron_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{session_name}.log"

        timeout_minutes = timeout_seconds // 60
        self._log_to_file(f"Running Claude CLI, output to {log_file}, timeout={timeout_seconds}s")

        try:
            # Run Claude CLI with --print flag for non-interactive mode
            # Use the project directory as working directory
            process = await asyncio.create_subprocess_exec(
                "claude",
                "--print",  # Non-interactive, just print output
                "--dangerously-skip-permissions",  # Skip permission prompts for automation
                prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(Path.home() / "src" / "redhat-ai-workflow"),
            )

            # Wait for completion with configurable timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout_seconds,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                # Clean up stale skill execution state so UI doesn't show "running" forever
                timeout_msg = f"Claude CLI timed out after {timeout_minutes} minutes"
                self._cleanup_skill_execution_state(skill, timeout_msg)
                return False, None, timeout_msg

            # Decode output
            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            error_output = stderr.decode("utf-8", errors="replace") if stderr else ""

            # Write to log file
            with open(log_file, "w") as f:
                f.write(f"=== Cron Job: {job_name} ===\n")
                f.write(f"Skill: {skill}\n")
                f.write(f"Session: {session_name}\n")
                f.write(f"Started: {datetime.now().isoformat()}\n")
                f.write(f"Exit Code: {process.returncode}\n")
                f.write(f"\n=== STDOUT ===\n{output}\n")
                if error_output:
                    f.write(f"\n=== STDERR ===\n{error_output}\n")

            self._log_to_file(f"Claude CLI completed with exit code {process.returncode}")

            if process.returncode == 0:
                # Truncate output for preview
                preview = output[:500] if len(output) > 500 else output
                return True, preview, None
            else:
                error_msg = error_output or f"Claude CLI exited with code {process.returncode}"
                return False, output[:200] if output else None, error_msg

        except FileNotFoundError:
            self._cleanup_skill_execution_state(skill, "Claude CLI not found in PATH")
            return False, None, "Claude CLI not found in PATH"
        except Exception as e:
            self._log_to_file(f"Claude CLI error: {e}")
            self._cleanup_skill_execution_state(skill, str(e))
            return False, None, str(e)

    async def _run_skill(self, skill_name: str, inputs: dict, job_name: str | None = None) -> str:
        """Run a skill and return its output.

        Args:
            skill_name: Name of the skill to run.
            inputs: Input parameters for the skill.
            job_name: Name of the cron job (for source tracking).
        """
        import yaml

        from .skill_engine import SkillExecutor

        skill_file = SKILLS_DIR / f"{skill_name}.yaml"
        if not skill_file.exists():
            raise FileNotFoundError(f"Skill not found: {skill_name}")

        with open(skill_file) as f:
            skill = yaml.safe_load(f)

        executor = SkillExecutor(
            skill=skill,
            inputs=inputs,
            debug=False,
            server=self.server,
            enable_interactive_recovery=False,  # No interactive recovery for scheduled jobs
            emit_events=True,  # Enable VS Code events for running skills viewer
            workspace_uri="cron",
            source="cron",
            source_details=job_name or skill_name,
        )

        result = await executor.execute()
        return result

    async def _send_notifications(
        self,
        job_name: str,
        skill: str,
        success: bool,
        output: str | None,
        error: str | None,
        notify_channels: list[str],
    ):
        """Send notifications for job completion."""
        if not self.notification_callback:
            return

        try:
            await self.notification_callback(
                job_name=job_name,
                skill=skill,
                success=success,
                output=output,
                error=error,
                channels=notify_channels,
            )
        except Exception as e:
            logger.error(f"Failed to send notifications for {job_name}: {e}")

    def reload_config(self):
        """Reload configuration and update jobs."""
        if not self.scheduler:
            return

        self.config = SchedulerConfig()

        # Remove jobs that no longer exist (but keep internal jobs like _config_watcher)
        current_job_ids = {j.id for j in self.scheduler.get_jobs()}
        new_job_names = {j.get("name") for j in self.config.get_cron_jobs()}

        for job_id in current_job_ids:
            # Skip internal jobs (prefixed with _)
            if job_id.startswith("_"):
                continue
            if job_id not in new_job_names:
                self.scheduler.remove_job(job_id)
                logger.info(f"Removed job: {job_id}")

        # Add/update jobs (replace_existing=True in _add_cron_job handles updates)
        for job in self.config.get_cron_jobs():
            self._add_cron_job(job)

        logger.info("Scheduler config reloaded")

    def check_config_changed(self) -> bool:
        """Check if config file has changed since last load."""
        if not CONFIG_FILE.exists():
            return False

        current_mtime = CONFIG_FILE.stat().st_mtime
        if self._config_mtime is None:
            self._config_mtime = current_mtime
            return False

        return current_mtime > self._config_mtime

    async def _check_config_and_reload(self):
        """Periodically check for config changes and reload if needed.

        This method is called by the config watcher job every 30 seconds.
        It handles:
        - Reloading job configurations when they change
        - Stopping the scheduler if it's been disabled in config
        """
        if not self.check_config_changed():
            return

        logger.info("Config file changed, checking for updates...")
        self._config_mtime = CONFIG_FILE.stat().st_mtime if CONFIG_FILE.exists() else None

        # Reload config
        old_enabled = self.config.enabled
        self.config = SchedulerConfig()

        # Check if scheduler was disabled
        if old_enabled and not self.config.enabled:
            logger.info("Scheduler disabled in config, stopping...")
            # Remove all jobs except the config watcher
            if self.scheduler:
                for job in self.scheduler.get_jobs():
                    if job.id != "_config_watcher":
                        self.scheduler.remove_job(job.id)
            logger.info("Scheduler jobs paused (config watcher still running)")
            return

        # Check if scheduler was enabled
        if not old_enabled and self.config.enabled:
            logger.info("Scheduler enabled in config, starting jobs...")

        # Reload jobs
        self.reload_config()

    async def run_job_now(self, job_name: str) -> dict:
        """Manually trigger a job to run immediately.

        Args:
            job_name: Name of the job to run

        Returns:
            Dict with success status and result/error
        """
        # Find the job config
        job_config = None
        for job in self.config.jobs:
            if job.get("name") == job_name:
                job_config = job
                break

        if not job_config:
            return {"success": False, "error": f"Job not found: {job_name}"}

        skill = job_config.get("skill", "")
        inputs = job_config.get("inputs", {})
        notify = job_config.get("notify", [])
        persona = job_config.get("persona", "")
        retry_config = self.config.get_retry_config(job_config)

        try:
            await self._execute_job(
                job_name=job_name,
                skill=skill,
                inputs=inputs,
                notify=notify,
                persona=persona,
                retry_config=retry_config,
            )
            return {"success": True, "message": f"Job {job_name} executed"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_job_info(self, job_name: str) -> dict | None:
        """Get information about a specific job."""
        if not self.scheduler:
            return None

        job = self.scheduler.get_job(job_name)
        if not job:
            return None

        # Find config
        job_config = None
        for j in self.config.jobs:
            if j.get("name") == job_name:
                job_config = j
                break

        next_run = job.next_run_time.isoformat() if job.next_run_time else None

        # Get retry config
        retry_config = self.config.get_retry_config(job_config) if job_config else None
        retry_info = None
        if retry_config:
            retry_info = {
                "enabled": retry_config.enabled,
                "max_attempts": retry_config.max_attempts,
                "backoff": retry_config.backoff,
                "retry_on": retry_config.retry_on,
            }

        return {
            "name": job_name,
            "skill": job_config.get("skill") if job_config else "unknown",
            "cron": job_config.get("cron") if job_config else "unknown",
            "next_run": next_run,
            "enabled": job_config.get("enabled", True) if job_config else False,
            "notify": job_config.get("notify", []) if job_config else [],
            "retry": retry_info,
            "recent_executions": self.execution_log.get_for_job(job_name),
        }

    def get_all_jobs(self) -> list[dict]:
        """Get information about all configured jobs."""
        jobs = []

        for job_config in self.config.jobs:
            job_name = job_config.get("name", "unnamed")
            job_info = {
                "name": job_name,
                "skill": job_config.get("skill", ""),
                "enabled": job_config.get("enabled", True),
                "notify": job_config.get("notify", []),
            }

            # Add cron-specific info
            if job_config.get("cron"):
                job_info["type"] = "cron"
                job_info["cron"] = job_config.get("cron")

                # Calculate next run time
                try:
                    cron = croniter(job_config["cron"], datetime.now())
                    job_info["next_run"] = cron.get_next(datetime).isoformat()
                except Exception:
                    job_info["next_run"] = None

            # Add poll-specific info
            elif job_config.get("trigger") == "poll":
                job_info["type"] = "poll"
                job_info["poll_interval"] = job_config.get("poll_interval", "1h")
                job_info["condition"] = job_config.get("condition", "")

            jobs.append(job_info)

        return jobs

    def get_status(self) -> dict:
        """Get scheduler status."""
        return {
            "enabled": self.config.enabled,
            "running": self._running,
            "timezone": self.config.timezone,
            "total_jobs": len(self.config.jobs),
            "cron_jobs": len(self.config.get_cron_jobs()),
            "poll_jobs": len(self.config.get_poll_jobs()),
            "recent_executions": self.execution_log.get_recent(10),
        }

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running


# Global scheduler instance
_scheduler: CronScheduler | None = None


def get_scheduler() -> CronScheduler | None:
    """Get the global scheduler instance."""
    return _scheduler


def init_scheduler(
    server: "FastMCP | None" = None,
    notification_callback: Callable | None = None,
) -> CronScheduler:
    """Initialize the global scheduler instance.

    This is a singleton - if a scheduler already exists, it returns the existing
    instance instead of creating a new one. This prevents duplicate job execution
    when multiple MCP server instances start (e.g., multiple Cursor windows).
    """
    global _scheduler

    # Singleton guard - return existing instance if already initialized
    if _scheduler is not None:
        logger.warning(
            "Scheduler already initialized, returning existing instance. "
            "This prevents duplicate job execution from multiple MCP connections."
        )
        return _scheduler

    _scheduler = CronScheduler(server=server, notification_callback=notification_callback)
    return _scheduler


async def start_scheduler(add_cron_jobs: bool = True):
    """Start the global scheduler.

    Args:
        add_cron_jobs: If False, skip adding cron jobs (cron_daemon handles them).
    """
    if _scheduler:
        await _scheduler.start(add_cron_jobs=add_cron_jobs)


async def stop_scheduler():
    """Stop the global scheduler."""
    if _scheduler:
        await _scheduler.stop()
