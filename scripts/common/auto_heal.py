"""
Auto-heal utilities for MCP tool failures.

This module provides functions to:
1. Detect common failure patterns
2. Suggest or apply automatic fixes
3. Log failures to memory for learning

Usage in skill compute blocks:
    from scripts.common.auto_heal import (
        detect_failure, get_quick_fix, log_failure, should_retry
    )
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

# Quick-fix patterns
AUTH_PATTERNS = [
    "unauthorized", "401", "forbidden", "403",
    "token expired", "authentication required",
    "not authorized", "permission denied"
]

NETWORK_PATTERNS = [
    "no route to host", "connection refused", "network unreachable",
    "timeout", "dial tcp", "connection reset", "eof"
]

REGISTRY_PATTERNS = [
    "manifest unknown", "podman login", "registry authentication",
    "image not found", "pull access denied"
]

TTY_PATTERNS = [
    "output is not a tty", "not a terminal", "aborting",
    "input is not a terminal"
]


def detect_failure(result: str, tool_name: str = "") -> dict:
    """
    Analyze a tool result for failure patterns.

    Args:
        result: The tool output to analyze
        tool_name: Name of the tool that was called

    Returns:
        dict with:
            - failed: bool
            - error_type: str (auth, network, registry, tty, unknown)
            - error_text: str (first 300 chars of error)
            - can_auto_fix: bool
            - fix_action: str (kube_login, vpn_connect, etc.)
            - fix_args: dict (e.g., {"cluster": "ephemeral"})
    """
    if not result:
        return {"failed": False}

    result_lower = str(result).lower()

    # Check for error indicators
    is_error = (
        "❌" in result or
        result_lower.startswith("error") or
        "failed" in result_lower[:100] or
        "exception" in result_lower[:100]
    )

    if not is_error:
        return {"failed": False}

    error_text = str(result)[:300]

    # Check auth issues
    if any(p in result_lower for p in AUTH_PATTERNS):
        # Determine which cluster based on context
        cluster = _guess_cluster(tool_name, result)
        return {
            "failed": True,
            "error_type": "auth",
            "error_text": error_text,
            "can_auto_fix": True,
            "fix_action": "kube_login",
            "fix_args": {"cluster": cluster},
            "fix_message": f"Auth expired. Run: kube_login('{cluster}')",
        }

    # Check network issues
    if any(p in result_lower for p in NETWORK_PATTERNS):
        return {
            "failed": True,
            "error_type": "network",
            "error_text": error_text,
            "can_auto_fix": True,
            "fix_action": "vpn_connect",
            "fix_args": {},
            "fix_message": "Network issue. Run: vpn_connect()",
        }

    # Check registry issues
    if any(p in result_lower for p in REGISTRY_PATTERNS):
        return {
            "failed": True,
            "error_type": "registry",
            "error_text": error_text,
            "can_auto_fix": False,
            "fix_action": "suggest_podman_login",
            "fix_args": {},
            "fix_message": "Registry auth required. Run: podman login quay.io",
        }

    # Check TTY issues
    if any(p in result_lower for p in TTY_PATTERNS):
        return {
            "failed": True,
            "error_type": "tty",
            "error_text": error_text,
            "can_auto_fix": False,
            "fix_action": "debug_tool",
            "fix_args": {"tool_name": tool_name},
            "fix_message": f"Tool needs --force flag. Run: debug_tool('{tool_name}')",
        }

    # Unknown error
    return {
        "failed": True,
        "error_type": "unknown",
        "error_text": error_text,
        "can_auto_fix": False,
        "fix_action": "debug_tool",
        "fix_args": {"tool_name": tool_name},
        "fix_message": f"Unknown error. Run: debug_tool('{tool_name}', '{error_text[:50]}')",
    }


def _guess_cluster(tool_name: str, result: str) -> str:
    """Guess which cluster based on tool name and error context."""
    tool_lower = tool_name.lower()
    result_lower = str(result).lower()

    if "bonfire" in tool_lower or "ephemeral" in result_lower:
        return "ephemeral"
    if "konflux" in tool_lower:
        return "konflux"
    if "prod" in result_lower:
        return "production"
    return "stage"


def get_quick_fix(failure: dict) -> Optional[tuple]:
    """
    Get the fix action and args for a failure.

    Returns:
        tuple of (tool_name, args) or None
    """
    if not failure.get("can_auto_fix"):
        return None

    action = failure.get("fix_action")
    args = failure.get("fix_args", {})

    if action == "kube_login":
        return ("kube_login", {"cluster": args.get("cluster", "stage")})
    elif action == "vpn_connect":
        return ("vpn_connect", {})

    return None


def should_retry(failure: dict, retry_count: int = 0, max_retries: int = 2) -> bool:
    """
    Determine if we should retry after applying a fix.

    Args:
        failure: The failure detection result
        retry_count: Current retry count
        max_retries: Maximum retries allowed

    Returns:
        True if should retry
    """
    if retry_count >= max_retries:
        return False

    if not failure.get("can_auto_fix"):
        return False

    return failure.get("error_type") in ["auth", "network"]


def log_failure(
    tool_name: str,
    error_text: str,
    skill_name: str = "",
    fixed: bool = False,
    memory_helper=None
) -> dict:
    """
    Log a failure to memory for learning.

    Args:
        tool_name: Name of the tool that failed
        error_text: Error message
        skill_name: Name of the skill that was running
        fixed: Whether the failure was auto-fixed
        memory_helper: Memory helper object from skill context

    Returns:
        Log entry dict
    """
    entry = {
        "tool": tool_name,
        "error": error_text[:100],
        "timestamp": datetime.now().isoformat(),
        "skill": skill_name,
        "auto_fixed": fixed,
    }

    if memory_helper:
        try:
            memory_helper.append_to_list(
                "learned/tool_failures",
                "failure_history",
                entry
            )
            # Update stats
            memory_helper.increment_field(
                "learned/tool_failures",
                "stats.total_failures"
            )
            if fixed:
                memory_helper.increment_field(
                    "learned/tool_failures",
                    "stats.auto_fixed"
                )
            else:
                memory_helper.increment_field(
                    "learned/tool_failures",
                    "stats.manual_required"
                )
        except Exception:
            pass  # Memory logging is best-effort

    return entry


def build_auto_heal_block(
    step_name: str,
    tool_name: str,
    output_var: str,
    cluster_hint: str = "auto"
) -> str:
    """
    Generate YAML for an auto-heal block after a tool call.

    This is a helper for skill developers to generate the YAML.

    Args:
        step_name: Base name for the step (e.g., "reserve_namespace")
        tool_name: The tool being called
        output_var: The output variable name
        cluster_hint: Cluster hint for auth fixes

    Returns:
        YAML string for auto-heal block
    """
    yaml = f"""
  # ==================== AUTO-HEAL: {step_name} ====================

  - name: detect_failure_{step_name}
    description: "Detect if {tool_name} failed"
    compute: |
      from scripts.common.auto_heal import detect_failure

      result = str({output_var}) if '{output_var}' in dir() and {output_var} else ""
      failure = detect_failure(result, "{tool_name}")
      result = failure
    output: failure_{step_name}
    on_error: continue

  - name: quick_fix_auth_{step_name}
    description: "Auto-fix auth issues for {tool_name}"
    condition: "failure_{step_name} and failure_{step_name}.get('error_type') == 'auth'"
    tool: kube_login
    args:
      cluster: "{cluster_hint if cluster_hint != 'auto' else '{{ failure_' + step_name + ".get('fix_args', {}).get('cluster', 'stage') }}'}"
    output: auth_fix_{step_name}
    on_error: continue

  - name: quick_fix_vpn_{step_name}
    description: "Auto-fix network issues for {tool_name}"
    condition: "failure_{step_name} and failure_{step_name}.get('error_type') == 'network'"
    tool: vpn_connect
    args: {{}}
    output: vpn_fix_{step_name}
    on_error: continue

  - name: log_failure_{step_name}
    description: "Log failure to memory for learning"
    condition: "failure_{step_name} and failure_{step_name}.get('failed')"
    compute: |
      from scripts.common.auto_heal import log_failure

      fixed = bool(auth_fix_{step_name} if 'auth_fix_{step_name}' in dir() else None) or \\
              bool(vpn_fix_{step_name} if 'vpn_fix_{step_name}' in dir() else None)

      entry = log_failure(
          tool_name="{tool_name}",
          error_text=failure_{step_name}.get('error_text', ''),
          skill_name="{{{{ skill_name }}}}",
          fixed=fixed,
          memory_helper=memory
      )
      result = entry
    output: logged_failure_{step_name}
    on_error: continue
"""
    return yaml







