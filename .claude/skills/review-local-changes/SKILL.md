---
name: review-local-changes
description: Multi-agent code review for LOCAL changes - no GitLab MR required
license: MIT
compatibility: opencode
metadata:
  version: "1.0"
  source: review_local_changes.yaml
  executable: "true"
---

# review_local_changes

Multi-agent code review for LOCAL changes - no GitLab MR required.

Reviews uncommitted changes using Claude + Gemini agents.
Perfect for pre-commit or pre-push reviews.

**Review Agents:**
- 🏗️ **Architecture Agent** (Claude): Design patterns, SOLID principles
- 🔒 **Security Agent** (Gemini): Security vulnerabilities, auth issues
- ⚡ **Performance Agent** (Claude): Performance bottlenecks
- 🧪 **Testing Agent** (Gemini): Test coverage, edge cases

**Modes:**
- `staged` (default): Review only staged changes (git diff --cached)
- `unstaged`: Review only unstaged changes (git diff)
- `all`: Review all uncommitted changes (git diff HEAD)
- `commit`: Review specific commit (git show <sha>)
- `branch`: Review changes since branching from main (git diff main...HEAD)

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("review_local_changes", '{
  "mode": "staged",
  "commit_sha": "example-commit_sha",
  "base_branch": "main",
  "repo": ".",
  "agents": "architecture,security,performance",
  "model": "sonnet",
  "files": "example-files"
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Get diff based on mode**
2. **Verify there are changes to review**
3. **Parse enabled agents**
4. **Run all review agents in parallel**
5. **Synthesize final review**
6. **Build review statistics**
7. **Log review to session**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `mode` | string | No | `staged` | What to review: staged, unstaged, all, commit, branch |
| `commit_sha` | string | No | `-` | Commit SHA to review (only for mode=commit) |
| `base_branch` | string | No | `main` | Base branch for mode=branch |
| `repo` | string | No | `.` | Repository path |
| `agents` | string | No | `architecture,security,performance` | Comma-separated agents to run |
| `model` | string | No | `sonnet` | Model to use (sonnet, opus, haiku) |
| `files` | string | No | `-` | Specific files to review (comma-separated, optional) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the review_local_changes skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("review_local_changes", '{
  "mode": "staged",
  "commit_sha": "example-commit_sha",
  "base_branch": "main",
  "repo": ".",
  "agents": "architecture,security,performance",
  "model": "sonnet",
  "files": "example-files"
}')
```

### Via Command (if configured)

```
/review-local-changes
```

## MCP Tools Used

- `memory_session_log`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/review_local_changes.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/review_local_changes.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
