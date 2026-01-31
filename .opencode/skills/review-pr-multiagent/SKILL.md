---
name: review-pr-multiagent
description: Multi-agent code review system using hybrid Claude + Gemini agents
license: MIT
compatibility: opencode
metadata:
  version: "2.0"
  source: review_pr_multiagent_test.yaml
  executable: "true"
---

# review_pr_multiagent

Multi-agent code review system using hybrid Claude + Gemini agents.

Uses Claude/Gemini CLI with Vertex AI - no API keys required!

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("review_pr_multiagent", '{
  "mr_id": "example-mr_id",
  "agents": "architecture,security,performance",
  "post_combined": false,
  "model": "sonnet"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load developer persona for GitLab tools**
2. **Get MR diff**
3. **Test Architecture Agent (Claude)**
4. **Test Security Agent (Gemini)**
5. **Build summary**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `mr_id` | integer | Yes | `-` | GitLab MR ID |
| `agents` | string | No | `architecture,security,performance` | Comma-separated agents (architecture,security,performance,testing,documentation,style) |
| `post_combined` | boolean | No | `false` | Post combined review to MR (default: false for testing) |
| `model` | string | No | `sonnet` | Model to use (sonnet, opus, haiku) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the review_pr_multiagent skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("review_pr_multiagent", '{
  "mr_id": "example-mr_id",
  "agents": "architecture,security,performance",
  "post_combined": false,
  "model": "sonnet"
}')
```

### Via Command (if configured)

```
/review-pr-multiagent
```

## MCP Tools Used

- `gitlab_mr_diff`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/review_pr_multiagent_test.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/review_pr_multiagent.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
