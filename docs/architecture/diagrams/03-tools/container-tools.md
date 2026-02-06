# Container Tools

> Docker, Podman, and Quay integration modules

## Diagram

```mermaid
classDiagram
    class DockerBasic {
        +docker_ps(): list
        +docker_images(): list
        +docker_logs(container): str
        +docker_inspect(container): dict
    }

    class DockerCore {
        +docker_run(image, args): str
        +docker_stop(container): str
        +docker_rm(container): str
        +docker_build(path, tag): str
        +docker_push(image): str
    }

    class PodmanBasic {
        +podman_ps(): list
        +podman_images(): list
        +podman_logs(container): str
    }

    class QuayBasic {
        +quay_list_repos(namespace): list
        +quay_list_tags(repo): list
        +quay_get_manifest(repo, tag): dict
        +quay_get_vulnerabilities(repo, tag): list
    }

    class QuayExtra {
        +quay_delete_tag(repo, tag): dict
        +quay_copy_tag(src, dest): dict
    }

    DockerBasic <|-- DockerCore
    QuayBasic <|-- QuayExtra
```

## Image Flow

```mermaid
flowchart TB
    subgraph Build[Build Phase]
        CODE[Source Code]
        DOCKERFILE[Dockerfile]
        BUILD[docker_build]
        IMAGE[Local Image]
    end

    subgraph Push[Push Phase]
        TAG[Tag Image]
        PUSH[docker_push]
        QUAY[Quay.io Registry]
    end

    subgraph Deploy[Deploy Phase]
        PULL[Pull Image]
        K8S[Kubernetes]
        PODS[Running Pods]
    end

    CODE --> BUILD
    DOCKERFILE --> BUILD
    BUILD --> IMAGE
    IMAGE --> TAG
    TAG --> PUSH
    PUSH --> QUAY
    QUAY --> PULL
    PULL --> K8S
    K8S --> PODS
```

## Components

| Module | File | Description |
|--------|------|-------------|
| aa_docker | `tool_modules/aa_docker/` | Docker operations |
| aa_podman | `tool_modules/aa_podman/` | Podman operations |
| aa_quay | `tool_modules/aa_quay/` | Quay.io operations |

## Tool Summary

| Tool | Module | Description |
|------|--------|-------------|
| `docker_ps` | docker | List containers |
| `docker_images` | docker | List images |
| `docker_build` | docker | Build image |
| `docker_push` | docker | Push to registry |
| `podman_ps` | podman | List containers |
| `quay_list_tags` | quay | List image tags |
| `quay_get_manifest` | quay | Get image manifest |

## Quay API Flow

```mermaid
sequenceDiagram
    participant Tool as Quay Tool
    participant Client as HTTP Client
    participant Quay as Quay.io API

    Tool->>Client: Build request
    Note over Client: Add Authorization header
    Client->>Quay: GET /api/v1/repository/{repo}/tag/
    Quay-->>Client: Tag list
    Client-->>Tool: Formatted tags

    Tool->>Client: Get manifest
    Client->>Quay: GET /api/v1/repository/{repo}/manifest/{digest}
    Quay-->>Client: Manifest data
    Client-->>Tool: Parsed manifest
```

## Configuration

```json
{
  "containers": {
    "docker": {
      "socket": "unix:///var/run/docker.sock"
    },
    "podman": {
      "socket": "unix:///run/user/1000/podman/podman.sock"
    },
    "quay": {
      "url": "https://quay.io",
      "namespace": "cloudservices",
      "token_env": "QUAY_TOKEN"
    }
  }
}
```

## Image Tag Formats

| Format | Example | Use Case |
|--------|---------|----------|
| Git SHA | `abc123def456...` | CI builds |
| Semantic | `v1.2.3` | Releases |
| Latest | `latest` | Development |
| Branch | `main`, `feature-x` | Branch builds |

## Related Diagrams

- [Tool Module Structure](./tool-module-structure.md)
- [Quay Integration](../07-integrations/quay-integration.md)
- [Ephemeral Deployment](../08-data-flows/ephemeral-deployment.md)
