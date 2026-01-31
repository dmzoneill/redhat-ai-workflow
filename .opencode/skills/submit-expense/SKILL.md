---
name: submit-expense
description: Submit a Remote Worker Expense to SAP Concur
license: MIT
compatibility: opencode
metadata:
  version: "2.0"
  source: submit_expense.yaml
  executable: "true"
---

# submit_expense

Submit a Remote Worker Expense to SAP Concur.

This skill provides a complete automated workflow:
1. Checks prerequisites (credentials, services)
2. Downloads GOMO bill if needed
3. Submits expense to Concur
4. Handles common errors automatically

**Prerequisites:**
- Bitwarden session: `export BW_SESSION=$(bw unlock --raw)`
- Redhatter service running on localhost:8009

**For SSO plugin auto-login (recommended):**
```bash
# Close Chrome, then restart with debugging:
google-chrome --remote-debugging-port=9222
export CHROME_CDP_URL=http://localhost:9222
```

**Common Issues & Auto-Fixes:**
- Cookie consent popups → Auto-dismissed
- "What's New" dialogs → Auto-dismissed
- Chrome profile locked → Uses profile copy
- Failed reports → Use cleanup mode

## When to Use This Skill

This skill is invoked automatically by the AI when appropriate, or can be called explicitly:

```
skill_run("submit_expense", '{
  "month": "example-month",
  "skip_download": false,
  "dry_run": false,
  "cleanup": false,
  "headless": false
}')
```

## What It Does

This is an **executable MCP skill** that runs a multi-step workflow. When invoked, it:

1. **Load admin persona for Concur expense tools**
2. **Search for code related to expense submission**
3. **Parse expense code search results**
4. **Get expense submission patterns and gotchas from knowledge base**
5. **Parse expense knowledge for submission context**
6. **Check for known Bitwarden issues before starting**
7. **Handle cleanup mode - delete unsubmitted reports**
8. **Check all prerequisites for expense submission**
9. **Parse workflow status to determine next steps**
10. **Get expense parameters for the month**
11. **Extract expense parameters**
12. **Check if receipt files exist**
13. **Parse receipt status**
14. **Download GOMO bill if receipt not available**
15. **Parse download result and update receipt status**
16. **Recheck receipt status after download**
17. **Update receipt status after download**
18. **Calculate EUR to USD conversion**
19. **Exit early for dry run**
20. **Verify all prerequisites before running full automation**
21. **Abort if prerequisites are missing**
22. **Run the full GOMO + Concur automation**
23. **Parse automation result and check for errors**
24. **Log expense submission to session**

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `month` | string | No | `-` | Month in YYYY-MM format (default: previous month) |
| `skip_download` | boolean | No | `false` | Skip GOMO download check if receipt already exists |
| `dry_run` | boolean | No | `false` | Check prerequisites without submitting |
| `cleanup` | boolean | No | `false` | Delete unsubmitted expense reports from previous failed runs |
| `headless` | boolean | No | `false` | Run browser in headless mode (default: false for SSO plugin support) |


## How to Invoke

### From Cursor/OpenCode

The AI will automatically detect when to use this skill based on context. You can also explicitly request it:

```
"Run the submit_expense skill for AAP-12345"
```

### Direct MCP Call

```python
skill_run("submit_expense", '{
  "month": "example-month",
  "skip_download": false,
  "dry_run": false,
  "cleanup": false,
  "headless": false
}')
```

### Via Command (if configured)

```
/submit-expense
```

## MCP Tools Used

- `check_known_issues`
- `code_search`
- `concur_check_receipt_status`
- `concur_download_gomo_bill`
- `concur_get_expense_params`
- `concur_run_full_automation`
- `concur_workflow_status`
- `knowledge_query`
- `memory_session_log`
- `persona_load`

## Implementation

This skill is implemented as an executable YAML workflow at:
- **Source**: `skills/submit_expense.yaml`
- **Engine**: MCP Skill Engine
- **Execution**: Server-side with error handling and state management

## Related

- [Skill Documentation](../../docs/skills/submit_expense.md) - Detailed implementation docs
- [MCP Skill Engine](../../docs/architecture/skill-engine.md) - How skills work
