---
description: Run comprehensive multi-agent code review
agent: developer
---

Run comprehensive multi-agent code review with 6 specialized agents (hybrid Claude + Gemini).

Execute: skill_run("review_pr_multiagent", '{"mr_id": $1, "post_combined": $2}')

**Agents:**
- Architecture (Claude): Design patterns, SOLID principles, code organization
- Security (Gemini): Vulnerabilities, auth issues, OWASP Top 10
- Performance (Claude): Algorithm efficiency, database queries, scalability
- Testing (Gemini): Test coverage, edge cases, test quality
- Documentation (Claude): Comments, API docs, README updates
- Style (Gemini): Naming conventions, formatting, consistency

**Performance:** ~1.8 minutes (parallel execution, 4.2x speedup)

**Usage:**
- `/review-mr-multiagent 1483` - Preview review without posting
- `/review-mr-multiagent 1483 true` - Post review to MR
