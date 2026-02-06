# GCloud Tools

> aa_gcloud module for Google Cloud Platform management

## Diagram

```mermaid
classDiagram
    class ComputeTools {
        +gcloud_compute_instances_list(): str
        +gcloud_compute_instances_start(instance, zone): str
        +gcloud_compute_instances_stop(instance, zone): str
        +gcloud_compute_instances_describe(instance, zone): str
    }

    class StorageTools {
        +gcloud_storage_ls(path): str
        +gcloud_storage_cp(source, dest): str
        +gcloud_storage_rm(path): str
    }

    class ProjectTools {
        +gcloud_projects_list(): str
        +gcloud_config_list(): str
        +gcloud_config_set_project(project): str
    }

    class AuthTools {
        +gcloud_auth_list(): str
    }

    class GKETools {
        +gcloud_container_clusters_list(): str
        +gcloud_container_clusters_get_credentials(cluster): str
    }
```

## Tool Categories

```mermaid
graph TB
    subgraph Compute[Compute Engine]
        LIST[gcloud_compute_instances_list]
        START[gcloud_compute_instances_start]
        STOP[gcloud_compute_instances_stop]
        DESC[gcloud_compute_instances_describe]
    end

    subgraph Storage[Cloud Storage]
        LS[gcloud_storage_ls]
        CP[gcloud_storage_cp]
        RM[gcloud_storage_rm]
    end

    subgraph Project[Project Management]
        PROJECTS[gcloud_projects_list]
        CONFIG[gcloud_config_list]
        SET[gcloud_config_set_project]
    end

    subgraph GKE[Kubernetes Engine]
        CLUSTERS[gcloud_container_clusters_list]
        CREDS[gcloud_container_clusters_get_credentials]
    end
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| tools_basic.py | `tool_modules/aa_gcloud/src/` | All GCloud CLI tools |

## Tool Summary

### Compute Tools

| Tool | Description |
|------|-------------|
| `gcloud_compute_instances_list` | List compute instances |
| `gcloud_compute_instances_start` | Start a compute instance |
| `gcloud_compute_instances_stop` | Stop a compute instance |
| `gcloud_compute_instances_describe` | Get instance details |

### Storage Tools

| Tool | Description |
|------|-------------|
| `gcloud_storage_ls` | List storage buckets/objects |
| `gcloud_storage_cp` | Copy files to/from GCS |
| `gcloud_storage_rm` | Remove storage objects |

### Project Tools

| Tool | Description |
|------|-------------|
| `gcloud_projects_list` | List GCP projects |
| `gcloud_config_list` | Show current configuration |
| `gcloud_config_set_project` | Set active project |

### Auth Tools

| Tool | Description |
|------|-------------|
| `gcloud_auth_list` | List authenticated accounts |

### GKE Tools

| Tool | Description |
|------|-------------|
| `gcloud_container_clusters_list` | List GKE clusters |
| `gcloud_container_clusters_get_credentials` | Get cluster credentials |

## Usage Examples

```python
# List projects
result = await gcloud_projects_list()

# List compute instances
result = await gcloud_compute_instances_list(project="my-project")

# Start an instance
result = await gcloud_compute_instances_start("my-vm", "us-central1-a")

# List GCS objects
result = await gcloud_storage_ls("gs://my-bucket/data/")

# Get GKE credentials
result = await gcloud_container_clusters_get_credentials(
    "my-cluster",
    region="us-central1"
)
```

## Configuration

Uses gcloud CLI configuration. Authenticate with:
```bash
gcloud auth login
gcloud auth application-default login
```

## Related Diagrams

- [AWS Tools](./aws-tools.md)
- [Kubernetes Tools](./k8s-tools.md)
