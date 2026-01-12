# Layer 5: Usage Pattern Learning - Design Document

**Created**: 2026-01-12
**Status**: DESIGN PHASE
**Purpose**: Learn from Claude's usage mistakes to prevent repetition

---

## Problem Statement

**Current Gap**: The auto-heal system learns from infrastructure failures (auth, network) but NOT from Claude's usage mistakes (wrong parameters, incorrect tool selection, workflow errors).

**Result**: Claude repeats the same mistakes across sessions because there's no feedback loop.

**Goal**: Design a system that:
1. Detects when Claude makes a usage mistake
2. Extracts the pattern and prevention steps
3. Warns Claude BEFORE making the same mistake again
4. Evolves confidence through repeated observations

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    LAYER 5: USAGE LEARNING                   │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐ │
│  │   DETECT     │───▶│   EXTRACT    │───▶│    LEARN     │ │
│  │  Usage Error │    │   Pattern    │    │  & Update    │ │
│  └──────────────┘    └──────────────┘    └──────────────┘ │
│         │                                         │         │
│         │                                         ▼         │
│         │                              ┌──────────────────┐ │
│         │                              │  STORAGE         │ │
│         │                              │  usage_patterns  │ │
│         │                              └──────────────────┘ │
│         │                                         │         │
│         ▼                                         │         │
│  ┌──────────────┐                                │         │
│  │   PREVENT    │◀───────────────────────────────┘         │
│  │  Warn Claude │                                          │
│  └──────────────┘                                          │
│         │                                                   │
│         ▼                                                   │
│  ┌──────────────────────────────────────────────┐         │
│  │  PRE-TOOL-CALL WARNINGS                      │         │
│  │  "⚠️ Common mistake: Always check X first"   │         │
│  └──────────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Error Type Classification

### 1.1 Usage Error Categories

```python
USAGE_ERROR_TYPES = {
    "INCORRECT_PARAMETER": {
        "description": "Wrong value for a parameter",
        "examples": [
            "namespace not owned",
            "branch doesn't exist",
            "invalid image tag format"
        ],
        "learnable": True
    },

    "MISSING_PREREQUISITE": {
        "description": "Tool called before required setup",
        "examples": [
            "no commits on branch",
            "namespace not reserved",
            "image not built yet"
        ],
        "learnable": True
    },

    "WRONG_TOOL_SELECTION": {
        "description": "Used wrong tool for the task",
        "examples": [
            "used kubectl instead of bonfire",
            "used git_commit before git_add"
        ],
        "learnable": True
    },

    "WORKFLOW_SEQUENCE": {
        "description": "Steps in wrong order",
        "examples": [
            "deploy before reserve",
            "push before commit",
            "create MR before push"
        ],
        "learnable": True
    },

    "PARAMETER_FORMAT": {
        "description": "Parameter format incorrect",
        "examples": [
            "short SHA instead of full 40-char",
            "relative path instead of absolute",
            "wrong date format"
        ],
        "learnable": True
    },

    "MISSING_PARAMETER": {
        "description": "Required parameter not provided",
        "examples": [
            "image_tag missing",
            "namespace not specified"
        ],
        "learnable": False  # Tools should validate this
    }
}
```

### 1.2 Detection Algorithm

```python
def classify_error_type(
    tool_name: str,
    params: dict,
    error_message: str,
    result: str
) -> dict:
    """
    Classify if this is a usage error vs infrastructure error.

    Returns:
        {
            "is_usage_error": bool,
            "error_category": str,
            "confidence": float,
            "evidence": dict
        }
    """

    # First check if it's infrastructure (existing Layer 3)
    if is_infrastructure_error(error_message):
        return {"is_usage_error": False}

    # Now check usage patterns
    classification = {
        "is_usage_error": False,
        "error_category": None,
        "confidence": 0.0,
        "evidence": {}
    }

    # Pattern 1: Check for ownership/permission issues (not auth)
    ownership_patterns = [
        r"namespace.*not owned",
        r"cannot release.*not yours",
        r"permission denied.*user mismatch",
        r"you don't own"
    ]
    if any(re.search(p, error_message, re.I) for p in ownership_patterns):
        classification["is_usage_error"] = True
        classification["error_category"] = "INCORRECT_PARAMETER"
        classification["confidence"] = 0.9
        classification["evidence"]["pattern"] = "ownership_mismatch"
        classification["evidence"]["incorrect_param"] = _extract_namespace_from_error(error_message)
        return classification

    # Pattern 2: Format validation errors
    format_patterns = {
        r"manifest unknown": {
            "check": lambda p: "image_tag" in p and len(p["image_tag"]) < 40,
            "category": "PARAMETER_FORMAT",
            "incorrect_param": "image_tag",
            "expected_format": "40-character SHA"
        },
        r"invalid.*format": {
            "category": "PARAMETER_FORMAT"
        }
    }
    for pattern, config in format_patterns.items():
        if re.search(pattern, error_message, re.I):
            if "check" in config and config["check"](params):
                classification["is_usage_error"] = True
                classification["error_category"] = config["category"]
                classification["confidence"] = 0.95
                classification["evidence"]["pattern"] = pattern
                classification["evidence"]["incorrect_param"] = config.get("incorrect_param")
                return classification

    # Pattern 3: Prerequisite missing
    prerequisite_patterns = [
        r"no commits",
        r"nothing to push",
        r"namespace.*not.*exist",
        r"branch.*does not exist",
        r"image.*not.*found.*build.*first"
    ]
    if any(re.search(p, error_message, re.I) for p in prerequisite_patterns):
        classification["is_usage_error"] = True
        classification["error_category"] = "MISSING_PREREQUISITE"
        classification["confidence"] = 0.85
        classification["evidence"]["pattern"] = "prerequisite_missing"
        return classification

    # Pattern 4: Workflow sequence errors
    sequence_indicators = {
        "bonfire_deploy": {
            "before": ["bonfire_namespace_reserve"],
            "error_if_missing": r"namespace.*not.*found"
        },
        "gitlab_mr_create": {
            "before": ["git_push"],
            "error_if_missing": r"branch.*not.*on.*remote"
        },
        "git_push": {
            "before": ["git_commit"],
            "error_if_missing": r"nothing to push|no commits"
        }
    }

    if tool_name in sequence_indicators:
        config = sequence_indicators[tool_name]
        if re.search(config["error_if_missing"], error_message, re.I):
            classification["is_usage_error"] = True
            classification["error_category"] = "WORKFLOW_SEQUENCE"
            classification["confidence"] = 0.8
            classification["evidence"]["missing_prerequisite"] = config["before"]
            return classification

    return classification
```

---

## Phase 2: Pattern Extraction

### 2.1 Data Schema

```yaml
# memory/learned/usage_patterns.yaml

usage_patterns:

  # Example 1: Parameter mistake
  - id: "bonfire_release_wrong_namespace"
    tool: "bonfire_namespace_release"
    error_category: "INCORRECT_PARAMETER"

    mistake_pattern:
      error_regex: "namespace.*not owned|cannot release"
      parameter: "namespace"
      common_mistakes:
        - "using arbitrary namespace name instead of owned one"
        - "typo in namespace name"

    root_cause: "Claude didn't verify namespace ownership before release"

    prevention_steps:
      - action: "call_tool_first"
        tool: "bonfire_namespace_list"
        args: {"mine_only": true}
        reason: "Get list of YOUR owned namespaces"

      - action: "extract_from_result"
        field: "namespaces[0].name"
        validate: "namespace exists in result"

      - action: "use_extracted_value"
        parameter: "namespace"
        reason: "Use verified owned namespace"

    observations: 12
    success_after_prevention: 11
    confidence: 0.92

    first_seen: "2026-01-05T14:23:00"
    last_seen: "2026-01-10T09:12:00"

    related_patterns: []

  # Example 2: Format mistake
  - id: "bonfire_deploy_short_sha"
    tool: "bonfire_deploy"
    error_category: "PARAMETER_FORMAT"

    mistake_pattern:
      error_regex: "manifest unknown|image not found"
      parameter: "image_tag"
      common_mistakes:
        - "using 8-char short SHA"
        - "using 7-char abbreviated SHA"
      validation:
        check: "len(image_tag) < 40"
        expected: "40-character full git SHA"

    root_cause: "Claude used git short SHA instead of full 40-char SHA"

    prevention_steps:
      - action: "validate_parameter"
        parameter: "image_tag"
        validation:
          regex: "^[a-f0-9]{40}$"
          error_message: "Must be full 40-character SHA"

      - action: "call_tool_if_invalid"
        tool: "git_rev_parse"
        args: {"ref": "<short_sha>"}
        reason: "Expand short SHA to full 40-char SHA"

      - action: "use_expanded_value"
        parameter: "image_tag"

    observations: 45
    success_after_prevention: 43
    confidence: 0.96

    first_seen: "2025-12-20T10:15:00"
    last_seen: "2026-01-11T16:45:00"

  # Example 3: Workflow sequence
  - id: "gitlab_mr_no_commits"
    tool: "gitlab_mr_create"
    error_category: "MISSING_PREREQUISITE"

    mistake_pattern:
      error_regex: "nothing to push|no commits|branch has no commits"
      context: "branch created but no commits made"

    root_cause: "Claude created branch and tried to create MR without committing changes"

    prevention_steps:
      - action: "check_condition"
        condition: "git log --oneline | wc -l > 0"
        tool_equivalent: "git_log"
        args: {"max_count": 1}
        reason: "Verify commits exist on branch"

      - action: "warn_if_false"
        message: "⚠️ No commits on branch. Commit your changes first with git_commit()"

      - action: "suggest_tool"
        tool: "git_commit"
        reason: "Commit changes before creating MR"

    observations: 8
    success_after_prevention: 7
    confidence: 0.88

    first_seen: "2026-01-08T11:30:00"
    last_seen: "2026-01-11T14:20:00"

# Statistics
stats:
  total_usage_patterns: 23
  high_confidence: 15  # >= 0.85
  medium_confidence: 6  # 0.70 - 0.84
  low_confidence: 2    # < 0.70

  by_category:
    INCORRECT_PARAMETER: 8
    PARAMETER_FORMAT: 7
    MISSING_PREREQUISITE: 5
    WORKFLOW_SEQUENCE: 3

  prevention_success_rate: 0.94  # 94% success after warning

  last_updated: "2026-01-12T11:00:00"
```

### 2.2 Extraction Logic

```python
def extract_usage_pattern(
    tool_name: str,
    params: dict,
    error_message: str,
    classification: dict,
    context: dict
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
        Pattern dict ready to be stored
    """

    pattern = {
        "id": f"{tool_name}_{classification['error_category'].lower()}_{hash(error_message[:50])}",
        "tool": tool_name,
        "error_category": classification["error_category"],
        "mistake_pattern": {},
        "root_cause": "",
        "prevention_steps": [],
        "observations": 1,
        "success_after_prevention": 0,
        "confidence": 0.5,  # Start low
        "first_seen": datetime.now().isoformat(),
        "last_seen": datetime.now().isoformat()
    }

    # Extract based on category
    if classification["error_category"] == "INCORRECT_PARAMETER":
        pattern["mistake_pattern"] = _extract_incorrect_param_pattern(
            tool_name, params, error_message, classification["evidence"]
        )
        pattern["prevention_steps"] = _generate_param_validation_steps(
            tool_name, classification["evidence"]
        )

    elif classification["error_category"] == "PARAMETER_FORMAT":
        pattern["mistake_pattern"] = _extract_format_pattern(
            params, error_message, classification["evidence"]
        )
        pattern["prevention_steps"] = _generate_format_validation_steps(
            classification["evidence"]
        )

    elif classification["error_category"] == "MISSING_PREREQUISITE":
        pattern["mistake_pattern"] = _extract_prerequisite_pattern(
            tool_name, error_message, context
        )
        pattern["prevention_steps"] = _generate_prerequisite_steps(
            tool_name, context
        )

    elif classification["error_category"] == "WORKFLOW_SEQUENCE":
        pattern["mistake_pattern"] = _extract_sequence_pattern(
            tool_name, error_message, context, classification["evidence"]
        )
        pattern["prevention_steps"] = _generate_sequence_steps(
            classification["evidence"]
        )

    # Generate root cause description
    pattern["root_cause"] = _generate_root_cause(
        tool_name, classification, pattern["mistake_pattern"]
    )

    return pattern
```

---

## Phase 3: Prevention Mechanism

### 3.1 Pre-Tool-Call Checker

```python
class UsagePatternChecker:
    """Check learned usage patterns before tool execution."""

    def __init__(self):
        self.patterns = self._load_patterns()

    def _load_patterns(self) -> dict:
        """Load usage patterns from memory."""
        patterns_file = Path("memory/learned/usage_patterns.yaml")
        if not patterns_file.exists():
            return {"usage_patterns": [], "stats": {}}

        with open(patterns_file) as f:
            return yaml.safe_load(f) or {"usage_patterns": [], "stats": {}}

    def check_before_call(
        self,
        tool_name: str,
        params: dict,
        context: dict = None
    ) -> dict:
        """
        Check for learned patterns before calling tool.

        Returns:
            {
                "warnings": list[str],
                "preventions": list[dict],
                "should_block": bool,
                "suggestions": list[dict]
            }
        """
        result = {
            "warnings": [],
            "preventions": [],
            "should_block": False,
            "suggestions": []
        }

        # Find patterns for this tool
        tool_patterns = [
            p for p in self.patterns.get("usage_patterns", [])
            if p["tool"] == tool_name and p["confidence"] >= 0.75
        ]

        for pattern in tool_patterns:
            # Check if current params match mistake pattern
            if self._matches_mistake_pattern(params, pattern):
                warning = self._generate_warning(pattern)
                result["warnings"].append(warning)

                # Add prevention steps
                for step in pattern["prevention_steps"]:
                    result["preventions"].append({
                        "action": step["action"],
                        "details": step,
                        "pattern_id": pattern["id"]
                    })

                # High confidence patterns can block
                if pattern["confidence"] >= 0.90:
                    result["should_block"] = True

        return result

    def _matches_mistake_pattern(self, params: dict, pattern: dict) -> bool:
        """Check if current params match a learned mistake."""
        mistake = pattern["mistake_pattern"]

        # Check parameter format validation
        if "validation" in mistake:
            param_name = mistake.get("parameter")
            if param_name in params:
                val = params[param_name]

                # Check regex
                if "regex" in mistake["validation"]:
                    if not re.match(mistake["validation"]["regex"], str(val)):
                        return True

                # Check length
                if "check" in mistake["validation"]:
                    check = mistake["validation"]["check"]
                    if "len(" in check:
                        # Parse and evaluate
                        if eval(check.replace(param_name, f"'{val}'")):
                            return True

        # Check common mistakes
        if "common_mistakes" in mistake:
            param_name = mistake.get("parameter")
            if param_name in params:
                val = str(params[param_name])
                # Could do fuzzy matching here
                for common_mistake in mistake["common_mistakes"]:
                    if common_mistake in val.lower():
                        return True

        return False

    def _generate_warning(self, pattern: dict) -> str:
        """Generate human-readable warning message."""
        confidence_emoji = {
            0.95: "🔴",  # Very high
            0.85: "🟠",  # High
            0.75: "🟡"   # Medium
        }

        emoji = "🟡"
        for threshold, e in sorted(confidence_emoji.items(), reverse=True):
            if pattern["confidence"] >= threshold:
                emoji = e
                break

        warning = f"{emoji} **Common mistake detected** ({pattern['confidence']:.0%} confidence, {pattern['observations']} observations)\n"
        warning += f"   Tool: `{pattern['tool']}`\n"
        warning += f"   Issue: {pattern['root_cause']}\n"
        warning += f"\n   Prevention steps:\n"

        for i, step in enumerate(pattern['prevention_steps'], 1):
            warning += f"   {i}. {step.get('reason', step.get('action'))}\n"

        return warning
```

### 3.2 Integration with Tool Decorator

```python
# Update auto_heal_decorator.py

from server.usage_pattern_checker import UsagePatternChecker

usage_checker = UsagePatternChecker()

def auto_heal(cluster: ClusterType = "auto", max_retries: int = 1, retry_on: list[str] | None = None):
    """Decorator with Layer 5 integration."""

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            tool_name = func.__name__

            # ===== NEW: LAYER 5 CHECK =====
            usage_check = usage_checker.check_before_call(
                tool_name=tool_name,
                params=kwargs,
                context={}  # Could include recent tool calls
            )

            if usage_check["warnings"]:
                logger.info(f"Layer 5: Usage warnings for {tool_name}:")
                for warning in usage_check["warnings"]:
                    logger.info(warning)

                # For now, just log warnings (don't block)
                # In future, could block based on should_block flag

            # ===== Continue with existing auto-heal logic =====
            last_result = None

            for attempt in range(max_retries + 1):
                try:
                    result = await func(*args, **kwargs)
                    last_result = result

                    # ... existing error detection ...

                    # ===== NEW: LAYER 5 LEARNING =====
                    # Check if this was a usage error
                    from server.usage_pattern_learner import UsagePatternLearner

                    learner = UsagePatternLearner()
                    await learner.analyze_result(
                        tool_name=tool_name,
                        params=kwargs,
                        result=result,
                        context={}
                    )

                    return result

                except Exception as e:
                    # ... existing exception handling ...
                    raise

            return last_result

        return wrapper

    return decorator
```

---

## Phase 4: Learning & Confidence Evolution

### 4.1 Pattern Merger

```python
class UsagePatternLearner:
    """Learn and update usage patterns from observations."""

    def __init__(self):
        self.patterns_file = Path("memory/learned/usage_patterns.yaml")
        self.patterns = self._load_patterns()

    async def analyze_result(
        self,
        tool_name: str,
        params: dict,
        result: str,
        context: dict
    ):
        """Analyze tool result for usage errors and learn."""

        # Step 1: Classify error
        from server.auto_heal_decorator import classify_error_type

        classification = classify_error_type(
            tool_name=tool_name,
            params=params,
            error_message=result,
            result=result
        )

        if not classification["is_usage_error"]:
            return  # Not a usage error, skip

        # Step 2: Extract pattern
        from server.auto_heal_decorator import extract_usage_pattern

        new_pattern = extract_usage_pattern(
            tool_name=tool_name,
            params=params,
            error_message=result,
            classification=classification,
            context=context
        )

        # Step 3: Merge with existing patterns
        await self._merge_or_add_pattern(new_pattern)

    async def _merge_or_add_pattern(self, new_pattern: dict):
        """Merge with existing pattern or add new."""

        existing_patterns = self.patterns.get("usage_patterns", [])

        # Find similar pattern (70% similarity threshold)
        similar = None
        max_similarity = 0.0

        for existing in existing_patterns:
            if existing["tool"] != new_pattern["tool"]:
                continue

            if existing["error_category"] != new_pattern["error_category"]:
                continue

            similarity = self._calculate_similarity(existing, new_pattern)

            if similarity > max_similarity and similarity >= 0.70:
                max_similarity = similarity
                similar = existing

        if similar:
            # Merge with existing
            await self._merge_patterns(similar, new_pattern)
        else:
            # Add as new pattern
            existing_patterns.append(new_pattern)
            self.patterns["usage_patterns"] = existing_patterns

        # Update stats
        self._update_stats()

        # Save
        await self._save_patterns()

    async def _merge_patterns(self, existing: dict, new: dict):
        """Merge new observation into existing pattern."""

        # Increment observations
        existing["observations"] += 1

        # Update last_seen
        existing["last_seen"] = datetime.now().isoformat()

        # Merge common mistakes
        if "common_mistakes" in new["mistake_pattern"]:
            if "common_mistakes" not in existing["mistake_pattern"]:
                existing["mistake_pattern"]["common_mistakes"] = []

            for mistake in new["mistake_pattern"]["common_mistakes"]:
                if mistake not in existing["mistake_pattern"]["common_mistakes"]:
                    existing["mistake_pattern"]["common_mistakes"].append(mistake)

        # Update confidence
        existing["confidence"] = self._calculate_confidence(existing)

    def _calculate_confidence(self, pattern: dict) -> float:
        """Calculate confidence score based on observations and success rate."""

        obs = pattern["observations"]
        success = pattern.get("success_after_prevention", 0)

        # Base confidence from observation count
        if obs >= 100:
            base = 0.95
        elif obs >= 45:
            base = 0.92
        elif obs >= 20:
            base = 0.85
        elif obs >= 10:
            base = 0.75
        elif obs >= 5:
            base = 0.65
        else:
            base = 0.50

        # Adjust by success rate
        if obs > 0:
            success_rate = success / obs
            # Weight success rate 30%
            final = (base * 0.7) + (success_rate * 0.3)
        else:
            final = base

        return min(final, 0.99)  # Cap at 99%

    def _calculate_similarity(self, p1: dict, p2: dict) -> float:
        """Calculate similarity between two patterns (0-1)."""

        score = 0.0
        weights = {
            "error_regex": 0.4,
            "parameter": 0.3,
            "root_cause": 0.2,
            "prevention_steps": 0.1
        }

        # Compare error regex
        if "error_regex" in p1["mistake_pattern"] and "error_regex" in p2["mistake_pattern"]:
            if p1["mistake_pattern"]["error_regex"] == p2["mistake_pattern"]["error_regex"]:
                score += weights["error_regex"]
            else:
                # Partial match
                r1 = set(p1["mistake_pattern"]["error_regex"].split("|"))
                r2 = set(p2["mistake_pattern"]["error_regex"].split("|"))
                overlap = len(r1 & r2) / max(len(r1), len(r2))
                score += weights["error_regex"] * overlap

        # Compare parameter
        if "parameter" in p1["mistake_pattern"] and "parameter" in p2["mistake_pattern"]:
            if p1["mistake_pattern"]["parameter"] == p2["mistake_pattern"]["parameter"]:
                score += weights["parameter"]

        # Compare root cause (fuzzy)
        from difflib import SequenceMatcher
        cause_sim = SequenceMatcher(None, p1["root_cause"], p2["root_cause"]).ratio()
        score += weights["root_cause"] * cause_sim

        # Compare prevention steps count
        steps1 = len(p1["prevention_steps"])
        steps2 = len(p2["prevention_steps"])
        if steps1 > 0 and steps2 > 0:
            steps_sim = min(steps1, steps2) / max(steps1, steps2)
            score += weights["prevention_steps"] * steps_sim

        return score
```

---

## Phase 5: Claude Integration

### 5.1 Dynamic Context Injection

**Option 1: Inject into CLAUDE.md at session start**

```python
# server/session_manager.py

async def inject_usage_warnings():
    """Inject high-confidence patterns into Claude's context."""

    learner = UsagePatternLearner()
    patterns = learner.patterns.get("usage_patterns", [])

    # Filter high-confidence patterns
    high_conf = [p for p in patterns if p["confidence"] >= 0.85]

    # Sort by observations (most common first)
    high_conf.sort(key=lambda p: p["observations"], reverse=True)

    # Generate markdown
    warnings_md = "## ⚠️ Learned Usage Patterns (Auto-Generated)\n\n"
    warnings_md += f"*Based on {len(high_conf)} high-confidence patterns from {sum(p['observations'] for p in high_conf)} observations*\n\n"

    for pattern in high_conf[:15]:  # Top 15 only
        warnings_md += f"### {pattern['tool']}\n\n"
        warnings_md += f"**Common mistake** ({pattern['confidence']:.0%} confidence, {pattern['observations']} observations):\n"
        warnings_md += f"- **Error**: {pattern['mistake_pattern'].get('error_regex', 'Unknown')}\n"
        warnings_md += f"- **Root cause**: {pattern['root_cause']}\n"
        warnings_md += f"\n**Prevention**:\n"

        for i, step in enumerate(pattern['prevention_steps'], 1):
            if step['action'] == 'call_tool_first':
                warnings_md += f"{i}. First call `{step['tool']}({', '.join(f'{k}={v}' for k, v in step['args'].items())})`\n"
            elif step['action'] == 'validate_parameter':
                warnings_md += f"{i}. Validate `{step['parameter']}` matches `{step['validation'].get('regex')}`\n"
            elif step['action'] == 'check_condition':
                warnings_md += f"{i}. Check that {step['reason']}\n"

        warnings_md += "\n---\n\n"

    return warnings_md
```

**Option 2: Real-time warnings in tool results**

```python
# When tool is ABOUT to be called, inject warning

async def execute_tool_with_warnings(tool_name: str, params: dict):
    """Execute tool with pre-call warnings."""

    # Check patterns
    checker = UsagePatternChecker()
    check_result = checker.check_before_call(tool_name, params)

    # If warnings exist, prepend to output
    if check_result["warnings"]:
        warning_text = "\n".join(check_result["warnings"])

        # Return warning BEFORE calling tool
        return {
            "type": "warning",
            "message": warning_text,
            "proceed": not check_result["should_block"],
            "suggestions": check_result["preventions"]
        }

    # No warnings, proceed normally
    return await execute_tool(tool_name, params)
```

### 5.2 Feedback Loop Example

```
Claude: I'll release the ephemeral namespace.
  → bonfire_namespace_release(namespace="ephemeral-abc-123")

Layer 5 Pre-Check:
  🔴 Common mistake detected (92% confidence, 12 observations)
  Tool: bonfire_namespace_release
  Issue: Claude didn't verify namespace ownership before release

  Prevention steps:
  1. First call bonfire_namespace_list(mine_only=True)
  2. Extract namespace from result
  3. Use verified owned namespace

  Do you want to proceed anyway? [Blocked due to high confidence]

Claude: You're right. Let me check owned namespaces first.
  → bonfire_namespace_list(mine_only=True)

Result: ["ephemeral-def-456"]

Claude: I see, the correct namespace is ephemeral-def-456, not ephemeral-abc-123.
  → bonfire_namespace_release(namespace="ephemeral-def-456")

✅ Success! Layer 5 learned pattern prevented error.

[System logs: pattern["success_after_prevention"] += 1]
[Confidence updated: 92% → 93%]
```

---

## Implementation Phases

### Phase 1: Detection & Storage (Week 1)
- [ ] Implement `classify_error_type()`
- [ ] Implement `extract_usage_pattern()`
- [ ] Create `memory/learned/usage_patterns.yaml` schema
- [ ] Basic pattern storage (no merging yet)
- [ ] Unit tests for classification

### Phase 2: Learning & Merging (Week 2)
- [ ] Implement `UsagePatternLearner` class
- [ ] Pattern similarity calculation
- [ ] Pattern merging logic
- [ ] Confidence evolution algorithm
- [ ] Integration tests

### Phase 3: Prevention (Week 3)
- [ ] Implement `UsagePatternChecker` class
- [ ] Pre-tool-call validation
- [ ] Warning generation
- [ ] Integration with `@auto_heal` decorator
- [ ] Testing with real tool calls

### Phase 4: Claude Integration (Week 4)
- [ ] Session-start context injection
- [ ] Real-time warnings in tool results
- [ ] Success tracking and feedback
- [ ] UI/UX for warnings
- [ ] End-to-end testing

### Phase 5: Optimization (Week 5)
- [ ] Performance optimization
- [ ] Pattern pruning (remove low-confidence old patterns)
- [ ] Dashboard/reporting
- [ ] Documentation
- [ ] Production deployment

---

## Success Metrics

**Target Metrics** (3 months post-deployment):

| Metric | Baseline | Target | Measurement |
|--------|----------|--------|-------------|
| **Repeated usage errors** | 100% | < 20% | Count of same error within 7 days |
| **Prevention success rate** | N/A | > 85% | Warnings heeded / total warnings |
| **False positive rate** | N/A | < 10% | Incorrect warnings / total warnings |
| **Pattern confidence** | N/A | > 80% avg | Average confidence of active patterns |
| **High-conf patterns** | 0 | > 20 | Patterns with conf >= 0.85 |
| **Claude compliance** | N/A | > 90% | Claude follows prevention steps |

**Leading Indicators** (1 month):

- [ ] 50+ usage patterns captured
- [ ] 10+ high-confidence patterns (>= 0.85)
- [ ] 5+ prevented errors logged
- [ ] Pattern similarity working (70%+ merge rate)
- [ ] No false positive warnings reported

---

## Design Decisions (APPROVED)

1. **Blocking vs Warning**: ✅ **APPROVED**
   - Block if confidence >= 0.95, warn if 0.75-0.94
   - Rationale: High-confidence patterns prevent repeated mistakes

2. **Context Window**: ✅ **APPROVED**
   - Last 10 tool calls for sequence detection
   - Rationale: Sufficient for workflow pattern detection without bloat

3. **Pattern Decay**: ✅ **APPROVED**
   - Reduce confidence 5% every 30 days if not observed
   - Rationale: Environment changes, patterns become stale

4. **User Override**: ✅ **APPROVED**
   - Flag `--ignore-usage-warning` to bypass (log the override)
   - Rationale: Allow experienced users to override when necessary

5. **Multi-User Learning**: ✅ **APPROVED**
   - Global patterns, track per-user success rates
   - Rationale: More data = better patterns, but track effectiveness

6. **Pattern Export**: ✅ **APPROVED**
   - Manually review conf >= 0.95 patterns quarterly for promotion to pre-flight
   - Rationale: Best patterns should become first-class prevention

---

## Next Steps

1. **Review this design** with stakeholders
2. **Prototype Phase 1** (detection + storage) in isolated branch
3. **Test with 10 common mistakes** manually
4. **Iterate on schema** based on real patterns
5. **Implement Phases 2-5** iteratively

---

**Status**: ✅ APPROVED - IMPLEMENTATION IN PROGRESS (Phase 1)
**Estimated Total Effort**: 5 weeks (1 developer)
**Dependencies**: Existing auto-heal infrastructure (Layers 1-4)
**Risk**: Low (isolated system, can be disabled if issues)

**Implementation Started**: 2026-01-12

---

*End of Design Document*
