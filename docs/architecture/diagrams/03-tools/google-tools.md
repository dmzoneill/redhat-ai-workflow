# Google Tools

> Google Workspace integration modules

## Diagram

```mermaid
classDiagram
    class GoogleCalendar {
        +calendar_list_events(days): list
        +calendar_get_event(id): dict
        +calendar_create_event(title, start, end): dict
        +calendar_update_event(id, fields): dict
        +calendar_delete_event(id): dict
    }

    class Gmail {
        +gmail_search(query): list
        +gmail_get_message(id): dict
        +gmail_send(to, subject, body): dict
        +gmail_reply(thread_id, body): dict
        +gmail_list_labels(): list
    }

    class GDrive {
        +gdrive_search(query): list
        +gdrive_get_file(id): dict
        +gdrive_download(id, path): str
        +gdrive_upload(path, folder): dict
        +gdrive_list_folder(id): list
    }

    class GoogleSlides {
        +slides_list_presentations(): list
        +slides_get_presentation(id): dict
        +slides_create_presentation(title): dict
        +slides_add_slide(pres_id, layout): dict
        +slides_update_text(pres_id, slide, text): dict
    }

    GoogleCalendar --> OAuth2
    Gmail --> OAuth2
    GDrive --> OAuth2
    GoogleSlides --> OAuth2

    class OAuth2 {
        +get_credentials(): Credentials
        +refresh_token(): str
        +authorize(): str
    }
```

## OAuth Flow

```mermaid
sequenceDiagram
    participant Tool as Google Tool
    participant Auth as OAuth2 Handler
    participant Token as Token Store
    participant Google as Google API

    Tool->>Auth: get_credentials()
    Auth->>Token: Load token
    
    alt Token valid
        Token-->>Auth: Valid token
    else Token expired
        Auth->>Google: Refresh token
        Google-->>Auth: New token
        Auth->>Token: Store token
    else No token
        Auth->>Google: OAuth flow
        Google-->>Auth: Authorization code
        Auth->>Google: Exchange for token
        Google-->>Auth: Access token
        Auth->>Token: Store token
    end

    Auth-->>Tool: Credentials
    Tool->>Google: API call
    Google-->>Tool: Response
```

## Components

| Module | File | Description |
|--------|------|-------------|
| aa_google_calendar | `tool_modules/aa_google_calendar/` | Calendar operations |
| aa_gmail | `tool_modules/aa_gmail/` | Email operations |
| aa_gdrive | `tool_modules/aa_gdrive/` | Drive operations |
| aa_google_slides | `tool_modules/aa_google_slides/` | Slides operations |

## Tool Summary

| Tool | Module | Description |
|------|--------|-------------|
| `calendar_list_events` | calendar | List upcoming events |
| `calendar_create_event` | calendar | Create event |
| `gmail_search` | gmail | Search emails |
| `gmail_send` | gmail | Send email |
| `gdrive_search` | gdrive | Search files |
| `gdrive_download` | gdrive | Download file |
| `slides_create_presentation` | slides | Create presentation |

## Configuration

```json
{
  "google": {
    "credentials_file": "~/.config/aa-workflow/google_credentials.json",
    "token_file": "~/.config/aa-workflow/google_token.json",
    "scopes": [
      "https://www.googleapis.com/auth/calendar",
      "https://www.googleapis.com/auth/gmail.modify",
      "https://www.googleapis.com/auth/drive"
    ]
  }
}
```

## Scopes

| Scope | Purpose |
|-------|---------|
| `calendar` | Read/write calendar events |
| `calendar.readonly` | Read-only calendar access |
| `gmail.modify` | Read/send emails |
| `drive` | Full Drive access |
| `drive.readonly` | Read-only Drive access |
| `presentations` | Create/edit presentations |

## Related Diagrams

- [Tool Module Structure](./tool-module-structure.md)
- [Google Integration](../07-integrations/google-integration.md)
- [Auth Flows](../07-integrations/auth-flows.md)
