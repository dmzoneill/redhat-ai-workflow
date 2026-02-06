# InScope Auto-Login

InScope tokens expire after **1 hour**. This document explains how automatic token refresh works.

## How It Works

1. **Token Storage**: Tokens are stored in `~/.cache/inscope/token` as JSON:
   ```json
   {
     "token": "eyJ...",
     "expires_at": 1738580940
   }
   ```

2. **Automatic Refresh**: When `_get_auth_token()` is called:
   - If token is valid with >5 minutes remaining → use it
   - If token is expiring soon (<5 min) or expired → trigger auto-login
   - Auto-login uses Selenium with the same Chrome profile as `rhtoken`

3. **Browser Automation**: The `inscope_auto_login.py` script:
   - Opens Chrome with your existing profile (`~/.config/google-chrome-beta/Profile 1`)
   - Navigates to InScope
   - If SSO login needed, gets credentials from `redhatter` service
   - Extracts JWT token from browser
   - Saves to cache file

## Setup

### Prerequisites

1. **Chrome Beta** with profile at `~/.config/google-chrome-beta/Profile 1`
2. **redhatter service** running (provides credentials)
3. **Python packages**: `selenium`, `requests`, `PyJWT`

### Install Dependencies

```bash
cd /home/daoneill/src/redhat-ai-workflow
uv pip install selenium PyJWT
```

### Enable Systemd Timer (Recommended)

For proactive token refresh every 45 minutes:

```bash
# Copy service files
cp systemd/inscope-token-refresh.service ~/.config/systemd/user/
cp systemd/inscope-token-refresh.timer ~/.config/systemd/user/

# Enable and start timer
systemctl --user daemon-reload
systemctl --user enable inscope-token-refresh.timer
systemctl --user start inscope-token-refresh.timer

# Check status
systemctl --user status inscope-token-refresh.timer
systemctl --user list-timers
```

### Manual Refresh

```bash
# With browser visible (for debugging)
python scripts/inscope_auto_login.py

# Headless
python scripts/inscope_auto_login.py --headless

# Check current status
python scripts/inscope_auto_login.py --check
```

### From MCP Tools

```
inscope_auto_login(headless=true)
```

## Token Lifecycle

```
┌─────────────────────────────────────────────────────────────┐
│                    Token Lifecycle (1 hour)                  │
├─────────────────────────────────────────────────────────────┤
│ 0min          45min              55min              60min   │
│   │             │                  │                  │     │
│   ▼             ▼                  ▼                  ▼     │
│ [ISSUED]    [TIMER]           [AUTO-REFRESH]     [EXPIRED] │
│              refresh            if <5min left               │
│              proactively        on API call                 │
└─────────────────────────────────────────────────────────────┘
```

## Troubleshooting

### Token Not Refreshing

1. Check if redhatter service is running:
   ```bash
   curl http://localhost:8009/health
   ```

2. Check Chrome profile exists:
   ```bash
   ls ~/.config/google-chrome-beta/Profile\ 1/
   ```

3. Run manually without headless to see what's happening:
   ```bash
   python scripts/inscope_auto_login.py
   ```

### ChromeDriver Issues

The script auto-downloads matching ChromeDriver. If issues persist:
```bash
# Check Chrome version
/opt/google/chrome-beta/google-chrome-beta --version

# Check ChromeDriver version
~/bin/chromedriver --version
```

### SSO Login Failing

If SSO login fails, ensure you can login manually in the same Chrome profile:
1. Open Chrome Beta
2. Navigate to https://inscope.corp.redhat.com/convo
3. Complete login
4. Then run the script (it should reuse the session)
