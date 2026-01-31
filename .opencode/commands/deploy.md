---
description: Deploy MR to ephemeral for testing
agent: devops
---

Deploy merge request $1 to an ephemeral environment for testing.

Execute: skill_run("test_mr_ephemeral", '{"mr_id": $1}')

This will:
- Get the full commit SHA from the MR
- Find or create an ephemeral namespace
- Deploy the changes using Bonfire
- Provide access URLs

**Usage:** `/deploy 1483`
