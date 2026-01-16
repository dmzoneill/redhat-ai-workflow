---
name: submit-expense
description: "Submit a Remote Worker Expense to SAP Concur with AI assistance."
arguments:
  - name: expense_type
---
# Submit Expense

Submit a Remote Worker Expense to SAP Concur with AI assistance.

## Prerequisites

1. **Chrome with debugging enabled**:
   ```bash
   google-chrome --remote-debugging-port=9222
   export CHROME_CDP_URL=http://localhost:9222
   ```

2. **SSO plugin active** in Chrome for Red Hat authentication

## Instructions

Submit an expense:

```text
skill_run("submit_expense", '{"expense_type": "$TYPE"}')
```

## Expense Types

| Type | Description |
|------|-------------|
| `gomo` | GOMO mobile bill |
| `internet` | Home internet |
| `equipment` | Remote work equipment |

## Examples

```bash
# Submit GOMO bill (auto-downloads from GOMO)
skill_run("submit_expense", '{"expense_type": "gomo"}')

# Submit internet expense
skill_run("submit_expense", '{"expense_type": "internet", "amount": 50.00}')

# Submit with specific receipt
skill_run("submit_expense", '{"expense_type": "gomo", "receipt_path": "/path/to/bill.pdf"}')

# Dry run (preview without submitting)
skill_run("submit_expense", '{"expense_type": "gomo", "dry_run": true}')
```

## What It Does

1. Checks prerequisites (credentials, Chrome)
2. Downloads GOMO bill if needed
3. Navigates to SAP Concur
4. Handles SSO authentication
5. Fills expense form
6. Attaches receipt
7. Submits for approval

## Auto-Remediation

The skill includes automatic error handling for:
- Cookie consent dialogs
- SSO redirects
- Form validation errors
- Session timeouts
