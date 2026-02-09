"""Pattern Mining - Auto-discover error patterns from tool failures.

Analyzes tool_failures.yaml to find frequently occurring errors that aren't
already captured in patterns.yaml.

This script groups similar errors together using sequence matching and suggests
new patterns when an error occurs 5+ times.
"""

from difflib import SequenceMatcher
from pathlib import Path

import yaml


def mine_patterns_from_failures():
    """Analyze tool_failures.yaml to discover new patterns.

    Returns:
        List of suggested patterns with frequency and examples.
    """
    # Load memory files
    memory_dir = Path(__file__).parent.parent / "memory" / "learned"
    failures_file = memory_dir / "tool_failures.yaml"
    patterns_file = memory_dir / "patterns.yaml"

    if not failures_file.exists():
        return []

    try:
        with open(failures_file) as f:
            failures = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as e:
        print(f"Warning: Could not load failures file: {e}")
        return []

    try:
        with open(patterns_file) as f:
            patterns = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as e:
        print(f"Warning: Could not load patterns file: {e}")
        patterns = {}

    # Group failures by error text similarity
    error_groups = []

    for failure in failures.get("failures", [])[-500:]:  # Last 500 failures only
        error = failure.get("error_snippet", "")
        if not error or len(error) < 10:  # Skip very short errors
            continue

        tool = failure.get("tool", "")
        error_type = failure.get("error_type", "")

        # Find similar errors
        matched = False
        for group in error_groups:
            similarity = SequenceMatcher(
                None, error.lower(), group["representative"].lower()
            ).ratio()
            if similarity > 0.75:  # 75% similarity threshold
                group["count"] += 1
                group["errors"].append(error)
                group["tools"].add(tool)
                group["error_types"].add(error_type)
                matched = True
                break

        if not matched:
            error_groups.append(
                {
                    "representative": error,
                    "count": 1,
                    "errors": [error],
                    "tools": {tool},
                    "error_types": {error_type},
                }
            )

    # Suggest patterns for frequent errors (5+ occurrences)
    suggestions = []
    for group in error_groups:
        if group["count"] >= 5:
            # Extract a pattern from the representative error
            pattern_text = _extract_pattern(group["representative"])

            # Check if already learned
            already_learned = _is_pattern_known(pattern_text, patterns)

            if not already_learned:
                suggestions.append(
                    {
                        "pattern": pattern_text,
                        "frequency": group["count"],
                        "examples": group["errors"][:3],
                        "tools": list(group["tools"])[:5],
                        "error_types": list(group["error_types"]),
                        "recommended_category": _recommend_category(
                            pattern_text, group["error_types"]
                        ),
                    }
                )

    # Sort by frequency descending
    suggestions.sort(key=lambda x: x["frequency"], reverse=True)

    return suggestions


def _extract_pattern(error: str) -> str:
    """Extract a pattern from an error message.

    Removes specific details like IDs, URLs, timestamps to create a reusable pattern.
    """
    import re

    # Remove common variable parts
    pattern = error.lower()

    # Remove timestamps
    pattern = re.sub(r"\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}:\d{2}", "[timestamp]", pattern)

    # Remove UUIDs/hashes
    pattern = re.sub(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        "[uuid]",
        pattern,
    )
    pattern = re.sub(r"\b[0-9a-f]{40}\b", "[sha]", pattern)
    pattern = re.sub(r"\b[0-9a-f]{64}\b", "[sha256]", pattern)

    # Remove URLs
    pattern = re.sub(r"https?://[^\s]+", "[url]", pattern)

    # Remove namespace/pod names with ephemeral- prefix
    pattern = re.sub(r"ephemeral-[a-z0-9-]+", "[namespace]", pattern)

    # Remove specific numbers
    pattern = re.sub(r"\b\d+\b", "[n]", pattern)

    # Collapse whitespace
    pattern = " ".join(pattern.split())

    # Take first 80 chars as pattern
    if len(pattern) > 80:
        pattern = pattern[:77] + "..."

    return pattern


def _is_pattern_known(pattern_text: str, patterns: dict) -> bool:
    """Check if a pattern is already in patterns.yaml."""
    pattern_lower = pattern_text.lower()

    for category in [
        "error_patterns",
        "auth_patterns",
        "bonfire_patterns",
        "pipeline_patterns",
        "jira_cli_patterns",
    ]:
        for existing in patterns.get(category, []):
            existing_pattern = existing.get("pattern", "").lower()
            if existing_pattern and existing_pattern in pattern_lower:
                return True
            if pattern_lower in existing_pattern:
                return True

    return False


def _recommend_category(pattern_text: str, error_types: set) -> str:
    """Recommend which category this pattern belongs to."""
    pattern_lower = pattern_text.lower()

    if "auth" in error_types or any(
        word in pattern_lower
        for word in ["unauthorized", "forbidden", "token", "authentication", "login"]
    ):
        return "auth_patterns"

    if any(
        word in pattern_lower
        for word in ["bonfire", "namespace", "ephemeral", "reservation", "clowdapp"]
    ):
        return "bonfire_patterns"

    if any(
        word in pattern_lower
        for word in [
            "pipeline",
            "ci",
            "job",
            "gitlab-ci",
            "workflow",
            "build failed",
            "test failed",
        ]
    ):
        return "pipeline_patterns"

    if any(
        word in pattern_lower for word in ["jira", "issue", "jpat", "story", "epic"]
    ):
        return "jira_cli_patterns"

    return "error_patterns"


if __name__ == "__main__":
    # Test the miner
    suggestions = mine_patterns_from_failures()

    if not suggestions:
        print("✅ No new patterns to suggest - all common errors are already learned!")
    else:
        print(f"## 🔍 Suggested Patterns ({len(suggestions)} found)\n")

        for i, suggestion in enumerate(suggestions[:10], 1):  # Show top 10
            print(f"### {i}. {suggestion['pattern']}")
            print(f"**Frequency:** {suggestion['frequency']} occurrences")
            print(f"**Category:** {suggestion['recommended_category']}")
            print(f"**Tools affected:** {', '.join(suggestion['tools'])}")
            print("\n**Examples:**")
            for example in suggestion["examples"]:
                print(f"- {example}")
            print("\n**Action:** Run `learn_pattern` skill to add this pattern\n")
