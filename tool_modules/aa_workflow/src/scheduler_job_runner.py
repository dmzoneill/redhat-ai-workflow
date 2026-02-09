"""Scheduler job execution engine.

Extracted from scheduler.py to reduce class size.

Provides:
- JobRunner: Mixin class with job execution logic including:
  - _execute_job(): Main job execution with retry loop
  - _run_with_claude_cli(): Execute via Claude CLI
  - _run_skill(): Direct skill execution
  - _send_notifications(): Notification dispatch
  - _detect_failure_type(): Classify errors for retry decisions
  - _apply_remediation(): Auto-fix auth/network failures before retry
  - _run_kube_login(): Refresh Kubernetes credentials
  - _run_vpn_connect(): Establish VPN connection
  - _cleanup_skill_execution_state(): Clean up stale UI state after timeout
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from .scheduler_config import JobExecutionLog, RetryConfig, SchedulerConfig

logger = logging.getLogger(__name__)


class JobRunner:
    """Mixin class providing job execution logic for CronScheduler.

    This class contains the job execution methods extracted from CronScheduler.
    It is designed to be used as a mixin - CronScheduler inherits from this class
    and provides the required attributes:
        - config: SchedulerConfig
        - execution_log: JobExecutionLog
        - notification_callback: Callable | None
        - server: FastMCP | None
    """

    # These attributes are provided by CronScheduler
    config: "SchedulerConfig"
    execution_log: "JobExecutionLog"
    notification_callback: Callable | None
    server: "FastMCP | None"

    def _log_to_file(self, message: str):
        """Write a log message to file for debugging."""
        try:
            log_file = Path.home() / ".config" / "aa-workflow" / "scheduler.log"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat()} - {message}\n")
        except Exception as exc:
            logger.debug("Suppressed error: %s", exc)

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
            execution_file = (
                Path.home() / ".config" / "aa-workflow" / "skill_execution.json"
            )
            if not execution_file.exists():
                return

            # Read current state to check if it's the same skill
            with open(execution_file, encoding="utf-8") as f:
                current_state = json.load(f)

            # Only clean up if it's the same skill and still "running"
            if current_state.get("skillName") != skill_name:
                self._log_to_file(
                    "Skill execution state is for different skill "
                    f"({current_state.get('skillName')}), not cleaning up"
                )
                return

            if current_state.get("status") != "running":
                self._log_to_file(
                    f"Skill execution state is already {current_state.get('status')}, not cleaning up"
                )
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
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(current_state, f, indent=2)
            tmp_file.rename(execution_file)

            self._log_to_file(
                f"Cleaned up stale skill execution state for {skill_name}"
            )
            logger.info(f"Cleaned up stale skill execution state for {skill_name}")

        except Exception as e:
            self._log_to_file(f"Failed to cleanup skill execution state: {e}")
            logger.warning(f"Failed to cleanup skill execution state: {e}")

    async def _execute_job(
        self,
        job_name: str,
        skill: str,
        inputs: dict,
        notify: list[str],
        persona: str = "",
        retry_config: "RetryConfig | None" = None,
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

        from .scheduler_config import RetryConfig

        start_time = time.time()
        now = datetime.now()
        # Replace / with - in skill name to avoid invalid file paths
        safe_skill = skill.replace("/", "-")
        session_name = (
            f"cron-{safe_skill}-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}"
        )
        persona_info = f", persona: {persona}" if persona else ""
        logger.info(
            f"Executing scheduled job: {job_name} (skill: {skill}{persona_info}) in session: {session_name}"
        )
        self._log_to_file(
            f"_execute_job called: job={job_name}, skill={skill}, persona={persona}, session={session_name}"
        )

        # Emit toast notification for job start
        try:
            from tool_modules.aa_workflow.src.notification_emitter import (
                notify_cron_job_started,
            )

            notify_cron_job_started(job_name, skill)
        except Exception as exc:
            logger.debug("Suppressed error: %s", exc)

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
                logger.info(
                    f"Job {job_name}: Retry attempt {attempt}/{retry_config.max_attempts} after {delay}s delay"
                )
                self._log_to_file(
                    f"Retry {attempt}/{retry_config.max_attempts} for {job_name}, waiting {delay}s"
                )
                await asyncio.sleep(delay)

            # Execute the job
            if use_claude_cli and claude_path:
                self._log_to_file(
                    f"Using Claude CLI at {claude_path} (attempt {attempt + 1})"
                )
                success, output, error_msg = await self._run_with_claude_cli(
                    job_name=job_name,
                    skill=skill,
                    inputs=inputs,
                    session_name=(
                        f"{session_name}-attempt{attempt + 1}"
                        if attempt > 0
                        else session_name
                    ),
                    persona=persona,
                    timeout_seconds=timeout_seconds,
                )
            else:
                if use_claude_cli and not claude_path:
                    self._log_to_file(
                        "Claude CLI not found, falling back to direct execution"
                    )
                else:
                    self._log_to_file(
                        f"Using direct execution mode (attempt {attempt + 1})"
                    )
                try:
                    output = await self._run_skill(skill, inputs, job_name=job_name)
                    success = True
                    logger.info(
                        f"Job {job_name} completed successfully (direct execution)"
                    )
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Job {job_name} failed: {e}")

            # If successful, break out of retry loop
            if success:
                if attempt > 0:
                    logger.info(
                        f"Job {job_name} succeeded after {attempt + 1} attempts"
                    )
                break

            # Detect failure type for potential retry
            failure_type = self._detect_failure_type(error_msg or output or "")
            retry_info["failure_type"] = failure_type

            # Check if we should retry
            if not retry_config.should_retry(failure_type, attempt):
                logger.info(
                    f"Job {job_name}: Not retrying (type={failure_type}, attempt={attempt})"
                )
                break

            # Apply remediation before retry
            remediation_applied, remediation_success = await self._apply_remediation(
                failure_type, job_name
            )
            retry_info["remediation_applied"] = remediation_applied
            retry_info["remediation_success"] = remediation_success

            if not remediation_success:
                logger.warning(
                    f"Job {job_name}: Remediation failed, but will still retry"
                )

        duration_ms = int((time.time() - start_time) * 1000)
        duration_seconds = duration_ms / 1000.0

        # Emit toast notification for job completion
        try:
            if success:
                from tool_modules.aa_workflow.src.notification_emitter import (
                    notify_cron_job_completed,
                )

                notify_cron_job_completed(job_name, skill, duration_seconds)
            else:
                from tool_modules.aa_workflow.src.notification_emitter import (
                    notify_cron_job_failed,
                )

                notify_cron_job_failed(job_name, skill, error_msg or "Unknown error")
        except Exception as exc:
            logger.debug("Suppressed error: %s", exc)

        # Log execution with retry info
        self.execution_log.log_execution(
            job_name=job_name,
            skill=skill,
            success=success,
            duration_ms=duration_ms,
            error=error_msg,
            output_preview=output,
            session_name=session_name,
            retry_info=(
                retry_info
                if retry_info["attempts"] > 1 or retry_info["failure_type"]
                else None
            ),
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
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=120
                )
                output = (stdout.decode() if stdout else "") + (
                    stderr.decode() if stderr else ""
                )

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
            vpn_script = os.path.expanduser(
                "~/src/redhatter/src/redhatter_vpn/vpn-connect"
            )

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
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=120
                )
                output = (stdout.decode() if stdout else "") + (
                    stderr.decode() if stderr else ""
                )

                if (
                    process.returncode == 0
                    or "successfully activated" in output.lower()
                ):
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
        self._log_to_file(
            f"Running Claude CLI, output to {log_file}, timeout={timeout_seconds}s"
        )

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
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"=== Cron Job: {job_name} ===\n")
                f.write(f"Skill: {skill}\n")
                f.write(f"Session: {session_name}\n")
                f.write(f"Started: {datetime.now().isoformat()}\n")
                f.write(f"Exit Code: {process.returncode}\n")
                f.write(f"\n=== STDOUT ===\n{output}\n")
                if error_output:
                    f.write(f"\n=== STDERR ===\n{error_output}\n")

            self._log_to_file(
                f"Claude CLI completed with exit code {process.returncode}"
            )

            if process.returncode == 0:
                # Truncate output for preview
                preview = output[:500] if len(output) > 500 else output
                return True, preview, None
            else:
                error_msg = (
                    error_output or f"Claude CLI exited with code {process.returncode}"
                )
                return False, output[:200] if output else None, error_msg

        except FileNotFoundError:
            self._cleanup_skill_execution_state(skill, "Claude CLI not found in PATH")
            return False, None, "Claude CLI not found in PATH"
        except Exception as e:
            self._log_to_file(f"Claude CLI error: {e}")
            self._cleanup_skill_execution_state(skill, str(e))
            return False, None, str(e)

    async def _run_skill(
        self, skill_name: str, inputs: dict, job_name: str | None = None
    ) -> str:
        """Run a skill and return its output.

        Args:
            skill_name: Name of the skill to run.
            inputs: Input parameters for the skill.
            job_name: Name of the cron job (for source tracking).
        """
        import yaml

        from .scheduler_config import SKILLS_DIR
        from .skill_engine import SkillExecutor, SkillExecutorConfig

        skill_file = SKILLS_DIR / f"{skill_name}.yaml"
        if not skill_file.exists():
            raise FileNotFoundError(f"Skill not found: {skill_name}")

        with open(skill_file, encoding="utf-8") as f:
            skill = yaml.safe_load(f)

        sched_config = SkillExecutorConfig(
            debug=False,
            enable_interactive_recovery=False,  # No interactive recovery for scheduled jobs
            emit_events=True,  # Enable VS Code events for running skills viewer
            workspace_uri="cron",
            source="cron",
            source_details=job_name or skill_name,
        )
        executor = SkillExecutor(
            skill=skill,
            inputs=inputs,
            config=sched_config,
            server=self.server,
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
