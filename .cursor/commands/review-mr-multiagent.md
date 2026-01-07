# /review-mr-multiagent

**Description:** Run comprehensive multi-agent code review with 6 specialized agents.

**Usage:**
```
skill_run("review_pr_multiagent", '{"mr_id": 1482}')
```

## Specialized Agents

Each agent focuses on a specific aspect with optimized model selection:

- 🏗️ **Architecture** (Sonnet 4.5): Design patterns, SOLID principles, code organization
- 🔒 **Security** (Sonnet 4.5): Vulnerabilities, auth issues, OWASP Top 10
- ⚡ **Performance** (Sonnet 3.7): Algorithm efficiency, database queries, scalability
- 🧪 **Testing** (Sonnet 3.7): Test coverage, edge cases, test quality
- 📝 **Documentation** (Haiku 3.5): Comments, API docs, README updates
- 🎨 **Style** (Haiku 3.5): Naming conventions, formatting, consistency

**Coordinator Agent** (Sonnet 4.5): Synthesizes all reviews into unified feedback

## Cost & Performance

- **Cost:** ~$0.12 per review (standard mode)
- **Time:** ~30 seconds (parallel execution)
- **Quality:** Expert-level insights from specialized agents

## Options

### Full Review (Default)
```
skill_run("review_pr_multiagent", '{"mr_id": 1482}')
```

### Selective Agents
Run only specific agents to optimize cost and time:

**Security audit:**
```
skill_run("review_pr_multiagent", '{
  "mr_id": 1482,
  "agents": "security,architecture"
}')
```
Cost: ~$0.05, Time: ~20s

**Hotfix check:**
```
skill_run("review_pr_multiagent", '{
  "mr_id": 1482,
  "agents": "security,testing"
}')
```
Cost: ~$0.03, Time: ~15s

**Documentation review:**
```
skill_run("review_pr_multiagent", '{
  "mr_id": 1482,
  "agents": "documentation,style"
}')
```
Cost: ~$0.01, Time: ~10s

### Preview Mode
Generate review without posting to MR:
```
skill_run("review_pr_multiagent", '{
  "mr_id": 1482,
  "post_combined": false
}')
```

### Sequential Execution
For rate limiting or debugging:
```
skill_run("review_pr_multiagent", '{
  "mr_id": 1482,
  "parallel": false
}')
```
Time: ~3-4 minutes

## What It Does

1. **Fetches MR details** - Title, description, author, status
2. **Gets code diff** - All changes for analysis
3. **Runs specialized agents** - Each agent reviews in parallel
4. **Coordinates findings** - Deduplicates and prioritizes issues
5. **Posts combined review** - Unified feedback on MR
6. **Auto-approves** - If no critical issues found

## Output Format

The coordinator creates a structured review:

```markdown
## 🤖 Multi-Agent Code Review

### 🔴 Critical Issues
- Issues that must be fixed before merge

### 🟡 Warnings
- Issues that should be addressed

### 💡 Suggestions
- Nice-to-have improvements

### 📊 Summary
- Overall assessment and recommendation
```

## Example Workflows

**High-priority feature:**
```
skill_run("review_pr_multiagent", '{"mr_id": 1482}')
```

**Production hotfix:**
```
skill_run("review_pr_multiagent", '{
  "mr_id": 1483,
  "agents": "security,testing"
}')
```

**New API endpoint:**
```
skill_run("review_pr_multiagent", '{
  "mr_id": 1484,
  "agents": "security,architecture,performance"
}')
```

## Model Optimization

The system uses tiered model selection for cost optimization:

| Model | Cost | Speed | Best For |
|-------|------|-------|----------|
| **Opus 4.5** | 10x | Slowest | Reserved for special cases |
| **Sonnet 4.5** | 5x | Medium | Critical reasoning (security, architecture) |
| **Sonnet 3.7** | 3x | Fast | Balanced tasks (performance, testing) |
| **Haiku 3.5** | 1x | Very fast | Simple tasks (docs, style) |

## Comparison: Single vs Multi-Agent

| Aspect | Single Agent | Multi-Agent |
|--------|-------------|-------------|
| **Coverage** | Broad but shallow | Deep in each domain |
| **Cost** | 1 API call (~$0.02) | 7 API calls (~$0.12) |
| **Time** | ~10 seconds | ~30 seconds (parallel) |
| **Quality** | Good overall | Excellent in focus areas |
| **Specialization** | Generalist | 6 specialists |

## Use Cases

**When to use multi-agent:**
- Production releases
- Security-critical changes
- Major architectural changes
- High-impact features
- New APIs or services

**When to use single-agent:**
- Small bug fixes
- Documentation updates
- Simple refactoring
- Quick reviews

## Integration

Replace single-agent reviews in workflows:
```yaml
# Old
- tool: skill_run
  args:
    skill_name: "review_pr"
    inputs: '{"mr_id": {{ mr_id }}}'

# New - Multi-agent
- tool: skill_run
  args:
    skill_name: "review_pr_multiagent"
    inputs: '{"mr_id": {{ mr_id }}}'
```

## Quick Reference

**Available Agents:**
- `architecture` - Design patterns, SOLID principles
- `security` - Vulnerabilities, OWASP Top 10
- `performance` - Efficiency, optimization
- `testing` - Coverage, edge cases
- `documentation` - Comments, API docs
- `style` - Naming, formatting

**Agent Combinations:**
- All agents: Full review (~$0.12, 30s)
- `security,architecture`: Security audit (~$0.05, 20s)
- `security,testing`: Hotfix check (~$0.03, 15s)
- `documentation,style`: Docs review (~$0.01, 10s)
- `architecture,performance,testing`: Feature review (~$0.08, 25s)
