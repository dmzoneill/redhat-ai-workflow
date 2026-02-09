"""Ollama instance configuration.

Supports 4 Ollama instances running on different hardware:
- NPU: Intel Core Ultra NPU (2-5W, best for classification)
- iGPU: Intel integrated GPU (8-15W, balanced)
- NVIDIA: Discrete GPU (40-60W, complex tasks)
- CPU: Fallback CPU inference (15-35W)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class OllamaInstance:
    """Configuration for a single Ollama instance."""

    name: str
    host: str
    default_model: str
    power_watts: str
    best_for: list[str] = field(default_factory=list)

    def __post_init__(self):
        # Ensure host doesn't have trailing slash
        self.host = self.host.rstrip("/")


# Hardcoded fallback instance configurations (used only if config.json is unavailable)
_FALLBACK_INSTANCES = {
    "npu": OllamaInstance(
        name="npu",
        host=os.getenv("OLLAMA_NPU_HOST", "http://localhost:11434"),
        default_model="qwen2.5:0.5b",
        power_watts="2-5W",
        best_for=["classification", "extraction", "simple_queries", "tool_filtering"],
    ),
    "igpu": OllamaInstance(
        name="igpu",
        host=os.getenv("OLLAMA_IGPU_HOST", "http://localhost:11435"),
        default_model="llama3.2:3b",
        power_watts="8-15W",
        best_for=["balanced_tasks", "medium_complexity", "summarization"],
    ),
    "nvidia": OllamaInstance(
        name="nvidia",
        host=os.getenv("OLLAMA_NVIDIA_HOST", "http://localhost:11436"),
        default_model="llama3:8b",
        power_watts="40-60W",
        best_for=["complex_reasoning", "code_generation", "long_context"],
    ),
    "cpu": OllamaInstance(
        name="cpu",
        host=os.getenv("OLLAMA_CPU_HOST", "http://localhost:11437"),
        default_model="qwen2.5:0.5b",
        power_watts="15-35W",
        best_for=["fallback", "testing", "offline"],
    ),
}

# Keep DEFAULT_INSTANCES as a public alias for backward compatibility
DEFAULT_INSTANCES = _FALLBACK_INSTANCES

# Cached instances (loaded from config.json if available)
_instances: Optional[dict[str, OllamaInstance]] = None


def _load_instances_from_config() -> dict[str, OllamaInstance]:
    """Load instance configuration from config.json first, falling back to hardcoded defaults."""
    # Start with hardcoded fallbacks
    instances = dict(_FALLBACK_INSTANCES)

    # Try to load from config.json (config.json values take priority)
    try:
        from server.config_manager import config as config_manager

        config = config_manager.get_all()
        ollama_config = config.get("ollama", {}).get("instances", {})
        for name, cfg in ollama_config.items():
            fallback = instances.get(name)
            if fallback:
                # Config.json values take priority over hardcoded fallbacks
                instances[name] = OllamaInstance(
                    name=name,
                    host=cfg.get("host", fallback.host),
                    default_model=cfg.get("default_model", fallback.default_model),
                    power_watts=cfg.get("power_watts", fallback.power_watts),
                    best_for=cfg.get("best_for", fallback.best_for),
                )
            else:
                # Add new instance from config.json
                instances[name] = OllamaInstance(
                    name=name,
                    host=cfg.get("host", "http://localhost:11434"),
                    default_model=cfg.get("default_model", "qwen2.5:0.5b"),
                    power_watts=cfg.get("power_watts", "unknown"),
                    best_for=cfg.get("best_for", []),
                )
    except (json.JSONDecodeError, KeyError) as exc:
        logger.debug("Suppressed error: %s", exc)

    return instances


def get_instances() -> dict[str, OllamaInstance]:
    """Get all configured Ollama instances."""
    global _instances
    if _instances is None:
        _instances = _load_instances_from_config()
    return _instances


def get_instance(name: str = "npu") -> OllamaInstance:
    """Get instance by name, default to NPU."""
    instances = get_instances()
    return instances.get(name, instances.get("npu", DEFAULT_INSTANCES["npu"]))


def reload_instances() -> None:
    """Reload instances from config (useful after config changes)."""
    global _instances
    _instances = None


def get_instance_names() -> list[str]:
    """Get list of all instance names."""
    return list(get_instances().keys())
