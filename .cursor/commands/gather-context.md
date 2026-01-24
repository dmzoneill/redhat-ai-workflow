# Gather Context

Gather relevant context for a task using semantic search and knowledge base.

## Instructions

Gather context before starting work on a feature, bug, or investigation:

```text
skill_run("gather_context", '{"query": "$QUERY"}')
```

This will:
1. Search codebase for related code (semantic search)
2. Load project knowledge and gotchas
3. Check for known issues and patterns
4. Return structured context for decision making

## Example

```bash
# Gather context for a feature
skill_run("gather_context", '{"query": "billing calculation vCPU hours"}')

# Gather context for a bug investigation
skill_run("gather_context", '{"query": "authentication timeout error"}')

# Gather context with specific project
skill_run("gather_context", '{"query": "API rate limiting", "project": "automation-analytics-backend"}')

# Minimal context (just code search)
skill_run("gather_context", '{"query": "webhook handler", "include_architecture": false, "include_gotchas": false}')
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `query` | (required) | What to search for |
| `project` | automation-analytics-backend | Project for knowledge lookup |
| `code_limit` | 5 | Max code search results |
| `include_architecture` | true | Include architecture overview |
| `include_gotchas` | true | Include project gotchas |
| `include_patterns` | true | Include coding patterns |
| `tool_name` | "" | Tool name for known issues lookup |

## Output

Returns structured context with:
- **code**: Related code snippets from semantic search
- **gotchas**: Project-specific warnings and tips
- **patterns**: Coding patterns to follow
- **architecture**: System architecture overview
- **known_issues**: Previously encountered issues and fixes
