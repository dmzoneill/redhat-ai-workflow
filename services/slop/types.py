"""
Slop Bot Type Definitions.

Provides enums and type definitions for slop findings to ensure
consistent categorization and enable auto-fixing.

Usage:
    from services.slop.types import SlopCategory, SlopSeverity, AUTO_FIXABLE_CATEGORIES

    if finding.category in AUTO_FIXABLE_CATEGORIES:
        apply_auto_fix(finding)
"""

from enum import Enum


class SlopCategory(str, Enum):
    """
    Valid categories for slop findings.

    Categories are grouped by fixability:
    - High-confidence: Deterministic fixes, safe for auto-fix
    - Medium-confidence: May need human review
    - Low-confidence: Too risky for auto-fix
    """

    # High-confidence (auto-fixable, >90% safe)
    UNUSED_IMPORTS = "unused_imports"
    UNUSED_VARIABLES = "unused_variables"
    DEAD_CODE = "dead_code"
    BARE_EXCEPT = "bare_except"
    EMPTY_EXCEPT = "empty_except"
    UNREACHABLE_CODE = "unreachable_code"

    # Medium-confidence (review recommended)
    COMPLEXITY = "complexity"
    CODE_DUPLICATION = "code_duplication"
    STYLE_ISSUES = "style_issues"
    TYPE_ISSUES = "type_issues"
    AI_SLOP = "ai_slop"
    HALLUCINATED_IMPORTS = "hallucinated_imports"
    DOCSTRING_INFLATION = "docstring_inflation"
    PLACEHOLDER_CODE = "placeholder_code"

    # Low-confidence (no auto-fix, human review required)
    SECURITY = "security"
    RACE_CONDITIONS = "race_conditions"
    MEMORY_LEAKS = "memory_leaks"
    EXCEPTION_HANDLING = "exception_handling"
    VERBOSITY = "verbosity"

    # Fallback for unclassified findings
    UNKNOWN = "unknown"


class SlopSeverity(str, Enum):
    """Severity levels for findings."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


# Map loop names to their primary category
# Each loop focuses on one type of issue
LOOP_CATEGORY_MAP: dict[str, SlopCategory] = {
    "zombie": SlopCategory.DEAD_CODE,
    "leaky": SlopCategory.MEMORY_LEAKS,
    "racer": SlopCategory.RACE_CONDITIONS,
    "leaker": SlopCategory.SECURITY,
    "swallower": SlopCategory.EXCEPTION_HANDLING,
    "tangled": SlopCategory.COMPLEXITY,
    "copycat": SlopCategory.CODE_DUPLICATION,
    "sloppy": SlopCategory.AI_SLOP,
    "ghost": SlopCategory.HALLUCINATED_IMPORTS,
    "drifter": SlopCategory.VERBOSITY,
}

# Sub-categories that loops may produce
# Used when LLM identifies more specific issues within a loop's domain
LOOP_ALLOWED_CATEGORIES: dict[str, set[SlopCategory]] = {
    "zombie": {
        SlopCategory.DEAD_CODE,
        SlopCategory.UNUSED_IMPORTS,
        SlopCategory.UNUSED_VARIABLES,
        SlopCategory.UNREACHABLE_CODE,
    },
    "leaky": {
        SlopCategory.MEMORY_LEAKS,
    },
    "racer": {
        SlopCategory.RACE_CONDITIONS,
    },
    "leaker": {
        SlopCategory.SECURITY,
    },
    "swallower": {
        SlopCategory.EXCEPTION_HANDLING,
        SlopCategory.BARE_EXCEPT,
        SlopCategory.EMPTY_EXCEPT,
    },
    "tangled": {
        SlopCategory.COMPLEXITY,
    },
    "copycat": {
        SlopCategory.CODE_DUPLICATION,
    },
    "sloppy": {
        SlopCategory.AI_SLOP,
        SlopCategory.PLACEHOLDER_CODE,
        SlopCategory.DOCSTRING_INFLATION,
    },
    "ghost": {
        SlopCategory.HALLUCINATED_IMPORTS,
        SlopCategory.UNUSED_IMPORTS,
    },
    "drifter": {
        SlopCategory.VERBOSITY,
        SlopCategory.STYLE_ISSUES,
    },
}

# Categories that are safe for auto-fix (>90% confidence)
# These have deterministic fixes that rarely cause issues
AUTO_FIXABLE_CATEGORIES: set[SlopCategory] = {
    SlopCategory.UNUSED_IMPORTS,
    SlopCategory.UNUSED_VARIABLES,
    SlopCategory.DEAD_CODE,
    SlopCategory.BARE_EXCEPT,
    SlopCategory.EMPTY_EXCEPT,
    SlopCategory.UNREACHABLE_CODE,
}

# Confidence scores by category (0.0 - 1.0)
# Used to determine if a finding should be auto-fixed
CATEGORY_CONFIDENCE: dict[SlopCategory, float] = {
    # High confidence - deterministic fixes
    SlopCategory.UNUSED_IMPORTS: 0.95,
    SlopCategory.UNUSED_VARIABLES: 0.90,
    SlopCategory.UNREACHABLE_CODE: 0.95,
    SlopCategory.BARE_EXCEPT: 0.92,
    SlopCategory.EMPTY_EXCEPT: 0.90,
    SlopCategory.DEAD_CODE: 0.85,
    # Medium confidence - may need review
    SlopCategory.STYLE_ISSUES: 0.70,
    SlopCategory.TYPE_ISSUES: 0.65,
    SlopCategory.COMPLEXITY: 0.50,
    SlopCategory.CODE_DUPLICATION: 0.60,
    SlopCategory.AI_SLOP: 0.55,
    SlopCategory.PLACEHOLDER_CODE: 0.75,
    SlopCategory.DOCSTRING_INFLATION: 0.70,
    SlopCategory.HALLUCINATED_IMPORTS: 0.80,
    # Low confidence - no auto-fix
    SlopCategory.SECURITY: 0.30,
    SlopCategory.RACE_CONDITIONS: 0.20,
    SlopCategory.MEMORY_LEAKS: 0.25,
    SlopCategory.EXCEPTION_HANDLING: 0.40,
    SlopCategory.VERBOSITY: 0.35,
    SlopCategory.UNKNOWN: 0.0,
}

# Tool reliability scores (0.0 - 1.0)
# Static tools are more reliable than LLM-only findings
TOOL_RELIABILITY: dict[str, float] = {
    # Tier 1: High reliability static tools
    "vulture": 0.95,  # Dead code detection
    "ruff": 0.90,  # Fast linting
    "bandit": 0.85,  # Security scanning
    "mypy": 0.80,  # Type checking
    "radon": 0.75,  # Complexity analysis
    "jscpd": 0.80,  # Code duplication
    # Tier 2: Slop-specific tools
    "slop-detector": 0.70,
    "karpeslop": 0.70,
    # LLM-only (no tool backing)
    "": 0.50,  # Empty tool = LLM-only
}


def get_category_for_loop(loop_name: str) -> SlopCategory:
    """Get the primary category for a loop."""
    return LOOP_CATEGORY_MAP.get(loop_name, SlopCategory.UNKNOWN)


def is_category_allowed_for_loop(loop_name: str, category: SlopCategory) -> bool:
    """Check if a category is valid for a given loop."""
    allowed = LOOP_ALLOWED_CATEGORIES.get(loop_name, set())
    return category in allowed or category == LOOP_CATEGORY_MAP.get(loop_name)


def calculate_fix_confidence(category: SlopCategory, tool: str = "") -> float:
    """
    Calculate confidence score for auto-fixing a finding.

    Combines category confidence with tool reliability.

    Args:
        category: The finding's category
        tool: The tool that detected it (empty = LLM-only)

    Returns:
        Confidence score between 0.0 and 1.0
    """
    category_score = CATEGORY_CONFIDENCE.get(category, 0.0)
    tool_score = TOOL_RELIABILITY.get(tool, TOOL_RELIABILITY.get("", 0.5))

    # Weighted combination: 60% category, 40% tool
    return (category_score * 0.6) + (tool_score * 0.4)


def is_auto_fixable(category: SlopCategory, tool: str = "", min_confidence: float = 0.90) -> bool:
    """
    Check if a finding should be auto-fixed.

    Args:
        category: The finding's category
        tool: The tool that detected it
        min_confidence: Minimum confidence threshold (default 0.90)

    Returns:
        True if the finding meets auto-fix criteria
    """
    if category not in AUTO_FIXABLE_CATEGORIES:
        return False

    confidence = calculate_fix_confidence(category, tool)
    return confidence >= min_confidence


# Valid category values for schema validation
VALID_CATEGORIES: set[str] = {c.value for c in SlopCategory}
VALID_SEVERITIES: set[str] = {s.value for s in SlopSeverity}
