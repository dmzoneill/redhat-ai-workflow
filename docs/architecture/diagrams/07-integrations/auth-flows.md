# Authentication Flows

> Authentication patterns across integrations

## Diagram

```mermaid
graph TB
    subgraph AuthTypes[Authentication Types]
        TOKEN[API Token<br/>Jira, GitLab]
        OAUTH[OAuth 2.0<br/>Google Workspace]
        KUBE[Kubeconfig<br/>Kubernetes]
        SSO[SSO/OIDC<br/>Internal services]
    end

    subgraph Storage[Credential Storage]
        CONFIG[config.json<br/>Static tokens]
        KEYRING[System keyring<br/>Sensitive data]
        KUBECONFIG[~/.kube/<br/>Cluster creds]
        TOKEN_FILE[token.json<br/>OAuth tokens]
    end

    AuthTypes --> Storage
```

## API Token Flow

```mermaid
sequenceDiagram
    participant Tool as MCP Tool
    participant Config as config.json
    participant Client as HTTP Client
    participant API as External API

    Tool->>Config: Get credentials
    Config-->>Tool: API token

    Tool->>Client: Build request
    Client->>Client: Add auth header

    Client->>API: Request with token
    API-->>Client: Response
    Client-->>Tool: Data
```

## OAuth 2.0 Flow

```mermaid
sequenceDiagram
    participant Tool as Google Tool
    participant Auth as Auth Handler
    participant Token as token.json
    participant Google as Google OAuth

    Tool->>Auth: Get credentials

    alt First time
        Auth->>Google: Redirect to consent
        Google-->>Auth: Authorization code
        Auth->>Google: Exchange code
        Google-->>Auth: Access + refresh tokens
        Auth->>Token: Save tokens
    else Token exists
        Auth->>Token: Load tokens
        alt Token expired
            Auth->>Google: Refresh token
            Google-->>Auth: New access token
            Auth->>Token: Update token
        end
    end

    Auth-->>Tool: Valid credentials
```

## Kubernetes Auth Flow

```mermaid
sequenceDiagram
    participant Tool as K8s Tool
    participant Config as Kubeconfig
    participant OIDC as OIDC Provider
    participant K8s as Kubernetes API

    Tool->>Config: Load kubeconfig
    Config-->>Tool: Cluster config

    alt Token expired
        Tool->>OIDC: Refresh token
        OIDC-->>Tool: New token
    end

    Tool->>K8s: API request
    K8s-->>Tool: Response
```

## SSO/OIDC Flow

```mermaid
sequenceDiagram
    participant Tool as InScope Tool
    participant SSO as SSO Provider
    participant Browser as Browser
    participant API as Internal API

    Tool->>SSO: Check token
    alt Token expired
        Tool->>Browser: Open login page
        Browser->>SSO: User authenticates
        SSO-->>Browser: Redirect with code
        Browser-->>Tool: Authorization code
        Tool->>SSO: Exchange code
        SSO-->>Tool: Access token
    end

    Tool->>API: Request with token
    API-->>Tool: Response
```

## Auto-Heal for Auth

```mermaid
flowchart TB
    subgraph Detection[Auth Failure Detection]
        K8S_401["K8s: 401 Unauthorized"]
        VPN_ERR["Network: Connection refused"]
        TOKEN_EXP["API: Token expired"]
    end

    subgraph Recovery[Auto-Recovery]
        KUBE_LOGIN[kube_login]
        VPN_CONNECT[vpn_connect]
        TOKEN_REFRESH[Refresh token]
    end

    K8S_401 --> KUBE_LOGIN
    VPN_ERR --> VPN_CONNECT
    TOKEN_EXP --> TOKEN_REFRESH
```

## Credential Matrix

| Service | Auth Type | Storage | Auto-Refresh |
|---------|-----------|---------|--------------|
| Jira | API Token | config.json | No |
| GitLab | PAT | config.json | No |
| Google | OAuth 2.0 | token.json | Yes |
| Kubernetes | OIDC | kubeconfig | Yes (auto-heal) |
| Slack | Bot Token | config.json | No |
| InScope | SSO | token cache | Yes |

## Components

| Component | File | Description |
|-----------|------|-------------|
| Config | `server/config.py` | Credential loading |
| Auto-heal | `server/auto_heal_decorator.py` | Auth recovery |
| Google auth | `tool_modules/aa_google_*/` | OAuth handling |

## Related Diagrams

- [Auto-Heal Decorator](../01-server/auto-heal-decorator.md)
- [Config System](../01-server/config-system.md)
- [Google Workspace](./google-workspace-integration.md)
