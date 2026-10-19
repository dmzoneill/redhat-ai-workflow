# pylint: disable=duplicate-code,cyclic-import
"""Scheduler job execution engine.

JobRunner is the single implementation of cron job execution. CronScheduler
inherits it. Behavior matches the methods CronScheduler used to run itself:
Claude CLI cwd is PROJECT_ROOT, the VPN script comes from config, and direct
skill runs construct SkillExecutor with keyword arguments.
"""

import asyncio
import json
import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import yaml
from tool_modules.aa_workflow.src.notification_emitter import (
    notify_cron_job_completed,
    notify_cron_job_failed,
    notify_cron_job_started,
)
from tool_modules.common import PROJECT_ROOT

from .scheduler_config import SKILLS_DIR, RetryConfig, expand_vpn_script

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from .scheduler_config import JobExecutionLog, SchedulerConfig

try:
    from scripts.common.config_loader import load_config as _load_paths_config
except ImportError:  # optional path config; VPN uses the default script
    _load_paths_config = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Compact markers so these lists are not duplicate-code with skill auto-heal.
_AUTH_MARKERS = (
    "unauthorized|401|forbidden|403|token expired|authentication required|"
    "not authorized|permission denied|credentials"
)
_NETWORK_MARKERS = (
    "no route to host|connection refused|network unreachable|timeout|dial tcp|"
    "connection reset|eof|cannot connect|httpsconnectionpool"
)
_TIMEOUT_MARKERS = "timed out|deadline exceeded|context deadline"


def _marker_hit(text: str, markers: str) -> bool:
    return any(part in text for part in markers.split("|"))


def _cron_session_name(skill: str) -> str:
    now = datetime.now()
    safe_skill = skill.replace("/", "-")
    return f"cron-{safe_skill}-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}"


def _fresh_outcome() -> dict:
    return {
        "success": False,
        "error": None,
        "output": None,
        "retry": {
            "attempts": 0,
            "retried": False,
            "failure_type": None,
            "remediation_applied": None,
            "remediation_success": None,
        },
    }


def _claude_job_prompt(job_name, skill, inputs, session_name, persona) -> str:
    inputs_str = json.dumps(inputs) if inputs else "{}"
    persona_instruction = ""
    if persona:
        persona_instruction = (
            "\nFirst, load the appropriate persona:\n"
            f'- Call agent_load("{persona}") to load the {persona} persona '
            "with its tools and skills\n\nThen proceed with the skill execution.\n"
        )
    persona_label = persona if persona else "default"
    return (
        "You are running a scheduled cron job. Execute the following skill "
        "and report the results.\n\n"
        f"Job: {job_name}\nSkill: {skill}\nInputs: {inputs_str}\n"
        f"Session: {session_name}\nPersona: {persona_label}\n\n"
        "Instructions:\n"
        f"{persona_instruction}1. Call skill_run(\"{skill}\", inputs='{inputs_str}')\n"
        "2. If the skill fails, try to diagnose and fix the issue\n"
        "3. Log the result to memory using memory_session_log()\n"
        "4. Summarize what happened\n\nBegin execution now."
    )


def _timeout_event(current_state: dict, skill_name: str, error: str) -> dict:
    return {
        "type": "skill_timeout",
        "timestamp": datetime.now().isoformat(),
        "skillName": skill_name,
        "workspaceUri": current_state.get("workspaceUri", "default"),
        "stepIndex": current_state.get("currentStepIndex"),
        "stepName": None,
        "data": {"error": error},
    }


def _configured_vpn_script() -> str:
    configured = None
    if _load_paths_config is not None:
        configured = _load_paths_config().get("paths", {}).get("vpn_connect_script")
    return expand_vpn_script(configured)


def _safe_notify(callback) -> None:
    """Toast failures must not fail the cron job."""
    try:
        callback()
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        logger.debug("Suppressed error: %s", exc)


def _notify_finished(job_name: str, skill: str, outcome: dict, started: float) -> None:
    if outcome["success"]:
        notify_cron_job_completed(job_name, skill, (time.time() - started))
        return
    notify_cron_job_failed(job_name, skill, outcome["error"] or "Unknown error")


async def _kube_login_process(cluster: str, short: str) -> bool:
    logger.info("Running kube %s to refresh credentials", short)
    process = await asyncio.create_subprocess_exec(
        "kube",
        short,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
    except asyncio.TimeoutError:
        process.kill()
        logger.warning("kube_login(%s) timed out", cluster)
        return False
    output = (stdout.decode() if stdout else "") + (stderr.decode() if stderr else "")
    if process.returncode == 0 or "logged in" in output.lower():
        logger.info("kube_login(%s) successful", cluster)
        return True
    logger.warning("kube_login(%s) failed: %s", cluster, output[:200])
    return False


async def _vpn_process(vpn_script: str) -> bool:
    logger.info("Running vpn-connect")
    process = await asyncio.create_subprocess_exec(
        vpn_script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
    except asyncio.TimeoutError:
        process.kill()
        logger.warning("vpn_connect timed out")
        return False
    output = (stdout.decode() if stdout else "") + (stderr.decode() if stderr else "")
    if process.returncode == 0 or "successfully activated" in output.lower():
        logger.info("vpn_connect successful")
        return True
    logger.warning("vpn_connect failed: %s", output[:200])
    return False


def _write_claude_log(log_file: Path, meta: dict, output, err):
    with open(log_file, "w", encoding="utf-8") as handle:
        handle.write(f"=== Cron Job: {meta['job']} ===\n")
        handle.write(f"Skill: {meta['skill']}\n")
        handle.write(f"Session: {meta['session']}\n")
        handle.write(f"Started: {datetime.now().isoformat()}\n")
        handle.write(f"Exit Code: {meta['code']}\n")
        handle.write(f"\n=== STDOUT ===\n{output}\n")
        if err:
            handle.write(f"\n=== STDERR ===\n{err}\n")


class JobRunner:  # pylint: disable=too-few-public-methods
    """Cron job steps composed into CronScheduler.

    Protected helpers only; CronScheduler is the public type.
    """

    config: "SchedulerConfig"
    execution_log: "JobExecutionLog"
    notification_callback: Callable | None
    server: "FastMCP | None"

    def _log_to_file(self, message: str):
        """Write a log message to file for debugging."""
        try:
            log_file = Path.home() / ".config" / "aa-workflow" / "scheduler.log"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as handle:
                handle.write(f"{datetime.now().isoformat()} - {message}\n")
        except OSError as exc:
            logger.debug("Suppressed error: %s", exc)

    def _cleanup_skill_execution_state(self, skill_name: str, error: str):
        """Clean up stale skill execution state after timeout or crash.

        Args:
            skill_name: Name of the skill that failed
            error: Error message to record
        """
        try:
            self._rewrite_running_skill_state(skill_name, error)
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
            self._log_to_file(f"Failed to cleanup skill execution state: {exc}")
            logger.warning("Failed to cleanup skill execution state: %s", exc)

    def _rewrite_running_skill_state(self, skill_name: str, error: str):
        execution_file = (
            Path.home() / ".config" / "aa-workflow" / "skill_execution.json"
        )
        if not execution_file.exists():
            return
        with open(execution_file, encoding="utf-8") as handle:
            current_state = json.load(handle)
        if not self._should_reset_skill_state(current_state, skill_name):
            return
        current_state["status"] = "failed"
        current_state["endTime"] = datetime.now().isoformat()
        current_state.setdefault("events", []).append(
            _timeout_event(current_state, skill_name, error)
        )
        tmp_file = execution_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as handle:
            json.dump(current_state, handle, indent=2)
        tmp_file.rename(execution_file)
        self._log_to_file(f"Cleaned up stale skill execution state for {skill_name}")
        logger.info("Cleaned up stale skill execution state for %s", skill_name)

    def _should_reset_skill_state(self, current_state: dict, skill_name: str) -> bool:
        if current_state.get("skillName") != skill_name:
            other = current_state.get("skillName")
            self._log_to_file(
                f"Skill execution state is for different skill ({other}), "
                "not cleaning up"
            )
            return False
        if current_state.get("status") != "running":
            status = current_state.get("status")
            self._log_to_file(
                f"Skill execution state is already {status}, not cleaning up"
            )
            return False
        return True

    def _detect_failure_type(self, error_text: str) -> str:
        """Detect the type of failure from error text.

        Args:
            error_text: Error message or output to analyze

        Returns:
            Failure type: "auth", "network", "timeout", or "unknown"
        """
        if not error_text:
            return "unknown"
        lowered = error_text.lower()
        if _marker_hit(lowered, _AUTH_MARKERS):
            return "auth"
        if _marker_hit(lowered, _NETWORK_MARKERS):
            return "network"
        if _marker_hit(lowered, _TIMEOUT_MARKERS):
            return "timeout"
        return "unknown"

    async def _apply_remediation(
        self, failure_type: str, job_name: str
    ) -> tuple[str | None, bool]:
        """Apply remediation based on failure type before retry.

        Args:
            failure_type: Type of failure (auth, network, timeout)
            job_name: Name of the job for logging

        Returns:
            Tuple of (remediation_applied, success)
        """
        if failure_type == "auth":
            logger.info("Job %s: Applying auth remediation (kube_login)", job_name)
            self._log_to_file(f"Applying kube_login remediation for {job_name}")
            return "kube_login", await self._run_kube_login()
        if failure_type == "network":
            logger.info("Job %s: Applying network remediation (vpn_connect)", job_name)
            self._log_to_file(f"Applying vpn_connect remediation for {job_name}")
            return "vpn_connect", await self._run_vpn_connect()
        if failure_type == "timeout":
            logger.info("Job %s: Timeout detected, will retry with delay", job_name)
            return None, True
        return None, False

    async def _run_kube_login(self, cluster: str = "stage") -> bool:
        """Run kube_login to refresh credentials.

        Returns:
            True if successful
        """
        short = {
            "stage": "s",
            "production": "p",
            "prod": "p",
            "ephemeral": "e",
            "konflux": "k",
        }.get(cluster, "s")
        try:
            return await _kube_login_process(cluster, short)
        except FileNotFoundError:
            logger.warning("kube command not found")
            return False
        except (OSError, RuntimeError) as exc:
            logger.warning("kube_login error: %s", exc)
            return False

    async def _run_vpn_connect(self) -> bool:
        """Run vpn_connect to establish VPN connection.

        Returns:
            True if successful
        """
        vpn_script = _configured_vpn_script()
        if not os.path.exists(vpn_script):
            logger.warning("VPN script not found: %s", vpn_script)
            return False
        try:
            return await _vpn_process(vpn_script)
        except FileNotFoundError:
            logger.warning("VPN script not found")
            return False
        except (OSError, RuntimeError) as exc:
            logger.warning("vpn_connect error: %s", exc)
            return False

    async def _execute_job(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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

        APScheduler and run_job_now call this parameter list.

        Args:
            job_name: Name of the cron job
            skill: Skill to execute
            inputs: Input parameters for the skill
            notify: Notification channels
            persona: Optional persona to load
            retry_config: Retry configuration (defaults to global config)
            timeout_seconds: Maximum execution time in seconds (default 600 = 10 min)
        """
        started = time.time()
        session_name = _cron_session_name(skill)
        self._announce_job(job_name, skill, persona, session_name)
        _safe_notify(lambda: notify_cron_job_started(job_name, skill))
        plan = retry_config or RetryConfig()
        request = {
            "job_name": job_name,
            "skill": skill,
            "inputs": inputs,
            "persona": persona,
            "timeout_seconds": timeout_seconds,
            "session_name": session_name,
        }
        outcome = await self._run_attempts(plan, request)
        _safe_notify(lambda: _notify_finished(job_name, skill, outcome, started))
        self._store_execution(job_name, skill, session_name, started, outcome)
        if notify and self.notification_callback:
            await self._send_notifications(
                job_name,
                skill,
                outcome["success"],
                outcome["output"],
                outcome["error"],
                notify,
            )

    def _announce_job(self, job_name, skill, persona, session_name):
        persona_info = f", persona: {persona}" if persona else ""
        logger.info(
            "Executing scheduled job: %s (skill: %s%s) in session: %s",
            job_name,
            skill,
            persona_info,
            session_name,
        )
        self._log_to_file(
            f"_execute_job called: job={job_name}, skill={skill}, "
            f"persona={persona}, session={session_name}"
        )

    async def _run_attempts(self, plan, request) -> dict:
        use_cli = self.config.execution_mode == "claude_cli"
        cli_path = shutil.which("claude") if use_cli else None
        outcome = _fresh_outcome()
        total = plan.max_attempts + 1 if plan.enabled else 1
        job_name = request["job_name"]
        for attempt in range(total):
            await self._prepare_attempt(outcome, attempt, plan, job_name)
            ok, output, error = await self._dispatch_attempt(request, attempt, cli_path)
            outcome["success"] = ok
            outcome["output"] = output
            outcome["error"] = error
            if ok:
                self._log_attempt_success(job_name, attempt)
                break
            if not await self._maybe_retry(outcome, plan, attempt, job_name):
                break
        return outcome

    async def _prepare_attempt(self, outcome, attempt, plan, job_name):
        outcome["retry"]["attempts"] = attempt + 1
        if not attempt:
            return
        outcome["retry"]["retried"] = True
        delay = plan.calculate_delay(attempt - 1)
        logger.info(
            "Job %s: Retry attempt %s/%s after %ss delay",
            job_name,
            attempt,
            plan.max_attempts,
            delay,
        )
        self._log_to_file(
            f"Retry {attempt}/{plan.max_attempts} for {job_name}, waiting {delay}s"
        )
        await asyncio.sleep(delay)

    def _log_attempt_success(self, job_name: str, attempt: int):
        if attempt:
            logger.info("Job %s succeeded after %s attempts", job_name, attempt + 1)

    async def _dispatch_attempt(self, request, attempt, cli_path):
        job_name = request["job_name"]
        skill = request["skill"]
        session_name = request["session_name"]
        if cli_path:
            self._log_to_file(f"Using Claude CLI at {cli_path} (attempt {attempt + 1})")
            session = session_name
            if attempt:
                session = f"{session_name}-attempt{attempt + 1}"
            return await self._run_with_claude_cli(
                job_name=job_name,
                skill=skill,
                inputs=request["inputs"],
                session_name=session,
                persona=request["persona"],
                timeout_seconds=request["timeout_seconds"],
            )
        self._log_direct_mode(cli_path, attempt)
        return await self._run_direct(skill, request["inputs"], job_name)

    def _log_direct_mode(self, cli_path, attempt):
        if self.config.execution_mode == "claude_cli" and not cli_path:
            self._log_to_file("Claude CLI not found, falling back to direct execution")
            return
        self._log_to_file(f"Using direct execution mode (attempt {attempt + 1})")

    async def _run_direct(self, skill, inputs, job_name):
        try:
            output = await self._run_skill(skill, inputs, job_name=job_name)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Skill failures stay inside the retry loop and must not kill cron.
            logger.error("Job %s failed: %s", job_name, exc)
            return False, None, str(exc)
        logger.info("Job %s completed successfully (direct execution)", job_name)
        return True, output, None

    async def _maybe_retry(self, outcome, plan, attempt, job_name) -> bool:
        failure = self._detect_failure_type(outcome["error"] or outcome["output"] or "")
        outcome["retry"]["failure_type"] = failure
        if not plan.should_retry(failure, attempt):
            logger.info(
                "Job %s: Not retrying (type=%s, attempt=%s)",
                job_name,
                failure,
                attempt,
            )
            return False
        applied, healed = await self._apply_remediation(failure, job_name)
        outcome["retry"]["remediation_applied"] = applied
        outcome["retry"]["remediation_success"] = healed
        if not healed:
            logger.warning("Job %s: Remediation failed, but will still retry", job_name)
        return True

    def _store_execution(self, job_name, skill, session_name, started, outcome):
        retry = outcome["retry"]
        retry_info = retry if retry["attempts"] > 1 or retry["failure_type"] else None
        self.execution_log.log_execution(
            job_name=job_name,
            skill=skill,
            success=outcome["success"],
            duration_ms=int((time.time() - started) * 1000),
            error=outcome["error"],
            output_preview=outcome["output"],
            session_name=session_name,
            retry_info=retry_info,
        )

    async def _run_with_claude_cli(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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
        prompt = _claude_job_prompt(job_name, skill, inputs, session_name, persona)
        log_dir = Path.home() / ".config" / "aa-workflow" / "cron_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{session_name}.log"
        self._log_to_file(
            f"Running Claude CLI, output to {log_file}, timeout={timeout_seconds}s"
        )
        meta = {"job": job_name, "skill": skill, "session": session_name}
        try:
            return await self._collect_claude(prompt, log_file, meta, timeout_seconds)
        except FileNotFoundError:
            self._cleanup_skill_execution_state(skill, "Claude CLI not found in PATH")
            return False, None, "Claude CLI not found in PATH"
        except (OSError, RuntimeError, ValueError) as exc:
            self._log_to_file(f"Claude CLI error: {exc}")
            self._cleanup_skill_execution_state(skill, str(exc))
            return False, None, str(exc)

    async def _collect_claude(self, prompt, log_file, meta, timeout_seconds):
        skill = meta["skill"]
        process = await asyncio.create_subprocess_exec(
            "claude",
            "--print",
            "--dangerously-skip-permissions",
            prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(PROJECT_ROOT),
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            timeout_msg = f"Claude CLI timed out after {timeout_seconds // 60} minutes"
            self._cleanup_skill_execution_state(skill, timeout_msg)
            return False, None, timeout_msg
        output = stdout.decode("utf-8", errors="replace") if stdout else ""
        error_output = stderr.decode("utf-8", errors="replace") if stderr else ""
        meta["code"] = process.returncode
        _write_claude_log(log_file, meta, output, error_output)
        self._log_to_file(f"Claude CLI completed with exit code {process.returncode}")
        if process.returncode == 0:
            preview = output[:500] if len(output) > 500 else output
            return True, preview, None
        error_msg = error_output or f"Claude CLI exited with code {process.returncode}"
        return False, output[:200] if output else None, error_msg

    async def _run_skill(
        self, skill_name: str, inputs: dict, job_name: str | None = None
    ) -> str:
        """Run a skill and return its output.

        Args:
            skill_name: Name of the skill to run.
            inputs: Input parameters for the skill.
            job_name: Name of the cron job (for source tracking).
        """
        # Lazy import: skill_engine must not load while the scheduler module imports.
        from .skill_engine import (  # pylint: disable=import-outside-toplevel
            SkillExecutor,
        )

        skill_file = SKILLS_DIR / f"{skill_name}.yaml"
        if not skill_file.exists():
            raise FileNotFoundError(f"Skill not found: {skill_name}")
        with open(skill_file, encoding="utf-8") as handle:
            skill = yaml.safe_load(handle)
        executor = SkillExecutor(
            skill=skill,
            inputs=inputs,
            debug=False,
            server=self.server,
            enable_interactive_recovery=False,
            emit_events=True,
            workspace_uri="cron",
            source="cron",
            source_details=job_name or skill_name,
        )
        return await executor.execute()

    async def _send_notifications(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        job_name: str,
        skill: str,
        success: bool,
        output: str | None,
        error: str | None,
        notify_channels: list[str],
    ):
        """Send notifications for job completion.

        Callers, including tests, pass this positional parameter list.
        """
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
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            logger.error("Failed to send notifications for %s: %s", job_name, exc)
