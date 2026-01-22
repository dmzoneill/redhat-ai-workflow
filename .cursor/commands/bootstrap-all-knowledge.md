# Bootstrap All Knowledge

Build project knowledge for all configured projects and all personas.

## Instructions

```text
skill_run("bootstrap_all_knowledge", '{}')
```

This iterates through all projects in `config.json` and all knowledge-relevant personas, generating project knowledge for any missing combinations.

## Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `force` | No | false | Regenerate all knowledge even if it exists |
| `projects` | No | "" | Comma-separated list of specific projects |
| `personas` | No | "" | Comma-separated list of specific personas |
| `skip_existing` | No | true | Skip combinations that already have knowledge |

## Examples

```bash
# Bootstrap all projects for all personas (skip existing)
skill_run("bootstrap_all_knowledge", '{}')

# Force regenerate all knowledge
skill_run("bootstrap_all_knowledge", '{"force": true}')

# Bootstrap specific projects only
skill_run("bootstrap_all_knowledge", '{"projects": "automation-analytics-backend,pdf-generator"}')

# Bootstrap specific personas only
skill_run("bootstrap_all_knowledge", '{"personas": "developer,devops"}')

# Bootstrap specific project for specific persona
skill_run("bootstrap_all_knowledge", '{"projects": "automation-analytics-backend", "personas": "incident"}')

# Refresh all (don't skip existing)
skill_run("bootstrap_all_knowledge", '{"skip_existing": false}')
```

## What It Does

1. **Gets all projects** from `config.json` (dynamic)
2. **Discovers all personas** from `personas/*.yaml` files (dynamic)
3. **Checks existing knowledge** in `memory/knowledge/personas/<persona>/<project>.yaml`
4. **For each missing combination**:
   - Runs `knowledge_scan(project, persona)` to generate knowledge
   - Tracks success/failure
5. **Reports summary** with matrix of results

## Personas

By default, knowledge is generated for **all discovered personas** from `personas/*.yaml`. Use the `personas` parameter to filter to specific ones if needed.

## Scheduled Execution

Add to cron for automatic maintenance:

```json
{
  "name": "daily_knowledge_bootstrap",
  "skill": "bootstrap_all_knowledge",
  "cron": "0 6 * * *",
  "persona": "workspace",
  "enabled": true,
  "args": {
    "skip_existing": true
  }
}
```

This runs daily at 6 AM, generating knowledge for any new projects or personas.

To check scheduled jobs:
```bash
python scripts/cron_daemon.py --list-jobs
```

## When to Use

- **New project added** - Generate knowledge for all personas
- **New persona created** - Generate knowledge for all projects
- **Initial setup** - Bootstrap knowledge for entire workspace
- **After major changes** - Refresh knowledge with `force: true`

## Output Example

```
## 🧠 Knowledge Bootstrap Complete

**Timestamp:** 2026-01-20 15:30:00 GMT

---

### 📊 Summary

- **Projects processed:** 5
- **Personas processed:** 4
- **Total combinations:** 20
- **Already had knowledge:** 8
- **Generated/refreshed:** 12

### 📁 Projects

| Project | Path |
|---------|------|
| automation-analytics-backend | `/home/user/src/automation-analytics-...` |
| pdf-generator | `/home/user/src/pdf-generator...` |

### 🎭 Personas: developer, devops, incident, release

### 📋 Generation Results

| Project | Persona | Status | Action |
|---------|---------|--------|--------|
| automation-analytics-backend | developer | ✅ | missing |
| automation-analytics-backend | devops | ⏭️ | Already exists |
| pdf-generator | incident | ✅ | missing |
```

## Related Commands

- `/bootstrap-knowledge` - Bootstrap single project (all personas)
- `/knowledge-scan` - Scan single project/persona
- `/knowledge-refresh` - Refresh single project's knowledge
- `/reindex-vectors` - Reindex vector search (different from knowledge)

## See Also

- [Project Knowledge README](../../memory/knowledge/README.md)
- [Knowledge Tools Documentation](../../docs/commands/README.md#knowledge-tools)
