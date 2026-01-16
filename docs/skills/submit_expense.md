# Submit Expense Skill

Automated Remote Worker Expense submission to SAP Concur with full auto-remediation.

## Overview

This skill automates the monthly expense submission workflow:
1. Downloads GOMO bill (if needed)
2. Logs into Concur via Red Hat SSO
3. Creates expense report
4. Uploads receipt and submits
5. **Cleans up failed submissions automatically**

## Prerequisites

### Required Services

```bash
# 1. Initialize Bitwarden session (for GOMO credentials)
export BW_SESSION=$(bw unlock --raw)

# 2. Start redhatter service (for Concur SSO credentials)
systemctl --user start redhatter
# Verify: curl http://localhost:8009/health
```

### Recommended: Chrome with SSO Plugin

For the SSO plugin to auto-login (avoids manual credential entry):

```bash
# Close existing Chrome, then restart with debugging:
google-chrome --remote-debugging-port=9222

# Set environment variable
export CHROME_CDP_URL=http://localhost:9222
```

> **Why?** The automation needs your Chrome profile with extensions (like SSO plugin) to work properly. Running Chrome with remote debugging allows Playwright to connect to your existing browser session.

## Usage

### Basic Usage

```python
# Full automation (recommended)
skill_run('submit_expense')

# Dry run - check prerequisites only
skill_run('submit_expense', '{"dry_run": true}')

# With visible browser (for debugging)
skill_run('submit_expense', '{"headless": false}')

# Specific month
skill_run('submit_expense', '{"month": "2025-12"}')
```

### Cleanup Mode

If previous automation runs failed, they may have left incomplete expense reports:

```python
# Delete all unsubmitted expense reports
skill_run('submit_expense', '{"cleanup": true}')

# Cleanup with visible browser
skill_run('submit_expense', '{"cleanup": true, "headless": false}')
```

### Direct Tool Usage

```python
# Check workflow status
concur_workflow_status()

# Download GOMO bill only
concur_download_gomo_bill(skip_concur=True)

# Run full automation
concur_run_full_automation(headless=False)

# Cleanup unsubmitted reports
concur_cleanup_unsubmitted(headless=False)
```

## Auto-Remediation

The skill automatically handles common issues:

### Browser Issues (Auto-Fixed)

| Issue | Auto-Fix | How It Works |
|-------|----------|--------------|
| Chrome profile locked | Uses profile copy | Copies `~/.config/google-chrome` to `/tmp` |
| Cookie consent popup | Dismisses TrustArc | Finds iframe, clicks Accept button |
| "What's New" dialog | Clicks Close | Finds modal dialog, clicks Close |
| Element blocked | Removes overlays | JS to remove `.truste_overlay` elements |
| Navigation aborted | Waits for load | Catches `net::ERR_ABORTED`, waits for DOM |

### Credential Issues (Manual Fix Required)

| Issue | Manual Fix Required |
|-------|---------------------|
| BW_SESSION not set | `export BW_SESSION=$(bw unlock --raw)` |
| Redhatter not running | `systemctl --user start redhatter` |

### Cleanup Issues (Auto-Fixed)

| Issue | Auto-Fix | How It Works |
|-------|----------|--------------|
| Wrong menu clicked | Correct menu selection | Finds "..." button as sibling of Submit Claim |
| Help menu opened | Position-based selection | Uses button position relative to Submit Claim |
| Confirm dialog not found | Multiple selectors | Tries `[role='dialog']`, `.sapcnqr-dialog`, etc. |

## Error Patterns

The skill recognizes these error patterns and provides fixes:

### Browser/Profile Errors

```yaml
- pattern: "ProcessSingleton"
  fix: "Chrome profile in use"
  auto_fix: "Script copies profile to /tmp/chrome-playwright-profile"

- pattern: "Failed to create a ProcessSingleton"
  fix: "Chrome profile locked"
  auto_fix: "1) Try CDP, 2) Copy profile, 3) Plain Chromium"
```

### UI Blocking Errors

```yaml
- pattern: "TrustArc Cookie Consent"
  fix: "Cookie consent popup"
  auto_fix: "dismiss_cookie_consent(page) + JS overlay removal"

- pattern: "What's New"
  fix: "Intro dialog"
  auto_fix: "dismiss_dialogs(page)"

- pattern: "Locator.click.*Timeout"
  fix: "Element blocked"
  auto_fix: "Remove overlays, dismiss dialogs, retry"
```

### Navigation Errors

```yaml
- pattern: "net::ERR_ABORTED"
  fix: "Navigation aborted (common with SSO)"
  auto_fix: "Catch error, wait for domcontentloaded"
```

### Cleanup Errors

```yaml
- pattern: "Delete option clicked but report not deleted"
  fix: "Wrong menu clicked"
  auto_fix: "Click '...' next to Submit Claim, not expense line kebab"

- pattern: "Help menu opened instead of More Actions"
  fix: "Clicked wrong button"
  auto_fix: "Use sibling selector from Submit Claim button"
```

## Troubleshooting

### Screenshots

All automation steps save screenshots to:
```
~/src/aa-concur/screenshots/
```

Key screenshots:
- `expense_list_initial_*.png` - Initial expense list
- `report_opened_*.png` - Report opened for deletion
- `delete_menu_*.png` - Delete menu visible
- `no_confirm_*.png` - Confirmation dialog issues

### Common Issues

1. **SSO plugin not working**
   - Ensure Chrome is launched with `--remote-debugging-port=9222`
   - Set `CHROME_CDP_URL=http://localhost:9222`
   - Script will connect to existing Chrome with extensions
   - If CDP fails, script copies profile (extensions may not work)

2. **Timeout errors**
   - Run with `headless=false` to see what's happening
   - Check screenshots for blocking elements
   - May need to dismiss additional dialogs

3. **Failed reports left behind**
   - Run cleanup: `skill_run('submit_expense', '{"cleanup": true}')`
   - Use `headless=false` to watch the cleanup

4. **Profile copy issues**
   - Script copies profile to `/tmp/chrome-playwright-profile`
   - Extensions may not work with copied profile
   - Use CDP connection for full extension support

5. **Delete not working**
   - Check screenshots to see which menu was clicked
   - The "..." button must be the one NEXT TO "Submit Claim"
   - NOT the expense line kebab (...)
   - NOT the help menu (?)

### Manual Cleanup

If automated cleanup fails, you can manually delete reports:

1. Go to https://us2.concursolutions.com/nui/expense
2. Click on each "Not Submitted" report
3. Click the "..." button next to "Submit Claim"
4. Select "Delete Claim"
5. Confirm deletion

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    submit_expense skill                      │
├─────────────────────────────────────────────────────────────┤
│  Phase 0: Cleanup (if requested)                            │
│  Phase 1: Check prerequisites                               │
│  Phase 2: Get expense parameters                            │
│  Phase 3: Check/download receipt                            │
│  Phase 4: Calculate amounts                                 │
│  Phase 5: Dry run exit (if requested)                       │
│  Phase 6: Full automation                                   │
│  Phase 7: Log session                                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    gomo_to_concur.py                         │
├─────────────────────────────────────────────────────────────┤
│  Browser Launch Strategy:                                   │
│  1. Try CDP connection (CHROME_CDP_URL)                     │
│  2. Copy Chrome profile to /tmp                             │
│  3. Fall back to plain Chromium                             │
├─────────────────────────────────────────────────────────────┤
│  Auto-Remediation Functions:                                │
│  - dismiss_cookie_consent() - TrustArc iframe               │
│  - dismiss_dialogs() - Modal dialogs                        │
│  - safe_click() - Retry with overlay removal                │
│  - Error handling for net::ERR_ABORTED                      │
├─────────────────────────────────────────────────────────────┤
│  Cleanup Functions:                                         │
│  - delete_expense_reports() - Delete unsubmitted reports    │
│  - Finds correct "..." menu (sibling of Submit Claim)       │
│  - Handles confirmation dialogs                             │
└─────────────────────────────────────────────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `skills/submit_expense.yaml` | Skill definition with error patterns |
| `tool_modules/aa_concur/src/tools_basic.py` | MCP tools |
| `~/src/aa-concur/scripts/gomo_to_concur.py` | Browser automation |
| `~/src/aa-concur/downloads/` | Downloaded bills |
| `~/src/aa-concur/screenshots/` | Debug screenshots |
| `memory/learned/patterns.yaml` | Learned error patterns |
| `memory/learned/tool_fixes.yaml` | Specific tool fixes |

## Memory Patterns

Learned patterns are stored in:
- `memory/learned/patterns.yaml` under `concur_patterns` and `concur_cleanup_patterns`
- `memory/learned/tool_fixes.yaml` for specific tool fixes

The system uses these patterns to:
1. Recognize known errors before they happen
2. Suggest fixes automatically
3. Remember solutions for future sessions

## Version History

- **v2.1** (2026-01-15): Fixed cleanup to delete reports correctly (click correct menu)
- **v2.0** (2026-01-15): Added auto-remediation, Chrome profile handling, cleanup mode
- **v1.1** (2026-01-14): Initial skill with guided workflow
- **v1.0** (2026-01-13): Basic expense parameter tools
