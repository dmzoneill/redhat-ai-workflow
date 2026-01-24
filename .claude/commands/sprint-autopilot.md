---
name: sprint-autopilot
description: "Work on a sprint issue with dynamic persona switching - full automation from issue to MR."
arguments:
  - name: issue_key
---
# Sprint Autopilot

Work on a sprint issue with dynamic persona switching - full automation from issue to MR.

## Instructions

Start autopilot on a Jira issue:

```text
skill_run("sprint_autopilot", '{"issue_key": "$JIRA_KEY"}')
```

This will:
1. Analyze the Jira issue for clarity
2. Check git safety (uncommitted changes, protected branches)
3. Create feature branch via start_work
4. Research codebase for relevant context
5. Pause for implementation (you code in Cursor)
6. Create MR when ready
7. Optionally deploy to ephemeral for testing
8. Update Jira with progress

## Example

```bash
# Start autopilot on an issue
skill_run("sprint_autopilot", '{"issue_key": "AAP-61214"}')

# With ephemeral deployment check
skill_run("sprint_autopilot", '{"issue_key": "AAP-61214", "needs_deployment_check": true}')

# Auto-stash uncommitted changes
skill_run("sprint_autopilot", '{"issue_key": "AAP-61214", "auto_stash": true}')

# Skip clarity check (for well-defined issues)
skill_run("sprint_autopilot", '{"issue_key": "AAP-61214", "skip_clarity_check": true}')
```

## Stages

| Stage | Persona | Actions |
|-------|---------|---------|
| 1. Issue Analysis | developer | Analyze requirements, check clarity |
| 2. Branch Setup | developer | Create feature branch via start_work |
| 3. Code Research | developer | Search codebase for relevant patterns |
| 4. Implementation | (you) | Human/Claude does actual coding in Cursor |
| 5. MR Creation | developer | Create merge request |
| 6. Deployment Check | devops | Optional ephemeral deployment |
| 7. Finalize | developer | Update Jira, log timeline |

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `issue_key` | (required) | Jira issue key (e.g., AAP-12345) |
| `repo_path` | . | Path to the repository |
| `needs_deployment_check` | false | Deploy to ephemeral for testing |
| `auto_stash` | true | Auto-stash uncommitted changes |
| `skip_clarity_check` | false | Skip issue clarity check |

## Output

- **success**: Whether the skill completed successfully
- **mr_url**: URL of the created merge request
- **branch**: Name of the feature branch
- **timeline**: Events logged during execution

## Safety Features

- Checks for uncommitted changes before starting
- Won't work on protected branches (main, master)
- Validates issue exists and is assigned to you
- Logs all actions for audit trail
