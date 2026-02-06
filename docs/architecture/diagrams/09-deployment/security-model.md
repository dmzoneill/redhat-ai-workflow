# Security Model

> Security considerations and credential handling

## Diagram

```mermaid
graph TB
    subgraph Credentials[Credential Storage]
        CONFIG[config.json<br/>API tokens]
        KEYRING[System keyring<br/>Sensitive data]
        KUBE[Kubeconfig<br/>Cluster creds]
        OAUTH[OAuth tokens<br/>Google, SSO]
    end

    subgraph Access[Access Control]
        USER[User-level services]
        FILE_PERMS[File permissions]
        DBUS_POLICY[D-Bus policy]
    end

    subgraph Protection[Protection Mechanisms]
        NO_LOG[No credential logging]
        MASK[Output masking]
        ROTATION[Token rotation]
    end

    Credentials --> Access
    Access --> Protection
```

## Credential Types

| Type | Storage | Rotation | Access |
|------|---------|----------|--------|
| API Tokens | config.json | Manual | File permissions |
| OAuth Tokens | token.json | Automatic | File permissions |
| Kubeconfig | ~/.kube/ | OIDC refresh | File permissions |
| SSO Tokens | Memory/cache | Automatic | Process-only |

## File Permissions

```mermaid
flowchart TB
    subgraph Sensitive[Sensitive Files]
        CONFIG["config.json<br/>600 (rw-------)"]
        STATE["state.json<br/>600 (rw-------)"]
        KUBE["~/.kube/config.*<br/>600 (rw-------)"]
        GOOGLE["token.json<br/>600 (rw-------)"]
    end

    subgraph Public[Public Files]
        PERSONAS["personas/*.yaml<br/>644 (rw-r--r--)"]
        SKILLS["skills/*.yaml<br/>644 (rw-r--r--)"]
        MEMORY["memory/*.yaml<br/>644 (rw-r--r--)"]
    end
```

## Credential Flow

```mermaid
sequenceDiagram
    participant Tool as MCP Tool
    participant Config as ConfigManager
    participant Store as Credential Store
    participant API as External API

    Tool->>Config: Get credentials
    Config->>Store: Load from storage
    Store-->>Config: Credentials

    Note over Config: Never log credentials

    Config-->>Tool: Masked reference
    Tool->>API: Request with auth
    API-->>Tool: Response

    Note over Tool: Mask sensitive data in output
```

## Security Rules

### Never Do

```mermaid
flowchart TB
    subgraph NeverDo[Security Anti-Patterns]
        LOG_CREDS["❌ Log credentials"]
        HARDCODE["❌ Hardcode secrets"]
        SHARE_KUBE["❌ Copy kubeconfig"]
        COMMIT_SECRETS["❌ Commit secrets"]
    end
```

### Always Do

```mermaid
flowchart TB
    subgraph AlwaysDo[Security Best Practices]
        MASK["✓ Mask sensitive output"]
        PERMS["✓ Restrict file permissions"]
        ROTATE["✓ Rotate tokens regularly"]
        VALIDATE["✓ Validate input"]
    end
```

## D-Bus Security

```mermaid
flowchart TB
    subgraph DBus[D-Bus Security]
        SESSION[Session bus only]
        USER[User-level access]
        NO_SYSTEM[No system bus]
    end

    subgraph Policy[Access Policy]
        SAME_USER[Same user only]
        NO_ROOT[No root access]
    end

    DBus --> Policy
```

## Output Masking

```python
# Before masking
"Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6..."

# After masking
"Authorization: Bearer [REDACTED]"

# Patterns masked:
# - API tokens
# - OAuth tokens
# - Passwords
# - Private keys
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| ConfigManager | `server/config_manager.py` | Credential loading |
| Output masking | Various | Sensitive data redaction |
| File permissions | systemd units | Permission enforcement |

## Related Diagrams

- [Auth Flows](../07-integrations/auth-flows.md)
- [Configuration Files](./configuration-files.md)
- [Config System](../01-server/config-system.md)
