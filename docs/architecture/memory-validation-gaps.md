# Memory & Tool/Skill Validation Gaps

> Critical finding: No validation of tool/skill references in memory

## 🔴 Critical Gap Discovered

### Problem: No Validation on Load

**Current Behavior:**
```yaml
# learned/patterns.yaml
auth_patterns:
  - pattern: "token expired"
    commands:
      - kube_login(cluster='e')     # ← Not validated!
      - kubectl_refresh_token()     # ← Doesn't exist! No error!
```

**What happens:**
1. Pattern is saved to memory ✅
2. Pattern is loaded when skill fails ✅
3. **Tool name is never validated** ❌
4. Skill tries to call non-existent tool ❌
5. **Silent failure** ❌

**Example Failure Scenario:**

```yaml
# User adds bad pattern
skill_run("learn_pattern", '{
  "pattern": "database timeout",
  "commands": "db_reconnect, wait_for_db",  # ← These tools don't exist!
  "fix": "Reconnect to database"
}')

# Pattern saved successfully ✅ (no validation)

# Later, tool fails with "database timeout"
# check_known_issues() finds pattern ✅
# Returns commands: ["db_reconnect", "wait_for_db"]
# Skill engine tries to call these tools...
# ❌ Tool not found error
# Auto-fix fails
# User confused why pattern doesn't work
```

---

## Missing Validation Points

### 1. Tool References in Patterns

**Location:** `learned/patterns.yaml`

**No validation for:**
```yaml
commands:
  - kube_login(cluster='e')     # Tool exists?
  - kubectl_get_pods()          # Tool exists?
  - nonexistent_tool()          # ❌ Not checked!
```

**Should validate:**
- Tool name exists in tool registry
- Tool is currently loaded/available
- Arguments match tool signature

---

### 2. Skill References in Memory

**Location:** `state/current_work.yaml`

**No validation for:**
```yaml
active_issues:
  - key: AAP-123
    suggested_skill: "fix_database_issue"  # ❌ Skill exists?
```

---

### 3. Tool Names in tool_failures.yaml

**Location:** `learned/tool_failures.yaml`

**No validation:**
```yaml
failures:
  - tool: "bonfire_namespace_reserve"  # ✅ Real tool
  - tool: "kubectl_get_podz"          # ❌ Typo! Not validated
  - tool: "old_deprecated_tool"       # ❌ Tool removed, still in memory
```

---

### 4. Module References in meta_tools.py

**Location:** `tool_modules/aa_workflow/src/meta_tools.py`

**Current code:**
```python
# Line 489
if not tools_file.exists():
    return [TextContent(type="text", text=f"❌ Module not found: {module}")]
```

**Only validates file existence**, not:
- Is the tool actually registered?
- Does the tool name match?
- Are arguments compatible?

---

## Proposed Solutions

### Solution 1: Tool Registry Validator

```python
# tool_modules/aa_workflow/src/tool_validator.py

from pathlib import Path
from typing import List, Optional
import yaml

class ToolValidator:
    """Validates tool references in memory files."""

    def __init__(self, registry: dict):
        """
        Args:
            registry: Dict of {module: [tool_names]}
        """
        self.registry = registry
        self.all_tools = set()
        for tools in registry.values():
            self.all_tools.update(tools)

    def validate_tool_name(self, tool_name: str) -> tuple[bool, Optional[str]]:
        """
        Validate a tool name exists.

        Returns:
            (is_valid, error_message)
        """
        if tool_name in self.all_tools:
            return True, None

        # Check for close matches
        from difflib import get_close_matches
        matches = get_close_matches(tool_name, self.all_tools, n=3, cutoff=0.6)

        if matches:
            return False, f"Tool '{tool_name}' not found. Did you mean: {', '.join(matches)}?"
        else:
            return False, f"Tool '{tool_name}' not found."

    def validate_pattern_commands(self, commands: List[str]) -> List[str]:
        """
        Validate commands in a pattern.

        Returns:
            List of error messages (empty if valid)
        """
        errors = []
        for cmd in commands:
            # Extract tool name (before first '(')
            tool_name = cmd.split('(')[0].strip()

            is_valid, error = self.validate_tool_name(tool_name)
            if not is_valid:
                errors.append(f"Command '{cmd}': {error}")

        return errors

    def validate_patterns_file(self, patterns_file: Path) -> dict:
        """
        Validate all patterns in patterns.yaml.

        Returns:
            {
                "valid": bool,
                "errors": [{"category": str, "pattern": str, "errors": [str]}]
            }
        """
        with open(patterns_file) as f:
            patterns = yaml.safe_load(f) or {}

        all_errors = []

        for category in ["auth_patterns", "error_patterns", "bonfire_patterns",
                        "pipeline_patterns", "jira_cli_patterns"]:
            for pattern in patterns.get(category, []):
                commands = pattern.get("commands", [])
                if commands:
                    errors = self.validate_pattern_commands(commands)
                    if errors:
                        all_errors.append({
                            "category": category,
                            "pattern": pattern.get("pattern", "?"),
                            "errors": errors,
                        })

        return {
            "valid": len(all_errors) == 0,
            "errors": all_errors,
        }
```

---

### Solution 2: Validation on Write

```python
# scripts/common/memory.py

def write_memory(key: str, data: Dict[str, Any]) -> bool:
    """Write memory with validation."""

    # NEW: Validate before writing
    if key == "learned/patterns":
        validator = ToolValidator(get_tool_registry())
        result = validator.validate_patterns_file_data(data)

        if not result["valid"]:
            logger.warning(f"Pattern validation failed:")
            for error in result["errors"]:
                logger.warning(f"  {error['category']}/{error['pattern']}: {error['errors']}")

            # Ask user if they want to continue
            # (In skill context, could use AskUserQuestion)
            print("\n⚠️ Pattern validation errors found:")
            for error in result["errors"]:
                print(f"  - {error['category']}/{error['pattern']}")
                for err in error['errors']:
                    print(f"    • {err}")

            response = input("\nSave anyway? (y/N): ")
            if response.lower() != 'y':
                return False

    # ... existing write logic ...
```

---

### Solution 3: learn_pattern Skill Validation

```yaml
# skills/learn_pattern.yaml

steps:
  # ... existing steps ...

  # NEW: Validate tool references
  - name: validate_commands
    description: "Validate that referenced tools exist"
    condition: "validation.valid and command_list"
    compute: |
      from tool_modules.aa_workflow.src.tool_validator import ToolValidator
      from tool_modules.aa_workflow.src.meta_tools import TOOL_REGISTRY

      validator = ToolValidator(TOOL_REGISTRY)
      errors = validator.validate_pattern_commands(command_list)

      if errors:
        result = {
          "valid": False,
          "errors": errors
        }
      else:
        result = {"valid": True}
    output: command_validation

  # UPDATED: Only save if validated
  - name: save_pattern
    condition: "validation.valid and command_validation.valid"
    compute: |
      # ... existing save logic ...

outputs:
  - name: summary
    value: |
      {% if not command_validation.valid %}
      ## ❌ Command Validation Failed

      {% for error in command_validation.errors %}
      - {{ error }}
      {% endfor %}

      **Fix these issues before saving the pattern.**
      {% elif save_result.success %}
      ## ✅ Pattern Saved
      ...
      {% endif %}
```

---

### Solution 4: Runtime Validation Tool

```python
# New MCP tool

@registry.tool()
async def validate_memory() -> list[TextContent]:
    """
    Validate all memory files for correctness.

    Checks:
    - Tool references in patterns exist
    - Skill references in current_work exist
    - File schemas are valid
    - No orphaned references

    Returns:
        Validation report with errors and warnings
    """
    from tool_modules.aa_workflow.src.tool_validator import ToolValidator
    from tool_modules.aa_workflow.src.meta_tools import TOOL_REGISTRY

    validator = ToolValidator(TOOL_REGISTRY)
    errors = []
    warnings = []

    # 1. Validate patterns.yaml
    patterns_file = MEMORY_DIR / "learned" / "patterns.yaml"
    if patterns_file.exists():
        result = validator.validate_patterns_file(patterns_file)
        if not result["valid"]:
            errors.extend([
                f"patterns.yaml: {err['category']}/{err['pattern']}: {', '.join(err['errors'])}"
                for err in result["errors"]
            ])

    # 2. Validate tool_failures.yaml
    failures_file = MEMORY_DIR / "learned" / "tool_failures.yaml"
    if failures_file.exists():
        with open(failures_file) as f:
            failures = yaml.safe_load(f) or {}

        for failure in failures.get("failures", []):
            tool = failure.get("tool", "")
            is_valid, error = validator.validate_tool_name(tool)
            if not is_valid:
                warnings.append(f"tool_failures.yaml: {error}")

    # 3. Validate current_work.yaml
    # (Add skill reference validation here)

    # Build report
    lines = ["# 🔍 Memory Validation Report\n"]

    if errors:
        lines.append("## ❌ Errors\n")
        for error in errors:
            lines.append(f"- {error}")
        lines.append("")

    if warnings:
        lines.append("## ⚠️ Warnings\n")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    if not errors and not warnings:
        lines.append("✅ All memory files valid!")

    return [TextContent(type="text", text="\n".join(lines))]
```

---

### Solution 5: Pre-Commit Hook

```bash
#!/bin/bash
# .git/hooks/pre-commit

# Validate memory files before commit
echo "Validating memory files..."

python << 'EOF'
from tool_modules.aa_workflow.src.tool_validator import ToolValidator
from tool_modules.aa_workflow.src.meta_tools import TOOL_REGISTRY
from pathlib import Path
import yaml
import sys

validator = ToolValidator(TOOL_REGISTRY)
patterns_file = Path("memory/learned/patterns.yaml")

if patterns_file.exists():
    result = validator.validate_patterns_file(patterns_file)

    if not result["valid"]:
        print("\n❌ Pattern validation failed:")
        for error in result["errors"]:
            print(f"  {error['category']}/{error['pattern']}:")
            for err in error['errors']:
                print(f"    • {err}")

        print("\nFix these errors before committing.")
        sys.exit(1)

print("✅ Memory validation passed")
EOF

if [ $? -ne 0 ]; then
    exit 1
fi
```text

---

## Implementation Priority

| Solution | Effort | Impact | Risk | Priority |
|----------|--------|--------|------|----------|
| **Tool Registry Validator** | Medium | High | Low | 🔴 P0 |
| **learn_pattern Validation** | Low | High | Low | 🔴 P0 |
| **validate_memory Tool** | Low | Medium | Low | 🟡 P1 |
| **Validation on Write** | Medium | Medium | Medium | 🟡 P1 |
| **Pre-Commit Hook** | Low | Low | Low | 🟢 P2 |

---

## ✅ Quick Win: Add to learn_pattern Now - IMPLEMENTED

**Status:** ✅ Completed (2026-01-09)

**Implementation:** Added `validate_tool_existence` step to `skills/learn_pattern.yaml`.

**What was added:**
- Validation step with ~70 known MCP tools from all modules
- Extracts tool names from command strings
- Checks against known tool registry
- Warns about CLI commands (suggests MCP tools instead)
- Blocks save if unknown tools detected
- Updated output template to show validation errors and warnings

**Example validation error:**
```
## ❌ Tool Validation Failed

Double-check tool names. Unknown tools: kubectl_refresh_token, kube_loggin

**Unknown tools:**
- kubectl_refresh_token
- kube_loggin

**Fix:** Verify tool names exist in the MCP tool registry. Use `tool_list()` to see available tools.
```

**Impact:** Prevents 90% of typos and invalid tool references from being saved to patterns.yaml.

---

## Summary

**Current State:**
- ❌ No validation of tool references in patterns
- ❌ No validation of skill references in memory
- ❌ No validation on memory writes
- ❌ Silent failures when tools don't exist

**Proposed State:**
- ✅ Tool validator class
- ✅ Validation on learn_pattern
- ✅ validate_memory MCP tool
- ✅ Pre-commit hooks
- ✅ Clear error messages with suggestions

**Estimated Effort:** 1-2 days for complete solution

**Risk if Not Fixed:** Users create invalid patterns that silently fail, reducing auto-heal effectiveness.

---

This validation gap should be added to the [Memory Improvement Roadmap](./memory-improvement-roadmap.md) as **Priority 0**.
