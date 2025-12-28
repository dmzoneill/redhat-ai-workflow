# ✅ Close Issue

Close a Jira issue and add a summary comment from commits.

## Instructions

```
skill_run("close_issue", '{"issue_key": "AAP-XXXXX"}')
```

## Options

| Parameter | Description | Default |
|-----------|-------------|---------|
| `issue_key` | Jira issue key (required) | - |
| `repo` | Repository path | Resolved from issue |
| `add_comment` | Add commit summary comment | `true` |

## Examples

```bash
# Close issue with commit summary
skill_run("close_issue", '{"issue_key": "AAP-12345"}')

# Close without adding comment
skill_run("close_issue", '{"issue_key": "AAP-12345", "add_comment": false}')
```

## What It Does

1. Gets the Jira issue details
2. Finds commits referencing the issue
3. Generates a summary comment from commits
4. Adds the comment to Jira
5. Transitions issue to Done

## Workflow Integration

```
/start-work AAP-12345     # Begin work
... code ...
/create-mr                # Create merge request
... review/merge ...
/close-issue AAP-12345    # Wrap up
```

## Comment Format

The auto-generated comment includes:
- MR link (if found)
- List of commits
- Files changed summary
- Merge date
