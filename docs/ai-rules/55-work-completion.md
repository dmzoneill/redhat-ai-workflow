# Work Completion: Update Jira After Work Done

## The Rule

**After completing work on a Jira issue, ALWAYS update the issue status and add a comment summarizing what was done.**

This keeps Jira in sync with reality and provides audit trail for the work.

## When to Update Jira

Update Jira after ANY of these actions:

| Action Completed | Jira Update |
|------------------|-------------|
| Created MR/PR | Transition to "In Review", add comment with MR link |
| MR merged | Transition to "Done" or "Closed", add comment |
| Code committed | Add comment summarizing changes |
| Bug fixed | Add comment with fix details |
| Investigation complete | Add comment with findings |
| Work blocked | Transition to "Blocked", add comment explaining blocker |
| Work paused | Add comment explaining why |

## How to Update Jira

### 1. Ensure Jira Tools Are Available

All personas include `jira_core` with essential tools. If you need additional Jira tools, load the developer persona:

```json
CallMcpTool(
  server: "project-0-redhat-ai-workflow-aa_workflow",
  toolName: "persona_load",
  arguments: {"persona": "developer"}
)
```

### 2. Transition the Issue Status

Use `jira_transition` to change the status:

```json
CallMcpTool(
  server: "project-0-redhat-ai-workflow-aa_workflow",
  toolName: "jira_transition",
  arguments: {
    "issue_key": "AAP-12345",
    "status": "In Review"
  }
)
```

Common status transitions:
- **Starting work**: "Open" → "In Progress"
- **MR created**: "In Progress" → "In Review"
- **MR merged**: "In Review" → "Done"
- **Work blocked**: Any → "Blocked"

### 3. Add a Comment

Use `jira_add_comment` to document what was done:

```json
CallMcpTool(
  server: "project-0-redhat-ai-workflow-aa_workflow",
  toolName: "jira_add_comment",
  arguments: {
    "issue_key": "AAP-12345",
    "comment": "MR created: https://gitlab.com/.../merge_requests/1234\n\nChanges:\n- Fixed the authentication bug\n- Added unit tests"
  }
)
```

## Comment Templates

### MR Created
```
MR created: {mr_url}

Changes:
- {change_1}
- {change_2}

Ready for review.
```

### MR Merged
```
MR merged: {mr_url}

Deployed to: {environment}
Commit: {sha}
```

### Investigation Complete
```
Investigation findings:

Root cause: {cause}
Recommendation: {recommendation}
```

### Work Blocked
```
Blocked by: {blocker_issue_key or description}

Reason: {explanation}
Next steps: {what_needs_to_happen}
```

## Workflow Integration

### After `create_mr` Skill
The `create_mr` skill should already handle this, but if doing manual MR creation:

1. Create the MR
2. Call `jira_transition(issue_key, "In Review")`
3. Call `jira_add_comment(issue_key, "MR created: {url}")`

### After Manual Code Work
When completing code changes outside of skills:

1. Commit the changes
2. Push to remote
3. Call `jira_add_comment(issue_key, "Committed: {summary of changes}")`
4. If work is complete, call `jira_transition(issue_key, "In Review")` or "Done"

### After `close_issue` Skill
The `close_issue` skill handles this automatically.

## Don't Forget

- **Always include the issue key** from the user's request or session context
- **Be specific in comments** - include MR links, commit SHAs, file names
- **Match the project's workflow** - AAP uses: Open → In Progress → In Review → Done
- **Check current status first** if unsure - use `jira_view_issue(issue_key)`

## Example Workflow

```
User: "fix the bug in AAP-12345 and create an MR"

Claude:
1. [Read the issue to understand the bug]
2. [Make the code fix]
3. [Create MR]
4. [Update Jira]:
   - jira_transition("AAP-12345", "In Review")
   - jira_add_comment("AAP-12345", "MR created: https://...")
5. [Report to user]
```
