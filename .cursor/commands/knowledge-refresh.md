# Knowledge Refresh

Refresh project knowledge and vector index.

## Instructions

Update knowledge and vector index:

```text
skill_run("knowledge_refresh", '{}')
```

This will:
1. Update the vector index with recent code changes
2. Re-scan project for architecture changes
3. Refresh knowledge confidence scores
4. Restart file watchers if needed

## Examples

```bash
# Refresh all knowledge
skill_run("knowledge_refresh", '{}')

# Refresh specific project
skill_run("knowledge_refresh", '{"project": "automation-analytics-backend"}')

# Force full re-index
skill_run("knowledge_refresh", '{"force": true}')
```

## When to Use

- After pulling major changes
- After switching branches
- If vector search results seem stale
- After adding new files/modules
- Periodically (weekly) for maintenance

## What Gets Updated

- **Vector Index**: Code embeddings for semantic search
- **Project Knowledge**: Architecture, patterns, gotchas
- **Confidence Scores**: Based on freshness of data
