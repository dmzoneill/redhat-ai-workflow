# Reindex All Vectors

Reindex all vector databases for semantic code search.

## Instructions

```text
skill_run("reindex_all_vectors", '{}')
```

This will update the vector indexes for all configured projects, ensuring semantic code search (`code_search`) works with the latest code.

## Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `force` | No | false | Force full re-index (not just changed files) |
| `projects` | No | "" | Comma-separated list of specific projects |
| `restart_watchers` | No | true | Restart file watchers after indexing |

## Examples

```bash
# Reindex all projects (incremental - only changed files)
skill_run("reindex_all_vectors", '{}')

# Force full reindex of all projects
skill_run("reindex_all_vectors", '{"force": true}')

# Reindex specific projects only
skill_run("reindex_all_vectors", '{"projects": "automation-analytics-backend,pdf-generator"}')

# Reindex without restarting watchers
skill_run("reindex_all_vectors", '{"restart_watchers": false}')
```

## What It Does

1. Gets list of all repositories from `config.json`
2. For each project with a valid path:
   - Runs `code_index` to update vector embeddings
   - Tracks files indexed and chunks created
3. Optionally restarts file watchers for auto-updates
4. Reports summary of all operations

## Scheduled Execution

This skill runs automatically every hour via the cron scheduler under the `workspace` persona.

## When to Use

- **After major code changes** - Ensure search reflects latest code
- **After git pull** - Update indexes with new changes
- **Troubleshooting search** - If `code_search` returns stale results
- **New project added** - Index a newly configured project

## Related Commands

- `/knowledge-refresh` - Refresh single project's knowledge
- `/bootstrap-knowledge` - Full knowledge bootstrap for a project
- `code_stats()` - View vector index statistics
- `code_health()` - Check vector search health
