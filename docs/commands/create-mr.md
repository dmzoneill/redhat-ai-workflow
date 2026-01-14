# /create-mr

> Create a GitLab MR from the current branch with proper formatting.

## Overview

Create a GitLab MR from the current branch with proper formatting.

**Underlying Skill:** `create_mr`

This command is a wrapper that calls the `create_mr` skill. For detailed process information, see [skills/create_mr.md](../skills/create_mr.md).

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `issue_key` | No | - |

## Usage

### Examples

```bash
skill_run("create_mr", '{"issue_key": "$JIRA_KEY"}')
```

```bash
# Create MR for current branch
skill_run("create_mr", '{"issue_key": "AAP-61214"}')

# Create as draft
skill_run("create_mr", '{"issue_key": "AAP-61214", "draft": true}')
```

```bash
AAP-61214 - feat(billing): Add invoice generation
```

## Process Flow

This command invokes the `create_mr` skill. The process flow is:

```mermaid
flowchart LR
    START([User runs /create-mr]) --> VALIDATE[Validate Arguments]
    VALIDATE --> CALL[Call create_mr skill]
    CALL --> EXECUTE[Execute Skill Steps]
    EXECUTE --> RESULT[Return Result]
    RESULT --> END([Complete])

    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style END fill:#10b981,stroke:#059669,color:#fff
    style CALL fill:#3b82f6,stroke:#2563eb,color:#fff
```text

For detailed step-by-step process, see the [create_mr skill documentation](../skills/create_mr.md).

## Details

## Instructions

Create an MR for the current branch:

```
skill_run("create_mr", '{"issue_key": "$JIRA_KEY"}')
```

This will:
1. Validate commit format
2. Run local linting (black, flake8, yamllint)
3. Check for merge conflicts with main
4. Push the branch
5. Create MR with proper title and description
6. Link to Jira issue
7. Update Jira status

## Example

```bash
# Create MR for current branch
skill_run("create_mr", '{"issue_key": "AAP-61214"}')

# Create as draft
skill_run("create_mr", '{"issue_key": "AAP-61214", "draft": true}')
```text

## MR Title Format

```
AAP-61214 - feat(billing): Add invoice generation
```

## MR Description Template

```markdown

## What does this MR do

[Description from Jira]

## Related to AAP-61214

## Testing

- [ ] Unit tests pass
- [ ] Manual testing done
```


## Related Commands

_(To be determined based on command relationships)_
