# Research Topic

Deep dive on a topic using internal and external sources.

## Instructions

```text
skill_run("research_topic", '{"topic": "$TOPIC"}')
```

## What It Does

1. Searches internal codebase for relevant implementations
2. Checks memory for past learnings and patterns
3. Queries project knowledge for architecture context
4. Optionally searches the web for external documentation

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `topic` | The topic to research | Yes |
| `project` | Project to search in (auto-detected) | No |
| `depth` | Research depth: 'quick', 'normal', 'deep' | No |
| `focus` | Specific aspect to focus on | No |

## Examples

```bash
# Basic research
skill_run("research_topic", '{"topic": "pytest fixtures"}')

# Deep research with focus
skill_run("research_topic", '{"topic": "authentication", "depth": "deep", "focus": "security"}')

# Quick code-only search
skill_run("research_topic", '{"topic": "Redis caching", "depth": "quick"}')
```

## Depth Levels

- **quick**: Code search only
- **normal**: Code + memory patterns (default)
- **deep**: All sources including architecture context
