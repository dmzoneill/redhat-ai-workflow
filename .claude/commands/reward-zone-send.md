---
name: reward-zone-send
description: "Send a recognition award to a colleague on Red Hat Reward Zone using pure HTTP (no browser)."
arguments:
  - name: recipient
    required: true
  - name: message
    required: true
  - name: points
  - name: award
---
# Reward Zone - Send Award

Send a recognition award to a colleague on Red Hat Reward Zone using pure HTTP (no browser).

## Instructions

```text
skill_run("reward_zone_send", '{"recipient": "$RECIPIENT", "message": "$MESSAGE", "points": 25, "award": "Focus on Team"}')
```

## What It Does

Automates the full "Send a Reward" flow via HTTP API calls:

1. Creates an HTTP session to rewardzone.redhat.com
2. Authenticates via SAML (pure HTTP, no browser launched)
3. Searches for the recipient by name/email
4. Submits the nomination with points and message

**No browser required** - uses HTTP session management with SAML auth.

## Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `recipient` | Yes | | Name or email to search for |
| `message` | Yes | | Why this person deserves the award |
| `points` | No | 25 | Points to award (5-100) |
| `award` | No | Focus on Team | Award type |
| `description` | No | same as message | Optional description |
| `dry_run` | No | false | Preview without submitting |

## Examples

**Quick send:**
```
/reward-zone-send recipient="Aparna Karve" message="Great work on the API migration!"
```

**With more options:**
```
skill_run("reward_zone_send", '{"recipient": "John Smith", "message": "Thanks for the help with the release!", "points": 50, "award": "Encourage Others"}')
```

**Dry run (preview):**
```
skill_run("reward_zone_send", '{"recipient": "Jane Doe", "message": "Excellent mentoring", "dry_run": true}')
```

## Prerequisites

- redhatter service running on localhost:8009
- Auth token at ~/.cache/redhatter/auth_token
- VPN connected

## See Also

- `/reward-zone` - General Reward Zone actions (check points, view awards)
