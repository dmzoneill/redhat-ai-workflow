# Plan Implementation

Create a structured implementation plan from research findings.

## Instructions

```text
skill_run("plan_implementation", '{"goal": "$GOAL"}')
```

## What It Does

1. Analyzes the goal and breaks it into steps
2. Identifies files that need to be modified
3. Checks for existing patterns to follow
4. Identifies risks and unknowns
5. Creates a checklist-style plan

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `goal` | What you want to implement | Yes |
| `project` | Project to plan for (auto-detected) | No |
| `issue_key` | Jira issue key if for a specific ticket | No |
| `constraints` | Any constraints or requirements | No |

## Examples

```bash
# Basic plan
skill_run("plan_implementation", '{"goal": "Add Redis caching to billing API"}')

# With Jira issue
skill_run("plan_implementation", '{"goal": "Implement user authentication", "issue_key": "AAP-12345"}')

# With constraints
skill_run("plan_implementation", '{"goal": "Refactor database layer", "constraints": "must be backwards compatible"}')
```

## Workflow

1. Use `research_topic` first to understand the domain
2. Use `compare_options` if choosing between approaches
3. Use `plan_implementation` to create the action plan
4. Use `start_work` when ready to implement
