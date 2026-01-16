# Knowledge Learn

Record learnings from completed tasks.

## Instructions

```text
knowledge_learn(learning="$LEARNING", task="$TASK_DESCRIPTION")
```

## What It Does

Records new learnings discovered during task completion:
1. Extracts key insights from the learning
2. Categorizes the learning (pattern, gotcha, fix, etc.)
3. Updates the appropriate knowledge section
4. Notifies you of the update

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `learning` | ✅ | What was learned |
| `task` | ⚪ | Task context (optional) |

## Examples

```bash
# Record a pattern discovery
knowledge_learn(
    learning="FastAPI dependency injection works best with Depends() for database sessions",
    task="Implementing user authentication"
)

# Record a gotcha
knowledge_learn(
    learning="Redis connection pool must be initialized before first request, not at import time",
    task="Fixing startup race condition"
)

# Record a testing insight
knowledge_learn(
    learning="Use pytest-asyncio with mode=auto for async test fixtures",
    task="Setting up async tests"
)
```

## Automatic Learning

The skill engine automatically calls `knowledge_learn` when:
1. A skill completes successfully
2. The skill result contains learnings
3. The learning is significant enough to record

## Learning Categories

Learnings are categorized as:
- **pattern** - Code patterns and best practices
- **gotcha** - Common pitfalls to avoid
- **fix** - Solutions to specific problems
- **architecture** - System design insights
- **testing** - Testing approaches

## See Also

- `/knowledge-update` - Update specific sections
- `/knowledge-scan` - Full project scan
- `/learn-pattern` - Record error patterns
