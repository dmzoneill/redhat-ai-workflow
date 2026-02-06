# Reward Zone

Send and receive recognition awards on Red Hat Reward Zone.

## Instructions

```text
skill_run("reward_zone", '{"action": "$ACTION", "recipient": "", "category": "", "points": "", "message": "", "dry_run": "", "headless": ""}')
```

## What It Does

Send and receive recognition awards on Red Hat Reward Zone.

This skill provides automated workflows for:
1. Sending nominations/awards to colleagues
2. Viewing received awards and recognition
3. Checking nomination points balance

**Prerequisites:**
- Red Hat SSO access (Kerberos ID + PIN/token)
- redhatter service running (provides credentials)

**Award Categories:**
- RH Multiplier - For collaboration and teamwork
- Team Advocate - For supporting team members
- Customer Focus - For customer-centric actions

**Common Uses:**
- "Send an award to [colleague]"
- "Give recognition to [name] for [reason]"
- "Check my reward zone points"
- "View my received awards"
- "Nominate [person] for team advocate"

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `action` | Action to perform: "send", "view_received", "check_points", or "view_sent"
 | Yes |
| `recipient` | Recipient's name or email (required for 'send' action) | No |
| `category` | Award category: "RH Multiplier", "Team Advocate", or "Customer Focus"
 (default: RH Multiplier) | No |
| `points` | Number of points to award (typically 25, 50, 75, or 100) (default: 25) | No |
| `message` | Recognition message explaining why the person deserves the award | No |
| `dry_run` | Preview the action without submitting | No |
| `headless` | Run browser in headless mode (set false for debugging) (default: True) | No |
