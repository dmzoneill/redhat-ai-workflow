"""
Usage Pattern Extractor - Layer 5 of Auto-Heal System.

This module extracts learnable patterns from classified usage errors.

Part of Layer 5: Usage Pattern Learning
"""

import hashlib
from datetime import datetime
from typing import Optional


def _generate_pattern_id(tool_name: str, category: str, error_snippet: str) -> str:
    """Generate unique pattern ID."""
    # Use hash of tool + category + error snippet
    content = f"{tool_name}_{category}_{error_snippet[:50]}"
    hash_val = hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()[:8]
    return f"{tool_name}_{category.lower()}_{hash_val}"


def _extract_incorrect_param_pattern(
    tool_name: str, params: dict, error_message: str, evidence: dict
) -> dict:
    """Extract pattern for INCORRECT_PARAMETER errors."""
    pattern = {
        "error_regex": "",
        "parameter": None,
        "common_mistakes": [],
    }

    # Extract parameter from evidence
    if "incorrect_param" in evidence:
        pattern["parameter"] = evidence["incorrect_param"]
        pattern["common_mistakes"].append(
            f"using incorrect value for {evidence['incorrect_param']}"
        )

    # Build error regex from evidence
    if "pattern" in evidence:
        pattern["error_regex"] = evidence["pattern"]
    else:
        # Extract key phrases from error
        phrases = []
        if "not owned" in error_message.lower():
            phrases.append("not owned")
        if "cannot release" in error_message.lower():
            phrases.append("cannot release")
        pattern["error_regex"] = "|".join(phrases) if phrases else "error"

    # Tool-specific common mistakes
    if tool_name == "bonfire_namespace_release" and "namespace" in str(
        params.get("namespace", "")
    ):
        pattern["common_mistakes"].append(
            "using arbitrary namespace name instead of owned one"
        )
        pattern["common_mistakes"].append("typo in namespace name")

    return pattern


def _extract_format_pattern(params: dict, error_message: str, evidence: dict) -> dict:
    """Extract pattern for PARAMETER_FORMAT errors."""
    pattern = {
        "error_regex": "",
        "parameter": None,
        "validation": {},
        "common_mistakes": [],
    }

    # Extract from evidence
    if "incorrect_param" in evidence:
        pattern["parameter"] = evidence["incorrect_param"]

    if "expected_format" in evidence:
        pattern["validation"]["expected"] = evidence["expected_format"]

    if "incorrect_value" in evidence:
        incorrect_val = str(evidence["incorrect_value"])
        pattern["validation"]["check"] = f"len({pattern['parameter']}) < 40"

        # Common mistakes
        if len(incorrect_val) in [7, 8]:
            pattern["common_mistakes"].append("using 8-char short SHA")
            pattern["common_mistakes"].append("using 7-char abbreviated SHA")

    # Build error regex
    if "manifest unknown" in error_message.lower():
        pattern["error_regex"] = "manifest unknown|image not found"
        if "expected_format" not in pattern["validation"]:
            pattern["validation"]["expected"] = "40-character full git SHA"
        if not pattern.get("parameter"):
            pattern["parameter"] = "image_tag"
        if "regex" not in pattern["validation"]:
            pattern["validation"]["regex"] = "^[a-f0-9]{40}$"

    return pattern


def _extract_prerequisite_pattern(
    tool_name: str, error_message: str, context: dict
) -> dict:
    """Extract pattern for MISSING_PREREQUISITE errors."""
    pattern = {"error_regex": "", "context": ""}

    # Determine what prerequisite is missing
    if (
        "no commits" in error_message.lower()
        or "nothing to push" in error_message.lower()
    ):
        pattern["error_regex"] = "nothing to push|no commits|branch has no commits"
        pattern["context"] = "branch created but no commits made"

    elif "namespace.*not.*exist" in error_message.lower():
        pattern["error_regex"] = "namespace.*not.*exist|namespace.*does not exist"
        pattern["context"] = "namespace not reserved before use"

    elif "branch.*does not exist" in error_message.lower():
        pattern["error_regex"] = "branch.*does not exist|branch.*not.*found"
        pattern["context"] = "branch not created or pushed"

    elif "image.*not.*found" in error_message.lower():
        pattern["error_regex"] = "image.*not.*found.*build|image.*not.*built"
        pattern["context"] = "image not built by CI/CD yet"

    else:
        # Generic prerequisite
        pattern["error_regex"] = "prerequisite|not.*ready|not.*available"
        pattern["context"] = "prerequisite step missing"

    return pattern


def _extract_sequence_pattern(
    tool_name: str, error_message: str, context: dict, evidence: dict
) -> dict:
    """Extract pattern for WORKFLOW_SEQUENCE errors."""
    pattern = {"error_regex": "", "missing_step": None, "correct_sequence": []}

    # Extract missing prerequisite from evidence
    if "missing_prerequisite" in evidence:
        pattern["missing_step"] = evidence["missing_prerequisite"]

    # Build sequence based on tool
    if tool_name == "bonfire_deploy":
        pattern["error_regex"] = "namespace.*not.*found|no.*namespace"
        pattern["correct_sequence"] = ["bonfire_namespace_reserve", "bonfire_deploy"]

    elif tool_name == "gitlab_mr_create":
        pattern["error_regex"] = "branch.*not.*on.*remote|nothing to push"
        pattern["correct_sequence"] = ["git_commit", "git_push", "gitlab_mr_create"]

    elif tool_name == "git_push":
        pattern["error_regex"] = "nothing to push|no commits"
        pattern["correct_sequence"] = ["git_add", "git_commit", "git_push"]

    elif tool_name == "bonfire_namespace_release":
        pattern["error_regex"] = "namespace.*not owned"
        pattern["correct_sequence"] = [
            "bonfire_namespace_list",
            "bonfire_namespace_release",
        ]

    return pattern


def _generate_param_validation_steps(tool_name: str, evidence: dict) -> list[dict]:
    """Generate prevention steps for parameter validation."""
    steps = []

    # For ownership issues
    if evidence.get("pattern") == "ownership_mismatch":
        steps.append(
            {
                "action": "call_tool_first",
                "tool": "bonfire_namespace_list",
                "args": {"mine_only": True},
                "reason": "Get list of YOUR owned namespaces",
            }
        )
        steps.append(
            {
                "action": "extract_from_result",
                "field": "namespaces[0].name",
                "validate": "namespace exists in result",
                "reason": "Verify namespace is owned by you",
            }
        )
        steps.append(
            {
                "action": "use_extracted_value",
                "parameter": "namespace",
                "reason": "Use verified owned namespace",
            }
        )

    return steps


def _generate_format_validation_steps(evidence: dict) -> list[dict]:
    """Generate prevention steps for format validation."""
    steps = []

    if (
        evidence.get("incorrect_param") == "image_tag"
        and evidence.get("expected_format") == "40-character SHA"
    ):
        steps.append(
            {
                "action": "validate_parameter",
                "parameter": "image_tag",
                "validation": {
                    "regex": "^[a-f0-9]{40}$",
                    "error_message": "Must be full 40-character SHA",
                },
                "reason": "Ensure full 40-char SHA, not short SHA",
            }
        )
        steps.append(
            {
                "action": "call_tool_if_invalid",
                "tool": "git_rev_parse",
                "args": {"ref": "<short_sha>"},
                "reason": "Expand short SHA to full 40-char SHA",
            }
        )
        steps.append(
            {
                "action": "use_expanded_value",
                "parameter": "image_tag",
                "reason": "Use full SHA",
            }
        )

    return steps


def _generate_prerequisite_steps(tool_name: str, context: dict) -> list[dict]:
    """Generate prevention steps for prerequisite checks."""
    steps = []

    # Tool-specific prerequisites
    if tool_name == "gitlab_mr_create":
        steps.append(
            {
                "action": "check_condition",
                "condition": "git log --oneline | wc -l > 0",
                "tool_equivalent": "git_log",
                "args": {"max_count": 1},
                "reason": "Verify commits exist on branch",
            }
        )
        steps.append(
            {
                "action": "warn_if_false",
                "message": "⚠️ No commits on branch. Commit your changes first with git_commit()",
                "reason": "Prevent MR creation without commits",
            }
        )
        steps.append(
            {
                "action": "suggest_tool",
                "tool": "git_commit",
                "reason": "Commit changes before creating MR",
            }
        )

    elif tool_name == "bonfire_deploy":
        steps.append(
            {
                "action": "check_tool_called",
                "tool": "bonfire_namespace_reserve",
                "reason": "Ensure namespace reserved before deploy",
            }
        )
        steps.append(
            {
                "action": "warn_if_not_called",
                "message": "⚠️ No namespace reserved. Call bonfire_namespace_reserve() first",
                "reason": "Deploy requires existing namespace",
            }
        )

    return steps


def _generate_sequence_steps(evidence: dict) -> list[dict]:
    """Generate prevention steps for sequence errors."""
    steps = []

    if "missing_prerequisite" in evidence:
        for prereq_tool in evidence["missing_prerequisite"]:
            steps.append(
                {
                    "action": "call_tool_first",
                    "tool": prereq_tool,
                    "reason": f"Required prerequisite: {prereq_tool} must be called first",
                }
            )

    steps.append(
        {
            "action": "verify_prerequisite_success",
            "reason": "Ensure prerequisite completed successfully",
        }
    )

    return steps


def _generate_root_cause(
    tool_name: str, classification: dict, mistake_pattern: dict
) -> str:
    """Generate human-readable root cause description."""
    category = classification.get("error_category", "")

    if category == "INCORRECT_PARAMETER":
        param = mistake_pattern.get("parameter", "parameter")
        return f"Claude used incorrect value for '{param}' parameter"

    elif category == "PARAMETER_FORMAT":
        param = mistake_pattern.get("parameter", "parameter")
        expected = mistake_pattern.get("validation", {}).get(
            "expected", "correct format"
        )
        return f"Claude used wrong format for '{param}' (expected: {expected})"

    elif category == "MISSING_PREREQUISITE":
        return (
            f"Claude called {tool_name} before completing required prerequisite steps"
        )

    elif category == "WORKFLOW_SEQUENCE":
        prereqs = classification.get("evidence", {}).get("missing_prerequisite", [])
        if prereqs:
            return (
                f"Claude called {tool_name} without first calling {', '.join(prereqs)}"
            )
        return f"Claude called {tool_name} in wrong workflow order"

    else:
        return f"Claude made a usage error with {tool_name}"


def extract_usage_pattern(
    tool_name: str,
    params: dict,
    error_message: str,
    classification: dict,
    context: Optional[dict] = None,
) -> dict:
    """
    Extract a learnable pattern from a usage error.

    Args:
        tool_name: Name of tool that failed
        params: Parameters that were passed
        error_message: Error message returned
        classification: Result from classify_error_type()
        context: Additional context (previous tool calls, etc.)

    Returns:
        Pattern dict ready to be stored in usage_patterns.yaml
    """
    if context is None:
        context = {}

    pattern = {
        "id": _generate_pattern_id(
            tool_name, classification.get("error_category", "unknown"), error_message
        ),
        "tool": tool_name,
        "error_category": classification.get("error_category"),
        "mistake_pattern": {},
        "root_cause": "",
        "prevention_steps": [],
        "observations": 1,
        "success_after_prevention": 0,
        "confidence": 0.5,  # Start low, will increase with observations
        "first_seen": datetime.now().isoformat(),
        "last_seen": datetime.now().isoformat(),
        "related_patterns": [],
    }

    # Extract based on category
    evidence = classification.get("evidence", {})
    category = classification.get("error_category")

    if category == "INCORRECT_PARAMETER":
        pattern["mistake_pattern"] = _extract_incorrect_param_pattern(
            tool_name, params, error_message, evidence
        )
        pattern["prevention_steps"] = _generate_param_validation_steps(
            tool_name, evidence
        )

    elif category == "PARAMETER_FORMAT":
        pattern["mistake_pattern"] = _extract_format_pattern(
            params, error_message, evidence
        )
        pattern["prevention_steps"] = _generate_format_validation_steps(evidence)

    elif category == "MISSING_PREREQUISITE":
        pattern["mistake_pattern"] = _extract_prerequisite_pattern(
            tool_name, error_message, context
        )
        pattern["prevention_steps"] = _generate_prerequisite_steps(tool_name, context)

    elif category == "WORKFLOW_SEQUENCE":
        pattern["mistake_pattern"] = _extract_sequence_pattern(
            tool_name, error_message, context, evidence
        )
        pattern["prevention_steps"] = _generate_sequence_steps(evidence)

    # Generate root cause description
    pattern["root_cause"] = _generate_root_cause(
        tool_name, classification, pattern["mistake_pattern"]
    )

    return pattern
