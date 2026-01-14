---
name: review-all-open
description: "Batch review all open Merge Requests (excluding your own)."
arguments:
  - name: repo_name
---
# Review All Open MRs

Batch review all open Merge Requests (excluding your own).

## Instructions

Review all open MRs in the repository:

```text
skill_run("review_all_prs", '{}')
```

This will:
1. List all open MRs (excluding yours)
2. For each MR:
   - Check commit format
   - Verify description
   - Check pipeline status
   - Analyze code patterns
3. Auto-approve clean MRs
4. Post feedback on MRs with issues
5. Send summary to team channel

## Options

```bash
# Review specific repository
skill_run("review_all_prs", '{"repo_name": "automation-analytics-backend"}')

# Dry run (don't actually approve/comment)
skill_run("review_all_prs", '{"dry_run": true}')
```

## Output

Summary of all reviewed MRs:
- ✅ Approved: X MRs
- 📝 Feedback posted: Y MRs
- ⏭️ Skipped (yours): Z MRs
