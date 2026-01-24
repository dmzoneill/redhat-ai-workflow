---
name: review-local-changes
description: "Multi-agent code review for local uncommitted/staged changes - no GitLab MR required."
arguments:
  - name: mode
---
# Review Local Changes

Multi-agent code review for local uncommitted/staged changes - no GitLab MR required.

## Instructions

Review your local changes before committing:

```text
skill_run("review_local_changes", '{}')
```

This will:
1. Get diff of your local changes
2. Run multi-agent review (Claude + Gemini)
3. Check architecture, security, performance, and testing
4. Provide actionable feedback

## Example

```bash
# Review staged changes (default)
skill_run("review_local_changes", '{}')

# Review all uncommitted changes
skill_run("review_local_changes", '{"mode": "all"}')

# Review only unstaged changes
skill_run("review_local_changes", '{"mode": "unstaged"}')

# Review changes since branching from main
skill_run("review_local_changes", '{"mode": "branch"}')

# Review a specific commit
skill_run("review_local_changes", '{"mode": "commit", "commit_sha": "abc123"}')

# Review with specific agents only
skill_run("review_local_changes", '{"agents": "architecture,security"}')
```

## Review Modes

| Mode | Description |
|------|-------------|
| `staged` | Review only staged changes (`git diff --cached`) |
| `unstaged` | Review only unstaged changes (`git diff`) |
| `all` | Review all uncommitted changes (`git diff HEAD`) |
| `commit` | Review specific commit (`git show <sha>`) |
| `branch` | Review changes since branching (`git diff main...HEAD`) |

## Review Agents

| Agent | Focus |
|-------|-------|
| Architecture (Claude) | Design patterns, SOLID principles, code structure |
| Security (Gemini) | Security vulnerabilities, auth issues, data exposure |
| Performance (Claude) | Performance bottlenecks, N+1 queries, memory |
| Testing (Gemini) | Test coverage, edge cases, assertions |

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `mode` | staged | What to review |
| `commit_sha` | "" | Commit SHA (for mode=commit) |
| `base_branch` | main | Base branch (for mode=branch) |
| `repo` | . | Repository path |
| `agents` | all | Comma-separated agent list |

## When to Use

- Before committing: `/review-local-changes` with mode=staged
- Before pushing: `/review-local-changes` with mode=branch
- After making changes: `/review-local-changes` with mode=all
