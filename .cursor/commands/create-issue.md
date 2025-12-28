# /create-issue

**Description:** Create a Jira issue with Markdown support and auto-conversion.

## Usage

### Quick Story

```
skill_run("create_jira_issue", '{
  "summary": "Add pytest-xdist parallelization",
  "issue_type": "story",
  "description": "## Overview\n\nSpeed up test suite with parallel execution.",
  "labels": ["testing", "performance"]
}')
```

### Full Story with All Fields

```
skill_run("create_jira_issue", '{
  "summary": "Add pytest-xdist parallelization",
  "issue_type": "story",
  "description": "Speed up test suite with parallel execution",
  "user_story": "As a developer, I want tests to run in parallel so that CI is faster.",
  "acceptance_criteria": "- [ ] Tests run in parallel\\n- [ ] No flaky tests\\n- [ ] 50% faster",
  "definition_of_done": "- Tests pass\\n- Code reviewed\\n- Documentation updated",
  "labels": ["testing", "performance"],
  "components": ["Automation Analytics"],
  "story_points": 5,
  "epic_link": "AAP-12000"
}')
```

### Quick Bug

```
skill_run("create_jira_issue", '{
  "summary": "API returns 500 on empty request",
  "issue_type": "bug",
  "description": "## Steps to Reproduce\\n\\n1. Send empty POST\\n2. See error"
}')
```

## Input Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `summary` | string | ✅ | Issue title |
| `issue_type` | string | | `story`, `bug`, `task`, `epic` (default: story) |
| `description` | string | | Main description (Markdown OK) |
| `user_story` | string | | User story text (Markdown OK) |
| `acceptance_criteria` | string | | AC list (Markdown OK) |
| `definition_of_done` | string | | DoD list (Markdown OK) |
| `supporting_documentation` | string | | Additional docs (Markdown OK) |
| `labels` | array | | Labels to apply |
| `components` | array | | Components (default: Automation Analytics) |
| `story_points` | int | | Estimate points |
| `epic_link` | string | | Epic key to link (e.g., AAP-12000) |
| `project` | string | | Jira project (default: AAP) |
| `assignee` | string | | Assignee username |
| `convert_markdown` | bool | | Auto-convert Markdown (default: true) |

## Markdown Support

The skill accepts Markdown and auto-converts to Jira wiki markup:

| Markdown | Jira |
|----------|------|
| `# Heading` | `h1. Heading` |
| `**bold**` | `*bold*` |
| `` `code` `` | `{{code}}` |
| `- item` | `* item` |
| `[link](url)` | `[link\|url]` |
| ` ```python ` | `{code:python}` |

## Issue Types

Case-insensitive: `Story`, `story`, `STORY` all work.

- `story` - Feature work
- `bug` - Defect fix
- `task` - General task
- `epic` - Large feature container

## Direct MCP Tool

For simpler issues, use the MCP tool directly:

```
jira_create_issue(
  issue_type="story",
  summary="Add caching layer",
  description="## Overview\n\nImprove performance...",
  labels="performance,caching",
  story_points=3
)
```

## After Creation

The skill outputs next steps:

1. View issue in Jira
2. Add to sprint
3. Start work with `skill_run("start_work", '{"issue_key": "AAP-XXXXX"}')`
