---
name: create-mr
description: "Create a GitLab MR from the current branch with proper formatting."
arguments:
  - name: issue_key
---
# Create Merge Request

Create a GitLab MR from the current branch with proper formatting.

## Instructions

Create an MR for the current branch:

```text
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
