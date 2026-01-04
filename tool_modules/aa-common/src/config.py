"""Configuration loading for AA MCP servers.

All configuration comes from:
1. Environment variables
2. config.json (project-specific settings)
3. System configs (~/.kube/*, ~/.docker/config.json, etc.)

NO secrets are stored in code.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any


def load_config() -> dict[str, Any]:
    """Load config.json configuration.

    Delegates to utils.load_config() for the canonical implementation.
    This function exists for backward compatibility.
    """
    from src.utils import load_config as utils_load_config

    return utils_load_config()


def get_os_env(key: str, default: str = "") -> str:
    """Get value from OS environment variable.

    Note: This is different from utils.get_env_config() which gets
    service config from config.json for a specific environment.
    """
    return os.getenv(key, default)


def get_token_from_kubeconfig(
    kubeconfig: str | None = None,
    environment: str | None = None,
) -> str:
    """Extract bearer token from kubeconfig using oc/kubectl.

    Supports multiple kubeconfig files for different environments:
    - ~/.kube/config.s (stage)
    - ~/.kube/config.p (production)
    - ~/.kube/config.e (ephemeral)
    - ~/.kube/config.k (konflux)

    Args:
        kubeconfig: Explicit path to kubeconfig file (takes priority)
        environment: Environment name (stage, prod, ephemeral, konflux)
                    Used to resolve kubeconfig if path not provided

    Returns:
        Bearer token string, or empty string if not available

    Example:
        # Explicit path
        token = get_token_from_kubeconfig("~/.kube/config.s")

        # By environment
        token = get_token_from_kubeconfig(environment="stage")
        token = get_token_from_kubeconfig(environment="prod")
    """
    # Resolve kubeconfig path
    if not kubeconfig and environment:
        from src.utils import get_kubeconfig

        kubeconfig = get_kubeconfig(environment)

    if not kubeconfig:
        return ""

    kubeconfig = str(Path(kubeconfig).expanduser())
    if not Path(kubeconfig).exists():
        return ""

    env = {**os.environ, "KUBECONFIG": kubeconfig}

    # Try oc whoami -t first (works with active sessions)
    try:
        result = subprocess.run(
            ["oc", "whoami", "-t"],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass

    # Fallback to kubectl config view (extracts stored token)
    try:
        result = subprocess.run(
            ["kubectl", "config", "view", "--minify", "-o", "jsonpath={.users[0].user.token}"],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass

    # Last resort: try to extract from raw kubeconfig
    try:
        result = subprocess.run(
            [
                "kubectl",
                "config",
                "view",
                "--raw",
                "--minify",
                "-o",
                "jsonpath={.users[0].user.token}",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def get_docker_auth(registry: str = "quay.io") -> str | None:
    """Get auth token from Docker/Podman config for a registry."""
    import base64

    # Try config.json paths first
    try:
        from src.utils import load_config

        cfg = load_config()
        paths_cfg = cfg.get("paths", {})
        docker_config = paths_cfg.get("docker_config")
        container_auth = paths_cfg.get("container_auth")
        config_paths = []
        if docker_config:
            config_paths.append(Path(os.path.expanduser(docker_config)))
        if container_auth:
            config_paths.append(Path(os.path.expanduser(container_auth)))
    except ImportError:
        config_paths = []

    # Fall back to standard locations
    config_paths.extend(
        [
            Path.home() / ".docker/config.json",
            Path.home() / ".config/containers/auth.json",
            Path(os.getenv("DOCKER_CONFIG", "")) / "config.json",
        ]
    )

    for path in config_paths:
        if not path.exists():
            continue
        try:
            with open(path) as f:
                config = json.load(f)

            auths = config.get("auths", {})
            for key, value in auths.items():
                if registry in key:
                    if "auth" in value:
                        decoded = base64.b64decode(value["auth"]).decode()
                        return decoded.split(":", 1)[1] if ":" in decoded else decoded
        except Exception:
            continue

    return None
