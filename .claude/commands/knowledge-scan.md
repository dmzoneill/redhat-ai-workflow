---
name: knowledge-scan
description: "Scan a project and generate persona-specific knowledge."
---
# Knowledge Scan

Scan a project and generate persona-specific knowledge.

## Instructions

```text
knowledge_scan(project="$PROJECT", persona="$PERSONA")
```

## What It Does

1. Scans the project directory structure
2. Analyzes code patterns and conventions
3. Detects testing frameworks and patterns
4. Identifies architecture and key components
5. Generates knowledge YAML file

## Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `project` | ⚪ | auto-detected | Project name from config.json |
| `persona` | ⚪ | current persona | developer, devops, tester, release |

## Examples

```bash
# Scan current project for current persona
knowledge_scan()

# Scan specific project
knowledge_scan(project="automation-analytics-backend")

# Scan for specific persona
knowledge_scan(project="automation-analytics-backend", persona="developer")

# Scan for devops knowledge
knowledge_scan(project="automation-analytics-backend", persona="devops")
```

## Generated Knowledge

The scan creates `memory/knowledge/personas/{persona}/{project}.yaml` with:

### Developer Persona
- Architecture overview
- Code patterns and conventions
- Testing approach
- Common gotchas

### DevOps Persona
- Deployment patterns
- Infrastructure details
- Monitoring setup
- Runbooks

### Tester Persona
- Test frameworks
- Test patterns
- Coverage requirements
- CI integration

### Release Persona
- Release process
- Version management
- Deployment targets
- Rollback procedures

## See Also

- `/bootstrap-knowledge` - Full knowledge generation for all personas
- `/knowledge-load` - Load knowledge into context
- `/knowledge-update` - Update specific knowledge sections
