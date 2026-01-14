# Sprint Planning

Analyze backlog for sprint planning.

## Instructions

```text
skill_run("sprint_planning", '{"project": "AAP"}')
```

## What It Does

1. Lists backlog issues by priority
2. Identifies blocked items
3. Shows story point estimates
4. Suggests sprint candidates
5. Flags issues needing refinement

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `project` | Jira project | `AAP` |
| `sprint` | Target sprint name | Next sprint |
| `capacity` | Team capacity (points) | Auto |

## Examples

```bash
# Analyze backlog
skill_run("sprint_planning", '{"project": "AAP"}')

# Plan specific sprint
skill_run("sprint_planning", '{"project": "AAP", "sprint": "Sprint 42"}')
```
