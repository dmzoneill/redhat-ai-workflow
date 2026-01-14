---
name: google-reauth
description: "Refresh your Google OAuth token to get new permissions (e.g., after adding Gmail scopes)."
---
# Re-authenticate Google OAuth

Refresh your Google OAuth token to get new permissions (e.g., after adding Gmail scopes).

## Quick Re-auth

Run this to delete token and re-authenticate:

```bash
rm -f ~/.config/google-calendar/token.json && echo "Token deleted. Run any Google tool to re-authenticate."
```

Then trigger authentication by running:

```python
google_calendar_status()
```text

This will open your browser for OAuth login with the new scopes.

## When to Use

- After adding Gmail scopes to your Google Cloud project
- If you get "insufficient scope" errors
- If your token expires or becomes invalid
- After enabling new Google APIs

## Verify Gmail Access

After re-authenticating, test email access:

```
skill_run("coffee")
```

If email shows in the briefing, you're all set! ☕
