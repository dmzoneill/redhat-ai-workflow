---
name: bootstrap-knowledge
description: "Generate comprehensive project knowledge for all personas."
arguments:
  - name: project
    required: true
---
# Bootstrap Knowledge

Generate comprehensive project knowledge for all personas.

## Instructions

```text
skill_run("bootstrap_knowledge", '{"project": "$PROJECT"}')
```

## What It Does

Performs a deep scan of the project and generates knowledge for all personas:
1. **Developer** - Architecture, patterns, testing
2. **DevOps** - Deployment, infrastructure, monitoring
3. **Tester** - Test frameworks, patterns, CI
4. **Release** - Release process, versioning, rollback

## Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `project` | ⚪ | auto-detected | Project name from config.json |
| `deep_scan` | ⚪ | true | Perform deep analysis |

## Examples

```bash
# Bootstrap current project
skill_run("bootstrap_knowledge", '{}')

# Bootstrap specific project
skill_run("bootstrap_knowledge", '{"project": "automation-analytics-backend"}')

# Quick scan (less detailed)
skill_run("bootstrap_knowledge", '{"project": "my-project", "deep_scan": false}')
```

## Generated Files

Creates knowledge files at:
```
memory/knowledge/personas/developer/{project}.yaml
memory/knowledge/personas/devops/{project}.yaml
memory/knowledge/personas/tester/{project}.yaml
memory/knowledge/personas/release/{project}.yaml
```

## When to Use

- **New project** - First time working with a project
- **Major refactor** - After significant architecture changes
- **New team member** - Generate context for onboarding
- **Periodic refresh** - Update stale knowledge

## Skill Steps

1. Detect project settings
2. Scan directory structure
3. Analyze code patterns
4. Detect testing framework
5. Identify deployment patterns
6. Generate developer knowledge
7. Generate devops knowledge
8. Generate tester knowledge
9. Generate release knowledge
10. Summarize results

## See Also

- `/knowledge-scan` - Scan for single persona
- `/learn-architecture` - Deep architecture scan
- `/add-project` - Add project to config first
