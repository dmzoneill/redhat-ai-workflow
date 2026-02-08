"""Shared utilities for MCP servers.

This module provides common functions used across multiple MCP servers,
eliminating code duplication and ensuring consistent behavior.
"""

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import cast

from server.error_patterns import AUTH_PATTERNS

logger = logging.getLogger(__name__)


# ==================== Output Formatting ====================


def truncate_output(
    text: str,
    max_length: int = 5000,
    suffix: str = "\n\n... (truncated)",
    mode: str = "head",
) -> str:
    """Truncate long output with a suffix/prefix message.

    Args:
        text: Text to potentially truncate
        max_length: Maximum length before truncation (default: 5000)
        suffix: Message to append/prepend when truncated
        mode: "head" keeps first N chars (default), "tail" keeps last N chars

    Returns:
        Original text if within limit, otherwise truncated with message
    """
    if not text or len(text) <= max_length:
        return text

    if mode == "tail":
        # Keep the end (useful for logs where recent output matters)
        prefix = suffix.rstrip() + "\n\n" if suffix else "... (truncated)\n\n"
        return prefix + text[-max_length:]
    else:
        # Keep the beginning (default)
        return text[:max_length] + suffix


def format_error(
    message: str,
    output: str = "",
    hint: str = "",
    tool_name: str = "",
) -> str:
    """Build consistent error response.

    Args:
        message: Error message
        output: Optional command output
        hint: Optional hint for fixing the error
        tool_name: Optional tool name for debug_tool hint

    Returns:
        Formatted error string
    """
    parts = [f"❌ {message}"]
    if output:
        parts.append(f"\n{output}")
    if hint:
        parts.append(f"\n💡 {hint}")
    if tool_name:
        parts.append(f"\n💡 To auto-fix: `debug_tool('{tool_name}')`")
    return "".join(parts)


def format_success(message: str, **details: str | int | bool) -> str:
    """Build consistent success response.

    Args:
        message: Success message
        **details: Key-value details to include

    Returns:
        Formatted success string
    """
    parts = [f"✅ {message}"]
    for key, value in details.items():
        # Convert snake_case to Title Case
        display_key = key.replace("_", " ").title()
        parts.append(f"\n  • {display_key}: {value}")
    return "".join(parts)


def format_warning(message: str, action: str = "") -> str:
    """Build consistent warning response.

    Args:
        message: Warning message
        action: Optional suggested action

    Returns:
        Formatted warning string
    """
    result = f"⚠️ {message}"
    if action:
        result += f"\n💡 {action}"
    return result


def format_list(
    title: str,
    items: list[str | dict],
    empty_message: str = "None found.",
    item_key: str = "",
) -> str:
    """Build consistent list response.

    Args:
        title: List title/header
        items: List of strings or dicts to format
        empty_message: Message when list is empty
        item_key: If items are dicts, key to use for display

    Returns:
        Formatted list string
    """
    if not items:
        return f"{title}\n{empty_message}"

    lines = [title]
    for item in items:
        if isinstance(item, dict) and item_key:
            lines.append(f"  • {item.get(item_key, str(item))}")
        else:
            lines.append(f"  • {item}")
    return "\n".join(lines)


# ==================== Config Loading ====================

# Import ConfigManager for centralized config access
from server.config_manager import config as _config_manager  # noqa: E402


def get_project_root() -> Path:
    """Get the project root directory (redhat-ai-workflow)."""
    # This file is at: server/utils.py
    # Project root is 1 level up
    return Path(__file__).parent.parent


def load_config(reload: bool = False) -> dict:
    """Load config.json from project root.

    Uses ConfigManager for thread-safe, debounced access with
    automatic cache invalidation when file changes externally.

    Args:
        reload: Force reload from disk (default: use cached with mtime check)

    Returns:
        Parsed config dictionary
    """
    if reload:
        _config_manager.reload()
    return _config_manager.get_all()


def get_section_config(section: str, default: dict | None = None) -> dict:
    """Get a specific section from config.json.

    Uses ConfigManager for thread-safe access.

    Args:
        section: Config section name (e.g., 'bonfire', 'prometheus')
        default: Default value if section not found

    Returns:
        Config section dictionary
    """
    result = _config_manager.get(section)
    if result is None:
        return default or {}
    return cast(dict, result)


# ==================== Kubeconfig Handling ====================


def _get_kube_base() -> Path:
    """Get kube config base directory from config.json or default."""
    config = load_config()
    paths_cfg = config.get("paths", {})
    kube_base = paths_cfg.get("kube_base")
    if kube_base:
        return Path(os.path.expanduser(kube_base))
    return Path.home() / ".kube"


# Environment to kubeconfig suffix mapping
KUBECONFIG_MAP = {
    # Stage
    "stage": "s",
    "s": "s",
    # Production
    "production": "p",
    "prod": "p",
    "p": "p",
    # Ephemeral
    "ephemeral": "e",
    "eph": "e",
    "e": "e",
    # App-SRE SaaS pipelines
    "appsre-pipelines": "ap",
    "ap": "ap",
    "saas": "ap",
    # Konflux
    "konflux": "k",
    "k": "k",
}


def get_kubeconfig(environment: str, namespace: str = "") -> str:
    """Get kubeconfig path for environment.

    Args:
        environment: Environment name (stage, production, ephemeral, etc.)
        namespace: Optional namespace (not used currently, for future)

    Returns:
        Full path to kubeconfig file

    Raises:
        ValueError: If environment is empty or invalid
    """
    if not environment or not environment.strip():
        raise ValueError(
            "Environment is required for kubeconfig lookup. "
            "Got empty environment. Check that the 'environment' parameter is being passed correctly."
        )

    # Try config.json first for custom paths
    config = load_config()

    # Check namespaces section
    namespaces = config.get("namespaces", {})
    env_lower = environment.lower()
    if env_lower in namespaces:
        kubeconfig = namespaces[env_lower].get("kubeconfig")
        if kubeconfig:
            return os.path.expanduser(cast(str, kubeconfig))

    # Check kubernetes.environments section
    k8s_envs = config.get("kubernetes", {}).get("environments", {})
    if env_lower in k8s_envs:
        kubeconfig = k8s_envs[env_lower].get("kubeconfig")
        if kubeconfig:
            return os.path.expanduser(cast(str, kubeconfig))

    # Fall back to standard mapping using kube_base from config
    kube_base = _get_kube_base()
    suffix = KUBECONFIG_MAP.get(env_lower, env_lower)
    return str(kube_base / f"config.{suffix}")


def get_cluster_short_name(environment: str) -> str:
    """Get short cluster name for kube/kube-clean commands.

    Args:
        environment: Environment name (stage, production, ephemeral, etc.)

    Returns:
        Short name (e, s, p, k)
    """
    return KUBECONFIG_MAP.get(environment.lower(), environment.lower())


async def check_cluster_auth(environment: str) -> bool:
    """Check if cluster authentication is valid.

    Args:
        environment: Environment name (stage, production, ephemeral, etc.)

    Returns:
        True if auth is valid, False otherwise.
    """
    kubeconfig = get_kubeconfig(environment)

    if not os.path.exists(kubeconfig):
        logger.info(f"Kubeconfig not found: {kubeconfig}")
        return False

    # Quick auth check using oc whoami
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["oc", "whoami"],
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "KUBECONFIG": kubeconfig},
        )
        if result.returncode == 0:
            logger.info(f"Auth valid for {environment}: {result.stdout.strip()}")
            return True
        else:
            logger.info(f"Auth check failed for {environment}: {result.stderr.strip()}")
            return False
    except Exception as e:
        logger.info(f"Auth check error for {environment}: {e}")
        return False


async def refresh_cluster_auth(environment: str) -> bool:
    """Refresh cluster authentication using kube-clean and kube.

    This runs the user's bash functions which handle the OAuth browser flow.

    Args:
        environment: Environment name (stage, production, ephemeral, etc.)

    Returns:
        True if refresh succeeded, False otherwise.
    """
    short_name = get_cluster_short_name(environment)
    logger.info(
        f"Refreshing {environment} auth via kube-clean {short_name} && kube {short_name}"
    )

    # First clean stale config
    clean_success, _, clean_stderr = await run_cmd_shell(
        ["kube-clean", short_name], timeout=30
    )
    if not clean_success:
        logger.warning(f"kube-clean {short_name} failed: {clean_stderr}")
        # Continue anyway - kube might still work

    # Run kube to trigger OAuth flow (opens browser)
    success, _, stderr = await run_cmd_shell(["kube", short_name], timeout=120)
    if success:
        logger.info(f"Auth refresh succeeded for {environment}")
        return True
    else:
        logger.error(f"Auth refresh failed for {environment}: {stderr}")
        return False


async def ensure_cluster_auth(
    environment: str, auto_refresh: bool = True
) -> tuple[bool, str]:
    """Ensure cluster authentication is valid, optionally refreshing if needed.

    Args:
        environment: Environment name (stage, production, ephemeral, etc.)
        auto_refresh: If True, automatically refresh auth if expired (default: True)

    Returns:
        Tuple of (success, error_message). error_message is empty on success.
    """
    if await check_cluster_auth(environment):
        return True, ""

    if not auto_refresh:
        return False, f"Authentication expired for {environment} cluster."

    logger.info(f"Auth expired for {environment}, attempting refresh...")
    if await refresh_cluster_auth(environment):
        return True, ""

    short_name = get_cluster_short_name(environment)
    return False, (
        f"❌ {environment.title()} cluster authentication failed.\n\n"
        f"A browser window should have opened for SSO login.\n"
        f"If not, manually run: `kube-clean {short_name} && kube {short_name}`\n\n"
        "Then retry the command."
    )


def get_env_config(environment: str, service: str) -> dict:
    """Get environment-specific config for a service.

    Args:
        environment: Environment name (stage, production)
        service: Service name (prometheus, alertmanager, kibana)

    Returns:
        Environment config dictionary with url, kubeconfig, namespace, etc.
    """
    config = load_config()
    service_config = config.get(service, {})
    environments = service_config.get("environments", {})

    # Normalize environment name
    env_key = environment.lower()
    if env_key == "prod":
        env_key = "production"

    env_config = cast(dict, environments.get(env_key, {}))

    # Ensure kubeconfig is resolved
    if "kubeconfig" in env_config:
        env_config["kubeconfig"] = os.path.expanduser(
            cast(str, env_config["kubeconfig"])
        )
    else:
        env_config["kubeconfig"] = get_kubeconfig(environment)

    return env_config


# ==================== Repository Handling ====================


def resolve_repo_path(repo: str) -> str:
    """Resolve repository name to full path.

    Checks:
    1. If repo is already a valid path
    2. config.json repositories section
    3. Common source directories (~src, ~repos, ~projects)

    Args:
        repo: Repository name or path

    Returns:
        Full path to repository
    """
    # Already a valid path?
    if os.path.isdir(repo):
        return repo

    # Expand user path
    expanded = os.path.expanduser(repo)
    if os.path.isdir(expanded):
        return expanded

    # Check config.json repositories
    config = load_config()
    repositories = config.get("repositories", {})
    if repo in repositories:
        path = repositories[repo].get("path")
        if path:
            expanded_path = os.path.expanduser(cast(str, path))
            if os.path.isdir(expanded_path):
                return expanded_path

    # Try workspace roots from config, then fall back to common directories
    paths_config = config.get("paths", {})
    workspace_roots = paths_config.get(
        "workspace_roots",
        [
            str(Path.home() / "src"),
            str(Path.home() / "repos"),
            str(Path.home() / "projects"),
        ],
    )
    for base_path in workspace_roots:
        candidate = Path(os.path.expanduser(base_path)) / repo
        if candidate.exists():
            return str(candidate)

    # Return as-is (may fail downstream, but that's expected)
    return repo


def get_repo_config(repo: str) -> dict:
    """Get configuration for a repository.

    Args:
        repo: Repository name or path

    Returns:
        Repository config from config.json, or empty dict
    """
    config = load_config()
    repositories = config.get("repositories", {})

    # Try exact match
    if repo in repositories:
        return cast(dict, repositories[repo])

    # Try matching by path
    for _name, repo_config in repositories.items():
        if repo_config.get("path", "").endswith(repo):
            return cast(dict, repo_config)

    return {}


# ==================== Command Execution ====================


async def run_cmd(
    cmd: list[str],
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 60,
    check: bool = False,
    use_shell: bool = True,
) -> tuple[bool, str]:
    """Run a command asynchronously through user's shell environment.

    This is the STANDARD way to run commands in this project. It ensures:
    - User's shell environment (~/.bashrc vars like JIRA_JPAT, KUBECONFIG)
    - Proper PATH with ~/bin
    - GUI access (DISPLAY, XAUTHORITY) for browser-based auth

    Args:
        cmd: Command and arguments as list
        cwd: Working directory
        env: Additional environment variables (merged with shell env)
        timeout: Timeout in seconds
        check: Raise exception on non-zero exit
        use_shell: If True (default), run through bash with sourced configs.
                   Set to False only for simple commands that don't need shell env.

    Returns:
        Tuple of (success, output) - stderr is merged with stdout on failure

    Example:
        # Standard usage - runs through user's shell
        success, output = await run_cmd(["rh-issue", "view-issue", "AAP-12345"])

        # With extra env vars
        success, output = await run_cmd(
            ["bonfire", "namespace", "list"],
            env={"KUBECONFIG": "~/.kube/config.e"}
        )

        # Simple command that doesn't need shell (rare)
        success, output = await run_cmd(["git", "status"], use_shell=False)
    """
    import shlex

    try:
        home = Path.home()

        if use_shell:
            # Build command string with proper quoting
            cmd_str = " ".join(shlex.quote(arg) for arg in cmd)
            if cwd:
                cmd_str = f"cd {shlex.quote(cwd)} && {cmd_str}"

            # Source shell configs
            sources = _build_shell_sources(home)
            if sources:
                cmd_str = f"{'; '.join(sources)}; {cmd_str}"

            shell_cmd = ["bash", "-c", cmd_str]
            run_env = _prepare_shell_environment(home)
            run_cwd = None  # cwd is handled in the command string
        else:
            shell_cmd = cmd
            run_env = os.environ.copy()
            run_cwd = cwd

        # Merge any additional env vars
        if env:
            run_env.update(env)

        result = await asyncio.to_thread(
            subprocess.run,
            shell_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=run_cwd,
            env=run_env,
        )

        output = result.stdout
        if result.returncode != 0:
            output = result.stderr or result.stdout or "Command failed"
            if check:
                raise subprocess.CalledProcessError(result.returncode, cmd, output)
            return False, output

        return True, output
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"
    except subprocess.CalledProcessError:
        raise
    except Exception as e:
        return False, str(e)


async def run_cmd_full(
    cmd: list[str],
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 300,
    use_shell: bool = True,
) -> tuple[bool, str, str]:
    """Run a command asynchronously with separate stdout/stderr.

    Same as run_cmd() but returns stdout and stderr separately.

    Args:
        cmd: Command and arguments as list
        cwd: Working directory
        env: Additional environment variables (merged with shell env)
        timeout: Timeout in seconds
        use_shell: If True (default), run through bash with sourced configs.

    Returns:
        Tuple of (success, stdout, stderr)
    """
    import shlex

    try:
        home = Path.home()

        if use_shell:
            cmd_str = " ".join(shlex.quote(arg) for arg in cmd)
            if cwd:
                cmd_str = f"cd {shlex.quote(cwd)} && {cmd_str}"

            sources = _build_shell_sources(home)
            if sources:
                cmd_str = f"{'; '.join(sources)}; {cmd_str}"

            shell_cmd = ["bash", "-c", cmd_str]
            run_env = _prepare_shell_environment(home)
            run_cwd = None
        else:
            shell_cmd = cmd
            run_env = os.environ.copy()
            run_cwd = cwd

        if env:
            run_env.update(env)

        result = await asyncio.to_thread(
            subprocess.run,
            shell_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=run_cwd,
            env=run_env,
        )

        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return False, "", f"Command not found: {cmd[0]}"
    except Exception as e:
        return False, "", str(e)


def run_cmd_sync(
    cmd: list[str],
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 60,
    use_shell: bool = True,
) -> tuple[bool, str]:
    """Synchronous version of run_cmd for non-async contexts.

    Use this in scripts that aren't async. For async code, prefer run_cmd().

    Args:
        cmd: Command and arguments as list
        cwd: Working directory
        env: Additional environment variables (merged with shell env)
        timeout: Timeout in seconds
        use_shell: If True (default), run through bash with sourced configs.

    Returns:
        Tuple of (success, output) - stderr is merged with stdout on failure
    """
    import shlex

    try:
        home = Path.home()

        if use_shell:
            cmd_str = " ".join(shlex.quote(arg) for arg in cmd)
            if cwd:
                cmd_str = f"cd {shlex.quote(cwd)} && {cmd_str}"

            sources = _build_shell_sources(home)
            if sources:
                cmd_str = f"{'; '.join(sources)}; {cmd_str}"

            shell_cmd = ["bash", "-c", cmd_str]
            run_env = _prepare_shell_environment(home)
            run_cwd = None
        else:
            shell_cmd = cmd
            run_env = os.environ.copy()
            run_cwd = cwd

        if env:
            run_env.update(env)

        result = subprocess.run(
            shell_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=run_cwd,
            env=run_env,
        )

        output = result.stdout
        if result.returncode != 0:
            output = result.stderr or result.stdout or "Command failed"
            return False, output

        return True, output
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"
    except Exception as e:
        return False, str(e)


def _build_shell_sources(home: Path) -> list[str]:
    """Build list of shell config source commands.

    Args:
        home: User home directory

    Returns:
        List of source commands for bash configs
    """
    sources = []

    bashrc = home / ".bashrc"
    if bashrc.exists():
        sources.append(f"source {bashrc} 2>/dev/null")

    # Source the bashrc.d loader which loads all scripts.d/*.sh files
    bashrc_d_loader = home / ".bashrc.d" / "00-loader.sh"
    if bashrc_d_loader.exists():
        sources.append(f"source {bashrc_d_loader} 2>/dev/null")

    # IMPORTANT: Also source all .sh files in bashrc.d root directly
    # These define functions like 'kube' for kubernetes auth
    # .bashrc conditionally loads these only for interactive+desktop sessions,
    # so we need to explicitly source them for MCP server context
    bashrc_d = home / ".bashrc.d"
    if bashrc_d.is_dir():
        for script in sorted(bashrc_d.glob("*.sh")):
            if script.name != "00-loader.sh":  # Already sourced above
                sources.append(f"source {script} 2>/dev/null")

    return sources


def _prepare_shell_environment(home: Path) -> dict[str, str]:
    """Prepare environment variables for shell execution.

    Args:
        home: User home directory

    Returns:
        Environment dict with all necessary variables set
    """
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["USER"] = home.name

    # CRITICAL: Clear virtualenv variables from MCP server's venv
    for var in ["VIRTUAL_ENV", "PIPENV_ACTIVE", "PYTHONHOME"]:
        env.pop(var, None)
    env["PIPENV_IGNORE_VIRTUALENVS"] = "1"

    # Set up PATH
    user_bin = str(home / "bin")
    path_parts = env.get("PATH", "").split(":")
    path_parts = [p for p in path_parts if ".venv" not in p]
    if user_bin not in path_parts:
        path_parts.insert(0, user_bin)
    env["PATH"] = ":".join(path_parts)

    # GUI environment (DISPLAY, XAUTHORITY)
    if "DISPLAY" in os.environ:
        env["DISPLAY"] = os.environ["DISPLAY"]
    elif "DISPLAY" not in env:
        env["DISPLAY"] = ":0"

    if "XAUTHORITY" in os.environ:
        env["XAUTHORITY"] = os.environ["XAUTHORITY"]
    elif "XAUTHORITY" not in env:
        xauth_path = home / ".Xauthority"
        if xauth_path.exists():
            env["XAUTHORITY"] = str(xauth_path)

    # Wayland environment
    if "WAYLAND_DISPLAY" in os.environ:
        env["WAYLAND_DISPLAY"] = os.environ["WAYLAND_DISPLAY"]
    elif "WAYLAND_DISPLAY" not in env:
        wayland_sock = Path(f"/run/user/{os.getuid()}/wayland-0")
        if wayland_sock.exists():
            env["WAYLAND_DISPLAY"] = "wayland-0"

    if "XDG_RUNTIME_DIR" in os.environ:
        env["XDG_RUNTIME_DIR"] = os.environ["XDG_RUNTIME_DIR"]
    elif "XDG_RUNTIME_DIR" not in env:
        runtime_dir = f"/run/user/{os.getuid()}"
        if os.path.isdir(runtime_dir):
            env["XDG_RUNTIME_DIR"] = runtime_dir

    return env


async def run_cmd_shell(
    cmd: list[str],
    cwd: str | None = None,
    timeout: int = 300,
) -> tuple[bool, str, str]:
    """DEPRECATED: Use run_cmd_full() instead.

    This is kept for backwards compatibility but just calls run_cmd_full().
    """
    return await run_cmd_full(cmd, cwd=cwd, timeout=timeout, use_shell=True)


def is_auth_error(output: str) -> bool:
    """Check if kubectl/oc error indicates auth failure.

    Args:
        output: Error output from kubectl/oc

    Returns:
        True if this is an authentication error
    """
    output_lower = output.lower()
    return any(pattern.lower() in output_lower for pattern in AUTH_PATTERNS)


def get_auth_hint(environment: str) -> str:
    """Get auth hint for an environment.

    Args:
        environment: Environment name (stage, production, ephemeral, konflux)

    Returns:
        Hint message for fixing auth
    """
    env_lower = environment.lower()
    cluster_map = {
        "stage": "s",
        "s": "s",
        "production": "p",
        "prod": "p",
        "p": "p",
        "ephemeral": "e",
        "eph": "e",
        "e": "e",
        "konflux": "k",
        "k": "k",
    }
    cluster = cluster_map.get(env_lower, env_lower)
    return f"🔑 Run: `kube_login('{cluster}')` to refresh authentication"


async def run_kubectl(
    args: list[str],
    kubeconfig: str | None = None,
    namespace: str | None = None,
    timeout: int = 60,
    environment: str | None = None,
    auto_auth: bool = True,
) -> tuple[bool, str]:
    """Run kubectl command with proper kubeconfig.

    Args:
        args: kubectl arguments (e.g., ["get", "pods"])
        kubeconfig: Explicit kubeconfig path (preferred)
        namespace: Kubernetes namespace
        timeout: Timeout in seconds
        environment: Environment name (used if kubeconfig not provided)
        auto_auth: If True, check and refresh auth before running (default: True)
                   Opens browser for SSO if credentials are stale.

    Returns:
        Tuple of (success, output)
    """
    # Resolve kubeconfig and environment
    resolved_env = environment
    if not kubeconfig and environment:
        kubeconfig = get_kubeconfig(environment, namespace or "")
        resolved_env = environment
    elif not kubeconfig:
        kubeconfig = get_kubeconfig("stage", namespace or "")
        resolved_env = "stage"
    else:
        # Try to determine environment from kubeconfig path
        kc_path = Path(kubeconfig).name
        if kc_path.endswith(".s"):
            resolved_env = "stage"
        elif kc_path.endswith(".p"):
            resolved_env = "production"
        elif kc_path.endswith(".e"):
            resolved_env = "ephemeral"
        elif kc_path.endswith(".k"):
            resolved_env = "konflux"

    # Check auth before running if auto_auth is enabled
    if auto_auth and resolved_env:
        auth_ok, auth_error = await ensure_cluster_auth(resolved_env, auto_refresh=True)
        if not auth_ok:
            return False, auth_error

    cmd = ["kubectl", f"--kubeconfig={kubeconfig}"]
    cmd.extend(args)
    if namespace:
        cmd.extend(["-n", namespace])

    success, output = await run_cmd(cmd, timeout=timeout)

    # Add hint on auth failures (even though we pre-checked, token could expire mid-operation)
    if not success and is_auth_error(output) and resolved_env:
        hint = get_auth_hint(resolved_env)
        output = f"{output}\n\n{hint}"

    return success, output


async def run_oc(
    args: list[str],
    environment: str = "stage",
    namespace: str | None = None,
    timeout: int = 60,
) -> tuple[bool, str]:
    """Run oc command with proper kubeconfig.

    Args:
        args: oc arguments
        environment: Environment for kubeconfig selection
        namespace: Kubernetes namespace
        timeout: Timeout in seconds

    Returns:
        Tuple of (success, output)
    """
    kubeconfig = get_kubeconfig(environment, namespace or "")
    cmd = ["oc", f"--kubeconfig={kubeconfig}"]
    cmd.extend(args)
    if namespace:
        cmd.extend(["-n", namespace])

    return await run_cmd(cmd, timeout=timeout)


# ==================== User Config ====================


def get_user_config() -> dict:
    """Get user configuration from config.json.

    Returns:
        User config with username, email, timezone, etc.
    """
    return get_section_config(
        "user",
        {
            "username": os.getenv("USER", "unknown"),
            "email": "",
            "timezone": "UTC",
        },
    )


def get_username() -> str:
    """Get the current user's username."""
    user_config = get_user_config()
    return cast(str, user_config.get("username", os.getenv("USER", "unknown")))


# ==================== Service URL Helpers ====================


def get_gitlab_host() -> str:
    """Get GitLab host from env var, config, or default.

    Priority:
    1. GITLAB_HOST environment variable
    2. config.json gitlab.host
    3. Default: gitlab.cee.redhat.com

    Returns:
        GitLab hostname (without https://)
    """
    env_host = os.getenv("GITLAB_HOST")
    if env_host:
        return env_host
    config = load_config()
    return cast(str, config.get("gitlab", {}).get("host", "gitlab.cee.redhat.com"))


def get_service_url(service: str, environment: str) -> str:
    """Get URL for a service in an environment.

    Args:
        service: Service name (prometheus, alertmanager, kibana)
        environment: Environment name (stage, production)

    Returns:
        Service URL

    Raises:
        ValueError: If URL not configured or environment is empty
    """
    if not environment or not environment.strip():
        raise ValueError(
            f"{service.capitalize()} URL not configured for empty environment. "
            f"The 'environment' parameter is required. "
            f"Check that the environment is being passed correctly from the skill."
        )

    env_config = get_env_config(environment, service)
    url = cast(str, env_config.get("url", ""))

    if not url:
        # Try environment variable fallback
        env_var = f"{service.upper()}_{environment.upper()}_URL"
        url = os.getenv(env_var, "")

    if not url:
        raise ValueError(
            f"{service.capitalize()} URL not configured for {environment}. "
            f"Set {service.upper()}_{environment.upper()}_URL or configure in config.json"
        )

    return url


async def get_bearer_token(
    kubeconfig: str,
    environment: str | None = None,
    auto_auth: bool = True,
) -> str | None:
    """Get bearer token from kubeconfig for API authentication.

    Tries multiple methods:
    1. Extract from kubeconfig file directly (older clusters)
    2. Use 'oc whoami --show-token' (modern OpenShift SSO)

    Args:
        kubeconfig: Path to kubeconfig file
        environment: Environment name for auto-auth (stage, prod, ephemeral)
        auto_auth: If True, refresh auth if token extraction fails

    Returns:
        Bearer token or None if not available
    """
    # Determine environment from kubeconfig path if not provided
    if not environment:
        kc_path = Path(kubeconfig).name
        if kc_path.endswith(".s"):
            environment = "stage"
        elif kc_path.endswith(".p"):
            environment = "production"
        elif kc_path.endswith(".e"):
            environment = "ephemeral"
        elif kc_path.endswith(".k"):
            environment = "konflux"

    # Check/refresh auth if enabled
    if auto_auth and environment:
        auth_ok, _ = await ensure_cluster_auth(environment, auto_refresh=True)
        if not auth_ok:
            logger.warning(f"Auth refresh failed for {environment}")
            return None

    # Method 1: Try extracting from kubeconfig file
    # Note: kubectl config view often returns "REDACTED" for SSO tokens
    try:
        cmd = [
            "kubectl",
            "--kubeconfig",
            kubeconfig,
            "config",
            "view",
            "--minify",
            "-o",
            "jsonpath={.users[0].user.token}",
        ]
        success, output = await run_cmd(cmd, timeout=10)
        token = output.strip()
        # "REDACTED" is returned by kubectl for security - not a real token
        if success and token and token.upper() != "REDACTED":
            return token
    except Exception as e:
        logger.debug(f"Token not in kubeconfig: {e}")

    # Method 2: Use oc whoami --show-token (works with SSO sessions)
    try:
        cmd = ["oc", "--kubeconfig", kubeconfig, "whoami", "--show-token"]
        success, output = await run_cmd(cmd, timeout=10)
        if success and output.strip():
            return output.strip()
    except Exception as e:
        logger.warning(f"Failed to get token via oc whoami: {e}")

    return None
