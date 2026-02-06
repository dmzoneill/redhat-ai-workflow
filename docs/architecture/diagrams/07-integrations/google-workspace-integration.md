# Google Workspace Integration

> Calendar, Gmail, Drive, and Slides integration

## Diagram

```mermaid
graph TB
    subgraph Modules[Google Modules]
        CALENDAR[aa_google_calendar]
        GMAIL[aa_gmail]
        GDRIVE[aa_gdrive]
        SLIDES[aa_google_slides]
    end

    subgraph Operations[Operations]
        CAL_OPS[List events<br/>Create event<br/>Update event]
        MAIL_OPS[Search mail<br/>Send mail<br/>Read mail]
        DRIVE_OPS[List files<br/>Read file<br/>Upload file]
        SLIDES_OPS[Create slides<br/>Update slides]
    end

    subgraph API[Google APIs]
        CAL_API[Calendar API v3]
        GMAIL_API[Gmail API v1]
        DRIVE_API[Drive API v3]
        SLIDES_API[Slides API v1]
    end

    subgraph Auth[Authentication]
        OAUTH[OAuth 2.0]
        CREDS[credentials.json]
        TOKEN[token.json]
    end

    Modules --> Operations
    Operations --> API
    API --> Auth
```

## OAuth Flow

```mermaid
sequenceDiagram
    participant Tool as Google Tool
    participant Auth as Auth Handler
    participant Token as token.json
    participant Google as Google OAuth

    Tool->>Auth: Get credentials
    Auth->>Token: Check token

    alt Token valid
        Token-->>Auth: Access token
    else Token expired
        Auth->>Token: Get refresh token
        Auth->>Google: Refresh access token
        Google-->>Auth: New access token
        Auth->>Token: Save new token
    else No token
        Auth->>Google: OAuth consent flow
        Google-->>Auth: Authorization code
        Auth->>Google: Exchange for tokens
        Google-->>Auth: Access + refresh tokens
        Auth->>Token: Save tokens
    end

    Auth-->>Tool: Valid credentials
```

## Calendar Tools

| Tool | Description | API |
|------|-------------|-----|
| calendar_list_events | List upcoming events | events.list |
| calendar_create_event | Create event | events.insert |
| calendar_update_event | Update event | events.update |
| calendar_delete_event | Delete event | events.delete |

## Gmail Tools

| Tool | Description | API |
|------|-------------|-----|
| gmail_search | Search emails | messages.list |
| gmail_read | Read email | messages.get |
| gmail_send | Send email | messages.send |
| gmail_reply | Reply to email | messages.send |

## Drive Tools

| Tool | Description | API |
|------|-------------|-----|
| gdrive_list | List files | files.list |
| gdrive_read | Read file | files.get |
| gdrive_upload | Upload file | files.create |
| gdrive_share | Share file | permissions.create |

## Slides Tools

| Tool | Description | API |
|------|-------------|-----|
| slides_create | Create presentation | presentations.create |
| slides_add_slide | Add slide | presentations.batchUpdate |
| slides_update_text | Update text | presentations.batchUpdate |

## Components

| Component | File | Description |
|-----------|------|-------------|
| aa_google_calendar | `tool_modules/aa_google_calendar/` | Calendar tools |
| aa_gmail | `tool_modules/aa_gmail/` | Gmail tools |
| aa_gdrive | `tool_modules/aa_gdrive/` | Drive tools |
| aa_google_slides | `tool_modules/aa_google_slides/` | Slides tools |

## Related Diagrams

- [Google Tools](../03-tools/google-tools.md)
- [Auth Flows](./auth-flows.md)
- [Meet Daemon](../02-services/meet-daemon.md)
