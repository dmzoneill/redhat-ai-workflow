"""Shared CLI command runner utilities.

Provides a consistent interface for running CLI commands with:
- Configurable timeouts
- Environment variable injection
- Working directory handling
- Standard error handling
"""

import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CLIRunner:
    """Configurable CLI command runner.

    Usage:
        # Simple runner
        git = CLIRunner("git")
        success, output = await git.run(["status"])

        # Runner with environment and timeout
        bonfire = CLIRunner(
            "bonfire",
            timeout=300,
            env_vars={"KUBECONFIG": "~/.kube/config.e"},
        )
        success, output = await bonfire.run(["namespace", "list"])
    """

    command: str
    timeout: int = 60
    env_vars: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    shell_mode: bool = False

    # Error patterns that indicate auth issues
    auth_error_patterns: list[str] = field(
        default_factory=lambda: ["Unauthorized", "401", "token expired", "JIRA_JPAT"]
    )

    # Error patterns that indicate network issues
    network_error_patterns: list[str] = field(
        default_factory=lambda: ["No route to host", "Connection refused", "Network is unreachable"]
    )

    def _build_env(self, extra_env: dict[str, str] | None = None) -> dict[str, str]:
        """Build environment variables for command."""
        env = os.environ.copy()
        env.update(self.env_vars)
        if extra_env:
            env.update(extra_env)
        return env

    def _resolve_cwd(self, cwd: str | None = None) -> str | None:
        """Resolve working directory, preferring explicit over default."""
        target = cwd or self.cwd
        if target and Path(target).exists():
            return str(Path(target).resolve())
        return None

    def _detect_error_type(self, output: str) -> str | None:
        """Detect the type of error from output.

        Returns:
            "auth" for authentication errors
            "network" for network errors
            None for other errors
        """
        for pattern in self.auth_error_patterns:
            if pattern.lower() in output.lower():
                return "auth"
        for pattern in self.network_error_patterns:
            if pattern.lower() in output.lower():
                return "network"
        return None

    async def run(
        self,
        args: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> tuple[bool, str]:
        """Run the command with given arguments.

        Args:
            args: Command arguments (command name is prepended automatically)
            cwd: Working directory (overrides default)
            env: Additional environment variables (merged with defaults)
            timeout: Timeout in seconds (overrides default)

        Returns:
            Tuple of (success, output)
        """
        cmd = [self.command] + args
        run_timeout = timeout or self.timeout
        run_cwd = self._resolve_cwd(cwd)
        run_env = self._build_env(env)

        logger.debug(f"Running: {' '.join(cmd)}")

        try:
            if self.shell_mode:
                # Run through shell for commands that need it
                import shlex

                cmd_str = " ".join(shlex.quote(arg) for arg in cmd)
                if run_cwd:
                    cmd_str = f"cd {shlex.quote(run_cwd)} && {cmd_str}"

                result = await asyncio.to_thread(
                    subprocess.run,
                    cmd_str,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=run_timeout,
                    env=run_env,
                )
            else:
                result = await asyncio.to_thread(
                    subprocess.run,
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=run_timeout,
                    cwd=run_cwd,
                    env=run_env,
                )

            if result.returncode == 0:
                return True, result.stdout
            else:
                output = result.stderr or result.stdout
                error_type = self._detect_error_type(output)
                if error_type:
                    logger.debug(f"Detected {error_type} error in output")
                return False, output

        except subprocess.TimeoutExpired:
            return False, f"Command timed out after {run_timeout}s"
        except FileNotFoundError:
            return False, f"Command not found: {self.command}"
        except PermissionError:
            return False, f"Permission denied: {self.command}"
        except OSError as e:
            return False, f"OS error running {self.command}: {e}"

    async def run_with_retry(
        self,
        args: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
        max_retries: int = 1,
        retry_delay: float = 1.0,
    ) -> tuple[bool, str]:
        """Run command with automatic retry on failure.

        Args:
            args: Command arguments
            cwd: Working directory
            env: Additional environment variables
            timeout: Timeout in seconds
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds

        Returns:
            Tuple of (success, output)
        """
        last_error = ""
        for attempt in range(max_retries + 1):
            success, output = await self.run(args, cwd=cwd, env=env, timeout=timeout)
            if success:
                return True, output

            last_error = output
            if attempt < max_retries:
                logger.debug(f"Attempt {attempt + 1} failed, retrying in {retry_delay}s...")
                await asyncio.sleep(retry_delay)

        return False, last_error


# Pre-configured runners for common tools


def git_runner(cwd: str | None = None, timeout: int = 60) -> CLIRunner:
    """Create a CLI runner for git commands.

    Args:
        cwd: Default working directory for git commands
        timeout: Default timeout in seconds
    """
    return CLIRunner("git", timeout=timeout, cwd=cwd)


def glab_runner(
    gitlab_host: str = "gitlab.com",
    cwd: str | None = None,
    timeout: int = 60,
) -> CLIRunner:
    """Create a CLI runner for glab (GitLab CLI) commands.

    Args:
        gitlab_host: GitLab host for authentication
        cwd: Default working directory
        timeout: Default timeout in seconds
    """
    return CLIRunner(
        "glab",
        timeout=timeout,
        cwd=cwd,
        env_vars={"GITLAB_HOST": gitlab_host},
    )


def bonfire_runner(kubeconfig: str, timeout: int = 300) -> CLIRunner:
    """Create a CLI runner for bonfire commands.

    Args:
        kubeconfig: Path to kubeconfig file for ephemeral cluster
        timeout: Default timeout in seconds
    """
    return CLIRunner(
        "bonfire",
        timeout=timeout,
        env_vars={"KUBECONFIG": kubeconfig},
        auth_error_patterns=["Unauthorized", "token expired", "403 Forbidden"],
    )


def kubectl_runner(kubeconfig: str, timeout: int = 60) -> CLIRunner:
    """Create a CLI runner for kubectl commands.

    Args:
        kubeconfig: Path to kubeconfig file
        timeout: Default timeout in seconds
    """
    return CLIRunner(
        "kubectl",
        timeout=timeout,
        env_vars={"KUBECONFIG": kubeconfig},
        auth_error_patterns=["Unauthorized", "token expired", "forbidden"],
    )


def skopeo_runner(timeout: int = 30) -> CLIRunner:
    """Create a CLI runner for skopeo commands.

    Args:
        timeout: Default timeout in seconds
    """
    return CLIRunner("skopeo", timeout=timeout)


def rh_issue_runner(timeout: int = 30) -> CLIRunner:
    """Create a CLI runner for rh-issue (Jira CLI) commands.

    Uses shell mode to ensure proper environment from ~/.bashrc.

    Args:
        timeout: Default timeout in seconds
    """
    return CLIRunner(
        "rh-issue",
        timeout=timeout,
        shell_mode=True,
        auth_error_patterns=["JIRA_JPAT", "401", "Unauthorized"],
    )
