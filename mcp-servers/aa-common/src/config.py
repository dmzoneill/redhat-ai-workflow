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


def find_repos_json() -> Path | None:
    """Find config.json in standard locations."""
    locations = [
        Path.cwd() / "config.json",
        Path.cwd().parent / "config.json",
        Path(__file__).parent.parent.parent.parent / "config.json",
        Path.home() / "src/ai-workflow/config.json",
    ]
    for loc in locations:
        if loc.exists():
            return loc
    return None


def load_repos_config() -> dict[str, Any]:
    """Load config.json configuration."""
    path = find_repos_json()
    if not path:
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def get_os_env(key: str, default: str = "") -> str:
    """Get value from OS environment variable.
    
    Note: This is different from utils.get_env_config() which gets
    service config from config.json for a specific environment.
    """
    return os.getenv(key, default)


def get_token_from_kubeconfig(kubeconfig: str) -> str:
    """Extract bearer token from kubeconfig using oc/kubectl."""
    if not kubeconfig or not Path(kubeconfig).expanduser().exists():
        return ""
    
    kubeconfig = str(Path(kubeconfig).expanduser())
    env = {**os.environ, "KUBECONFIG": kubeconfig}
    
    # Try oc whoami -t first
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
    
    # Fallback to kubectl
    try:
        result = subprocess.run(
            ["kubectl", "config", "view", "--minify", "-o", "jsonpath={.users[0].user.token}"],
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
    
    config_paths = [
        Path.home() / ".docker/config.json",
        Path.home() / ".config/containers/auth.json",
        Path(os.getenv("DOCKER_CONFIG", "")) / "config.json",
    ]
    
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

