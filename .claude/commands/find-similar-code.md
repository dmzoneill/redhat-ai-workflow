---
name: find-similar-code
description: "Find code similar to a given pattern or description."
arguments:
  - name: query
    required: true
---
# Find Similar Code

Find code similar to a given pattern or description.

## Instructions

```text
skill_run("find_similar_code", '{"query": "$QUERY"}')
```

## What It Does

1. Uses semantic search to find similar code
2. Ranks results by relevance
3. Shows code snippets with context

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `query` | Description of what to find | Yes |
| `project` | Project to search | No (auto-detected) |
| `limit` | Max results to return | No (default: 10) |

## Examples

```bash
# Find authentication code
skill_run("find_similar_code", '{"query": "user authentication and login"}')

# Find error handling patterns
skill_run("find_similar_code", '{"query": "exception handling and retry logic"}')
```
