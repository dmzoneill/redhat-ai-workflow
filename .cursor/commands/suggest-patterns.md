# Suggest Patterns

Auto-discover error patterns from tool failure history.

## Instructions

Analyze failures and suggest new patterns:

```text
skill_run("suggest_patterns", '{}')
```

This will:
1. Analyze `memory/learned/tool_failures.yaml`
2. Group similar errors together
3. Identify frequently occurring errors (5+ times)
4. Suggest new patterns to add to memory
5. Show which errors aren't yet captured

## Examples

```bash
# Analyze all failures
skill_run("suggest_patterns", '{}')

# Focus on specific tool
skill_run("suggest_patterns", '{"tool_filter": "bonfire"}')

# Lower threshold for suggestions
skill_run("suggest_patterns", '{"min_occurrences": 3}')
```

## When to Use

- After a week of heavy tool usage
- When you notice repeated failures
- During maintenance/cleanup sessions
- To improve auto-remediation coverage

## Output

The skill will show:
- **Suggested Patterns**: New patterns worth adding
- **Occurrence Count**: How often each error appeared
- **Sample Errors**: Example failures for context
- **Recommended Fix**: Suggested remediation approach
