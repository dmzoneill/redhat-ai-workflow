---
name: knowledge-update
description: "Update a specific section of project knowledge."
---
# Knowledge Update

Update a specific section of project knowledge.

## Instructions

```text
knowledge_update(project="$PROJECT", persona="$PERSONA", section="$SECTION", content="$CONTENT")
```

## What It Does

Updates a specific section of the knowledge file without rewriting everything. Useful for:
- Adding new learnings
- Updating patterns
- Recording gotchas
- Refining architecture understanding

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `project` | ⚪ | Project name (auto-detected) |
| `persona` | ⚪ | Persona (auto-detected) |
| `section` | ✅ | Section to update |
| `content` | ✅ | New content (YAML format) |

## Sections

Common sections in knowledge files:
- `architecture` - System architecture
- `patterns` - Code patterns and conventions
- `testing` - Testing approach
- `gotchas` - Common pitfalls
- `deployment` - Deployment details
- `dependencies` - Key dependencies

## Examples

```bash
# Update architecture section
knowledge_update(
    section="architecture",
    content="api_framework: FastAPI\ndatabase: PostgreSQL"
)

# Add a gotcha
knowledge_update(
    section="gotchas",
    content="- Always use UTC for timestamps\n- Redis keys expire after 24h"
)

# Update testing patterns
knowledge_update(
    project="automation-analytics-backend",
    persona="developer",
    section="testing",
    content="framework: pytest\nmarkers: [unit, integration, smoke]"
)
```

## Notifications

When knowledge is updated, a notification is sent to inform you of the change.

## See Also

- `/knowledge-scan` - Full project scan
- `/knowledge-load` - Load knowledge into context
- `/knowledge-learn` - Record learnings from tasks
