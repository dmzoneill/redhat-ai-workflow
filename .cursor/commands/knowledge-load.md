# Knowledge Load

Load project knowledge into the current context.

## Instructions

```text
knowledge_load(project="$PROJECT", persona="$PERSONA")
```

## What It Does

Loads persona-specific knowledge for a project into the AI's context window, providing:
- Architecture understanding
- Code patterns and conventions
- Testing approaches
- Common gotchas and solutions

## Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `project` | ⚪ | auto-detected | Project name from config.json |
| `persona` | ⚪ | current persona | developer, devops, tester, release |

## Examples

```bash
# Load knowledge for current project and persona
knowledge_load()

# Load specific project knowledge
knowledge_load(project="automation-analytics-backend")

# Load devops knowledge
knowledge_load(project="automation-analytics-backend", persona="devops")
```

## Auto-Loading

Knowledge is automatically loaded during `session_start()` if:
1. A project is detected from the current directory
2. Knowledge exists for the current persona

If no knowledge exists, you'll be prompted to run `/knowledge-scan`.

## Knowledge Location

Knowledge files are stored at:
```
memory/knowledge/personas/{persona}/{project}.yaml
```

## See Also

- `/knowledge-scan` - Generate knowledge for a project
- `/knowledge-list` - List available knowledge files
- `/knowledge-update` - Update specific sections
