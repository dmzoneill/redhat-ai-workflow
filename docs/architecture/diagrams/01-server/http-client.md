# HTTP Client

> Shared HTTP client utilities for external API calls

## Diagram

```mermaid
sequenceDiagram
    participant Tool as Tool Module
    participant Client as http_client.py
    participant Session as aiohttp.ClientSession
    participant API as External API

    Tool->>Client: get_session()

    alt Session exists
        Client-->>Tool: Existing session
    else No session
        Client->>Session: Create new session
        Client->>Client: Configure timeouts
        Client->>Client: Configure headers
        Client-->>Tool: New session
    end

    Tool->>Session: request(method, url, **kwargs)
    Session->>API: HTTP Request
    API-->>Session: HTTP Response
    Session-->>Tool: Response object

    Note over Tool,API: Error handling
    alt Success
        Tool->>Tool: Process response
    else Auth error
        Tool->>Tool: Trigger auto-heal
    else Network error
        Tool->>Tool: Retry or fail
    end
```

## Class Structure

```mermaid
classDiagram
    class HTTPClient {
        -_session: ClientSession
        -_timeout: ClientTimeout
        +get_session(): ClientSession
        +close_session()
        +request(method, url, **kwargs): Response
        +get(url, **kwargs): Response
        +post(url, **kwargs): Response
        +put(url, **kwargs): Response
        +delete(url, **kwargs): Response
    }

    class ClientConfig {
        +timeout_total: int
        +timeout_connect: int
        +timeout_sock_read: int
        +default_headers: dict
        +ssl_verify: bool
    }

    class ResponseHandler {
        +check_status(response)
        +parse_json(response): dict
        +parse_text(response): str
        +handle_error(response, error)
    }

    HTTPClient --> ClientConfig : uses
    HTTPClient --> ResponseHandler : uses
```

## Request Flow

```mermaid
flowchart TB
    subgraph Input[Request Input]
        METHOD[HTTP Method]
        URL[URL]
        HEADERS[Headers]
        BODY[Request Body]
        AUTH[Authentication]
    end

    subgraph Client[HTTP Client]
        SESSION[aiohttp Session]
        TIMEOUT[Timeout Config]
        RETRY[Retry Logic]
    end

    subgraph Output[Response Handling]
        STATUS[Status Check]
        PARSE[Parse Response]
        ERROR[Error Handler]
    end

    METHOD --> SESSION
    URL --> SESSION
    HEADERS --> SESSION
    BODY --> SESSION
    AUTH --> SESSION

    SESSION --> TIMEOUT
    TIMEOUT --> RETRY

    RETRY --> STATUS
    STATUS --> PARSE
    STATUS --> ERROR
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| HTTPClient | `server/http_client.py` | Main client class |
| get_session | `server/http_client.py` | Get/create session |
| close_session | `server/http_client.py` | Cleanup session |
| Timeouts | `server/timeouts.py` | Timeout constants |

## Timeout Configuration

| Timeout | Default | Description |
|---------|---------|-------------|
| total | 30s | Total request timeout |
| connect | 10s | Connection timeout |
| sock_read | 20s | Socket read timeout |

## Common Headers

```python
DEFAULT_HEADERS = {
    "User-Agent": "aa-workflow/1.0",
    "Accept": "application/json",
    "Content-Type": "application/json",
}
```

## Error Handling

| Error Type | Action |
|------------|--------|
| 401/403 | Trigger auto-heal (kube_login) |
| 429 | Retry with backoff |
| 5xx | Retry up to max_retries |
| Timeout | Retry or fail |
| Connection | Check VPN, retry |

## Related Diagrams

- [Auto-Heal Decorator](./auto-heal-decorator.md)
- [External Integrations](../07-integrations/auth-flows.md)
- [Tool Registry](./tool-registry.md)
