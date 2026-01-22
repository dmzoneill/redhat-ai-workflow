---
name: compare-options
description: "Compare multiple approaches, libraries, or patterns before making a decision."
arguments:
  - name: question
    required: true
  - name: options
    required: true
---
# Compare Options

Compare multiple approaches, libraries, or patterns before making a decision.

## Instructions

```text
skill_run("compare_options", '{"question": "$QUESTION", "options": "$OPTIONS"}')
```

## What It Does

1. Takes a list of options to compare
2. Searches codebase for existing usage of each
3. Checks memory for past experiences
4. Creates a comparison matrix with pros/cons

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `question` | What decision are you making? | Yes |
| `options` | Comma-separated options to compare | Yes |
| `criteria` | Comma-separated evaluation criteria | No |
| `project` | Project context (auto-detected) | No |

## Examples

```bash
# Compare caching solutions
skill_run("compare_options", '{"question": "Which caching solution to use?", "options": "Redis, Memcached, Django cache"}')

# Compare with specific criteria
skill_run("compare_options", '{"question": "Which ORM to use?", "options": "SQLAlchemy, Django ORM", "criteria": "performance, ease of use, documentation"}')
```

## Next Steps

After comparing:
- Use **WebSearch** to research pros/cons
- Use `plan_implementation` once you've decided
