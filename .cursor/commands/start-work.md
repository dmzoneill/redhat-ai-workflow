# Start Work on Issue

Begin work on a Jira issue - creates branch, sets up environment.

## Instructions

Start working on a Jira issue:

```text
skill_run("start_work", '{"issue_key": "$JIRA_KEY"}')
```

This will:
1. Fetch Jira issue details
2. Create a branch: `aap-XXXXX-short-description`
3. Switch to the branch
4. Show issue context and acceptance criteria
5. Suggest next steps

## Example

```bash
# Start work on an issue
skill_run("start_work", '{"issue_key": "AAP-61214"}')

# With specific repository
skill_run("start_work", '{"issue_key": "AAP-61214", "repo": "automation-analytics-backend"}')
```text

## Branch Naming

Branch will be created as:
```
aap-61214-short-description-from-jira-title
```

## What Happens Next

After starting work:
1. Make your code changes
2. Commit with: `AAP-61214 - type(scope): description`
3. Push and create MR: `/create-mr`
