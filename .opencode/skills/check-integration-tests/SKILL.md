---
name: check-integration-tests
description: Check Konflux integration test status and results
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: check_integration_tests.yaml
  executable: "true"
---

# check_integration_tests

Check Konflux integration test status and results.

This skill:
- Lists integration test runs
- Gets test results
- Shows snapshots

Uses: konflux_list_integration_tests, konflux_get_test_results, konflux_list_snapshots,
      konflux_get_snapshot

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("check_integration_tests", '{
  "namespace": "aap-aa-tenant",
  "limit": 10
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load release persona for Konflux integration test tools**
2. **Check for known Konflux/test issues**
3. **Get testing-related gotchas from knowledge**
4. **Parse testing-related gotchas**
5. **List integration test runs**
6. **Parse test list**
7. **Get results of first failed test**
8. **List recent snapshots**
9. **Parse snapshot list**
10. **Detect failure patterns from integration test operations**
11. **Learn from Konflux auth failures**
12. **Log skill execution to session**
13. **Track integration test checks for patterns**
14. **Track failed tests for flakiness detection**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `namespace` | string | No | `aap-aa-tenant` | Konflux namespace |
| `limit` | integer | No | `10` | Number of results to show |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the check_integration_tests skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("check_integration_tests", '{
  "namespace": "aap-aa-tenant",
  "limit": 10
}')
```

### Via Command (if configured)

```
/check-integration-tests
```

## MCP Tools Used

- `knowledge_query`
- `konflux_get_test_results`
- `konflux_list_integration_tests`
- `konflux_list_snapshots`
- `learn_tool_fix`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/check_integration_tests.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/check_integration_tests.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
