# ⚡ start_work

> Begin or resume working on a Jira issue

## Overview

The `start_work` skill is your entry point for beginning work on any Jira issue. It handles all the setup—fetching issue details, creating or checking out feature branches, and showing any existing MR feedback.

## Quick Start

```
skill_run("start_work", '{"issue_key": "AAP-12345"}')
```

Or with explicit repository:

```
skill_run("start_work", '{"issue_key": "AAP-12345", "repo_name": "automation-analytics-backend"}')
```

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `issue_key` | string | ✅ Yes | - | Jira issue key (e.g., AAP-12345) |
| `repo` | string | No | - | Repository path |
| `repo_name` | string | No | - | Repository name from config.json |

## Flow

```mermaid
flowchart TD
    START([Start]) --> RESOLVE[Resolve Repository]
    RESOLVE --> JIRA[Get Jira Issue Details]
    JIRA --> CHECK{Branch Exists?}
    
    CHECK -->|No| CREATE[Create Feature Branch]
    CREATE --> BRANCH[aap-12345-summary]
    BRANCH --> STATUS[Update Jira Status]
    
    CHECK -->|Yes| CHECKOUT[Checkout Existing Branch]
    CHECKOUT --> PULL[Git Pull Latest]
    PULL --> MR{Open MR?}
    
    MR -->|Yes| FEEDBACK[Get MR Feedback]
    FEEDBACK --> PIPELINE[Check Pipeline Status]
    PIPELINE --> CONTEXT[Show Context]
    
    MR -->|No| JIRA_STATUS[Check Jira Updates]
    JIRA_STATUS --> CONTEXT
    
    STATUS --> READY([Ready to Code! 🚀])
    CONTEXT --> READY
    
    style START fill:#6366f1,stroke:#4f46e5,color:#fff
    style READY fill:#10b981,stroke:#059669,color:#fff
    style CREATE fill:#3b82f6,stroke:#2563eb,color:#fff
    style FEEDBACK fill:#f59e0b,stroke:#d97706,color:#fff
```

## MCP Tools Used

- `jira_view_issue` - Get issue details
- `git_fetch` - Fetch remote branches
- `git_branch_list` - Check existing branches
- `git_checkout` - Switch branches
- `git_branch_create` - Create new branch
- `git_pull` - Update branch
- `gitlab_mr_list` - Find existing MRs
- `gitlab_mr_view` - Get MR details
- `gitlab_mr_comments` - Get feedback
- `gitlab_ci_status` - Check pipelines
- `jira_set_status` - Update issue status

## Repository Resolution

The skill intelligently resolves which repository to use:

1. **Explicit `repo` path** - Highest priority
2. **`repo_name` from config** - Looks up in `config.json`
3. **Issue key prefix** - Maps AAP → automation-analytics-backend
4. **Current directory** - Falls back to cwd if it's a git repo

## Scenarios

### Starting Fresh Work

```
You: Start working on AAP-12345

Claude: [Runs start_work skill]
        
        ✅ Step 1: Got issue details
           "Implement new REST API endpoint"
        
        ✅ Step 2: Created branch
           aap-12345-implement-new-rest-api-endpoint
        
        ✅ Step 3: Updated Jira status
           Status: In Progress
        
        Ready to code! Your branch is set up.
```

### Resuming Existing Work

```
You: Resume work on AAP-12345

Claude: [Runs start_work skill]
        
        ✅ Found existing branch: aap-12345-implement-rest-api
        ✅ Checked out and pulled latest
        
        📋 Existing MR: !456
        📊 Pipeline: Passed ✅
        
        💬 Reviewer Feedback:
        - jsmith: "Consider adding validation here"
        - mwilson: "Looks good, minor suggestion..."
        
        Ready to continue!
```

## Related Skills

- [create_mr](./create_mr.md) - Create merge request when done
- [sync_branch](./sync_branch.md) - Sync with main
- [close_issue](./close_issue.md) - Close when merged

