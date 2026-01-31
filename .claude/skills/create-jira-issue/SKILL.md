---
name: create-jira-issue
description: Create a new Jira issue with proper linking and team notification
license: MIT
compatibility: opencode
metadata:
  version: "1.2"
  source: create_jira_issue.yaml
  executable: "true"
---

# create_jira_issue

Create a new Jira issue with proper linking and team notification.

**Enhanced with Semantic Search:**
- Searches codebase for related code based on issue summary
- Adds relevant file references to issue description
- Identifies potential areas of impact
- Suggests related components/modules

Use for:
- Creating bug reports (with relevant code context)
- Creating feature requests (with implementation hints)
- Creating sub-tasks
- Linking related issues

The skill will:
1. Search codebase for related code (semantic search)
2. Create the issue with enriched description
3. Link to related issues
4. Transition to appropriate status
5. Notify team channel via Slack

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("create_jira_issue", '{
  "summary": "example-summary",
  "description": "example-description",
  "issue_type": "Task",
  "project": "AAP",
  "repo": "automation-analytics-backend",
  "search_code": true,
  "notify_team": true,
  "labels": "example-labels",
  "priority": "Medium",
  "link_to": "example-link_to",
  "link_type": "relates to",
  "start_progress": false,
  "slack_format": false,
  "problem_description": "example-problem_description",
  "user_story": "example-user_story",
  "acceptance_criteria": "example-acceptance_criteria",
  "definition_of_done": "example-definition_of_done",
  "components": "example-components"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for Jira tools**
2. **Initialize failure tracking**
3. **Check for known Jira issues**
4. **Get Jira best practices from knowledge**
5. **Parse Jira best practices**
6. **Search codebase for code related to the issue**
7. **Parse semantic search results**
8. **Build enhanced description with code context**
9. **Create the Jira issue with enhanced description**
10. **Parse issue creation result**
11. **Link to related issue**
12. **Parse link result**
13. **Update issue with additional fields**
14. **Transition to In Progress**
15. **Get the created issue details**
16. **Log issue creation**
17. **Track issue creations for patterns**
18. **Add created issue to active issues**
19. **Build Slack notification message for the new issue**
20. **Send Slack notification to team channel**
21. **Parse notification result**
22. **Detect failure patterns from issue creation**
23. **Learn from Jira auth failures**
24. **Learn from project not found failures**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `summary` | string | Yes | `-` | Issue summary/title |
| `description` | string | No | `-` | Issue description (markdown supported) |
| `issue_type` | string | No | `Task` | Issue type: 'Bug', 'Task', 'Story', 'Sub-task' |
| `project` | string | No | `AAP` | Jira project key |
| `repo` | string | No | `automation-analytics-backend` | Repository to search for related code |
| `search_code` | boolean | No | `true` | Search codebase for related code (semantic search) |
| `notify_team` | boolean | No | `true` | Send Slack notification to team channel about the new issue |
| `labels` | string | No | `-` | Comma-separated labels |
| `priority` | string | No | `Medium` | Priority: 'Highest', 'High', 'Medium', 'Low', 'Lowest' |
| `link_to` | string | No | `-` | Issue key to link to (e.g., AAP-12345) |
| `link_type` | string | No | `relates to` | Link type: 'relates to', 'blocks', 'is blocked by', 'duplicates' |
| `start_progress` | boolean | No | `false` | Immediately transition to In Progress |
| `slack_format` | boolean | No | `false` | Use Slack link format in report |
| `problem_description` | string | No | `-` | Problem description (required by AAP, falls back to description) |
| `user_story` | string | No | `-` | User story text (for Story type): 'As a..., I want..., so that...' |
| `acceptance_criteria` | string | No | `-` | Acceptance criteria (for Story type) |
| `definition_of_done` | string | No | `-` | Definition of done (for Story type) |
| `components` | string | No | `-` | Comma-separated components (e.g., 'Automation Analytics') |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the create_jira_issue skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("create_jira_issue", '{
  "summary": "example-summary",
  "description": "example-description",
  "issue_type": "Task",
  "project": "AAP",
  "repo": "automation-analytics-backend",
  "search_code": true,
  "notify_team": true,
  "labels": "example-labels",
  "priority": "Medium",
  "link_to": "example-link_to",
  "link_type": "relates to",
  "start_progress": false,
  "slack_format": false,
  "problem_description": "example-problem_description",
  "user_story": "example-user_story",
  "acceptance_criteria": "example-acceptance_criteria",
  "definition_of_done": "example-definition_of_done",
  "components": "example-components"
}')
```

### Via Command (if configured)

```
/create-jira-issue
```

## MCP Tools Used

- `code_search`
- `jira_create_issue`
- `jira_link_issues`
- `jira_transition`
- `jira_update_issue`
- `jira_view_issue`
- `knowledge_query`
- `learn_tool_fix`
- `memory_append`
- `memory_session_log`
- `persona_load`
- `skill_run`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/create_jira_issue.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/create_jira_issue.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
