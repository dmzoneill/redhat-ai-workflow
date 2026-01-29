# 🦭 Podman Module

Container management tools using Podman and podman-compose.

## Overview

The podman module provides tools for managing containers using Podman, the daemonless container engine. It's a drop-in replacement for Docker that's commonly used on Fedora, RHEL, and other Red Hat-based systems.

## Tools

### Container Management

| Tool | Description |
|------|-------------|
| `podman_ps` | List running containers |
| `podman_run` | Run a container from an image |
| `podman_stop` | Stop a running container |
| `podman_rm` | Remove a container |
| `podman_exec` | Execute command in container |
| `podman_cp` | Copy files to/from container |
| `podman_logs` | View container logs |

### Compose Operations

| Tool | Description |
|------|-------------|
| `podman_compose_status` | Check podman-compose container status |
| `podman_compose_up` | Start podman-compose services |
| `podman_compose_down` | Stop podman-compose services |

### Image Management

| Tool | Description |
|------|-------------|
| `podman_images` | List container images |
| `podman_pull` | Pull a container image |
| `podman_build` | Build a container image |

## Usage Examples

### List Running Containers

```python
# List all running containers
podman_ps()

# Include stopped containers
podman_ps(all_containers=True)

# Filter by name
podman_ps(filter_name="backend")
```

### Run a Container

```python
# Simple run
podman_run(image="nginx:latest", name="web")

# With port mapping and volumes
podman_run(
    image="postgres:15",
    name="db",
    ports="5432:5432",
    volumes="/data/postgres:/var/lib/postgresql/data:Z",
    env_vars="POSTGRES_PASSWORD=secret"
)
```

### Execute Commands

```python
# Run a command in container
podman_exec(container="web", command="ls -la /var/www")

# With working directory and user
podman_exec(
    container="app",
    command="python manage.py migrate",
    workdir="/app",
    user="appuser"
)
```

### Compose Operations

```python
# Start services
podman_compose_up(repo="backend")

# Start with build
podman_compose_up(repo="backend", build=True)

# Start specific services
podman_compose_up(repo="backend", services="db redis")

# Stop services
podman_compose_down(repo="backend")

# Stop and remove volumes
podman_compose_down(repo="backend", volumes=True)
```

### View Logs

```python
# Last 100 lines
podman_logs(container="app")

# Last 50 lines with timestamps
podman_logs(container="app", tail=50, timestamps=True)

# Logs from last hour
podman_logs(container="app", since="1h")
```

### Build Images

```python
# Simple build
podman_build(repo="backend", tag="myapp:latest")

# Build with custom Dockerfile
podman_build(
    repo="backend",
    tag="myapp:v1.0",
    dockerfile="Dockerfile.prod",
    build_args="VERSION=1.0 ENV=production"
)

# Build without cache
podman_build(repo="backend", tag="myapp:latest", no_cache=True)
```

### Copy Files

```python
# Copy to container
podman_cp(
    source="/tmp/config.yaml",
    destination="app:/etc/myapp/config.yaml",
    to_container=True
)

# Copy from container
podman_cp(
    source="app:/var/log/app.log",
    destination="/tmp/app.log",
    to_container=False
)
```

## Podman vs Docker

Podman is designed as a drop-in replacement for Docker:

| Feature | Docker | Podman |
|---------|--------|--------|
| Daemon | Required | Daemonless |
| Root | Often needed | Rootless by default |
| Compose | docker-compose | podman-compose |
| CLI | docker | podman (compatible) |
| Systemd | External | Native integration |

### Key Differences

1. **Daemonless**: Podman doesn't require a background daemon
2. **Rootless**: Runs containers as non-root by default
3. **SELinux**: Better integration with `:Z` volume labels
4. **Systemd**: Can generate systemd unit files for containers

## SELinux Volume Labels

When mounting volumes on SELinux-enabled systems (Fedora, RHEL):

```python
# Use :Z for private unshared label
podman_run(
    image="myapp",
    volumes="/host/data:/container/data:Z"
)

# Use :z for shared label (multiple containers)
podman_run(
    image="myapp",
    volumes="/host/shared:/container/shared:z"
)
```

## Requirements

- `podman` CLI installed
- `podman-compose` for compose operations
- Podman socket running (for some operations)

### Installation (Fedora/RHEL)

```bash
# Install podman
sudo dnf install podman podman-compose

# Enable user socket (for rootless)
systemctl --user enable --now podman.socket
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `CONTAINER_HOST` | Podman socket URL (optional) |
| `REGISTRY_AUTH_FILE` | Path to auth file for registries |

## See Also

- [Docker Module](./docker.md) - Docker equivalent tools
- [Quay Module](./quay.md) - Container registry operations
- [Bonfire Module](./bonfire.md) - Ephemeral deployments
