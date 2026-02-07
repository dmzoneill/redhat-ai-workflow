"""
Usage Pattern Classifier - Layer 5 of Auto-Heal System.

This module classifies errors as usage errors (Claude's mistakes) vs
infrastructure errors (auth, network, etc).

Part of Layer 5: Usage Pattern Learning
"""

import re
from typing import Any, Optional

# Usage Error Categories
USAGE_ERROR_TYPES = {
    "INCORRECT_PARAMETER": {
        "description": "Wrong value for a parameter",
        "examples": [
            "namespace not owned",
            "branch doesn't exist",
            "invalid image tag format",
        ],
        "learnable": True,
    },
    "MISSING_PREREQUISITE": {
        "description": "Tool called before required setup",
        "examples": [
            "no commits on branch",
            "namespace not reserved",
            "image not built yet",
        ],
        "learnable": True,
    },
    "WRONG_TOOL_SELECTION": {
        "description": "Used wrong tool for the task",
        "examples": [
            "used kubectl instead of bonfire",
            "used git_commit before git_add",
        ],
        "learnable": True,
    },
    "WORKFLOW_SEQUENCE": {
        "description": "Steps in wrong order",
        "examples": [
            "deploy before reserve",
            "push before commit",
            "create MR before push",
        ],
        "learnable": True,
    },
    "PARAMETER_FORMAT": {
        "description": "Parameter format incorrect",
        "examples": [
            "short SHA instead of full 40-char",
            "relative path instead of absolute",
            "wrong date format",
        ],
        "learnable": True,
    },
    "MISSING_PARAMETER": {
        "description": "Required parameter not provided",
        "examples": ["image_tag missing", "namespace not specified"],
        "learnable": False,  # Tools should validate this
    },
}

# Infrastructure error patterns (from Layer 3)
AUTH_PATTERNS = [
    "unauthorized",
    "401",
    "forbidden",
    "403",
    "token expired",
    "authentication required",
    "not authorized",
    "the server has asked for the client to provide credentials",
]

NETWORK_PATTERNS = [
    "no route to host",
    "connection refused",
    "network unreachable",
    "timeout",
    "dial tcp",
    "connection reset",
    "eof",
    "cannot connect",
]


def is_infrastructure_error(error_message: str) -> bool:
    """
    Check if error is infrastructure-related (auth, network).

    These are handled by Layer 3 auto-heal, not Layer 5.

    Args:
        error_message: Error message to check

    Returns:
        True if infrastructure error
    """
    if not error_message:
        return False

    error_lower = error_message.lower()

    # Check auth patterns
    if any(p in error_lower for p in AUTH_PATTERNS):
        return True

    # Check network patterns
    if any(p in error_lower for p in NETWORK_PATTERNS):
        return True

    return False


def _extract_namespace_from_error(error_message: str) -> Optional[str]:
    """Extract namespace name from error message."""
    # Pattern: "namespace 'ephemeral-abc-123' not owned"
    match = re.search(r"namespace\s+['\"]?([a-z0-9-]+)['\"]?", error_message, re.I)
    if match:
        return match.group(1)
    return None


def _extract_parameter_from_error(
    error_message: str, param_hint: str = ""
) -> Optional[str]:
    """Extract parameter value from error message."""
    if param_hint:
        # Try to find param_hint in message
        pattern = rf"{param_hint}[:\s=]+['\"]?([^'\"\\s]+)['\"]?"
        match = re.search(pattern, error_message, re.I)
        if match:
            return match.group(1)
    return None


def classify_error_type(
    tool_name: str, params: dict, error_message: str, result: str = ""
) -> dict:
    """
    Classify if this is a usage error vs infrastructure error.

    Args:
        tool_name: Name of tool that was called
        params: Parameters that were passed to the tool
        error_message: Error message from the tool
        result: Full result/output from the tool

    Returns:
        {
            "is_usage_error": bool,
            "error_category": str | None,
            "confidence": float,
            "evidence": dict,
            "learnable": bool
        }
    """

    # First check if it's infrastructure (existing Layer 3)
    if is_infrastructure_error(error_message):
        return {
            "is_usage_error": False,
            "error_category": None,
            "confidence": 0.0,
            "evidence": {},
            "learnable": False,
            "reason": "Infrastructure error (handled by Layer 3)",
        }

    # Now check usage patterns
    classification: dict[str, Any] = {
        "is_usage_error": False,
        "error_category": None,
        "confidence": 0.0,
        "evidence": {},
        "learnable": False,
    }

    # Pattern 1: Ownership/permission issues (not auth)
    ownership_patterns = [
        r"namespace.*not owned",
        r"cannot release.*not yours",
        r"you don't own",
        r"not owned by.*you",
    ]
    for pattern in ownership_patterns:
        if re.search(pattern, error_message, re.I):
            classification["is_usage_error"] = True
            classification["error_category"] = "INCORRECT_PARAMETER"
            classification["confidence"] = 0.9
            classification["learnable"] = True
            classification["evidence"]["pattern"] = "ownership_mismatch"
            classification["evidence"]["incorrect_param"] = (
                _extract_namespace_from_error(error_message)
            )
            classification["evidence"]["tool"] = tool_name
            return classification

    # Pattern 2: Format validation errors
    format_checks: dict[str, dict[str, Any]] = {
        r"manifest unknown": {
            "param_check": lambda p: "image_tag" in p
            and len(str(p.get("image_tag", ""))) < 40,
            "category": "PARAMETER_FORMAT",
            "incorrect_param": "image_tag",
            "expected_format": "40-character SHA",
            "confidence": 0.95,
        },
        r"invalid.*format": {
            "category": "PARAMETER_FORMAT",
            "confidence": 0.8,
        },
    }

    for pattern, config in format_checks.items():
        if re.search(pattern, error_message, re.I):
            # If there's a param check, validate it
            if "param_check" in config:
                if config["param_check"](params):
                    classification["is_usage_error"] = True
                    classification["error_category"] = config["category"]
                    classification["confidence"] = config["confidence"]
                    classification["learnable"] = True
                    classification["evidence"]["pattern"] = pattern
                    classification["evidence"]["incorrect_param"] = config.get(
                        "incorrect_param"
                    )
                    classification["evidence"]["expected_format"] = config.get(
                        "expected_format"
                    )
                    if "incorrect_param" in config:
                        classification["evidence"]["incorrect_value"] = params.get(
                            config["incorrect_param"]
                        )
                    return classification
            else:
                # No param check, just pattern match
                classification["is_usage_error"] = True
                classification["error_category"] = config["category"]
                classification["confidence"] = config["confidence"]
                classification["learnable"] = True
                classification["evidence"]["pattern"] = pattern
                return classification

    # Pattern 3: Workflow sequence errors (check before prerequisite to prioritize)
    # Some errors could be both, but workflow sequence is more specific
    sequence_indicators: dict[str, dict[str, Any]] = {
        "bonfire_deploy": {
            "before": ["bonfire_namespace_reserve"],
            "error_if_missing": r"namespace.*not.*found|no.*namespace",
        },
        "bonfire_namespace_release": {
            "before": ["bonfire_namespace_list"],
            "error_if_missing": r"namespace.*not owned",
        },
        "gitlab_mr_create": {
            "before": ["git_push"],
            "error_if_missing": r"branch.*not.*on.*remote|nothing to push",
        },
        "git_push": {
            "before": ["git_commit"],
            "error_if_missing": r"nothing to push|no commits",
        },
    }

    if tool_name in sequence_indicators:
        config = sequence_indicators[tool_name]
        if re.search(config["error_if_missing"], error_message, re.I):
            classification["is_usage_error"] = True
            classification["error_category"] = "WORKFLOW_SEQUENCE"
            classification["confidence"] = 0.8
            classification["learnable"] = True
            classification["evidence"]["missing_prerequisite"] = config["before"]
            classification["evidence"]["sequence_error"] = True
            return classification

    # Pattern 4: Prerequisite missing (more generic than workflow sequence)
    prerequisite_patterns = [
        r"no commits",
        r"nothing to push",
        r"namespace.*not.*exist",
        r"namespace.*does not exist",
        r"branch.*does not exist",
        r"image.*not.*found.*build",
    ]
    for pattern in prerequisite_patterns:
        if re.search(pattern, error_message, re.I):
            classification["is_usage_error"] = True
            classification["error_category"] = "MISSING_PREREQUISITE"
            classification["confidence"] = 0.85
            classification["learnable"] = True
            classification["evidence"]["pattern"] = "prerequisite_missing"
            classification["evidence"]["prerequisite_pattern"] = pattern
            return classification

    # Pattern 5: TTY/interactive errors (edge case - might be usage or tool issue)
    tty_patterns = [
        r"output is not a tty",
        r"not a terminal",
        r"input is not a terminal",
    ]
    for pattern in tty_patterns:
        if re.search(pattern, error_message, re.I):
            classification["is_usage_error"] = True
            classification["error_category"] = "WRONG_TOOL_SELECTION"
            classification["confidence"] = 0.7  # Lower confidence - might be env issue
            classification["learnable"] = True
            classification["evidence"]["pattern"] = "tty_required"
            classification["evidence"][
                "suggestion"
            ] = "Use non-interactive flag or debug_tool()"
            return classification

    # No pattern matched
    return classification


def get_error_category_info(category: str) -> dict:
    """Get information about an error category."""
    return USAGE_ERROR_TYPES.get(category, {})


def is_learnable_error(classification: dict) -> bool:
    """Check if error classification is learnable."""
    if not classification.get("is_usage_error"):
        return False

    category = classification.get("error_category")
    if not category:
        return False

    category_info = USAGE_ERROR_TYPES.get(category, {})
    return bool(category_info.get("learnable", False))
