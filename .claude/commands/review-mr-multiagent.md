# Multi-Agent Code Review

**Description:** Run comprehensive multi-agent code review with 6 specialized agents (hybrid Claude + Gemini).

## Specialized Agents

Each agent focuses on a specific aspect using Claude or Gemini via Vertex AI:

- **Architecture** (Claude): Design patterns, SOLID principles, code organization
- **Security** (Gemini): Vulnerabilities, auth issues, OWASP Top 10
- **Performance** (Claude): Algorithm efficiency, database queries, scalability
- **Testing** (Gemini): Test coverage, edge cases, test quality
- **Documentation** (Claude): Comments, API docs, README updates
- **Style** (Gemini): Naming conventions, formatting, consistency

**No API Keys Required** - Uses your Claude Code/Gemini CLI setup with Vertex AI!

## Usage

**Basic review (auto-posts to MR):**
```bash
skill_run("review_pr_multiagent", '{"mr_id": 1483, "post_combined": true}')
```

**Preview review without posting:**
```bash
skill_run("review_pr_multiagent", '{"mr_id": 1483}')
```

**Debug mode (show full output):**
```bash
skill_run("review_pr_multiagent", '{"mr_id": 1483, "debug": true}')
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `mr_id` | integer | *required* | GitLab MR ID to review |
| `post_combined` | boolean | `false` | Post synthesized review to MR |
| `debug` | boolean | `false` | Show full review output (up to 10k chars) |
| `agents` | string | all 6 agents | Comma-separated agent list |
| `model` | string | `sonnet` | Model to use for agents |

## Selective Agent Reviews

**Security and testing only:**
```bash
skill_run("review_pr_multiagent", '{
  "mr_id": 1483,
  "agents": "security,testing",
  "post_combined": true
}')
```

**Architecture and performance only:**
```bash
skill_run("review_pr_multiagent", '{
  "mr_id": 1483,
  "agents": "architecture,performance",
  "post_combined": true
}')
```

## How It Works

1. **Parallel Execution**: All 6 agents run simultaneously (~1.8 minutes total)
2. **Specialized Analysis**: Each agent reviews from their expertise area
3. **Synthesis**: Final agent combines all reviews into a natural, single-engineer perspective
4. **Output**: Professional review without mentioning AI/agents/tools

## Output Format

The final review sounds like it's from a single senior engineer:

```markdown
# Code Review: MR !1483

Thanks for working on this rollups issue. I've reviewed the changes...

## Critical Issues

[Substantive findings organized by severity]

## Warnings

[Important considerations]

## Suggestions

[Improvements and optimizations]
```

**No emojis, no AI mentions, no multi-agent references** - just professional feedback.

## Performance

- **Time**: ~1.8 minutes (with parallel execution)
- **Agents**: 6 specialized reviewers
- **Models**: Hybrid Claude + Gemini via Vertex AI
- **Speedup**: 4.2x faster than sequential execution

## Examples

**Full review with posting:**
```bash
skill_run("review_pr_multiagent", '{"mr_id": 1483, "post_combined": true}')
```

**Quick security/testing check:**
```bash
skill_run("review_pr_multiagent", '{
  "mr_id": 1483,
  "agents": "security,testing",
  "post_combined": true
}')
```

**Preview before posting:**
```bash
skill_run("review_pr_multiagent", '{"mr_id": 1483}')
# Review, then post manually if satisfied
skill_run("review_pr_multiagent", '{"mr_id": 1483, "post_combined": true}')
```

## See Also

- Documentation: `docs/multi-agent-code-review.md`
- Model selection: `docs/multiagent-model-selection.md`
- Single-agent review: `/review` skill
