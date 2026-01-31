---
description: Single-agent code review (faster, simpler)
agent: developer
---

Run a single-agent code review on merge request $1.

Execute: skill_run("review_pr", '{"mr_id": $1}')

This is faster than the multi-agent review and good for quick checks.
